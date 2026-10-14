"""Validated location snapshots. No HA or Apple account access."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from math import asin, cos, isfinite, radians, sin, sqrt
from urllib.parse import urlsplit, urlunsplit


class SyncError(Exception):
    """Only fixed error codes may cross the network boundary."""
    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def validate_url(value):
    """Reject embedded credentials, queries, fragments and unsupported schemes."""
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except (ValueError, AttributeError):
        raise ValueError("invalid_url") from None
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment or any(c.isspace() for c in value)):
        raise ValueError("invalid_url")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("invalid_url")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def number(value, minimum=None, maximum=None):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        if not isfinite(value):
            return None
        if minimum is not None and value < minimum:
            return None
        if maximum is not None and value > maximum:
            return None
        return value
    except (ValueError, TypeError):
        return None


def timestamp(value):
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            value = datetime.fromtimestamp(value, timezone.utc)
        if not isinstance(value, datetime) or value.tzinfo is None or value.timestamp() <= 0:
            raise ValueError
        # Traccar stores timestamps at millisecond precision.
        return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    except (ValueError, TypeError, OverflowError, OSError):
        raise SyncError("missing_time") from None


@dataclass(frozen=True)
class Point:
    device_id: str
    name: str
    latitude: float
    longitude: float
    time: str
    speed: float | None = None  # knots (OsmAnd 6.8.1 default speed unit)
    course: float | None = None
    battery: float | None = None
    accuracy: float | None = None

    @classmethod
    def create(cls, device_id, name, latitude, longitude, time, **optional):
        lat, lon = number(latitude, -90, 90), number(longitude, -180, 180)
        if lat is None or lon is None:
            raise SyncError("missing_location")
        if not isinstance(device_id, str) or not device_id:
            raise SyncError("source_unavailable")
        return cls(device_id, name, lat, lon, timestamp(time),
                   number(optional.get("speed"), 0),
                   number(optional.get("course"), 0, 360),
                   number(optional.get("battery"), 0, 100),
                   number(optional.get("accuracy"), 0))

    @property
    def key(self):
        data = f"{self.device_id}|{self.time}|{self.latitude:.8f}|{self.longitude:.8f}"
        return sha256(data.encode()).hexdigest()

    @property
    def coords(self):
        return [self.latitude, self.longitude]

    def stored(self):
        return asdict(self)

    def distance(self, coords):
        lat1, lat2 = radians(coords[0]), radians(self.latitude)
        dlat = lat2 - lat1
        dlon = radians(self.longitude - coords[1])
        return 6371000 * 2 * asin(min(1, sqrt(sin(dlat / 2) ** 2
                                          + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2)))

    def osmand(self, config):
        # The official protocol resolves this uniqueId to its internal deviceId.
        payload = {"id": self.device_id, "lat": self.latitude, "lon": self.longitude,
                   "timestamp": self.time}
        for setting, field, value in (
            ("upload_speed", "speed", self.speed),
            ("upload_course", "bearing", self.course),
            ("upload_battery", "batt", self.battery),
            ("upload_accuracy", "accuracy", self.accuracy),
        ):
            if config.get(setting, True) and value is not None:
                payload[field] = value
        return payload
