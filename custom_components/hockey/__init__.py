"""The Hockey integration."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS, build_unique_id
from .coordinator import HockeyGameDataCoordinator, build_api

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up hockey from a config entry."""
    # Entries created before unique ids were assigned would not be seen by the
    # duplicate check, so backfill them here.
    if entry.unique_id is None:
        unique_id = build_unique_id(
            entry.data.get("league"), entry.data.get("team_id"), entry.data.get("client_code")
        )
        _LOGGER.debug("Assigning unique_id %s to entry %s", unique_id, entry.entry_id)
        hass.config_entries.async_update_entry(entry, unique_id=unique_id)

    # One coordinator per entry, shared by every platform, so the sensor and the
    # event entity always describe the same update.
    coordinator = HockeyGameDataCoordinator(
        hass, entry.data.get("league"), entry.data.get("team_id"), build_api(entry.data), entry
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator}

    # Re-setup on options change so new display thresholds apply immediately.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry after its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        stored = hass.data[DOMAIN].pop(entry.entry_id, None) or {}
        coordinator = stored.get("coordinator")
        if coordinator is not None:
            # Stops the scheduled refresh; without this it survives a reload.
            await coordinator.async_shutdown()
    return unload_ok
