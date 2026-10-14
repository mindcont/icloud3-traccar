"""Constants for the optional, independent iCloud3 Traccar integration."""
DOMAIN = "icloud3_traccar"
DEFAULTS = {
    "enabled": False,
    "interval": 30,
    "min_distance": 0.0,
    "upload_speed": True,
    "upload_course": True,
    "upload_battery": True,
    "upload_accuracy": True,
    "retries": 3,
    "devices": [],
}
ERRORS = {
    "authentication": "Traccar authentication failed",
    "permission": "Traccar permission denied",
    "unavailable": "Traccar temporarily unavailable",
    "invalid_response": "Unexpected Traccar response",
    "duplicate_device": "Multiple Traccar devices have the same uniqueId",
    "request_rejected": "Traccar rejected the request",
    "missing_location": "Missing or invalid latitude/longitude",
    "missing_time": "Missing or invalid location timestamp",
    "source_unavailable": "iCloud3 device is not available in memory",
    "recorder_unavailable": "Recorder history is unavailable",
    "position_not_confirmed": "Receiver accepted the request but the position is not visible; check server filters",
    "storage_error": "Unable to save sync checkpoint",
}
