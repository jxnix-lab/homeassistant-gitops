"""Update entity for GitOps integration."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import GitOpsCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GitOps update entity."""
    coordinator: GitOpsCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities([GitOpsLocalChangesUpdate(coordinator)])


class GitOpsLocalChangesUpdate(UpdateEntity):
    """Update entity for local uncommitted changes."""

    _attr_has_entity_name = True
    _attr_name = "Sync Status"
    _attr_unique_id = "gitops_local_changes"
    _attr_icon = "mdi:sync"
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.RELEASE_NOTES
    )

    def __init__(self, coordinator: GitOpsCoordinator) -> None:
        """Initialize the update entity."""
        self.coordinator = coordinator
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "gitops")},
            "name": "GitOps",
            "manufacturer": "JaxLabs",
            "model": "GitOps",
        }

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_update",
                self._handle_coordinator_update,
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @property
    def installed_version(self) -> str | None:
        """Return the current commit SHA."""
        if self.coordinator._repo:
            return self.coordinator._repo.head.commit.hexsha[:7]
        return None

    @property
    def latest_version(self) -> str | None:
        """Return '<sha>-dirty' if there are uncommitted changes, otherwise current commit."""
        if not self.coordinator._repo:
            return None

        if self.coordinator._repo.is_dirty() or self.coordinator._repo.untracked_files:
            current_sha = self.coordinator._repo.head.commit.hexsha[:7]
            return f"{current_sha}-dirty"

        return self.installed_version

    @property
    def release_url(self) -> str | None:
        """Return URL for release notes."""
        return None

    async def async_release_notes(self) -> str | None:
        """Return the release notes (git diff)."""
        if not self.coordinator._repo:
            return None

        if not self.coordinator._repo.is_dirty() and not self.coordinator._repo.untracked_files:
            return None

        # Get diff of modified files
        diff_lines = []

        # Show modified files
        if self.coordinator._repo.is_dirty():
            diff = self.coordinator._repo.git.diff()
            if diff:
                # Split diff by file
                file_diffs = diff.split('diff --git')
                for file_diff in file_diffs:
                    if not file_diff.strip():
                        continue

                    # Extract filename from diff header
                    lines = file_diff.split('\n')
                    filename = "Unknown file"
                    for line in lines[:5]:
                        if line.startswith(' a/') or line.startswith(' b/'):
                            filename = line.split('/', 1)[1] if '/' in line else filename
                            break

                    diff_lines.append(f"<details><summary><b>{filename}</b></summary>\n")
                    diff_lines.append("```diff")
                    diff_lines.append("diff --git" + file_diff)
                    diff_lines.append("```")
                    diff_lines.append("</details>\n")

        # Show untracked files with contents
        if self.coordinator._repo.untracked_files:
            diff_lines.append("## Untracked Files\n")
            for file in self.coordinator._repo.untracked_files:
                try:
                    # Read file content
                    file_path = Path(self.coordinator._repo.working_dir) / file
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()

                    # Determine file extension for syntax highlighting
                    ext = file_path.suffix.lstrip('.')
                    if ext in ['py', 'yaml', 'yml', 'json', 'js', 'ts', 'sh', 'bash']:
                        lang = ext if ext != 'yml' else 'yaml'
                    else:
                        lang = ''

                    # Show file with content in collapsible section
                    diff_lines.append(f"<details><summary><b>{file}</b> (new file)</summary>\n")
                    diff_lines.append(f"```{lang}")
                    diff_lines.append(content)
                    diff_lines.append("```")
                    diff_lines.append("</details>\n")
                except Exception as e:
                    # If we can't read the file, just show the name
                    diff_lines.append(f"- `{file}` (binary or unreadable)\n")

        return "\n".join(diff_lines) if diff_lines else "No changes detected"

    async def async_install(
        self, version: str | None, backup: bool, **kwargs
    ) -> None:
        """Commit and push local changes."""
        if not self.coordinator._repo:
            raise Exception("Git repository not initialized")

        repo = self.coordinator._repo

        # Stage all changes
        repo.git.add(A=True)

        # Create commit message
        modified = [item.a_path for item in repo.index.diff("HEAD")]
        untracked = repo.untracked_files

        commit_msg_parts = ["Update Home Assistant configuration"]

        if modified:
            commit_msg_parts.append(f"\nModified files: {', '.join(modified)}")
        if untracked:
            commit_msg_parts.append(f"\nNew files: {', '.join(untracked)}")

        commit_msg_parts.append("\n\n✨ Committed via GitOps integration")

        # Commit
        repo.index.commit("\n".join(commit_msg_parts))

        # Push
        origin = repo.remote("origin")
        origin.push()

        _LOGGER.info("Committed and pushed local changes")

        # Update state
        self.async_write_ha_state()
