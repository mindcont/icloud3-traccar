"""Real loopback HTTP + asynchronous worker tests. Never use a production server."""
import asyncio
import copy
import importlib
import json
import logging
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import aiohttp
from aiohttp import web

from ha_stub import install, namespace
namespace()
install()
from custom_components.icloud3_traccar.api import TraccarClient
from custom_components.icloud3_traccar.const import DEFAULTS, DOMAIN
from custom_components.icloud3_traccar.coordinator import Coordinator
from custom_components.icloud3_traccar.models import Point, SyncError, validate_url
from custom_components.icloud3_traccar.source import Device, Source


class Store:
    def __init__(self):
        self.value = None
    async def async_load(self):
        return copy.deepcopy(self.value)
    async def async_save(self, value):
        self.value = copy.deepcopy(value)


class MemorySource:
    def __init__(self):
        self.registry = {"ha-id-1": Device("ha-id-1", "Phone", "device_tracker.phone", "phone"),
                         "ha-id-2": Device("ha-id-2", "Watch", "device_tracker.watch", "watch")}
        self.points = {uid: Point.create(uid, d.name, 31.1, 121.2, "2025-01-01T00:00:00Z",
                                        speed=10, course=45, battery=75, accuracy=5)
                       for uid, d in self.registry.items()}
        self.rows = {uid: [] for uid in self.registry}
        self.history_calls = []
    def devices(self):
        return self.registry
    def current(self, device):
        return self.points[device.device_id]
    async def history(self, device, start, end):
        self.history_calls.append((device.device_id, start, end))
        return [s for s in self.rows[device.device_id]
                if getattr(s, "last_updated", None) is None or start <= s.last_updated < end]
    historical = staticmethod(Source.historical)


