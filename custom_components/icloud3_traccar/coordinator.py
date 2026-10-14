"""Independent workers and durable live/history checkpoints."""
import asyncio
from copy import deepcopy
from hashlib import sha256
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from math import atan2, cos, degrees, radians, sin

from .const import DEFAULTS, ERRORS
from .models import Point, SyncError, timestamp


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class Coordinator:
    def __init__(self, client, source, store, config, notify=lambda: None):
        self.client, self.source, self.store = client, source, store
        self.config = dict(DEFAULTS, **config)
        self.notify = notify
        self.data = {"live": {}, "pending": {}, "history": None,
                     "success": 0, "failure": 0, "last_success": None,
                     "last_device_id": None, "error": None, "connection": "unknown",
                     "created": [], "reused": [], "device_ids": {}, "target": None}
        self._save_lock = asyncio.Lock()
        self._live_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(4)
        self.history_task = None
        self.stopping = False

    async def load(self):
        try:
            saved = await self.store.async_load()
            if saved:
                if not isinstance(saved, dict):
                    raise ValueError
                for key in ("live", "pending", "device_ids"):
                    if key in saved and not isinstance(saved[key], dict):
                        raise ValueError
                self.data.update(saved)
        except Exception:
            raise SyncError("storage_error") from None
        target = sha256((self.config.get("server_url", "") + "|"
                         + self.config.get("receiver_url", "")).encode()).hexdigest()
        if self.data.get("target") and self.data["target"] != target:
            self.data.update(live={}, pending={}, created=[], reused=[], device_ids={},
                             success=0, failure=0, last_success=None, last_device_id=None)
            if self.data.get("history"):
                self.data["history"]["status"] = "cancelled"
        self.data["target"] = target
        # Resume requires user action: a restart must never silently read Recorder.
        if self.data.get("history") and self.data["history"]["status"] == "running":
            self.data["history"]["status"] = "paused"
        await self.save()

    async def save(self):
        async with self._save_lock:
            try:
                await self.store.async_save(deepcopy(self.data))
            except Exception:
                raise SyncError("storage_error") from None
        self.notify()

    def selected(self):
        devices = self.source.devices()
        selected = self.config.get("devices", [])
        return {uid: d for uid, d in devices.items() if not selected or uid in selected}

    def error(self, error):
        self.data["failure"] += 1
        self.data["error"] = ERRORS.get(error.code, "Traccar operation failed")
        if error.code in ("authentication", "permission", "unavailable", "invalid_response"):
            self.data["connection"] = "unavailable"
        self.notify()

    def status(self):
        job = self.data.get("history")
        history = ({k: job[k] for k in (
            "status", "start", "end", "window", "device_index", "offset",
            "processed", "success", "failure", "skipped", "reasons", "total_devices",
            "progress",
        )} if job else None)
        return {
            "enabled": self.config["enabled"],
            "connection": self.data["connection"],
            "token": "configured" if self.config.get("token") else "not_configured",
            "last_success": self.data["last_success"],
            "last_device_id": self.data["last_device_id"],
            "success": self.data["success"], "failure": self.data["failure"],
            "recent_error": self.data["error"],
            "created_devices": len(self.data["created"]),
            "reused_devices": len(self.data["reused"]),
            "history": history,
        }

    async def upload(self, point, allow_reimport=False):
        sent = await self.client.send(point, self.config, allow_reimport)
        self.data["connection"] = "connected"
        self.data["error"] = None
        self.data["created"] = sorted(set(self.data["created"]) | self.client.created)
        self.data["reused"] = sorted((set(self.data["reused"]) | self.client.reused)
                                      - set(self.data["created"]))
        self.data["device_ids"].update({uid: device["id"]
                                       for uid, device in self.client.devices.items()})
        if sent:
            self.data["success"] += 1
            self.data["last_success"] = utcnow()
            self.data["last_device_id"] = point.device_id
        return sent

    def _motion(self, point, previous):
        """iCloud3 has no speed/course fields; estimate from consecutive live fixes."""
        if not previous:
            return point
        elapsed = (datetime.fromisoformat(point.time)
                   - datetime.fromisoformat(previous["time"])).total_seconds()
        if elapsed <= 0 or elapsed > 3600:
            return point
        coords = previous["coords"]
        distance = point.distance(coords)
        lat1, lat2 = radians(coords[0]), radians(point.latitude)
        dlon = radians(point.longitude - coords[1])
        heading = degrees(atan2(sin(dlon) * cos(lat2),
                               cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon))) % 360
        return replace(point, speed=distance / elapsed * 1.9438444924,
                       course=heading if distance else None)

    async def tick(self, _now=None):
        if self.stopping or not self.config["enabled"] or self._live_lock.locked():
            return
        async with self._live_lock:
            # Registry/memory failures are isolated from HA and the iCloud3 worker.
            try:
                devices = self.selected()
                await asyncio.gather(*(self._live(d) for d in devices.values()))
            except asyncio.CancelledError:
                raise
            except Exception:
                self.error(SyncError("source_unavailable"))

    async def _live(self, device):
        async with self._semaphore:
            try:
                pending = self.data["pending"].get(device.device_id)
                if pending:
                    await self._send_live(Point.create(**pending))
                point = self.source.current(device)
                previous = self.data["live"].get(point.device_id)
                if previous and point.key == previous["key"]:
                    return
                if (previous and point.distance(previous["coords"]) < self.config["min_distance"]):
                    return
                point = self._motion(point, previous)
                self.data["pending"][point.device_id] = point.stored()
                await self.save()  # Persist BEFORE the external operation.
                await self._send_live(point)
            except asyncio.CancelledError:
                raise
            except SyncError as error:
                self.error(error)
                await self.save()
            except Exception:
                self.error(SyncError("source_unavailable"))

    async def _send_live(self, point):
        await self.upload(point)
        self.data["live"][point.device_id] = {
            "key": point.key, "coords": point.coords, "time": point.time,
        }
        self.data["pending"].pop(point.device_id, None)
        await self.save()

    async def start_history(self, options):
        if self.history_task and not self.history_task.done():
            raise ValueError("history_running")
        start, end = timestamp(options["start"]), timestamp(options["end"])
        if start >= end or datetime.fromisoformat(end) > datetime.now(timezone.utc):
            raise ValueError("invalid_range")
        devices = self.source.devices()
        ids = options.get("devices") or list(self.selected())
        if not ids or any(uid not in devices for uid in ids):
            raise ValueError("no_devices")
        batch_size = int(options.get("batch_size", 100))
        if not 1 <= batch_size <= 1000:
            raise ValueError("invalid_batch_size")
        old_job = self.data.get("history")
        if old_job and old_job["status"] in ("running", "paused"):
            raise ValueError("history_pending")
        # Resolve entity IDs from registry now, not a manually maintained map.
        self.data["history"] = {
            "status": "running", "start": start, "end": end, "window": start,
            "devices": [{"device_id": uid, "entity_id": devices[uid].entity_id}
                        for uid in dict.fromkeys(ids)],
            "device_index": 0, "offset": 0, "last_row_key": None, "processed": 0, "success": 0,
            "failure": 0, "skipped": 0, "reasons": {}, "previous_coords": {},
            "batch_size": batch_size, "skip_duplicates": options.get("skip_duplicates", True),
            "allow_reimport": options.get("allow_reimport", False),
            "total_devices": len(set(ids)), "progress": 0.0,
        }
        await self.save()
        self.history_task = asyncio.create_task(self.run_history())

    async def resume_history(self):
        if self.history_task and not self.history_task.done():
            raise ValueError("history_running")
        if not self.data.get("history") or self.data["history"]["status"] != "paused":
            raise ValueError("no_history")
        self.data["history"]["status"] = "running"
        await self.save()
        self.history_task = asyncio.create_task(self.run_history())

    async def pause_history(self, cancel=False):
        job = self.data.get("history")
        if not job or job["status"] not in ("running", "paused"):
            return
        job["status"] = "cancelled" if cancel else "paused"
        if self.history_task and not self.history_task.done():
            self.history_task.cancel()
            await asyncio.gather(self.history_task, return_exceptions=True)
        await self.save()

    def _skip(self, job, reason):
        job["skipped"] += 1
        job["reasons"][reason] = job["reasons"].get(reason, 0) + 1

    @staticmethod
    def _row_key(state):
        attrs = state.attributes
        # Validate an offset against Recorder purges/late writes before resuming.
        data = (getattr(state, "last_updated", None), attrs.get("latitude"), attrs.get("longitude"))
        return sha256(repr(data).encode()).hexdigest()

    async def run_history(self):
        job = self.data["history"]
        try:
            end = datetime.fromisoformat(job["end"])
            while job["device_index"] < len(job["devices"]) and job["status"] == "running":
                recorded = job["devices"][job["device_index"]]
                uid = recorded["device_id"]
                device = self.source.devices().get(uid)
                # Do not attach old history to a replacement device or silently change entity.
                if not device or device.entity_id != recorded["entity_id"]:
                    raise SyncError("source_unavailable")
                start = datetime.fromisoformat(job["window"])
                stop = min(start + timedelta(hours=1), end)
                rows = await self.source.history(device, start, stop)
                if job["offset"] and (len(rows) < job["offset"] or
                        self._row_key(rows[job["offset"] - 1]) != job.get("last_row_key")):
                    # Replay this window safely using server-side duplicate checks.
                    job["offset"] = 0
                    job["previous_coords"].pop(uid, None)
                for offset in range(job["offset"], len(rows)):
                    if self.stopping or job["status"] != "running":
                        return
                    try:
                        point = self.source.historical(device, rows[offset])
                    except SyncError as error:
                        self._skip(job, error.code)
                    else:
                        if (job["skip_duplicates"]
                                and job["previous_coords"].get(uid) == point.coords):
                            self._skip(job, "duplicate_coordinates")
                        else:
                            sent = await self.upload(point, job["allow_reimport"])
                            if sent:
                                job["success"] += 1
                            else:
                                self._skip(job, "already_imported")
                            job["previous_coords"][uid] = point.coords
                    job["offset"] = offset + 1
                    job["last_row_key"] = self._row_key(rows[offset])
                    job["processed"] += 1
                    await self.save()  # failed rows never advance the cursor
                    if job["processed"] % job["batch_size"] == 0:
                        await asyncio.sleep(0)
                job["window"] = stop.isoformat()
                job["offset"] = 0
                job["last_row_key"] = None
                if stop == end:
                    job["device_index"] += 1
                    job["window"] = job["start"]
                duration = (end - datetime.fromisoformat(job["start"])).total_seconds()
                elapsed = (datetime.fromisoformat(job["window"])
                           - datetime.fromisoformat(job["start"])).total_seconds()
                job["progress"] = round(100 * (job["device_index"] + elapsed / duration)
                                         / job["total_devices"], 2)
                await self.save()
                await asyncio.sleep(0)
            if job["device_index"] == len(job["devices"]):
                job["status"], job["progress"] = "completed", 100.0
                await self.save()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            job["failure"] += 1
            job["status"] = "paused"
            self.error(error if isinstance(error, SyncError) else SyncError("recorder_unavailable"))
            try:
                await self.save()
            except SyncError:
                self.notify()

    async def stop(self):
        self.stopping = True
        tasks = list(getattr(self, "live_tasks", ()))
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.pause_history()
        # Live work is cancelled and awaited by the integration before saving.
        await self.save()
