"""Separate configuration and explicit history actions; never touch Apple login."""
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .api import TraccarClient
from .const import DEFAULTS, DOMAIN
from .models import SyncError, timestamp, validate_url
from .source import Source


def settings_schema(hass, config):
    fields = {}
    for key in ("enabled", "upload_speed", "upload_course", "upload_battery", "upload_accuracy"):
        fields[vol.Optional(key, default=config.get(key, DEFAULTS[key]))] = bool
    for key in ("server_url", "receiver_url"):
        fields[vol.Optional(key, default=config.get(key, ""))] = str
    # Deliberately NEVER set a token default or include it in placeholders.
    fields[vol.Optional("token")] = selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))
    fields[vol.Optional("interval", default=config.get("interval", 30))] = vol.All(
        vol.Coerce(int), vol.Range(min=5, max=3600))
    fields[vol.Optional("min_distance", default=config.get("min_distance", 0))] = vol.All(
        vol.Coerce(float), vol.Range(min=0, max=100000))
    fields[vol.Optional("retries", default=config.get("retries", 3))] = vol.All(
        vol.Coerce(int), vol.Range(min=0, max=10))
    fields[vol.Optional("devices", default=config.get("devices", []))] = device_selector(hass)
    return vol.Schema(fields)


def device_selector(hass):
    return selector.SelectSelector(selector.SelectSelectorConfig(
        options=[{"value": uid, "label": f"{d.name} ({uid})"}
                 for uid, d in Source(hass).devices().items()], multiple=True))


async def validate(hass, user_input, existing=None):
    data = dict(DEFAULTS, **(existing or {}))
    data.update(user_input)
    if not user_input.get("token") and existing:
        data["token"] = existing.get("token", "")
    for key in ("server_url", "receiver_url", "token"):
        data[key] = data.get(key, "").strip()
    complete = all(data.get(k) for k in ("server_url", "receiver_url", "token"))
    if not complete:
        if data["enabled"] or any(data.get(k) for k in ("server_url", "receiver_url", "token")):
            raise ValueError("missing_connection")
        return data
    data["server_url"] = validate_url(data["server_url"])
    data["receiver_url"] = validate_url(data["receiver_url"])
    if "\n" in data["token"] or "\r" in data["token"]:
        raise ValueError("invalid_token")
    await TraccarClient(async_get_clientsession(hass), data).validate()
    return data


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors = {}
        if user_input is not None:
            try:
                data = await validate(self.hass, user_input)
            except (SyncError, ValueError) as error:
                errors["base"] = error.code if isinstance(error, SyncError) else str(error)
            else:
                return self.async_create_entry(title="iCloud3 Traccar", data=data)
        return self.async_show_form(step_id="user", data_schema=settings_schema(self.hass, {}),
                                    errors=errors,
                                    description_placeholders={"token_status": "未配置 / Not configured"})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow(config_entry)


class OptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry):
        self.entry = entry

    @property
    def coordinator(self):
        return self.hass.data[DOMAIN][self.entry.entry_id]

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=[
            "settings", "history", "resume", "pause", "cancel", "status"])

    async def async_step_settings(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                data = await validate(self.hass, user_input, self.entry.data)
            except (SyncError, ValueError) as error:
                errors["base"] = error.code if isinstance(error, SyncError) else str(error)
            else:
                self.hass.config_entries.async_update_entry(self.entry, data=data)
                return self.async_create_entry(title="", data={})
        return self.async_show_form(
            step_id="settings", data_schema=settings_schema(self.hass, self.entry.data),
            errors=errors, description_placeholders={
                "token_status": "已配置 / Configured" if self.entry.data.get("token") else "未配置 / Not configured"})

    async def async_step_history(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                if not all(self.entry.data.get(k) for k in ("server_url", "receiver_url", "token")):
                    raise ValueError("missing_connection")
                # Require explicit UTC offset; HA local datetime selectors omit it.
                timestamp(user_input["start"])
                timestamp(user_input["end"])
                await self.coordinator.start_history(user_input)
            except (SyncError, ValueError) as error:
                errors["base"] = "invalid_range" if isinstance(error, SyncError) else str(error)
            else:
                return self.async_create_entry(title="", data={})
        schema = vol.Schema({
            vol.Required("start"): str, vol.Required("end"): str,
            vol.Optional("devices", default=[]): device_selector(self.hass),
            vol.Optional("skip_duplicates", default=True): bool,
            vol.Optional("batch_size", default=100): vol.All(vol.Coerce(int), vol.Range(min=1, max=1000)),
            vol.Optional("allow_reimport", default=False): bool,
        })
        return self.async_show_form(step_id="history", data_schema=schema, errors=errors)

    async def async_step_resume(self, user_input=None):
        try:
            await self.coordinator.resume_history()
        except ValueError as error:
            return self.async_abort(reason=str(error))
        return self.async_create_entry(title="", data={})

    async def async_step_pause(self, user_input=None):
        await self.coordinator.pause_history()
        return self.async_create_entry(title="", data={})

    async def async_step_cancel(self, user_input=None):
        await self.coordinator.pause_history(cancel=True)
        return self.async_create_entry(title="", data={})

    async def async_step_status(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data={})
        import json
        return self.async_show_form(step_id="status", data_schema=vol.Schema({}),
                                    description_placeholders={
                                        "status": json.dumps(self.coordinator.status(), ensure_ascii=False)})
