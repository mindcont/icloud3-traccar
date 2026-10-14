"""Real Home Assistant 2025.3.4 import/flow/lifecycle contract tests (Python 3.13).

Run separately from tests/, which deliberately uses offline HA adapter doubles.
"""
import asyncio
import importlib
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntries, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        dt_util.set_default_time_zone(dt_util.get_time_zone("UTC"))
        self.hass = HomeAssistant(self.directory.name)
        self.hass.config_entries = ConfigEntries(self.hass, {})
        await dr.async_load(self.hass)
        await er.async_load(self.hass)

    async def asyncTearDown(self):
        await self.hass.async_stop(force=True)
        self.directory.cleanup()

    async def test_integration_flow_platform_diagnostics_import(self):
        for name in ("", ".config_flow", ".source", ".sensor", ".diagnostics"):
            importlib.import_module("custom_components.icloud3_traccar" + name)

    async def test_actual_flow_schema_disabled_entry_and_options(self):
        from custom_components.icloud3_traccar.config_flow import ConfigFlow, OptionsFlow
        flow = ConfigFlow()
        flow.hass = self.hass
        flow.context = {"source": "user"}
        result = await flow.async_step_user()
        self.assertEqual(result["type"], "form")
        schema = result["data_schema"]
        values = schema({})
        self.assertFalse(values["enabled"])
        result = await flow.async_step_user(values)
        self.assertEqual(result["type"], "create_entry")
        entry = self.make_entry(result["data"])
        options = OptionsFlow(entry)
        options.hass = self.hass
        options.context = {"source": "user"}
        self.assertEqual((await options.async_step_init())["type"], "menu")
        self.assertEqual((await options.async_step_settings())["type"], "form")
        self.assertEqual((await options.async_step_history())["type"], "form")

    def make_entry(self, data):
        return ConfigEntry(version=1, minor_version=1, domain="icloud3_traccar",
                           title="Test", source="user", data=data, options={},
                           unique_id="icloud3_traccar", discovery_keys={}, subentries_data=[])

    async def test_setup_disabled_unload_real_ha_store_and_events(self):
        from custom_components.icloud3_traccar import async_setup_entry, async_unload_entry
        entry = self.make_entry({})
        with patch.object(self.hass.config_entries, "async_forward_entry_setups", new=AsyncMock()), \
             patch.object(self.hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=True)):
            self.assertTrue(await async_setup_entry(self.hass, entry))
            coordinator = self.hass.data["icloud3_traccar"][entry.entry_id]
            self.assertFalse(coordinator.config["enabled"])
            self.assertIsNone(coordinator.client)
            self.assertTrue(await async_unload_entry(self.hass, entry))
        await entry._async_process_on_unload(self.hass)

    async def test_actual_recorder_read_only_history_and_attribute_changes(self):
        from homeassistant.components import recorder
        from homeassistant.components.recorder.core import Recorder
        from homeassistant.helpers.recorder import DATA_RECORDER, RecorderData
        from custom_components.icloud3_traccar.source import Source, Device
        self.hass.data[DATA_RECORDER] = RecorderData()
        instance = Recorder(
            hass=self.hass, auto_purge=False, auto_repack=False, keep_days=10,
            commit_interval=0, uri="sqlite:///" + self.directory.name + "/history.sqlite",
            db_max_retries=1, db_retry_wait=1, entity_filter=None, exclude_event_types=set(),
        )
        self.hass.data[recorder.DATA_INSTANCE] = instance
        recorder.get_instance.cache_clear()
        instance.async_initialize()
        instance.async_register()
        instance.start()
        await asyncio.wait_for(instance.async_db_ready, timeout=30)
        await self.hass.async_start()
        start = dt_util.utcnow() - timedelta(seconds=1)
        self.hass.states.async_set("device_tracker.test_phone", "home", {
            "latitude": 31.1, "longitude": 121.2, "gps_accuracy": 5})
        await self.hass.async_block_till_done()
        await instance.async_block_till_done()
        # Same state, changed attributes must still appear in history.
        self.hass.states.async_set("device_tracker.test_phone", "home", {
            "latitude": 31.2, "longitude": 121.3, "gps_accuracy": 6})
        await self.hass.async_block_till_done()
        await instance.async_block_till_done()
        source = Source(self.hass)
        device = Device("test-ha-id", "Test Phone", "device_tracker.test_phone", "test_phone")
        end = dt_util.utcnow() + timedelta(seconds=1)
        rows = await source.history(device, start, end)
        points = [source.historical(device, state) for state in rows]
        self.assertEqual([point.latitude for point in points], [31.1, 31.2])
        self.assertLess(points[0].time, points[1].time)
        self.assertEqual(points[0].device_id, "test-ha-id")
        repeated = await source.history(device, start, end)
        self.assertEqual(len(repeated), len(rows))
        self.assertEqual(self.hass.states.get(device.entity_id).attributes["latitude"], 31.2)


if __name__ == "__main__":
    unittest.main()
