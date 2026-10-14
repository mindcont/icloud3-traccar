"""Allowlist diagnostics: never serialize entry.data, URLs or sync checkpoints."""
from .const import DOMAIN


async def async_get_config_entry_diagnostics(hass, entry):
    return hass.data[DOMAIN][entry.entry_id].status()
