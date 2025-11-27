"""The GitOps Integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_DRIFT_CHECK_INTERVAL,
    CONF_ENABLE_DRIFT_DETECTION,
    DEFAULT_DRIFT_CHECK_INTERVAL,
    DOMAIN,
)
from .coordinator import GitOpsCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.UPDATE]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GitOps from a config entry."""
    _LOGGER.info("Setting up GitOps integration")

    # Create coordinator
    coordinator = GitOpsCoordinator(hass, entry)

    # Store coordinator
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Initialize coordinator
    await coordinator.async_setup()

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register startup handler for crash recovery
    async def handle_startup(event):
        """Handle Home Assistant startup."""
        await coordinator.check_deployment_journal()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, handle_startup)

    # Set up drift detection if enabled
    if entry.data.get(CONF_ENABLE_DRIFT_DETECTION, False):
        interval = entry.data.get(CONF_DRIFT_CHECK_INTERVAL, DEFAULT_DRIFT_CHECK_INTERVAL)

        async def check_drift(now):
            """Periodic drift check."""
            await coordinator.check_drift()

        entry.async_on_unload(
            async_track_time_interval(hass, check_drift, timedelta(seconds=interval))
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading GitOps integration")

    # Unload platforms
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