def row(time="2025-01-01T00:00:00+00:00", latitude=31.1, longitude=121.2):
    return NS(last_updated=datetime.fromisoformat(time) if time else None,
              attributes={"latitude": latitude, "longitude": longitude, "battery": 80,
                          "gps_accuracy": 6})


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.devices = {}
        self.positions = []
        self.requests = []
        self.receiver_failures = 0
        self.create_ambiguous = False
        self.receive_ambiguous = False
        self.status = 0
        self.receiver_gate = None
        self.gated_latitude = None
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", self.handle)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        self.config = dict(DEFAULTS, enabled=True, server_url=self.url,
                           receiver_url=self.url + "/receiver", token="test-only-secret", retries=2)
        self.session = aiohttp.ClientSession()
        self.sleeps = []
        async def sleep(delay):
            self.sleeps.append(delay)
        self.client = TraccarClient(self.session, self.config, sleep=sleep)
        self.source = MemorySource()
        self.store = Store()
        self.coordinator = Coordinator(self.client, self.source, self.store, self.config)
        await self.coordinator.load()

    async def asyncTearDown(self):
        await self.coordinator.stop()
        await self.session.close()
        await self.runner.cleanup()

    async def handle(self, request):
        body = await request.post() if request.path == "/receiver" else (
            await request.json() if request.can_read_body else None)
        self.requests.append((request.method, request.path, dict(request.query), body,
                              request.headers.get("Authorization")))
        if self.status:
            return web.Response(status=self.status, text="sensitive server message")
        if request.path.startswith("/api/"):
            if request.headers.get("Authorization") != "Bearer test-only-secret":
                return web.Response(status=401)
        if request.path == "/api/devices" and request.method == "GET":
            return web.json_response([d for d in self.devices.values()
                                      if d["uniqueId"] == request.query["uniqueId"]])
        if request.path == "/api/devices" and request.method == "POST":
            if any(d["uniqueId"] == body["uniqueId"] for d in self.devices.values()):
                return web.Response(status=409)
            device = dict(body, id=max(self.devices, default=0) + 1)
            self.devices[device["id"]] = device
            if self.create_ambiguous:
                self.create_ambiguous = False
                return web.Response(status=503)
            return web.json_response(device)
        if request.path.startswith("/api/devices/") and request.method == "PUT":
            self.devices[body["id"]] = body
            return web.json_response(body)
        if request.path == "/api/positions" and request.method == "GET":
            start, end = datetime.fromisoformat(request.query["from"]), datetime.fromisoformat(request.query["to"])
            return web.json_response([p for p in self.positions
                if p["deviceId"] == int(request.query["deviceId"])
                and start <= datetime.fromisoformat(p["fixTime"]) <= end])
        if request.path == "/receiver" and request.method == "POST":
            if self.receiver_gate and (self.gated_latitude is None
                                       or float(body["lat"]) == self.gated_latitude):
                await self.receiver_gate.wait()
            if self.receiver_failures:
                self.receiver_failures -= 1
                return web.Response(status=503)
            device = next((d for d in self.devices.values() if d["uniqueId"] == body["id"]), None)
            if not device:
                return web.Response(status=400)
            self.positions.append({"deviceId": device["id"], "latitude": float(body["lat"]),
                                   "longitude": float(body["lon"]), "fixTime": body["timestamp"]})
            if self.receive_ambiguous:
                self.receive_ambiguous = False
                return web.Response(status=503)
            return web.Response(text="ignored command response")
        return web.Response(status=405)

    async def test_request_construction_and_unique_id(self):
        point = self.source.points["ha-id-1"]
        self.assertTrue(await self.client.send(point, self.config))
        self.assertEqual(self.devices[1]["uniqueId"], point.device_id)
        request = next(r for r in self.requests if r[1] == "/receiver")
        self.assertEqual(request[2], {})  # no coordinates or token in query string
        self.assertIsNone(request[4])  # REST token never forwarded to receiver
        self.assertEqual(dict(request[3]), {k: str(v) for k, v in point.osmand(self.config).items()})
        self.assertEqual(self.positions[0]["deviceId"], 1)
        self.assertFalse(any(r[0] == "POST" and r[1] == "/api/positions" for r in self.requests))

    async def test_existing_device_reused_and_name_updated(self):
        self.devices[42] = {"id": 42, "uniqueId": "ha-id-1", "name": "Old", "attributes": {"x": 1}}
        await self.client.send(self.source.points["ha-id-1"], self.config)
        self.assertEqual(len(self.devices), 1)
        self.assertEqual(self.devices[42]["name"], "Phone")
        self.assertEqual(self.devices[42]["uniqueId"], "ha-id-1")
        self.assertEqual(self.devices[42]["attributes"], {"x": 1})
        self.assertEqual(self.positions[0]["deviceId"], 42)

    async def test_auto_creation_and_concurrent_reuse(self):
        await asyncio.gather(*(self.client.send(self.source.points["ha-id-1"], self.config) for _ in range(4)))
        self.assertEqual(len(self.devices), 1)
        self.assertEqual(len(self.positions), 1)

    async def test_ambiguous_creation_requeries_before_retry(self):
        self.create_ambiguous = True
        await self.client.send(self.source.points["ha-id-1"], self.config)
        self.assertEqual(len(self.devices), 1)
        self.assertEqual(sum(r[0] == "POST" and r[1] == "/api/devices" for r in self.requests), 1)

    async def test_live_dedup_and_time_change(self):
        await self.coordinator.tick()
        await self.coordinator.tick()
        self.assertEqual(len(self.positions), 2)
        self.source.points["ha-id-1"] = replace(self.source.points["ha-id-1"], time="2025-01-01T00:01:00.000+00:00")
        await self.coordinator.tick()
        self.assertEqual(len(self.positions), 3)
        self.assertEqual(self.coordinator.data["success"], 3)

    async def test_multiple_devices_and_selection(self):
        self.coordinator.config["devices"] = ["ha-id-2"]
        await self.coordinator.tick()
        self.assertEqual([d["uniqueId"] for d in self.devices.values()], ["ha-id-2"])
        self.assertEqual(self.coordinator.data["device_ids"], {"ha-id-2": 1})

    async def test_min_distance(self):
        self.coordinator.config["min_distance"] = 100
        await self.coordinator.tick()
        self.source.points["ha-id-1"] = replace(self.source.points["ha-id-1"], time="2025-01-01T00:01:00.000+00:00", latitude=31.100001)
        await self.coordinator.tick()
        self.assertEqual(len(self.positions), 2)

    async def test_retry_backoff(self):
        self.receiver_failures = 2
        await self.client.send(self.source.points["ha-id-1"], self.config)
        self.assertEqual(self.sleeps, [1, 2])
        self.assertEqual(len(self.positions), 1)

    async def test_ambiguous_position_response_readback(self):
        self.receive_ambiguous = True
        await self.client.send(self.source.points["ha-id-1"], self.config)
        self.assertEqual(len(self.positions), 1)
        self.assertEqual(self.sleeps, [1])

    async def test_unavailable_persists_pending_and_recovers_after_restart(self):
        self.status = 503
        await self.coordinator.tick()
        self.assertEqual(self.coordinator.data["failure"], 2)
        self.assertEqual(len(self.store.value["pending"]), 2)
        self.assertEqual(self.coordinator.status()["connection"], "unavailable")
        self.status = 0
        restarted = Coordinator(self.client, self.source, self.store, self.config)
        await restarted.load()
        await restarted.tick()
        self.assertEqual(len(self.positions), 2)
        self.assertFalse(restarted.data["pending"])
        self.assertEqual(len(self.devices), 2)

    async def test_network_exception_sanitized_and_retried(self):
        self.client.session = NS(request=lambda *a, **kw: (_ for _ in ()).throw(
            aiohttp.ClientConnectionError("test-only-secret password lat=31.1")))
        with self.assertRaises(SyncError) as context:
            await self.client.validate()
        self.assertEqual(str(context.exception), "unavailable")
        self.assertEqual(self.sleeps, [1, 2])

    async def test_auth_failure_does_not_retry_or_expose_body(self):
        self.status = 401
        with self.assertRaises(SyncError) as context:
            await self.client.validate()
        self.assertEqual(context.exception.code, "authentication")
        self.assertEqual(self.sleeps, [])
        self.assertNotIn("sensitive", str(context.exception))

    async def test_remote_deleted_device_recreated(self):
        await self.client.send(self.source.points["ha-id-1"], self.config)
        self.devices.clear()
        changed = replace(self.source.points["ha-id-1"], time="2025-01-01T00:02:00.000+00:00")
        await self.client.send(changed, self.config)
        self.assertEqual(len(self.devices), 1)
        self.assertEqual(len(self.positions), 2)

    async def test_field_switches(self):
        config = dict(self.config, **{k: False for k in DEFAULTS if k.startswith("upload_")})
        await self.client.send(self.source.points["ha-id-1"], config)
        payload = next(r[3] for r in self.requests if r[1] == "/receiver")
        self.assertEqual(set(payload), {"id", "lat", "lon", "timestamp"})

    async def history(self, **options):
        settings = dict(start="2025-01-01T00:00:00Z", end="2025-01-01T02:00:00Z",
                        devices=["ha-id-1"], skip_duplicates=False, batch_size=1)
        settings.update(options)
        await self.coordinator.start_history(settings)
        await self.coordinator.history_task
        return self.coordinator.data["history"]

    async def test_history_range_and_timestamp(self):
        self.source.rows["ha-id-1"] = [row("2024-12-31T23:59:59+00:00"), row(),
            row("2025-01-01T01:00:00+00:00", 32), row("2025-01-01T02:00:00+00:00", 33)]
        job = await self.history()
        self.assertEqual(job["success"], 2)
        self.assertEqual(job["progress"], 100)
        self.assertEqual([p["fixTime"] for p in self.positions], ["2025-01-01T00:00:00.000+00:00", "2025-01-01T01:00:00.000+00:00"])
        self.assertEqual(len(self.source.history_calls), 2)

    async def test_history_resume_failed_row_and_live_isolation(self):
        self.source.rows["ha-id-1"] = [row(), row("2025-01-01T00:01:00+00:00", 32)]
        self.receiver_failures = 3
        job = await self.history()
        self.assertEqual(job["status"], "paused")
        self.assertEqual(job["offset"], 0)
        self.assertEqual(job["failure"], 1)
        await self.coordinator.tick()  # live still runs despite paused history
        self.assertEqual(len(self.positions), 2)
        await self.coordinator.resume_history()
        await self.coordinator.history_task
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["processed"], 2)
        self.assertEqual(len(self.positions), 3)
        self.assertEqual(job["reasons"], {"already_imported": 1})

    async def test_slow_history_fix_does_not_hold_new_live_fix_for_same_device(self):
        self.source.rows["ha-id-1"] = [row(latitude=32)]
        self.receiver_gate = asyncio.Event()
        self.gated_latitude = 32
        await self.coordinator.start_history({"start": "2025-01-01T00:00:00Z",
            "end": "2025-01-01T01:00:00Z", "devices": ["ha-id-1"]})
        await asyncio.sleep(0.02)
        await asyncio.wait_for(self.coordinator.tick(), timeout=1)
        self.assertEqual(len(self.positions), 2)
        self.assertFalse(self.coordinator.history_task.done())
        self.receiver_gate.set()
        await self.coordinator.history_task
        self.assertEqual(len(self.positions), 3)
        self.assertEqual(len(self.devices), 2)

    async def test_history_checkpoint_restart_requires_manual_resume(self):
        self.source.rows["ha-id-1"] = [row(), row("2025-01-01T00:01:00+00:00", 32)]
        original = self.client.send
        async def send(point, *args):
            if point.latitude == 32:
                raise SyncError("unavailable", True)
            return await original(point, *args)
        self.client.send = send
        job = await self.history()
        self.assertEqual(job["offset"], 1)
        self.store.value["history"]["status"] = "running"  # abrupt termination
        restarted = Coordinator(self.client, self.source, self.store, self.config)
        await restarted.load()
        self.assertIsNone(restarted.history_task)
        self.assertEqual(restarted.data["history"]["status"], "paused")
        self.client.send = original
        await restarted.resume_history()
        await restarted.history_task
        self.assertEqual(len(self.positions), 2)
        self.assertEqual(restarted.data["history"]["success"], 2)

    async def test_history_resume_after_recorder_purge_rechecks_window(self):
        self.source.rows["ha-id-1"] = [row(), row("2025-01-01T00:01:00+00:00", 32)]
        original = self.client.send
        async def send(point, *args):
            if point.latitude == 32:
                raise SyncError("unavailable", True)
            return await original(point, *args)
        self.client.send = send
        job = await self.history()
        self.assertEqual(job["offset"], 1)
        self.source.rows["ha-id-1"].pop(0)  # Recorder purged a row during interruption.
        self.client.send = original
        await self.coordinator.resume_history()
        await self.coordinator.history_task
        self.assertEqual(job["status"], "completed")
        self.assertEqual(len(self.positions), 2)

    async def test_history_live_same_device_and_overlap_dedup(self):
        await self.coordinator.tick()
        self.source.rows["ha-id-1"] = [row()]
        job = await self.history()
        self.assertEqual(len(self.devices), 2)
        self.assertEqual(len(self.positions), 2)
        self.assertEqual(job["reasons"], {"already_imported": 1})
        await self.history()
        self.assertEqual(len(self.positions), 2)

    async def test_history_reimport_requires_explicit_flag(self):
        self.source.rows["ha-id-1"] = [row()]
        await self.history()
        await self.history(allow_reimport=True)
        self.assertEqual(len(self.positions), 2)
        self.assertEqual(len(self.devices), 1)

    async def test_history_skips_invalid_and_repeated_coordinates(self):
        self.source.rows["ha-id-1"] = [row(), row("2025-01-01T00:01:00+00:00"),
            row("2025-01-01T00:02:00+00:00", None), row(None, 33)]
        job = await self.history(skip_duplicates=True)
        # MemorySource includes invalid-time rows in both windows; use one window here.
        self.assertEqual(job["success"], 1)
        self.assertEqual(job["reasons"]["duplicate_coordinates"], 1)
        self.assertEqual(job["reasons"]["missing_location"], 1)
        self.assertGreaterEqual(job["reasons"]["missing_time"], 1)

    async def test_history_invalid_ranges_and_devices(self):
        for options in ({"start": "2025-01-02T00:00:00Z", "end": "2025-01-01T00:00:00Z"},
                        {"start": "2025-01-01T00:00:00Z", "end": "2099-01-01T00:00:00Z"},
                        {"devices": ["not-icloud3"]}, {"batch_size": 0}):
            with self.assertRaises(ValueError):
                await self.history(**options)

    async def test_disabled_and_no_recorder_read_for_live(self):
        self.coordinator.config["enabled"] = False
        await self.coordinator.tick()
        self.assertFalse(self.requests)
        self.coordinator.config["enabled"] = True
        await self.coordinator.tick()
        self.assertEqual(self.source.history_calls, [])

    async def test_diagnostics_and_logs_have_no_secrets_or_coordinates(self):
        self.status = 503
        records = []
        class Handler(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())
        handler = Handler()
        logging.getLogger().addHandler(handler)
        try:
            await self.coordinator.tick()
        finally:
            logging.getLogger().removeHandler(handler)
        from custom_components.icloud3_traccar.diagnostics import async_get_config_entry_diagnostics
        status = await async_get_config_entry_diagnostics(NS(data={DOMAIN: {"entry": self.coordinator}}), NS(entry_id="entry"))
        payload = json.dumps(status) + "\n".join(records)
        for secret in ("test-only-secret", "121.2", "31.1", "sensitive server message"):
            self.assertNotIn(secret, payload)
        self.assertEqual(status["token"], "configured")

    async def test_server_change_resets_destination_checkpoints(self):
        await self.coordinator.tick()
        other = Coordinator(self.client, self.source, self.store,
                            dict(self.config, receiver_url=self.url + "/new-receiver"))
        await other.load()
        self.assertFalse(other.data["live"])
        self.assertFalse(other.data["device_ids"])

    async def test_pending_stored_before_network_and_disk_failure_stops_upload(self):
        self.store.async_save = AsyncMock(side_effect=OSError("secret path"))
        await self.coordinator.tick()
        self.assertFalse(self.positions)
        self.store.async_save = Store.async_save.__get__(self.store)

    async def test_slow_network_does_not_block_event_loop(self):
        self.receiver_gate = asyncio.Event()
        task = asyncio.create_task(self.coordinator.tick())
        await asyncio.sleep(0.03)
        self.assertFalse(task.done())
        # Event loop can still serve other HA work while HTTP is pending.
        self.receiver_gate.set()
        await task
        self.assertEqual(len(self.positions), 2)

    async def test_receiver_ack_without_persistence_is_not_counted_successful(self):
        self.client.exists = AsyncMock(return_value=False)
        with self.assertRaises(SyncError) as context:
            await self.client.send(self.source.points["ha-id-1"], self.config)
        self.assertEqual(context.exception.code, "position_not_confirmed")
        self.assertEqual(self.sleeps, [0.25, 0.5, 1.0])
        self.assertEqual(sum(r[1] == "/receiver" for r in self.requests), 1)

    async def test_duplicate_remote_unique_ids_fail_without_creation(self):
        self.devices = {1: {"id": 1, "uniqueId": "ha-id-1", "name": "One"},
                        2: {"id": 2, "uniqueId": "ha-id-1", "name": "Two"}}
        with self.assertRaises(SyncError) as context:
            await self.client.send(self.source.points["ha-id-1"], self.config)
        self.assertEqual(context.exception.code, "duplicate_device")
        self.assertFalse(self.positions)
        self.assertFalse(any(r[0] == "POST" for r in self.requests))

    async def test_history_pause_preserves_cursor_and_resumes(self):
        self.source.rows["ha-id-1"] = [row()]
        self.receiver_gate = asyncio.Event()
        await self.coordinator.start_history({"start": "2025-01-01T00:00:00Z",
            "end": "2025-01-01T01:00:00Z", "devices": ["ha-id-1"]})
        await asyncio.sleep(0.02)
        await self.coordinator.pause_history()
        job = self.coordinator.data["history"]
        self.assertEqual(job["status"], "paused")
        self.assertEqual(job["offset"], 0)
        self.receiver_gate.set()
        await self.coordinator.resume_history()
        await self.coordinator.history_task
        self.assertEqual(job["status"], "completed")
        self.assertEqual(len(self.positions), 1)

    async def test_config_flow_validation_with_http(self):
        flow_module = importlib.import_module("custom_components.icloud3_traccar.config_flow")
        hass = NS(session=self.session, entities=NS(entities={}), devices=NS(async_get=lambda _: None))
        flow = flow_module.ConfigFlow()
        flow.hass = hass
        shown = await flow.async_step_user()
        self.assertEqual(shown["type"], "form")
        result = await flow.async_step_user(self.config)
        self.assertEqual(result["type"], "create_entry")
        self.assertFalse(self.devices)  # validating never creates devices or sends positions
        self.status = 401
        rejected = await flow.async_step_user(self.config)
        self.assertEqual(rejected["errors"], {"base": "authentication"})
        self.assertNotIn("test-only-secret", repr(rejected))


