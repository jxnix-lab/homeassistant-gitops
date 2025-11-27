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

    entities = [
        GitOpsDeploymentStatusSensor(coordinator),
        GitOpsCurrentCommitSensor(coordinator),
    ]

    async_add_entities(entities)


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
                self.hass,
                f"{DOMAIN}_update",
                self._handle_coordinator_update,
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class GitOpsDeploymentStatusSensor(GitOpsBaseSensor):
    """Sensor for current deployment status."""

    _attr_name = "Deployment Status"
    _attr_unique_id = "gitops_deployment_status"
    _attr_icon = "mdi:git"

    @property
    def native_value(self) -> str:
        """Return the state."""
        return self.coordinator.deployment_state.status

    @property
    def extra_state_attributes(self) -> dict[str, any]:
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
        """Return the state."""
        if self.coordinator._repo:
            return self.coordinator._repo.head.commit.hexsha[:7]
        return None

    @property
    def extra_state_attributes(self) -> dict[str, any]:
        """Return additional attributes."""
        if not self.coordinator._repo:
            return {}

        commit = self.coordinator._repo.head.commit
        return {
            "full_sha": commit.hexsha,
            "message": commit.message.strip(),
            "author": str(commit.author),
            "timestamp": datetime.fromtimestamp(commit.committed_date).isoformat(),
        }


