"""The GitOps Integration."""
from __future__ import annotations

import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_DRIFT_CHECK_INTERVAL,
    CONF_ENABLE_DRIFT_DETECTION,
    CONF_UPDATE_CHECK_INTERVAL,
    DEFAULT_DRIFT_CHECK_INTERVAL,
    DEFAULT_UPDATE_CHECK_INTERVAL,
    DOMAIN,
)
from .coordinator import GitOpsCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.UPDATE]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GitOps from a config entry."""
    _LOGGER.info("Setting up GitOps integration")

    coordinator = GitOpsCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await coordinator.async_setup()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ── Services ────────────────────────────────────────────────

    async def handle_deploy(call: ServiceCall) -> None:
        """Pull latest config, sync secrets, validate, and reload."""
        await coordinator.async_deploy()

    async def handle_check_updates(call: ServiceCall) -> None:
        """Fetch from remote and check for available updates."""
        await coordinator.async_check_for_updates()

    hass.services.async_register(DOMAIN, "deploy", handle_deploy)
    hass.services.async_register(DOMAIN, "check_updates", handle_check_updates)

    # ── Periodic update check ───────────────────────────────────

    interval = entry.data.get(
        CONF_UPDATE_CHECK_INTERVAL, DEFAULT_UPDATE_CHECK_INTERVAL
    )

    async def periodic_update_check(now):
        await coordinator.async_check_for_updates()

    entry.async_on_unload(
        async_track_time_interval(
            hass, periodic_update_check, timedelta(seconds=interval)
        )
    )

    # ── Drift detection ─────────────────────────────────────────

    if entry.data.get(CONF_ENABLE_DRIFT_DETECTION, False):
        drift_interval = entry.data.get(
            CONF_DRIFT_CHECK_INTERVAL, DEFAULT_DRIFT_CHECK_INTERVAL
        )

        async def check_drift(now):
            await coordinator.check_drift()

        entry.async_on_unload(
            async_track_time_interval(
                hass, check_drift, timedelta(seconds=drift_interval)
            )
        )

    # ── Startup handler ─────────────────────────────────────────

    async def handle_startup(event):
        await coordinator.check_deployment_journal()
        await coordinator.async_check_for_updates()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, handle_startup)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading GitOps integration")

    if unload_ok := await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    ):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()

        hass.services.async_remove(DOMAIN, "deploy")
        hass.services.async_remove(DOMAIN, "check_updates")

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
