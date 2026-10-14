"""Optional iCloud3 Traccar bridge, isolated from iCloud3's startup and tracking."""
import asyncio
from datetime import timedelta

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .api import TraccarClient
from .const import DEFAULTS, DOMAIN
from .coordinator import Coordinator
from .models import SyncError
from .source import Source


async def async_setup_entry(hass, entry):
    config = dict(DEFAULTS, **entry.data)
    # Empty entries are allowed and always disabled. No Apple module is imported.
    if not all(config.get(k) for k in ("server_url", "receiver_url", "token")):
        config["enabled"] = False
        client = None
    else:
        try:
            client = TraccarClient(async_get_clientsession(hass), config)
        except ValueError:
            config["enabled"] = False
            client = None
    coordinator = Coordinator(client, Source(hass),
                              Store(hass, 1, f"{DOMAIN}.{entry.entry_id}"), config)
    try:
        await coordinator.load()
    except SyncError as error:
        coordinator.config["enabled"] = False
        coordinator.error(error)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    tasks = set()

    @callback
    def schedule(_now=None):
        if coordinator.stopping or not coordinator.config["enabled"]:
            return
        # Only one tick per interval; delayed network work cannot build a task backlog.
        if tasks:
            return
        task = hass.async_create_background_task(coordinator.tick(), "icloud3_traccar_live")
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def shutdown(_event):
        try:
            await coordinator.stop()
        except SyncError as error:
            coordinator.error(error)

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, shutdown))
    coordinator.live_tasks = tasks
    entry.async_on_unload(async_track_time_interval(hass, schedule,
                                                   timedelta(seconds=config["interval"])))
    entry.async_on_unload(entry.add_update_listener(_updated))
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    schedule()
    return True


async def _updated(hass, entry):
    # Only settings changes reload. History options save an empty options dictionary.
    coordinator = hass.data[DOMAIN][entry.entry_id]
    if dict(DEFAULTS, **entry.data) != coordinator.config:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    if not await hass.config_entries.async_unload_platforms(entry, ["sensor"]):
        return False
    coordinator.stopping = True
    tasks = list(coordinator.live_tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    try:
        await coordinator.stop()
    except SyncError:
        pass
    hass.data[DOMAIN].pop(entry.entry_id)
    return True
