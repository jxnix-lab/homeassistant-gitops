"""Config flow for GitOps Integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_DOPPLER_API_URL,
    CONF_DOPPLER_SERVICE_TOKEN,
    CONF_DRIFT_CHECK_INTERVAL,
    CONF_ENABLE_DRIFT_DETECTION,
    CONF_UPDATE_CHECK_INTERVAL,
    DEFAULT_DOPPLER_API_URL,
    DEFAULT_DRIFT_CHECK_INTERVAL,
    DEFAULT_UPDATE_CHECK_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def validate_doppler_connection(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, Any]:
    """Validate Doppler service token and return project info."""
    session = async_get_clientsession(hass)
    api_url = data.get(CONF_DOPPLER_API_URL, DEFAULT_DOPPLER_API_URL)
    token = data[CONF_DOPPLER_SERVICE_TOKEN]

    url = f"{api_url}/v3/configs/config/secrets/download"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    try:
        async with session.get(url, headers=headers, params={"format": "json"}) as resp:
            if resp.status == 401:
                raise CannotConnect("Invalid service token")
            if resp.status == 403:
                raise CannotConnect("Token does not have access to this config")
            if resp.status != 200:
                text = await resp.text()
                raise CannotConnect(f"HTTP {resp.status}: {text}")
            secrets = await resp.json()
    except aiohttp.ClientError as err:
        raise CannotConnect(f"Connection failed: {err}") from err

    project = secrets.get("DOPPLER_PROJECT", "unknown")
    config = secrets.get("DOPPLER_CONFIG", "unknown")
    secret_count = len([k for k in secrets if not k.startswith("DOPPLER_")])

    return {
        "title": f"GitOps ({project}/{config})",
        "project": project,
        "config": config,
        "secret_count": secret_count,
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GitOps Integration."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_doppler_connection(self.hass, user_input)
            except CannotConnect as err:
                errors["base"] = "cannot_connect"
                description_placeholders["error"] = str(err)
            except Exception as err:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
                description_placeholders["error"] = str(err)
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        defaults = user_input or {}

        data_schema = vol.Schema({
            vol.Required(
                CONF_DOPPLER_SERVICE_TOKEN,
                default=defaults.get(CONF_DOPPLER_SERVICE_TOKEN, ""),
            ): str,
            vol.Optional(
                CONF_DOPPLER_API_URL,
                default=defaults.get(CONF_DOPPLER_API_URL, DEFAULT_DOPPLER_API_URL),
            ): str,
            vol.Optional(
                CONF_UPDATE_CHECK_INTERVAL,
                default=defaults.get(CONF_UPDATE_CHECK_INTERVAL, DEFAULT_UPDATE_CHECK_INTERVAL),
            ): int,
            vol.Optional(
                CONF_ENABLE_DRIFT_DETECTION,
                default=defaults.get(CONF_ENABLE_DRIFT_DETECTION, False),
            ): bool,
            vol.Optional(
                CONF_DRIFT_CHECK_INTERVAL,
                default=defaults.get(CONF_DRIFT_CHECK_INTERVAL, DEFAULT_DRIFT_CHECK_INTERVAL),
            ): int,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for GitOps Integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data_schema = vol.Schema({
            vol.Optional(
                CONF_UPDATE_CHECK_INTERVAL,
                default=self.config_entry.data.get(
                    CONF_UPDATE_CHECK_INTERVAL, DEFAULT_UPDATE_CHECK_INTERVAL
                ),
            ): int,
            vol.Optional(
                CONF_ENABLE_DRIFT_DETECTION,
                default=self.config_entry.data.get(CONF_ENABLE_DRIFT_DETECTION, False),
            ): bool,
            vol.Optional(
                CONF_DRIFT_CHECK_INTERVAL,
                default=self.config_entry.data.get(
                    CONF_DRIFT_CHECK_INTERVAL, DEFAULT_DRIFT_CHECK_INTERVAL
                ),
            ): int,
        })

        return self.async_show_form(step_id="init", data_schema=data_schema)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
