"""GitOps coordinator for managing deployments and state."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import git
import yaml
from aiohttp import web
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_DOPPLER_API_URL,
    CONF_DOPPLER_SERVICE_TOKEN,
    DEFAULT_DOPPLER_API_URL,
    DOMAIN,
    RELOAD_PATTERNS,
    REPAIR_DOPPLER_CONNECTION,
    REPAIR_GIT_CONNECTION,
    REPAIR_GIT_LOCK,
    REPAIR_RESTART_REQUIRED,
    RESTART_REQUIRED_PATTERNS,
    STATE_DEPLOYING,
    STATE_FAILED,
    STATE_IDLE,
    STATE_RELOADING,
    STATE_RESTART_REQUIRED,
    STATE_SUCCESS,
    STATE_VALIDATING,
)

_LOGGER = logging.getLogger(__name__)

WEBHOOK_NOTIFY = "gitops-notify"
WEBHOOK_SECRETS_REFRESH = "gitops-secrets-refresh"


@dataclass
class GitState:
    """Track git remote vs local state."""

    local_sha: str | None = None
    local_message: str | None = None
    remote_sha: str | None = None
    remote_message: str | None = None
    commits_behind: int = 0
    update_available: bool = False
    last_check: datetime | None = None
    commit_log: list[dict[str, str]] = field(default_factory=list)


@dataclass
class DeploymentState:
    """Track deployment state."""

    status: str = STATE_IDLE
    commit_sha: str | None = None
    commit_message: str | None = None
    timestamp: datetime | None = None
    error: str | None = None
    changed_files: list[str] | None = None
    reload_domains: list[str] | None = None
    restart_required: bool = False


class GitOpsCoordinator:
    """Coordinate GitOps operations."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        self.hass = hass
        self.config_entry = config_entry
        self._deployment_lock = asyncio.Lock()
        self._deployment_state = DeploymentState()
        self._git_state = GitState()
        self._repo: git.Repo | None = None
        self._journal_path = Path("/config/.gitops_journal.json")

    # ── Properties ──────────────────────────────────────────────────

    @property
    def git_state(self) -> GitState:
        """Get current git state."""
        return self._git_state

    @property
    def deployment_state(self) -> DeploymentState:
        """Get current deployment state."""
        return self._deployment_state

    @property
    def _doppler_headers(self) -> dict[str, str]:
        """Get headers for Doppler API requests."""
        token = self.config_entry.data[CONF_DOPPLER_SERVICE_TOKEN]
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    @property
    def _doppler_base_url(self) -> str:
        """Get Doppler API base URL."""
        return self.config_entry.data.get(CONF_DOPPLER_API_URL, DEFAULT_DOPPLER_API_URL)

    # ── Setup / Shutdown ────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Set up the coordinator."""
        # Initialize git repository
        try:
            self._repo = await self.hass.async_add_executor_job(git.Repo, "/config")
            _LOGGER.info("Git repository initialized at /config")
            await self._update_local_state()
        except Exception as err:
            _LOGGER.error("Failed to initialize git repository: %s", err)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                REPAIR_GIT_CONNECTION,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="git_connection_failed",
                translation_placeholders={"error": str(err)},
            )

        # Load secrets from Doppler
        await self._load_secrets()

        # Register webhooks
        webhook.async_register(
            self.hass, DOMAIN, "GitOps Push Notification",
            WEBHOOK_NOTIFY, self._handle_notify_webhook,
        )
        webhook.async_register(
            self.hass, DOMAIN, "GitOps Secrets Refresh",
            WEBHOOK_SECRETS_REFRESH, self._handle_secrets_webhook,
        )
        _LOGGER.info("Webhooks registered: %s, %s", WEBHOOK_NOTIFY, WEBHOOK_SECRETS_REFRESH)

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        webhook.async_unregister(self.hass, WEBHOOK_NOTIFY)
        webhook.async_unregister(self.hass, WEBHOOK_SECRETS_REFRESH)

    # ── Git Operations ──────────────────────────────────────────────

    async def _update_local_state(self) -> None:
        """Update local git state from HEAD."""
        if not self._repo:
            return

        def _read_head():
            commit = self._repo.head.commit
            return commit.hexsha[:7], commit.message.strip().split("\n")[0]

        sha, msg = await self.hass.async_add_executor_job(_read_head)
        self._git_state.local_sha = sha
        self._git_state.local_message = msg

    async def async_check_for_updates(self) -> None:
        """Fetch from remote and check for available updates."""
        if not self._repo:
            _LOGGER.warning("Git repository not initialized, skipping update check")
            return

        try:
            # Fetch from remote
            await self.hass.async_add_executor_job(self._repo.remotes.origin.fetch)

            # Compare local HEAD to remote tracking branch
            def _compare():
                local = self._repo.head.commit
                tracking = self._repo.active_branch.tracking_branch()
                if tracking is None:
                    _LOGGER.warning("No tracking branch configured")
                    return

                remote = tracking.commit

                local_sha = local.hexsha[:7]
                remote_sha = remote.hexsha[:7]
                remote_msg = remote.message.strip().split("\n")[0]

                # Count commits behind
                behind = list(self._repo.iter_commits(f"{local.hexsha}..{remote.hexsha}"))

                # Build commit log
                commit_log = []
                for c in behind[:20]:  # Cap at 20
                    commit_log.append({
                        "sha": c.hexsha[:7],
                        "message": c.message.strip().split("\n")[0],
                        "author": str(c.author),
                        "timestamp": datetime.fromtimestamp(
                            c.committed_date, tz=UTC
                        ).isoformat(),
                    })

                return {
                    "local_sha": local_sha,
                    "remote_sha": remote_sha,
                    "remote_message": remote_msg,
                    "commits_behind": len(behind),
                    "commit_log": commit_log,
                }

            result = await self.hass.async_add_executor_job(_compare)
            if result is None:
                return

            self._git_state.local_sha = result["local_sha"]
            self._git_state.remote_sha = result["remote_sha"]
            self._git_state.remote_message = result["remote_message"]
            self._git_state.commits_behind = result["commits_behind"]
            self._git_state.commit_log = result["commit_log"]
            self._git_state.update_available = result["commits_behind"] > 0
            self._git_state.last_check = datetime.now(UTC)

            if self._git_state.update_available:
                _LOGGER.info(
                    "Update available: %d commit(s) behind (%s → %s)",
                    result["commits_behind"],
                    result["local_sha"],
                    result["remote_sha"],
                )
            else:
                _LOGGER.debug("Up to date at %s", result["local_sha"])

            # Clear git connection issues on success
            ir.async_delete_issue(self.hass, DOMAIN, REPAIR_GIT_CONNECTION)

        except Exception as err:
            _LOGGER.error("Failed to check for updates: %s", err)

        finally:
            async_dispatcher_send(self.hass, f"{DOMAIN}_update")

    async def async_deploy(self) -> None:
        """Pull latest commits, sync secrets, validate, and reload."""
        if not self._repo:
            raise RuntimeError("Git repository not initialized")

        async with self._deployment_lock:
            self._deployment_state = DeploymentState(
                status=STATE_DEPLOYING,
                timestamp=datetime.now(UTC),
            )
            async_dispatcher_send(self.hass, f"{DOMAIN}_update")

            try:
                # Check for git lock file
                lock_file = Path("/config/.git/index.lock")
                if await self.hass.async_add_executor_job(lock_file.exists):
                    ir.async_create_issue(
                        self.hass, DOMAIN, REPAIR_GIT_LOCK,
                        is_fixable=True, severity=ir.IssueSeverity.ERROR,
                        translation_key="git_lock_detected",
                    )
                    raise RuntimeError("Git lock file detected — remove .git/index.lock")

                # Pull latest changes
                _LOGGER.info("Pulling latest changes")
                changed_files = await self._git_pull()
                self._deployment_state.changed_files = changed_files

                # Update commit info
                await self._update_local_state()
                self._deployment_state.commit_sha = self._git_state.local_sha
                self._deployment_state.commit_message = self._git_state.local_message

                # Sync secrets from Doppler (config may reference new secrets)
                _LOGGER.info("Syncing secrets from Doppler")
                await self._load_secrets()

                # Validate configuration
                self._deployment_state.status = STATE_VALIDATING
                async_dispatcher_send(self.hass, f"{DOMAIN}_update")
                _LOGGER.info("Validating configuration")
                await self._validate_config()

                # Determine reloads
                self._deployment_state.status = STATE_RELOADING
                async_dispatcher_send(self.hass, f"{DOMAIN}_update")

                reload_domains = self._determine_reload_domains(changed_files)
                self._deployment_state.reload_domains = reload_domains

                restart_required = self._check_restart_required(changed_files)
                self._deployment_state.restart_required = restart_required

                if restart_required:
                    _LOGGER.warning("Restart required for changes to take effect")
                    ir.async_create_issue(
                        self.hass, DOMAIN, REPAIR_RESTART_REQUIRED,
                        is_fixable=False, severity=ir.IssueSeverity.WARNING,
                        translation_key="restart_required",
                        translation_placeholders={
                            "commit": self._deployment_state.commit_sha or "",
                            "message": self._deployment_state.commit_message or "",
                        },
                    )
                    self._deployment_state.status = STATE_RESTART_REQUIRED
                else:
                    _LOGGER.info("Reloading domains: %s", reload_domains)
                    await self._execute_reloads(reload_domains)
                    self._deployment_state.status = STATE_SUCCESS

                _LOGGER.info(
                    "Deployment completed: %s (%s)",
                    self._deployment_state.commit_sha,
                    self._deployment_state.status,
                )

                # Reset git state — we're up to date now
                self._git_state.update_available = False
                self._git_state.commits_behind = 0
                self._git_state.commit_log = []
                self._git_state.remote_sha = self._git_state.local_sha

            except Exception as err:
                _LOGGER.error("Deployment failed: %s", err, exc_info=True)
                self._deployment_state.status = STATE_FAILED
                self._deployment_state.error = str(err)

            finally:
                async_dispatcher_send(self.hass, f"{DOMAIN}_update")

    async def _git_pull(self) -> list[str]:
        """Pull latest changes and return list of changed files."""
        old_commit = self._repo.head.commit

        await self.hass.async_add_executor_job(self._repo.remotes.origin.pull)

        new_commit = self._repo.head.commit

        if old_commit != new_commit:
            diff = old_commit.diff(new_commit)
            changed_files = [item.a_path for item in diff]
            _LOGGER.info("Changed files: %s", changed_files)
            return changed_files

        return []

    async def _validate_config(self) -> None:
        """Validate Home Assistant configuration."""
        try:
            await self.hass.services.async_call(
                "homeassistant", "check_config", blocking=True
            )
        except Exception as err:
            raise RuntimeError(f"Config validation failed: {err}") from err

    def _determine_reload_domains(self, changed_files: list[str]) -> list[str]:
        """Determine which domains need to be reloaded."""
        domains = set()
        for domain, patterns in RELOAD_PATTERNS.items():
            for pattern in patterns:
                for changed_file in changed_files:
                    if fnmatch(changed_file, pattern):
                        domains.add(domain)
                        break
        return list(domains)

    def _check_restart_required(self, changed_files: list[str]) -> bool:
        """Check if any changed files require a full restart."""
        for pattern in RESTART_REQUIRED_PATTERNS:
            for changed_file in changed_files:
                if fnmatch(changed_file, pattern):
                    return True
        return False

    async def _execute_reloads(self, domains: list[str]) -> None:
        """Execute reload for each domain."""
        for domain in domains:
            try:
                _LOGGER.info("Reloading domain: %s", domain)
                await self.hass.services.async_call(
                    domain, "reload", blocking=True, timeout=30
                )
            except Exception as err:
                _LOGGER.error("Failed to reload %s: %s", domain, err)
                raise

    # ── Doppler Secrets ─────────────────────────────────────────────

    async def _fetch_doppler_secrets(self) -> dict[str, str]:
        """Fetch secrets from Doppler."""
        session = async_get_clientsession(self.hass)
        url = f"{self._doppler_base_url}/v3/configs/config/secrets/download"

        async with session.get(
            url, headers=self._doppler_headers, params={"format": "json"}
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Doppler API error (HTTP {resp.status}): {text}")
            data = await resp.json()
            return {k: v for k, v in data.items() if not k.startswith("DOPPLER_")}

    async def _load_secrets(self) -> None:
        """Load secrets from Doppler and write to secrets_doppler.yaml."""
        try:
            secrets = await self._fetch_doppler_secrets()
            await self._write_secrets_file(secrets)
            await self._ensure_secrets_yaml_includes()
            _LOGGER.info("Synced %d secrets from Doppler", len(secrets))
            ir.async_delete_issue(self.hass, DOMAIN, REPAIR_DOPPLER_CONNECTION)
        except Exception as err:
            _LOGGER.error("Failed to load secrets from Doppler: %s", err)
            ir.async_create_issue(
                self.hass, DOMAIN, REPAIR_DOPPLER_CONNECTION,
                is_fixable=True, severity=ir.IssueSeverity.WARNING,
                translation_key="doppler_connection_failed",
                translation_placeholders={"error": str(err)},
            )

    async def _write_secrets_file(self, secrets: dict[str, str]) -> None:
        """Write secrets to secrets_doppler.yaml (atomic)."""
        secrets_path = Path("/config/secrets_doppler.yaml")

        content = "# Managed by GitOps Integration - DO NOT EDIT MANUALLY\n"
        content += f"# Synced from Doppler at {datetime.now(UTC).isoformat()}\n\n"
        content += yaml.safe_dump(secrets, default_flow_style=False)

        temp_path = secrets_path.with_suffix(".tmp")
        await self.hass.async_add_executor_job(temp_path.write_text, content)
        await self.hass.async_add_executor_job(temp_path.rename, secrets_path)

    async def _ensure_secrets_yaml_includes(self) -> None:
        """Ensure secrets.yaml includes secrets_doppler.yaml."""
        secrets_yaml = Path("/config/secrets.yaml")
        include_line = "<<: !include secrets_doppler.yaml\n"

        if not await self.hass.async_add_executor_job(secrets_yaml.exists):
            content = (
                "# Doppler secrets (managed by GitOps integration)\n"
                + include_line
                + "\n# Your manual secrets here\n"
            )
            await self.hass.async_add_executor_job(secrets_yaml.write_text, content)
            _LOGGER.info("Created secrets.yaml with Doppler include")
        else:
            content = await self.hass.async_add_executor_job(secrets_yaml.read_text)
            if "secrets_doppler.yaml" not in content:
                if "secrets_infisical.yaml" in content:
                    new_content = content.replace(
                        "secrets_infisical.yaml", "secrets_doppler.yaml"
                    )
                    _LOGGER.info("Migrated secrets.yaml include from Infisical to Doppler")
                else:
                    new_content = (
                        "# Doppler secrets (managed by GitOps integration)\n"
                        + include_line + "\n" + content
                    )
                    _LOGGER.info("Added Doppler include to existing secrets.yaml")
                await self.hass.async_add_executor_job(
                    secrets_yaml.write_text, new_content
                )

    # ── Webhooks ────────────────────────────────────────────────────

    async def _handle_notify_webhook(
        self, hass: HomeAssistant, webhook_id: str, request: web.Request,
    ) -> web.Response:
        """Handle push notification — triggers an update check."""
        _LOGGER.info("Push notification received, checking for updates")
        asyncio.create_task(self.async_check_for_updates())
        return web.Response(status=200, text="OK")

    async def _handle_secrets_webhook(
        self, hass: HomeAssistant, webhook_id: str, request: web.Request,
    ) -> web.Response:
        """Handle secrets refresh webhook."""
        _LOGGER.info("Secrets refresh triggered via webhook")
        asyncio.create_task(self._load_secrets())
        return web.Response(status=202, text="Secrets refresh triggered")

    # ── Drift Detection ─────────────────────────────────────────────

    async def check_drift(self) -> None:
        """Check for uncommitted local changes."""
        if not self._repo:
            return
        try:
            if await self.hass.async_add_executor_job(self._repo.is_dirty):
                _LOGGER.info("Configuration drift detected (uncommitted changes)")
        except Exception as err:
            _LOGGER.error("Failed to check drift: %s", err)

    # ── Journal (crash recovery) ────────────────────────────────────

    async def check_deployment_journal(self) -> None:
        """Check for interrupted deployments on startup."""
        if not await self.hass.async_add_executor_job(self._journal_path.exists):
            return

        try:
            journal_data = json.loads(
                await self.hass.async_add_executor_job(self._journal_path.read_text)
            )
            if journal_data.get("status") == "started":
                _LOGGER.warning(
                    "Detected incomplete deployment from %s",
                    journal_data.get("timestamp"),
                )
                ir.async_create_issue(
                    self.hass, DOMAIN, "deployment_interrupted",
                    is_fixable=False, severity=ir.IssueSeverity.WARNING,
                    translation_key="deployment_interrupted",
                    translation_placeholders={
                        "timestamp": journal_data.get("timestamp", "unknown"),
                        "commit": journal_data.get("commit_sha", "unknown"),
                    },
                )
        except Exception as err:
            _LOGGER.error("Failed to read deployment journal: %s", err)

    # ── Helpers ──────────────────────────────────────────────────────

    def get_repo_url(self) -> str | None:
        """Get HTTPS URL for the repository (for compare links)."""
        if not self._repo:
            return None
        try:
            url = self._repo.remotes.origin.url
            # git@github.com:user/repo.git → https://github.com/user/repo
            if url.startswith("git@"):
                match = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", url)
                if match:
                    return f"https://{match.group(1)}/{match.group(2)}"
            if url.endswith(".git"):
                url = url[:-4]
            if url.startswith("https://"):
                return url
        except Exception:
            pass
        return None
