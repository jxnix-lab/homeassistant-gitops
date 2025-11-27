"""Config flow for GitOps Integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_DRIFT_CHECK_INTERVAL,
    CONF_ENABLE_DRIFT_DETECTION,
    CONF_INFISICAL_CLIENT_ID,
    CONF_INFISICAL_CLIENT_SECRET,
    CONF_INFISICAL_ENVIRONMENT,
    CONF_INFISICAL_PATH,
    CONF_INFISICAL_PROJECT_ID,
    CONF_INFISICAL_URL,
    CONF_SECRETS_WEBHOOK_SECRET,
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_SECRET,
    DEFAULT_DRIFT_CHECK_INTERVAL,
    DEFAULT_INFISICAL_ENVIRONMENT,
    DEFAULT_INFISICAL_PATH,
    DEFAULT_INFISICAL_URL,
    DEFAULT_WEBHOOK_ID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _validate_infisical_sync(data: dict[str, Any]) -> dict[str, Any]:
    """Synchronous Infisical validation (runs in executor)."""
    import secrets as secrets_module
    from infisical_sdk import InfisicalSDKClient

    client = InfisicalSDKClient(host=data[CONF_INFISICAL_URL])
    client.auth.universal_auth.login(
        client_id=data[CONF_INFISICAL_CLIENT_ID],
        client_secret=data[CONF_INFISICAL_CLIENT_SECRET],
    )

    # Try to fetch secrets to validate credentials
    response = client.secrets.list_secrets(
        project_id=data[CONF_INFISICAL_PROJECT_ID],
        environment_slug=data[CONF_INFISICAL_ENVIRONMENT],
        secret_path=data[CONF_INFISICAL_PATH],
    )

    # Extract secrets list from response
    secrets = response.secrets if hasattr(response, 'secrets') else []

    # Look for existing webhook secrets
    webhook_secret = None
    secrets_webhook_secret = None

    for secret in secrets:
        if secret.secretKey == "GITOPS_WEBHOOK_SECRET":
            webhook_secret = secret.secretValue
            _LOGGER.info("Found existing GITOPS_WEBHOOK_SECRET in Infisical")
        elif secret.secretKey == "GITOPS_SECRETS_WEBHOOK_SECRET":
            secrets_webhook_secret = secret.secretValue
            _LOGGER.info("Found existing GITOPS_SECRETS_WEBHOOK_SECRET in Infisical")

    # Generate and store deployment webhook secret if not found
    if not webhook_secret:
        webhook_secret = secrets_module.token_urlsafe(32)
        _LOGGER.info("Generating new GITOPS_WEBHOOK_SECRET and storing in Infisical")

        client.secrets.create_secret_by_name(
            secret_name="GITOPS_WEBHOOK_SECRET",
            project_id=data[CONF_INFISICAL_PROJECT_ID],
            environment_slug=data[CONF_INFISICAL_ENVIRONMENT],
            secret_path=data[CONF_INFISICAL_PATH],
            secret_value=webhook_secret,
        )

    # Generate and store secrets refresh webhook secret if not found
    if not secrets_webhook_secret:
        secrets_webhook_secret = secrets_module.token_urlsafe(32)
        _LOGGER.info("Generating new GITOPS_SECRETS_WEBHOOK_SECRET and storing in Infisical")

        client.secrets.create_secret_by_name(
            secret_name="GITOPS_SECRETS_WEBHOOK_SECRET",
            project_id=data[CONF_INFISICAL_PROJECT_ID],
            environment_slug=data[CONF_INFISICAL_ENVIRONMENT],
            secret_path=data[CONF_INFISICAL_PATH],
            secret_value=secrets_webhook_secret,
        )

    return {
        "title": "GitOps",
        "webhook_secret": webhook_secret,
        "secrets_webhook_secret": secrets_webhook_secret,
    }


async def validate_infisical_connection(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, Any]:
    """Validate Infisical connection and fetch/generate webhook secret."""
    try:
        return await hass.async_add_executor_job(_validate_infisical_sync, data)
    except Exception as err:
        _LOGGER.error("Failed to connect to Infisical: %s", err)
        raise CannotConnect from err


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GitOps Integration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_infisical_connection(self.hass, user_input)
            except CannotConnect as err:
                errors["base"] = "cannot_connect"
                description_placeholders["error"] = str(err.__cause__) if err.__cause__ else str(err)
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
                description_placeholders["error"] = str(err)
            else:
                # Add webhook secrets to config data
                user_input[CONF_WEBHOOK_SECRET] = info["webhook_secret"]
                user_input[CONF_SECRETS_WEBHOOK_SECRET] = info["secrets_webhook_secret"]
                return self.async_create_entry(title=info["title"], data=user_input)

        # Use user_input for defaults if it exists (preserves values on error)
        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_WEBHOOK_ID,
                    default=user_input.get(CONF_WEBHOOK_ID, DEFAULT_WEBHOOK_ID) if user_input else DEFAULT_WEBHOOK_ID
                ): str,
                vol.Required(
                    CONF_INFISICAL_URL,
                    default=user_input.get(CONF_INFISICAL_URL, DEFAULT_INFISICAL_URL) if user_input else DEFAULT_INFISICAL_URL
                ): str,
                vol.Required(
                    CONF_INFISICAL_CLIENT_ID,
                    default=user_input.get(CONF_INFISICAL_CLIENT_ID, "") if user_input else ""
                ): str,
                vol.Required(
                    CONF_INFISICAL_CLIENT_SECRET,
                    default=user_input.get(CONF_INFISICAL_CLIENT_SECRET, "") if user_input else ""
                ): str,
                vol.Required(
                    CONF_INFISICAL_PROJECT_ID,
                    default=user_input.get(CONF_INFISICAL_PROJECT_ID, "") if user_input else ""
                ): str,
                vol.Required(
                    CONF_INFISICAL_ENVIRONMENT,
                    default=user_input.get(CONF_INFISICAL_ENVIRONMENT, DEFAULT_INFISICAL_ENVIRONMENT) if user_input else DEFAULT_INFISICAL_ENVIRONMENT
                ): str,
                vol.Required(
                    CONF_INFISICAL_PATH,
                    default=user_input.get(CONF_INFISICAL_PATH, DEFAULT_INFISICAL_PATH) if user_input else DEFAULT_INFISICAL_PATH
                ): str,
                vol.Optional(
                    CONF_ENABLE_DRIFT_DETECTION,
                    default=user_input.get(CONF_ENABLE_DRIFT_DETECTION, False) if user_input else False
                ): bool,
                vol.Optional(
                    CONF_DRIFT_CHECK_INTERVAL,
                    default=user_input.get(CONF_DRIFT_CHECK_INTERVAL, DEFAULT_DRIFT_CHECK_INTERVAL) if user_input else DEFAULT_DRIFT_CHECK_INTERVAL
                ): int,
            }
        )

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

        data_schema = vol.Schema(
            {
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
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
