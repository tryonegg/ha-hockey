from homeassistant import config_entries
import voluptuous as vol
import logging
from typing import Any, Dict, Optional, Union
from homeassistant.core import callback

from homeassistant.helpers.selector import (
    BooleanSelector,
    ColorRGBSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    DOMAIN,
    build_unique_id,
    OPT_LINGER_HOURS,
    OPT_LAST_RESULT_HOURS,
    DEFAULT_LINGER_HOURS,
    DEFAULT_LAST_RESULT_HOURS,
    COLOR_OPTIONS,
    OPT_RESET_COLORS,
)
from .team_colors import COLOR_KEYS, default_colors, hex_to_rgb
from .api.hockeytech import HockeyTechApi
from .api.nhl import NHLApi
from .league_config import HOCKEYTECH_LEAGUES

_LOGGER = logging.getLogger(__name__)

# ============================================================================
# API Factory & Helper Functions
# ============================================================================

def _get_hockeytech_api(key: str, client_code: str) -> HockeyTechApi:
    """Create a HockeyTech API instance."""
    return HockeyTechApi(key, client_code)


def _get_nhl_api() -> NHLApi:
    """Create an NHL API instance."""
    return NHLApi()


def _get_league_api(league: str) -> HockeyTechApi:
    """Create a HockeyTech API instance for a predefined league."""
    league_config = HOCKEYTECH_LEAGUES[league]
    return _get_hockeytech_api(league_config["api_key"], league_config["client_code"])


def _build_leagues_dict() -> Dict[str, str]:
    """Build leagues dictionary dynamically from config and hardcoded entries."""
    leagues = {}
    # Add NHL first
    leagues["nhl"] = "NHL"
    # Add all leagues from league_config in alphabetical order
    for league_code in sorted(HOCKEYTECH_LEAGUES.keys()):
        league_info = HOCKEYTECH_LEAGUES[league_code]
        leagues[league_code] = league_info.get("name", league_code.upper())
    # Add HockeyTech custom as last item
    leagues["hockeytech"] = "HockeyTech (Custom)"
    return leagues


LEAGUES = _build_leagues_dict()


class HockeyOptionsFlow(config_entries.OptionsFlow):
    """How long a finished game stays on the card."""

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None) -> Any:
        if user_input is not None:
            settings = dict(user_input)
            if settings.pop(OPT_RESET_COLORS, False):
                # Drop the overrides so the shipped team palette applies again.
                for key in COLOR_OPTIONS:
                    settings.pop(key, None)
            return self.async_create_entry(data=settings)

        options = self.config_entry.options
        data = self.config_entry.data
        preset = default_colors(data.get("league"), data.get("team_id")) or {}

        def color_default(option: str, key: str):
            """Start each picker on the colour currently in effect."""
            return options.get(option) or hex_to_rgb(preset.get(key)) or [0, 0, 0]
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    OPT_LINGER_HOURS,
                    default=options.get(OPT_LINGER_HOURS, DEFAULT_LINGER_HOURS),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=168, step=1, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(
                    OPT_LAST_RESULT_HOURS,
                    default=options.get(OPT_LAST_RESULT_HOURS, DEFAULT_LAST_RESULT_HOURS),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=168, step=1, mode=NumberSelectorMode.BOX)
                ),
                **{
                    vol.Optional(option, default=color_default(option, key)): ColorRGBSelector()
                    for option, key in zip(COLOR_OPTIONS, COLOR_KEYS)
                },
                vol.Optional(OPT_RESET_COLORS, default=False): BooleanSelector(),
            }),
        )


class HockeyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> HockeyOptionsFlow:
        """Expose the per-team display options."""
        return HockeyOptionsFlow()

    async def _async_abort_if_team_configured(self, team_id: str, client_code: Optional[str] = None) -> None:
        """Reject a team that already has a config entry.

        Without this a second entry is created whose sensor collides on
        unique_id with the first, so it silently produces no entity.
        """
        await self.async_set_unique_id(build_unique_id(self.league, team_id, client_code))
        self._abort_if_unique_id_configured()

    
    async def _async_fetch_and_store_teams(
        self,
        api: Union[HockeyTechApi, NHLApi],
        is_nhl: bool = False
    ) -> Optional[Dict[str, str]]:
        """Fetch teams from API and store in self.teams_list.
        
        Returns team options dict or None on error.
        """
        try:
            self.teams_list = await api.get_teams()
            if not self.teams_list:
                _LOGGER.error(f"No teams returned from API")
                return None
            
            if is_nhl:
                return {team["abbr"]: team["name"] for team in self.teams_list}
            else:
                return {str(team["id"]): team["name"] for team in self.teams_list}
        except Exception as e:
            _LOGGER.error(f"Error fetching teams from API: {e}")
            return None
    
    async def _async_fetch_hockeytech_teams(
        self,
        api: HockeyTechApi
    ) -> Optional[Dict[str, str]]:
        """Fetch the league's full team list.

        Deliberately not scoped to a season: a league between seasons would
        otherwise offer only the teams that made last season's playoffs.

        Returns team options dict or None on error.
        """
        try:
            self.teams_list = await api.get_teams()
            if not self.teams_list:
                _LOGGER.error("No teams returned from HockeyTech API")
                return None

            return {str(team["id"]): team["name"] for team in self.teams_list}
        except Exception as e:
            _LOGGER.error(f"Error fetching teams from HockeyTech: {e}")
            return None
    
    def _find_selected_team(self, team_id: str, is_nhl: bool = False) -> str:
        """Find team name from teams list by ID.
        
        Returns team name or 'Unknown Team' if not found.
        """
        if is_nhl:
            team = next((t for t in self.teams_list if t["abbr"] == team_id), None)
        else:
            team = next((t for t in self.teams_list if str(t["id"]) == team_id), None)
        return team["name"] if team else "Unknown Team"

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> Any:
        if user_input is not None:
            self.league = user_input["league"]
            
            if self.league == "nhl":
                return await self.async_step_nhl()
            
            elif self.league in HOCKEYTECH_LEAGUES:
                # PWHL, OHL, and other HockeyTech-based leagues
                return await self.async_step_hockeytech_league()
            
            return await self.async_step_hockeytech()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("league"): vol.In(LEAGUES)
            }),
        )

    async def async_step_hockeytech(self, user_input: Optional[Dict[str, Any]] = None) -> Any:
        """Credentials step for custom HockeyTech leagues."""
        if user_input is not None:
            self.ht_creds = user_input
            return await self.async_step_hockeytech_team()

        return self.async_show_form(
            step_id="hockeytech",
            data_schema=vol.Schema({
                vol.Required("key"): str,
                vol.Required("client_code"): str,
            }),
        )

    async def async_step_hockeytech_team(self, user_input: Optional[Dict[str, Any]] = None) -> Any:
        """Team selection step for custom HockeyTech leagues."""
        if user_input is not None:
            team_id = user_input["team_id"]
            team_name = self._find_selected_team(team_id, is_nhl=False)
            await self._async_abort_if_team_configured(team_id, self.ht_creds["client_code"])

            return self.async_create_entry(
                title=team_name,
                data={
                    "league": self.league,
                    "team_id": team_id,
                    "key": self.ht_creds["key"],
                    "client_code": self.ht_creds["client_code"],
                }
            )

        # Fetch teams using provided credentials
        api = _get_hockeytech_api(self.ht_creds["key"], self.ht_creds["client_code"])
        team_options = await self._async_fetch_hockeytech_teams(api)
        
        if team_options is None:
            return self.async_show_form(
                step_id="hockeytech_team",
                data_schema=vol.Schema({
                    vol.Required("team_id"): str,
                }),
                errors={"base": "invalid_credentials"},
            )

        return self.async_show_form(
            step_id="hockeytech_team",
            data_schema=vol.Schema({
                vol.Required("team_id"): vol.In(team_options)
            }),
        )

    async def async_step_nhl(self, user_input: Optional[Dict[str, Any]] = None) -> Any:
        """Skip directly to team selection for NHL."""
        return await self.async_step_nhl_team()
    
    async def async_step_nhl_team(self, user_input: Optional[Dict[str, Any]] = None) -> Any:
        """Team selection step for NHL."""
        if user_input is not None:
            team_id = user_input["team_id"]
            team_name = self._find_selected_team(team_id, is_nhl=True)
            await self._async_abort_if_team_configured(team_id)

            return self.async_create_entry(
                title=team_name,
                data={
                    "league": self.league,
                    "team_id": team_id,
                },
            )

        # Fetch teams from NHL API
        api = _get_nhl_api()
        team_options = await self._async_fetch_and_store_teams(api, is_nhl=True)
        
        if team_options is None:
            return self.async_show_form(
                step_id="nhl_team",
                data_schema=vol.Schema({
                    vol.Required("team_id"): str,
                }),
                errors={"base": "cannot_connect"},
            )

        return self.async_show_form(
            step_id="nhl_team",
            data_schema=vol.Schema({
                vol.Required("team_id"): vol.In(team_options)
            }),
        )
    
    async def async_step_hockeytech_league(self, user_input: Optional[Dict[str, Any]] = None) -> Any:
        """Handle team selection for HockeyTech-based leagues (PWHL, OHL, etc)."""
        api = _get_league_api(self.league)
        team_options = await self._async_fetch_hockeytech_teams(api)
        
        if team_options is None:
            return self.async_abort(reason="cannot_connect")
        
        return await self.async_step_hockeytech_league_team()

    async def async_step_hockeytech_league_team(self, user_input: Optional[Dict[str, Any]] = None) -> Any:
        """Team selection for HockeyTech-based leagues (PWHL, OHL, etc)."""
        if user_input is not None:
            team_id = user_input["team_id"]
            team_name = self._find_selected_team(team_id, is_nhl=False)
            await self._async_abort_if_team_configured(team_id)

            return self.async_create_entry(
                title=team_name,
                data={
                    "league": self.league,
                    "team_id": team_id,
                },
            )

        # Build team options from already-fetched teams list
        team_options = {str(team["id"]): team["name"] for team in self.teams_list}

        return self.async_show_form(
            step_id="hockeytech_league_team",
            data_schema=vol.Schema({
                vol.Required("team_id"): vol.In(team_options)
            }),
        )
