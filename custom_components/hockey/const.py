from homeassistant.helpers.device_registry import DeviceInfo

from .league_config import HOCKEYTECH_LEAGUES

DOMAIN = "hockey"
PLATFORMS = ["sensor", "event"]

# Leagues configured with their own credentials all share this league key, so
# the client code is what actually distinguishes one from another.
CUSTOM_HOCKEYTECH = "hockeytech"

# Options (per config entry)
OPT_LINGER_HOURS = "linger_hours"
OPT_LAST_RESULT_HOURS = "last_result_hours"
OPT_COLOR_HOME_BACKGROUND = "color_home_background"
OPT_COLOR_HOME_TEXT = "color_home_text"
OPT_COLOR_HOME_ACCENT = "color_home_accent"
OPT_COLOR_AWAY_BACKGROUND = "color_away_background"
OPT_COLOR_AWAY_TEXT = "color_away_text"
OPT_COLOR_AWAY_ACCENT = "color_away_accent"
OPT_RESET_COLORS = "reset_colors"

# Same order as team_colors.COLOR_KEYS.
COLOR_OPTIONS = (
    OPT_COLOR_HOME_BACKGROUND,
    OPT_COLOR_HOME_TEXT,
    OPT_COLOR_HOME_ACCENT,
    OPT_COLOR_AWAY_BACKGROUND,
    OPT_COLOR_AWAY_TEXT,
    OPT_COLOR_AWAY_ACCENT,
)

# How long a finished game stays as the main scorebug, measured from the
# estimated end of the game. Neither API publishes an end time.
DEFAULT_LINGER_HOURS = 9
# Once the next game is this close, stop showing the previous result at all.
# The same threshold also makes a lingering final yield early to an imminent game.
DEFAULT_LAST_RESULT_HOURS = 6
# No feed gives a game end time, so it is estimated from puck drop.
ESTIMATED_GAME_HOURS = 3


def build_unique_id(league: str, team_id, client_code=None) -> str:
    """Stable identity for one tracked team.

    Used for both the config entry and the sensor so the two can never
    disagree about what counts as a duplicate.
    """
    if league == CUSTOM_HOCKEYTECH and client_code:
        return f"{league}_{client_code}_{team_id}"
    return f"{league}_{team_id}"


def league_display_name(league: str) -> str:
    """Human-readable league name, used as the device manufacturer."""
    if league == "nhl":
        return "NHL"
    if league == CUSTOM_HOCKEYTECH:
        return "HockeyTech"
    return HOCKEYTECH_LEAGUES.get(league, {}).get("name", league.upper())


def build_device_info(league: str, team_id, team_name: str, client_code=None) -> DeviceInfo:
    """Group a team's sensors and event entity under one device.

    Every entity for the same team shares this identifier so they show up
    together on the config entry's page, like Home Assistant's other
    "service" integrations.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, build_unique_id(league, team_id, client_code))},
        name=team_name,
        manufacturer=league_display_name(league),
        model="Tracked Team",
    )

