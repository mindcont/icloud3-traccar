"""Exercise actual integration/flow functions against explicit HA adapter doubles."""
import asyncio
import importlib
import importlib.util
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import voluptuous as vol
from ha_stub import install, namespace
namespace()
install()
from custom_components.icloud3_traccar.const import DEFAULTS, DOMAIN
from custom_components.icloud3_traccar.source import Source
from custom_components.icloud3_traccar.config_flow import ConfigFlow, OptionsFlow, settings_schema, validate
from custom_components.icloud3_traccar.models import SyncError


class Store:
    async def async_load(self):
        return None
    async def async_save(self, data):
        self.data = data


class Entry:
    def __init__(self, **data):
        self.data = dict(DEFAULTS, **data)
        self.entry_id = "entry"
        self.unloads = []
    def async_on_unload(self, func):
        self.unloads.append(func)
    def add_update_listener(self, func):
        self.listener = func
        return lambda: None


def fake_hass():
    def update(entry, **changes):
        for key, value in changes.items():
            setattr(entry, key, value)
    return NS(data={}, session=NS(), store=Store(),
              config_entries=NS(async_forward_entry_setups=AsyncMock(),
                                async_unload_platforms=AsyncMock(return_value=True),
                                async_update_entry=update, async_reload=AsyncMock()),
              bus=NS(async_listen_once=lambda *args: lambda: None),
              async_create_background_task=lambda coro, name: asyncio.create_task(coro),
              entities=NS(entities={}), devices=NS(async_get=lambda _: None))


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.hass = fake_hass()
        self.entity = NS(platform="icloud3", domain="device_tracker", device_id="original-ha-id",
                         unique_id="icloud3_phone", entity_id="device_tracker.actual_phone",
                         disabled_by=None, original_name="Phone")
        self.hass.entities.entities = {"entity": self.entity}
        self.hass.devices.async_get = lambda _: NS(name="Original", name_by_user="My Phone")

    def test_registry_uses_original_device_id_and_actual_entity_id(self):
        devices = Source(self.hass).devices()
        device = devices["original-ha-id"]
        self.assertEqual(device.device_id, self.entity.device_id)
        self.assertEqual(device.entity_id, self.entity.entity_id)
        self.assertEqual(device.devicename, "phone")
        self.assertEqual(device.name, "My Phone")
        self.assertEqual(self.entity.unique_id, "icloud3_phone")

    def test_excludes_other_integrations_disabled_or_unregistered_devices(self):
        for change in ({"platform": "ezviz"}, {"disabled_by": "user"}, {"domain": "sensor"},
                       {"device_id": None}, {"unique_id": "invented"}):
            entity = NS(**(vars(self.entity) | change))
            self.hass.entities.entities = {"entity": entity}
            self.assertFalse(Source(self.hass).devices())

    def test_current_memory_no_apple_import_no_recorder(self):
        source = Source(self.hass)
        device = source.devices()["original-ha-id"]
        memory = NS(loc_data_latitude=30.2, loc_data_longitude=120.3,
                    loc_data_secs=1735689600, dev_data_battery_level=80,
                    loc_data_gps_accuracy=9)
        module = NS(GlobalVariables=NS(Devices_by_devicename={"phone": memory}))
        with patch.dict(sys.modules, {"custom_components.icloud3.global_variables": module}):
            point = source.current(device)
        self.assertEqual(point.device_id, "original-ha-id")
        self.assertEqual(point.time, "2025-01-01T00:00:00.000+00:00")
        self.assertEqual(point.battery, 80)
        self.assertEqual(vars(memory)["loc_data_latitude"], 30.2)

    def test_missing_memory_fails_safely(self):
        with patch.dict(sys.modules, {"custom_components.icloud3.global_variables": NS()}):
            with self.assertRaises(SyncError) as context:
                Source(self.hass).current(Source(self.hass).devices()["original-ha-id"])
            self.assertEqual(str(context.exception), "source_unavailable")

    async def test_recorder_actual_query_contract_attributes_and_read_executor(self):
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end = datetime(2025, 1, 2, tzinfo=timezone.utc)
        included = NS(last_updated=start, attributes={"latitude": 30, "longitude": 120})
        excluded = NS(last_updated=end, attributes={"latitude": 31, "longitude": 121})
        result = {self.entity.entity_id: [excluded, included]}
        async def execute(query):
            return query()
        self.hass.recorder = NS(async_add_executor_job=execute)
        with patch("homeassistant.components.recorder.history.get_significant_states", return_value=result) as query:
            source = Source(self.hass)
            device = source.devices()["original-ha-id"]
            rows = await source.history(device, start, end)
        self.assertEqual(rows, [included])
        kwargs = query.call_args.kwargs
        self.assertEqual(kwargs["entity_ids"], [self.entity.entity_id])
        self.assertFalse(kwargs["significant_changes_only"])
        self.assertFalse(kwargs["include_start_time_state"])
        self.assertFalse(kwargs["minimal_response"])
        self.assertFalse(kwargs["no_attributes"])
        self.assertLess(query.call_args.args[1], start)
        self.assertEqual(source.historical(device, rows[0]).time, "2025-01-01T00:00:00.000+00:00")

    async def test_recorder_failure_is_sanitized(self):
        self.hass.recorder = NS(async_add_executor_job=AsyncMock(side_effect=RuntimeError("HA_TOKEN=secret")))
        source = Source(self.hass)
        with self.assertRaises(SyncError) as context:
            await source.history(source.devices()["original-ha-id"],
                                 datetime(2025, 1, 1, tzinfo=timezone.utc),
                                 datetime(2025, 1, 2, tzinfo=timezone.utc))
        self.assertEqual(str(context.exception), "recorder_unavailable")

    async def test_empty_config_defaults_disabled_and_no_network(self):
        entry = await validate(self.hass, {})
        self.assertFalse(entry["enabled"])
        with self.assertRaisesRegex(ValueError, "missing_connection"):
            await validate(self.hass, {"enabled": True})

    def test_password_schema_never_contains_full_or_masked_token_default(self):
        schema = settings_schema(self.hass, {"token": "SHOULD_NEVER_APPEAR"})
        token_key = next(k for k in schema.schema if k.schema == "token")
        self.assertIs(token_key.default, vol.UNDEFINED)
        self.assertEqual(schema.schema[token_key].config["type"], "password")
        self.assertNotIn("SHOULD_NEVER_APPEAR", repr(schema))
        for values in ({"interval": 0}, {"interval": 4000}, {"retries": 11}, {"min_distance": -1}):
            with self.assertRaises(vol.Invalid):
                schema(values)

    async def test_keep_token_on_blank_and_validate_connection(self):
        with patch("custom_components.icloud3_traccar.config_flow.TraccarClient") as client:
            client.return_value.validate = AsyncMock()
            result = await validate(self.hass, {"token": "", "interval": 60}, {
                "token": "configured-secret", "server_url": "https://example.test",
                "receiver_url": "https://example.test/osmand"})
        self.assertEqual(result["token"], "configured-secret")
        self.assertEqual(result["interval"], 60)

    async def test_options_menu_settings_history_actions_and_status(self):
        entry = Entry(token="configured-secret", server_url="https://example.test",
                      receiver_url="https://example.test/osmand")
        coordinator = NS(start_history=AsyncMock(), resume_history=AsyncMock(),
                         pause_history=AsyncMock(), status=lambda: {"token": "configured"})
        self.hass.data = {DOMAIN: {"entry": coordinator}}
        flow = OptionsFlow(entry)
        flow.hass = self.hass
        self.assertEqual((await flow.async_step_init())["type"], "menu")
        for action in ("settings", "history", "status"):
            form = await getattr(flow, f"async_step_{action}")()
            self.assertEqual(form["type"], "form")
            self.assertNotIn("configured-secret", repr(form))
        options = {"start": "2025-01-01T00:00:00Z", "end": "2025-01-02T00:00:00Z"}
        self.assertEqual((await flow.async_step_history(options))["type"], "create_entry")
        coordinator.start_history.assert_awaited_once_with(options)
        await flow.async_step_resume()
        await flow.async_step_pause()
        await flow.async_step_cancel()
        coordinator.resume_history.assert_awaited_once()
        self.assertEqual(coordinator.pause_history.await_count, 2)
        with patch("custom_components.icloud3_traccar.config_flow.TraccarClient") as client:
            client.return_value.validate = AsyncMock()
            await flow.async_step_settings({"enabled": False, "interval": 60})
        self.assertEqual(entry.data["interval"], 60)
        self.assertEqual(entry.data["token"], "configured-secret")

    async def test_real_integration_module_import_setup_and_unload_with_ha_doubles(self):
        name = "custom_components.icloud3_traccar"
        path = Path(__file__).resolve().parents[1] / "custom_components/icloud3_traccar/__init__.py"
        spec = importlib.util.spec_from_file_location(name, path, submodule_search_locations=[str(path.parent)])
        integration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(integration)
        entry = Entry()
        self.assertTrue(await integration.async_setup_entry(self.hass, entry))
        coordinator = self.hass.data[DOMAIN][entry.entry_id]
        self.assertFalse(coordinator.config["enabled"])
        self.assertIsNone(coordinator.client)
        self.assertFalse(coordinator.live_tasks)
        self.assertTrue(await integration.async_unload_entry(self.hass, entry))
        self.assertNotIn(entry.entry_id, self.hass.data[DOMAIN])

    def test_manifest_translation_and_sensor_module_imports(self):
        root = Path(__file__).resolve().parents[1] / "custom_components/icloud3_traccar"
        manifest = json.loads((root / "manifest.json").read_text())
        self.assertTrue(manifest["config_flow"])
        english = json.loads((root / "strings.json").read_text())
        for lang in ("en", "zh-Hans", "zh-Hant"):
            translated = json.loads((root / "translations" / f"{lang}.json").read_text())
            self.assertEqual(set(english["options"]["step"]), set(translated["options"]["step"]))
            self.assertEqual(set(english["config"]["error"]), set(translated["config"]["error"]))
        for module in ("sensor", "diagnostics"):
            importlib.import_module(f"custom_components.icloud3_traccar.{module}")
