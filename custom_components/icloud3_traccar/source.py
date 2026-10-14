"""Read-only adapter for iCloud3 memory and explicitly requested Recorder history."""
import sys
from dataclasses import dataclass
from datetime import timedelta
from functools import partial

from homeassistant.helpers import device_registry as dr, entity_registry as er

from .models import Point, SyncError


@dataclass(frozen=True)
class Device:
    device_id: str
    name: str
    entity_id: str
    devicename: str


class Source:
    def __init__(self, hass):
        self.hass = hass

    def devices(self):
        """The registry device_id is authoritative; no generated IDs or manual mapping."""
        registry = er.async_get(self.hass)
        devices = dr.async_get(self.hass)
        result = {}
        for entry in registry.entities.values():
            if (entry.platform != "icloud3" or entry.domain != "device_tracker"
                    or not entry.device_id or entry.disabled_by):
                continue
            device = devices.async_get(entry.device_id)
            name = (device.name_by_user or device.name) if device else None
            # iCloud3 defines the tracker unique_id as icloud3_{devicename}.
            if not entry.unique_id.startswith("icloud3_"):
                continue
            result[entry.device_id] = Device(entry.device_id, name or entry.original_name
                                            or entry.entity_id, entry.entity_id,
                                            entry.unique_id[len("icloud3_"):])
        return result

    def current(self, device):
        # Never import/start iCloud3 or call Apple APIs. iCloud3 is the sole writer.
        module = sys.modules.get("custom_components.icloud3.global_variables")
        gb = getattr(module, "GlobalVariables", None)
        memory = getattr(gb, "Devices_by_devicename", {}).get(device.devicename)
        if memory is None:
            raise SyncError("source_unavailable")
        return Point.create(
            device.device_id, device.name,
            memory.loc_data_latitude, memory.loc_data_longitude,
            memory.loc_data_secs,
            battery=memory.dev_data_battery_level,
            accuracy=memory.loc_data_gps_accuracy,
        )

    async def history(self, device, start, end):
        """Only called by an explicit history job; Recorder supplies a read-only session."""
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.history import get_significant_states
            query = partial(
                get_significant_states, self.hass,
                # Query is exclusive at the start; include the exact boundary ourselves.
                start - timedelta(microseconds=1), end,
                entity_ids=[device.entity_id], include_start_time_state=False,
                significant_changes_only=False, minimal_response=False, no_attributes=False,
            )
            rows = await get_instance(self.hass).async_add_executor_job(query)
            states = rows.get(device.entity_id, [])
            # Recorder can return metadata-only states without a timestamp.
            # They cannot represent a historical location, so skip them before
            # Point.create() validates the timestamp.
            return sorted((s for s in states if getattr(s, "last_updated", None) is not None
                           and start <= s.last_updated < end),
                          key=lambda s: s.last_updated)
        except Exception:
            # DB drivers may include URLs/credentials or values in their exceptions.
            raise SyncError("recorder_unavailable") from None

    @staticmethod
    def historical(device, state):
        attrs = state.attributes
        return Point.create(device.device_id, device.name,
                            attrs.get("latitude"), attrs.get("longitude"),
                            getattr(state, "last_updated", None),
                            battery=attrs.get("battery_level", attrs.get("battery")),
                            accuracy=attrs.get("gps_accuracy"))