class ModelTests(unittest.TestCase):
    def test_invalid_urls_and_credentials(self):
        for url in ("https://user:pass@host", "https://host?token=x", "ftp://host", "https://host/#secret", "https://host:bad", "https://host:0"):
            with self.assertRaises(ValueError):
                validate_url(url)

    def test_coordinate_and_time_validation(self):
        for lat, lon in ((None, 1), (float("nan"), 1), (91, 1), (0, 181), (True, 1)):
            with self.assertRaises(SyncError):
                Point.create("id", "Name", lat, lon, "2025-01-01T00:00:00Z")
        for time in (None, "bad", "2025-01-01T00:00:00", 0, float("inf")):
            with self.assertRaises(SyncError):
                Point.create("id", "Name", 0, 0, time)
        self.assertEqual(Point.create("id", "Name", 0, 0, "2025-01-01T08:00:00+08:00").time,
                         "2025-01-01T00:00:00.000+00:00")

    def test_no_icloud3_core_changes_or_control_api(self):
        root = Path(__file__).resolve().parents[1] / "custom_components/icloud3_traccar"
        code = "\n".join(p.read_text() for p in root.glob("*.py"))
        for forbidden in ("play_sound(", "lost_mode(", "send_command(", "sqlite3", "sqlalchemy", '"DELETE"'):
            self.assertNotIn(forbidden, code)


if __name__ == "__main__":
    unittest.main()
