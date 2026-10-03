"""Hockey sensor platform."""
from datetime import datetime
import logging
from typing import Any, Dict, Optional

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, build_device_info, build_unique_id

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up hockey sensors from a config entry."""
    data = config_entry.data
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    async_add_entities([
        HockeyGameStateSensor(
            data.get("league"), data.get("team_id"), config_entry.title, data, coordinator
        ),
        HockeyNextGameSensor(
            data.get("league"), data.get("team_id"), config_entry.title, data, coordinator
        ),
    ])
    return True


class HockeyGameStateSensor(CoordinatorEntity, SensorEntity):
    """Sensor for hockey game state."""

    def __init__(self, league: str, team_id: str, team_name: str, data: Dict[str, Any], coordinator: "HockeyGameDataCoordinator") -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._league = league
        self._team_id = team_id
        self._team_name = team_name
        self._data = data

        # Use team_id in unique_id to support multiple teams per league
        self._attr_unique_id = f"hockey_{build_unique_id(league, team_id, data.get('client_code'))}"
        # Use league_teamname as the sensor name
        self._attr_name = f"{league.upper()}_{self._team_name}"
        self._attr_has_entity_name = False
        self._attr_icon = "mdi:hockey-sticks"
        self._attr_state_class = None
        self._attr_device_info = build_device_info(league, team_id, team_name, data.get("client_code"))

    @property
    def native_value(self) -> str:
        """Return the game state."""
        if self.coordinator.data:
            return self.coordinator.data.get("state", "No data")
        return "No data"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional game information as attributes."""
        if not self.coordinator.data:
            return {}

        return self.coordinator.data


class HockeyNextGameSensor(CoordinatorEntity, SensorEntity):
    """Scheduled start of the team's next game.

    A timestamp sensor is what Home Assistant's time trigger accepts along
    with an offset, so "an hour before puck drop" needs no template. Unknown
    when nothing is scheduled.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, league: str, team_id: str, team_name: str, data: Dict[str, Any], coordinator: "HockeyGameDataCoordinator") -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"hockey_next_game_{build_unique_id(league, team_id, data.get('client_code'))}"
        self._attr_name = f"{league.upper()}_{team_name} Next Game"
        self._attr_has_entity_name = False
        self._attr_icon = "mdi:clock-start"
        self._attr_device_info = build_device_info(league, team_id, team_name, data.get("client_code"))

    @property
    def native_value(self) -> Optional[datetime]:
        """Return the next puck drop."""
        raw = (self.coordinator.data or {}).get("next_game_start")
        return dt_util.parse_datetime(raw) if raw else None
