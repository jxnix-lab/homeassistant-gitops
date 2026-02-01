"""Update entity for GitOps integration."""
from __future__ import annotations

import logging
from datetime import datetime

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
    async_add_entities([GitOpsConfigUpdate(coordinator)])


class GitOpsConfigUpdate(UpdateEntity):
    """Update entity that tracks remote git commits available to deploy."""

    _attr_has_entity_name = True
    _attr_name = "Configuration"
    _attr_unique_id = "gitops_config_update"
    _attr_icon = "mdi:source-branch-sync"
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES
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
                self.hass, f"{DOMAIN}_update", self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @property
    def installed_version(self) -> str | None:
        """Return the current local commit SHA."""
        return self.coordinator.git_state.local_sha

    @property
    def latest_version(self) -> str | None:
        """Return the remote commit SHA if an update is available."""
        state = self.coordinator.git_state
        if state.update_available and state.remote_sha:
            return state.remote_sha
        return self.installed_version

    @property
    def release_url(self) -> str | None:
        """Return GitHub compare URL between local and remote."""
        state = self.coordinator.git_state
        repo_url = self.coordinator.get_repo_url()
        if repo_url and state.local_sha and state.remote_sha and state.update_available:
            return f"{repo_url}/compare/{state.local_sha}...{state.remote_sha}"
        return None

    async def async_release_notes(self) -> str | None:
        """Return commit log as markdown release notes."""
        state = self.coordinator.git_state
        if not state.commit_log:
            return None

        count = state.commits_behind
        lines = [f"### {count} new commit{'s' if count != 1 else ''}\n"]

        for entry in state.commit_log:
            sha = entry["sha"]
            msg = entry["message"]
            author = entry.get("author", "")
            lines.append(f"- **`{sha}`** {msg}")

        deploy_state = self.coordinator.deployment_state
        if deploy_state.status not in ("idle", "success"):
            lines.append(f"\n*Last deploy: {deploy_state.status}*")
            if deploy_state.error:
                lines.append(f"*Error: {deploy_state.error}*")

        return "\n".join(lines)

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional attributes."""
        state = self.coordinator.git_state
        deploy = self.coordinator.deployment_state
        return {
            "commits_behind": state.commits_behind,
            "last_check": state.last_check.isoformat() if state.last_check else None,
            "remote_message": state.remote_message,
            "deploy_status": deploy.status,
            "deploy_timestamp": deploy.timestamp.isoformat() if deploy.timestamp else None,
        }

    async def async_install(
        self, version: str | None, backup: bool, **kwargs
    ) -> None:
        """Deploy the latest configuration."""
        await self.coordinator.async_deploy()
