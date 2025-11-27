"""GitOps coordinator for managing deployments and state."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import git
from aiohttp import web
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from infisical_sdk import InfisicalSDKClient
import yaml

from .const import (
    CONF_INFISICAL_CLIENT_ID,
    CONF_INFISICAL_CLIENT_SECRET,
    CONF_INFISICAL_ENVIRONMENT,
    CONF_INFISICAL_PATH,
    CONF_INFISICAL_PROJECT_ID,
    CONF_INFISICAL_URL,
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_SECRET,
    DOMAIN,
    RELOAD_PATTERNS,
    REPAIR_GIT_CONNECTION,
    REPAIR_GIT_LOCK,
    REPAIR_INFISICAL_CONNECTION,
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
        self._repo: git.Repo | None = None
        self._infisical_client: InfisicalSDKClient | None = None
        self._journal_path = Path("/config/.gitops_journal.json")
        self._loaded_integration_version: str | None = None

    async def async_setup(self) -> None:
        """Set up the coordinator."""
        # Initialize git repository
        try:
            self._repo = await self.hass.async_add_executor_job(
                git.Repo, "/config"
            )
            _LOGGER.info("Git repository initialized at /config")
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

        # Initialize Infisical client
        await self._setup_infisical()

        # Load secrets on startup
        await self._load_secrets()

        # Track current integration version
        await self._track_integration_version()

        # Register deployment webhook
        webhook.async_register(
            self.hass,
            DOMAIN,
            "GitOps Deployment",
            self.config_entry.data[CONF_WEBHOOK_ID],
            self._handle_deployment_webhook,
        )
        _LOGGER.info(
            "Deployment webhook registered: %s", self.config_entry.data[CONF_WEBHOOK_ID]
        )

        # Register secrets refresh webhook (unauthenticated - just triggers a refresh)
        webhook.async_register(
            self.hass,
            DOMAIN,
            "GitOps Secrets Refresh",
            "gitops-secrets-refresh",
            self._handle_secrets_webhook,
        )
        _LOGGER.info("Secrets refresh webhook registered: gitops-secrets-refresh")

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        # Unregister webhooks
        webhook.async_unregister(
            self.hass, self.config_entry.data[CONF_WEBHOOK_ID]
        )
        webhook.async_unregister(self.hass, "gitops-secrets-refresh")

    async def _setup_infisical(self) -> None:
        """Set up Infisical client."""
        try:
            self._infisical_client = await self.hass.async_add_executor_job(
                self._create_infisical_client
            )
            _LOGGER.info("Infisical client initialized")
        except Exception as err:
            _LOGGER.error("Failed to initialize Infisical client: %s", err)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                REPAIR_INFISICAL_CONNECTION,
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="infisical_connection_failed",
                translation_placeholders={"error": str(err)},
            )

    def _create_infisical_client(self) -> InfisicalSDKClient:
        """Create and authenticate Infisical client."""
        client = InfisicalSDKClient(
            host=self.config_entry.data[CONF_INFISICAL_URL]
        )
        client.auth.universal_auth.login(
            client_id=self.config_entry.data[CONF_INFISICAL_CLIENT_ID],
            client_secret=self.config_entry.data[CONF_INFISICAL_CLIENT_SECRET],
        )
        return client

    async def _load_secrets(self) -> None:
        """Load secrets from Infisical and write to secrets_infisical.yaml."""
        if not self._infisical_client:
            _LOGGER.warning("Infisical client not initialized, skipping secret sync")
            return

        try:
            # Fetch secrets
            secrets = await self.hass.async_add_executor_job(
                self._fetch_infisical_secrets
            )

            # Write to secrets_infisical.yaml
            await self._write_infisical_secrets_file(secrets)

            # Ensure secrets.yaml includes secrets_infisical.yaml
            await self._ensure_secrets_yaml_includes_infisical()

            _LOGGER.info("Successfully synced %d secrets from Infisical", len(secrets))

        except Exception as err:
            _LOGGER.error("Failed to load secrets from Infisical: %s", err)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                REPAIR_INFISICAL_CONNECTION,
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="infisical_sync_failed",
                translation_placeholders={"error": str(err)},
            )

    def _fetch_infisical_secrets(self) -> list[dict[str, str]]:
        """Fetch secrets from Infisical."""
        response = self._infisical_client.secrets.list_secrets(
            project_id=self.config_entry.data[CONF_INFISICAL_PROJECT_ID],
            environment_slug=self.config_entry.data[CONF_INFISICAL_ENVIRONMENT],
            secret_path=self.config_entry.data[CONF_INFISICAL_PATH],
        )
        secrets = response.secrets if hasattr(response, 'secrets') else []
        return [{"name": s.secretKey, "value": s.secretValue} for s in secrets]

    async def _write_infisical_secrets_file(
        self, secrets: list[dict[str, str]]
    ) -> None:
        """Write Infisical secrets to dedicated YAML file."""
        secrets_path = Path("/config/secrets_infisical.yaml")

        # Build YAML content
        content = "# Managed by GitOps Integration - DO NOT EDIT MANUALLY\n"
        content += f"# Synced from Infisical at {datetime.now(UTC).isoformat()}\n"
        content += f"# Source: {self.config_entry.data[CONF_INFISICAL_PATH]} path in {self.config_entry.data[CONF_INFISICAL_ENVIRONMENT]} environment\n\n"

        # Add each secret
        secrets_dict = {s["name"]: s["value"] for s in secrets}
        content += yaml.safe_dump(secrets_dict, default_flow_style=False)

        # Atomic write (write to temp file, then rename)
        temp_path = secrets_path.with_suffix(".tmp")
        await self.hass.async_add_executor_job(temp_path.write_text, content)
        await self.hass.async_add_executor_job(temp_path.rename, secrets_path)

        _LOGGER.debug("Wrote secrets to %s", secrets_path)

    async def _ensure_secrets_yaml_includes_infisical(self) -> None:
        """Add include directive to secrets.yaml if not present."""
        secrets_yaml = Path("/config/secrets.yaml")
        include_line = "<<: !include secrets_infisical.yaml\n"

        if not await self.hass.async_add_executor_job(secrets_yaml.exists):
            # Create new secrets.yaml with include
            content = (
                "# Infisical secrets (managed by GitOps integration)\n"
                + include_line
                + "\n# Your manual secrets here\n"
            )
            await self.hass.async_add_executor_job(secrets_yaml.write_text, content)
            _LOGGER.info("Created secrets.yaml with Infisical include")
        else:
            # Check if include already present
            content = await self.hass.async_add_executor_job(secrets_yaml.read_text)
            if "secrets_infisical.yaml" not in content:
                # Prepend include to existing file
                new_content = (
                    "# Infisical secrets (managed by GitOps integration)\n"
                    + include_line
                    + "\n# Existing secrets\n"
                    + content
                )
                await self.hass.async_add_executor_job(
                    secrets_yaml.write_text, new_content
                )
                _LOGGER.info("Added Infisical include to existing secrets.yaml")

    async def _handle_secrets_webhook(
        self,
        hass: HomeAssistant,
        webhook_id: str,
        request: web.Request,
    ) -> web.Response:
        """Handle incoming webhook from Infisical for secrets refresh."""
        _LOGGER.info("Secrets refresh webhook triggered, reloading secrets from Infisical")

        # Trigger secrets reload in background
        asyncio.create_task(self._load_secrets())

        return web.Response(status=202, text="Secrets refresh triggered")

    async def _handle_deployment_webhook(
        self,
        hass: HomeAssistant,
        webhook_id: str,
        request: web.Request,
    ) -> web.Response:
        """Handle incoming webhook from GitHub Actions."""
        # Verify webhook secret
        signature = request.headers.get("X-Hub-Signature-256")
        if not signature:
            _LOGGER.warning("Webhook received without signature")
            return web.Response(status=401, text="Missing signature")

        body = await request.read()
        expected_signature = (
            "sha256="
            + hmac.new(
                self.config_entry.data[CONF_WEBHOOK_SECRET].encode(),
                body,
                hashlib.sha256,
            ).hexdigest()
        )

        if not hmac.compare_digest(signature, expected_signature):
            _LOGGER.warning(
                "Webhook signature verification failed. Received: %s, Expected: %s, Body length: %d",
                signature,
                expected_signature,
                len(body),
            )
            return web.Response(status=401, text="Invalid signature")

        # Parse payload from body (already read for signature verification)
        try:
            import json
            payload = json.loads(body.decode())
        except Exception as err:
            _LOGGER.error("Failed to parse webhook payload: %s", err)
            return web.Response(status=400, text="Invalid JSON")

        # Execute deployment and stream progress via SSE
        response = web.StreamResponse()
        response.headers["Content-Type"] = "text/event-stream"
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Connection"] = "keep-alive"
        await response.prepare(request)

        try:
            # Stream deployment progress
            async for event in self._deploy_with_progress(payload):
                await response.write(f"data: {event}\n\n".encode())

            await response.write_eof()
            return response
        except Exception as err:
            _LOGGER.error("Deployment streaming failed: %s", err)
            await response.write(f"data: {{\"status\":\"error\",\"error\":\"{str(err)}\"}}\n\n".encode())
            await response.write_eof()
            return response

    async def _deploy_with_progress(self, payload: dict[str, Any]):
        """Execute deployment and yield progress updates as JSON."""
        import json

        async with self._deployment_lock:
            self._deployment_state.status = STATE_DEPLOYING
            self._deployment_state.timestamp = datetime.now(UTC)
            self._deployment_state.error = None

            yield json.dumps({"status": "started", "message": "Deployment started"})

            # Write deployment journal
            await self._write_journal("started", payload)

            try:
                # Check for git lock file
                lock_file = Path("/config/.git/index.lock")
                if await self.hass.async_add_executor_job(lock_file.exists):
                    error_msg = "Git lock file detected"
                    _LOGGER.error(error_msg)
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        REPAIR_GIT_LOCK,
                        is_fixable=True,
                        severity=ir.IssueSeverity.ERROR,
                        translation_key="git_lock_detected",
                    )
                    self._deployment_state.status = STATE_FAILED
                    self._deployment_state.error = error_msg
                    await self._write_journal("failed", payload, error="git_lock")
                    yield json.dumps({"status": "failed", "error": error_msg})
                    return

                # Pull latest changes
                yield json.dumps({"status": "pulling", "message": "Pulling latest changes from git"})
                _LOGGER.info("Pulling latest changes from git")
                changed_files = await self._git_pull()
                self._deployment_state.changed_files = changed_files

                # Get commit info
                commit = await self.hass.async_add_executor_job(
                    lambda: self._repo.head.commit
                )
                self._deployment_state.commit_sha = commit.hexsha[:7]
                self._deployment_state.commit_message = commit.message.strip()

                yield json.dumps({
                    "status": "pulled",
                    "commit_sha": self._deployment_state.commit_sha,
                    "commit_message": self._deployment_state.commit_message,
                    "changed_files": changed_files
                })

                # Validate configuration
                self._deployment_state.status = STATE_VALIDATING
                yield json.dumps({"status": "validating", "message": "Validating Home Assistant configuration"})
                _LOGGER.info("Validating Home Assistant configuration")
                await self._validate_config()
                yield json.dumps({"status": "validated", "message": "Configuration is valid"})

                # Determine what needs to reload
                self._deployment_state.status = STATE_RELOADING
                reload_domains = await self._determine_reload_domains(changed_files)
                self._deployment_state.reload_domains = reload_domains

                # Check if restart required
                restart_required = await self._check_restart_required(changed_files)
                self._deployment_state.restart_required = restart_required

                if restart_required:
                    _LOGGER.warning("Restart required for changes to take effect")
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        REPAIR_RESTART_REQUIRED,
                        is_fixable=False,
                        severity=ir.IssueSeverity.WARNING,
                        translation_key="restart_required",
                        translation_placeholders={
                            "commit": self._deployment_state.commit_sha,
                            "message": self._deployment_state.commit_message,
                        },
                    )
                    self._deployment_state.status = STATE_RESTART_REQUIRED
                    yield json.dumps({
                        "status": "restart_required",
                        "message": "Restart required for changes to take effect",
                        "commit_sha": self._deployment_state.commit_sha,
                        "commit_message": self._deployment_state.commit_message
                    })
                else:
                    # Execute reloads
                    yield json.dumps({"status": "reloading", "message": f"Reloading domains: {', '.join(reload_domains)}"})
                    _LOGGER.info("Reloading domains: %s", reload_domains)
                    await self._execute_reloads(reload_domains)
                    self._deployment_state.status = STATE_SUCCESS
                    yield json.dumps({
                        "status": "success",
                        "message": "Deployment completed successfully",
                        "reloaded_domains": reload_domains
                    })

                await self._write_journal("success", payload)
                _LOGGER.info("Deployment completed successfully")

                # Check if integration was updated
                await self._check_integration_update()

            except Exception as err:
                _LOGGER.error("Deployment failed: %s", err, exc_info=True)
                self._deployment_state.status = STATE_FAILED
                self._deployment_state.error = str(err)
                await self._write_journal("failed", payload, error=str(err))
                yield json.dumps({"status": "failed", "error": str(err)})

            finally:
                # Update sensors
                async_dispatcher_send(self.hass, f"{DOMAIN}_update")

    async def _deploy(self, payload: dict[str, Any]) -> None:
        """Execute deployment."""
        async with self._deployment_lock:
            self._deployment_state.status = STATE_DEPLOYING
            self._deployment_state.timestamp = datetime.now(UTC)
            self._deployment_state.error = None

            # Write deployment journal
            await self._write_journal("started", payload)

            try:
                # Check for git lock file
                lock_file = Path("/config/.git/index.lock")
                if await self.hass.async_add_executor_job(lock_file.exists):
                    _LOGGER.error("Git lock file exists, creating repair issue")
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        REPAIR_GIT_LOCK,
                        is_fixable=True,
                        severity=ir.IssueSeverity.ERROR,
                        translation_key="git_lock_detected",
                    )
                    self._deployment_state.status = STATE_FAILED
                    self._deployment_state.error = "Git lock file detected"
                    await self._write_journal("failed", payload, error="git_lock")
                    return

                # Pull latest changes
                _LOGGER.info("Pulling latest changes from git")
                changed_files = await self._git_pull()
                self._deployment_state.changed_files = changed_files

                # Get commit info
                commit = await self.hass.async_add_executor_job(
                    lambda: self._repo.head.commit
                )
                self._deployment_state.commit_sha = commit.hexsha[:7]
                self._deployment_state.commit_message = commit.message.strip()

                # Validate configuration
                self._deployment_state.status = STATE_VALIDATING
                _LOGGER.info("Validating Home Assistant configuration")
                await self._validate_config()

                # Determine what needs to reload
                self._deployment_state.status = STATE_RELOADING
                reload_domains = await self._determine_reload_domains(changed_files)
                self._deployment_state.reload_domains = reload_domains

                # Check if restart required
                restart_required = await self._check_restart_required(changed_files)
                self._deployment_state.restart_required = restart_required

                if restart_required:
                    _LOGGER.warning("Restart required for changes to take effect")
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        REPAIR_RESTART_REQUIRED,
                        is_fixable=False,
                        severity=ir.IssueSeverity.WARNING,
                        translation_key="restart_required",
                        translation_placeholders={
                            "commit": self._deployment_state.commit_sha,
                            "message": self._deployment_state.commit_message,
                        },
                    )
                    self._deployment_state.status = STATE_RESTART_REQUIRED
                else:
                    # Execute reloads
                    _LOGGER.info("Reloading domains: %s", reload_domains)
                    await self._execute_reloads(reload_domains)
                    self._deployment_state.status = STATE_SUCCESS

                await self._write_journal("success", payload)
                _LOGGER.info("Deployment completed successfully")

                # Check if integration was updated
                await self._check_integration_update()

            except Exception as err:
                _LOGGER.error("Deployment failed: %s", err, exc_info=True)
                self._deployment_state.status = STATE_FAILED
                self._deployment_state.error = str(err)
                await self._write_journal("failed", payload, error=str(err))

            finally:
                # Update sensors
                async_dispatcher_send(self.hass, f"{DOMAIN}_update")

    async def _git_pull(self) -> list[str]:
        """Pull latest changes and return list of changed files."""
        # Get current commit
        old_commit = self._repo.head.commit

        # Pull changes
        await self.hass.async_add_executor_job(
            self._repo.remotes.origin.pull, "homeassistant"
        )

        # Get new commit
        new_commit = self._repo.head.commit

        # Get diff
        if old_commit != new_commit:
            diff = old_commit.diff(new_commit)
            changed_files = [item.a_path for item in diff]
            _LOGGER.info("Changed files: %s", changed_files)
            return changed_files

        return []

    async def _validate_config(self) -> None:
        """Validate Home Assistant configuration."""
        # Use Home Assistant's config check service
        try:
            await self.hass.services.async_call(
                "homeassistant", "check_config", blocking=True
            )
            _LOGGER.info("Configuration validation passed")
        except Exception as err:
            _LOGGER.error("Configuration validation failed: %s", err)
            raise RuntimeError(f"Config validation failed: {err}") from err

    async def _determine_reload_domains(
        self, changed_files: list[str]
    ) -> list[str]:
        """Determine which domains need to be reloaded."""
        domains = set()

        for domain, patterns in RELOAD_PATTERNS.items():
            for pattern in patterns:
                for changed_file in changed_files:
                    if self._match_pattern(changed_file, pattern):
                        domains.add(domain)
                        break

        return list(domains)

    async def _check_restart_required(self, changed_files: list[str]) -> bool:
        """Check if any changed files require a full restart."""
        for pattern in RESTART_REQUIRED_PATTERNS:
            for changed_file in changed_files:
                if self._match_pattern(changed_file, pattern):
                    return True
        return False

    def _match_pattern(self, filepath: str, pattern: str) -> bool:
        """Match file path against pattern (supports wildcards)."""
        from fnmatch import fnmatch

        return fnmatch(filepath, pattern)

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

    async def _write_journal(
        self,
        status: str,
        payload: dict[str, Any],
        error: str | None = None,
    ) -> None:
        """Write deployment journal for crash recovery."""
        journal_data = {
            "status": status,
            "timestamp": datetime.now(UTC).isoformat(),
            "commit_sha": self._deployment_state.commit_sha,
            "commit_message": self._deployment_state.commit_message,
            "payload": payload,
            "error": error,
        }

        await self.hass.async_add_executor_job(
            self._journal_path.write_text, json.dumps(journal_data, indent=2)
        )

    async def check_deployment_journal(self) -> None:
        """Check deployment journal on startup for crash recovery."""
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
                    self.hass,
                    DOMAIN,
                    "deployment_interrupted",
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="deployment_interrupted",
                    translation_placeholders={
                        "timestamp": journal_data.get("timestamp", "unknown"),
                        "commit": journal_data.get("commit_sha", "unknown"),
                    },
                )

        except Exception as err:
            _LOGGER.error("Failed to read deployment journal: %s", err)

    async def check_drift(self) -> None:
        """Check for configuration drift."""
        if not self._repo:
            return

        try:
            # Check for uncommitted changes
            if await self.hass.async_add_executor_job(self._repo.is_dirty):
                _LOGGER.info("Detected configuration drift")
                # Trigger drift detection workflow
                # This would create a PR via GitHub API
                # Implementation TBD based on requirements

        except Exception as err:
            _LOGGER.error("Failed to check drift: %s", err)

    async def _track_integration_version(self) -> None:
        """Track the current integration code SHA."""
        if not self._repo:
            return

        try:
            # Get the git SHA of the custom_components/gitops directory
            integration_sha = await self.hass.async_add_executor_job(
                self._repo.git.log,
                "-1",
                "--format=%H",
                "--",
                "custom_components/gitops/"
            )
            self._loaded_integration_version = integration_sha.strip()
            _LOGGER.info("Tracking integration code SHA: %s", self._loaded_integration_version[:7])
        except Exception as err:
            _LOGGER.error("Failed to track integration version: %s", err)

    async def _check_integration_update(self) -> None:
        """Check if integration files were updated and need reload."""
        if not self._repo or not self._loaded_integration_version:
            return

        try:
            # Check if custom_components/gitops files changed
            diff = self._repo.git.diff("HEAD~1", "HEAD", "--name-only")
            changed_files = diff.split("\n") if diff else []

            integration_files_changed = any(
                f.startswith("custom_components/gitops/") for f in changed_files
            )

            if not integration_files_changed:
                return

            # Get current integration SHA
            current_sha = await self.hass.async_add_executor_job(
                self._repo.git.log,
                "-1",
                "--format=%H",
                "--",
                "custom_components/gitops/"
            )
            current_sha = current_sha.strip()

            # If SHA changed, create repair issue
            if current_sha != self._loaded_integration_version:
                _LOGGER.warning(
                    "Integration updated from %s to %s, reload recommended",
                    self._loaded_integration_version[:7],
                    current_sha[:7],
                )

                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    "integration_needs_reload",
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="integration_needs_reload",
                    translation_placeholders={
                        "old_version": self._loaded_integration_version[:7],
                        "new_version": current_sha[:7],
                    },
                )

        except Exception as err:
            _LOGGER.error("Failed to check integration update: %s", err)

    @property
    def deployment_state(self) -> DeploymentState:
        """Get current deployment state."""
        return self._deployment_state
