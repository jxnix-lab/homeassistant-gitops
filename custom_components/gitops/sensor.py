"""Sensors for GitOps Integration."""
from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.sensor import SensorEntity
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
    """Set up GitOps sensors."""
    coordinator: GitOpsCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities([
        GitOpsDeploymentStatusSensor(coordinator),
        GitOpsCurrentCommitSensor(coordinator),
    ])


class GitOpsBaseSensor(SensorEntity):
    """Base class for GitOps sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GitOpsCoordinator) -> None:
        """Initialize the sensor."""
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


class GitOpsDeploymentStatusSensor(GitOpsBaseSensor):
    """Sensor for current deployment status."""

    _attr_name = "Deployment Status"
    _attr_unique_id = "gitops_deployment_status"
    _attr_icon = "mdi:rocket-launch"

    @property
    def native_value(self) -> str:
        """Return the state."""
        return self.coordinator.deployment_state.status

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional attributes."""
        state = self.coordinator.deployment_state
        attrs = {
            "commit_sha": state.commit_sha,
            "commit_message": state.commit_message,
            "timestamp": state.timestamp.isoformat() if state.timestamp else None,
            "changed_files": state.changed_files or [],
            "reload_domains": state.reload_domains or [],
            "restart_required": state.restart_required,
        }
        if state.error:
            attrs["error"] = state.error
        return attrs


class GitOpsCurrentCommitSensor(GitOpsBaseSensor):
    """Sensor for current git commit."""

    _attr_name = "Current Commit"
    _attr_unique_id = "gitops_current_commit"
    _attr_icon = "mdi:source-commit"

    @property
    def native_value(self) -> str | None:
        """Return the current commit SHA."""
        return self.coordinator.git_state.local_sha

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional attributes."""
        git = self.coordinator.git_state
        return {
            "message": git.local_message,
            "remote_sha": git.remote_sha,
            "commits_behind": git.commits_behind,
            "update_available": git.update_available,
            "last_check": git.last_check.isoformat() if git.last_check else None,
        }
