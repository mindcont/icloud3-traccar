"""Official Traccar 6.8.1 REST device API and OsmAnd HTTP receiver."""
import asyncio
from datetime import datetime, timedelta
from weakref import WeakValueDictionary

import aiohttp

from .models import SyncError, timestamp, validate_url


class TraccarClient:
    def __init__(self, session, config, sleep=asyncio.sleep):
        self.session = session
        base = validate_url(config["server_url"])
        self.base = base if base.endswith("/api") else base + "/api"
        self.receiver = validate_url(config["receiver_url"])
        self.token = config["token"]
        self.retries = config.get("retries", 3)
        self.sleep = sleep
        self.devices = {}
        self.locks = {}
        self.point_locks = WeakValueDictionary()
        self.created = set()
        self.reused = set()

    def lock(self, unique_id):
        return self.locks.setdefault(unique_id, asyncio.Lock())

    async def _request(self, method, path="", *, body=None, params=None, receiver=False):
        """Never propagate URLs, payloads, raw responses or aiohttp exceptions."""
        url = self.receiver if receiver else self.base + path
        headers = {} if receiver else {"Authorization": f"Bearer {self.token}"}
        try:
            async with self.session.request(
                method, url, headers=headers, params=params,
                data=body if receiver else None,
                json=body if not receiver else None,
                timeout=aiohttp.ClientTimeout(total=15), allow_redirects=False,
            ) as response:
                status = response.status
                if status == 401:
                    raise SyncError("authentication")
                if status == 403:
                    raise SyncError("permission")
                if status in (408, 429) or status >= 500:
                    raise SyncError("unavailable", retryable=True)
                if status == 404:
                    raise SyncError("device_not_found")
                if not 200 <= status < 300:
                    raise SyncError("request_rejected")
                if receiver:
                    # Never interpret command data returned by OsmAnd.
                    await response.read()
                    return None
                return await response.json()
        except SyncError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError):
            raise SyncError("unavailable", retryable=True) from None
        except (ValueError, TypeError):
            raise SyncError("invalid_response") from None

    async def _read(self, path, params=None):
        for attempt in range(self.retries + 1):
            try:
                return await self._request("GET", path, params=params)
            except SyncError as error:
                if not error.retryable or attempt == self.retries:
                    raise
                await self.sleep(min(2 ** attempt, 30))

    async def validate(self):
        data = await self._read("/devices", {"uniqueId": "icloud3-traccar-connection-check"})
        if not isinstance(data, list):
            raise SyncError("invalid_response")

    async def _lookup(self, unique_id):
        devices = await self._read("/devices", {"uniqueId": unique_id})
        if not isinstance(devices, list):
            raise SyncError("invalid_response")
        matches = [d for d in devices if isinstance(d, dict) and d.get("uniqueId") == unique_id]
        if len(matches) > 1:
            raise SyncError("duplicate_device")
        if matches and (not isinstance(matches[0].get("id"), int) or matches[0]["id"] <= 0):
            raise SyncError("invalid_response")
        return matches[0] if matches else None

    async def ensure_device(self, unique_id, name, refresh=False):
        cached = self.devices.get(unique_id)
        if cached and cached.get("name") == name and not refresh:
            return cached["id"]
        async with self.lock(unique_id):
            return await self._resolve_device(unique_id, name, refresh)

    async def _resolve_device(self, unique_id, name, refresh=False):
        """Serialize device resolution, not unrelated history/live position retries."""
        cached = self.devices.get(unique_id)
        if cached and cached.get("name") == name and not refresh:
            return cached["id"]
        device = None
        for attempt in range(self.retries + 1):
            device = await self._lookup(unique_id)
            if device:
                if unique_id not in self.created:
                    self.reused.add(unique_id)
                break
            try:
                device = await self._request("POST", "/devices",
                                             body={"name": name, "uniqueId": unique_id})
                if (not isinstance(device, dict) or device.get("uniqueId") != unique_id
                        or not isinstance(device.get("id"), int) or device["id"] <= 0):
                    raise SyncError("invalid_response")
                self.created.add(unique_id)
                break
            except SyncError as error:
                # A timeout/conflict may follow a successful creation. Resolve first.
                device = await self._lookup(unique_id)
                if device:
                    self.reused.add(unique_id)
                    break
                if not error.retryable or attempt == self.retries:
                    raise
                await self.sleep(min(2 ** attempt, 30))
        if device.get("name") != name:
            updated = dict(device, name=name)  # preserve uniqueId and all other server fields
            for attempt in range(self.retries + 1):
                try:
                    await self._request("PUT", f"/devices/{device['id']}", body=updated)
                    device = updated
                    break
                except SyncError as error:
                    if error.code == "device_not_found":
                        self.devices.pop(unique_id, None)
                        # Let the outer send retry resolve the deleted device. Avoid recursion.
                        raise
                    if not error.retryable or attempt == self.retries:
                        raise
                    await self.sleep(min(2 ** attempt, 30))
        self.devices[unique_id] = device
        return device["id"]

    async def exists(self, device_id, point):
        """Read-back protects retries/restarts and overlapping history imports."""
        moment = datetime.fromisoformat(point.time)
        positions = await self._read("/positions", {
            "deviceId": device_id,
            "from": (moment - timedelta(milliseconds=1)).isoformat(),
            "to": (moment + timedelta(milliseconds=1)).isoformat(),
        })
        if not isinstance(positions, list):
            raise SyncError("invalid_response")
        for p in positions:
            try:
                if (p["deviceId"] == device_id and timestamp(p["fixTime"]) == point.time
                        and abs(float(p["latitude"]) - point.latitude) < 1e-8
                        and abs(float(p["longitude"]) - point.longitude) < 1e-8):
                    return True
            except (KeyError, TypeError, ValueError, SyncError):
                continue
        return False

    async def send(self, point, config, allow_reimport=False):
        # Identical points serialize; an old history fix cannot hold up a new live fix.
        point_lock = self.point_locks.setdefault(point.key, asyncio.Lock())
        async with point_lock:
            for attempt in range(self.retries + 1):
                try:
                    device_id = await self.ensure_device(point.device_id, point.name)
                    if not allow_reimport and await self.exists(device_id, point):
                        return False
                    await self._request("POST", body=point.osmand(config), receiver=True)
                    # OsmAnd ACK can precede persistence or a server-side history filter.
                    for check in range(4):
                        if await self.exists(device_id, point):
                            return True
                        if check < 3:
                            await self.sleep(0.25 * 2 ** check)
                    raise SyncError("position_not_confirmed")
                except SyncError as error:
                    if error.code in ("device_not_found", "request_rejected"):
                        # Receiver returns 400 for an unknown uniqueId in 6.8.1.
                        self.devices.pop(point.device_id, None)
                        if attempt < self.retries:
                            await self.ensure_device(point.device_id, point.name, refresh=True)
                    elif not error.retryable:
                        raise
                    if attempt == self.retries:
                        raise
                    await self.sleep(min(2 ** attempt, 30))
