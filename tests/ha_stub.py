"""Small HA adapter doubles for offline tests, NOT a Home Assistant runtime."""
import sys
import types
from pathlib import Path


def module(name, **attrs):
    result = types.ModuleType(name)
    result.__path__ = []
    result.__dict__.update(attrs)
    sys.modules[name] = result
    if "." in name:
        parent, child = name.rsplit(".", 1)
        setattr(sys.modules[parent], child, result)
    return result


def install():
    module("homeassistant")
    module("homeassistant.core", callback=lambda f: f)
    module("homeassistant.const", EVENT_HOMEASSISTANT_STOP="homeassistant_stop")
    module("homeassistant.helpers")
    module("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: hass.session)
    module("homeassistant.helpers.device_registry", async_get=lambda hass: hass.devices)
    module("homeassistant.helpers.entity_registry", async_get=lambda hass: hass.entities)
    module("homeassistant.helpers.entity", EntityCategory=types.SimpleNamespace(DIAGNOSTIC="diagnostic"))
    module("homeassistant.helpers.event", async_track_time_interval=lambda *args: lambda: None)
    module("homeassistant.helpers.storage", Store=lambda hass, *args: hass.store)
    module("homeassistant.components")
    module("homeassistant.components.sensor", SensorEntity=type("SensorEntity", (), {}))
    module("homeassistant.components.recorder", get_instance=lambda hass: hass.recorder)
    module("homeassistant.components.recorder.history", get_significant_states=lambda *args, **kwargs: {})

    class Selector:
        def __init__(self, config):
            self.config = config
        def __call__(self, value):
            return value

    module("homeassistant.helpers.selector", TextSelector=Selector, TextSelectorConfig=dict,
           TextSelectorType=types.SimpleNamespace(PASSWORD="password"),
           SelectSelector=Selector, SelectSelectorConfig=dict)

    class Flow:
        def __init_subclass__(cls, **kwargs):
            pass
        async def async_set_unique_id(self, value):
            self.unique_id = value
        def _abort_if_unique_id_configured(self):
            pass
        def async_show_form(self, **kwargs):
            return dict(type="form", **kwargs)
        def async_show_menu(self, **kwargs):
            return dict(type="menu", **kwargs)
        def async_create_entry(self, **kwargs):
            return dict(type="create_entry", **kwargs)
        def async_abort(self, **kwargs):
            return dict(type="abort", **kwargs)
    module("homeassistant.config_entries", ConfigFlow=Flow, OptionsFlow=Flow)


# Core-only tests import a namespace package to avoid loading HA's integration adapter.
def namespace():
    root = Path(__file__).resolve().parents[1]
    if "custom_components" not in sys.modules:
        module("custom_components").__path__ = [str(root / "custom_components")]
    if "custom_components.icloud3_traccar" not in sys.modules:
        module("custom_components.icloud3_traccar").__path__ = [
            str(root / "custom_components/icloud3_traccar")]
