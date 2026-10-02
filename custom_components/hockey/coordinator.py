"""Update coordinator for the Hockey integration."""
from datetime import timedelta, datetime
import logging
from typing import Any, Dict, Optional
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    OPT_LINGER_HOURS,
    OPT_LAST_RESULT_HOURS,
    DEFAULT_LINGER_HOURS,
    DEFAULT_LAST_RESULT_HOURS,
    ESTIMATED_GAME_HOURS,
)
from .api.hockeytech import HockeyTechApi, GameStatus
from .team_colors import matchup_colors, resolve_colors
from .api.nhl import NHLApi
from .league_config import HOCKEYTECH_LEAGUES

_LOGGER = logging.getLogger(__name__)
DEFAULT_UPDATE_INTERVAL = timedelta(hours=1)
LIVE_UPDATE_INTERVAL = timedelta(seconds=15)
PREGAME_UPDATE_INTERVAL = timedelta(seconds=60)  # Poll faster as puck drop approaches
PREGAME_THRESHOLD = timedelta(minutes=15)  # Start pregame polling this far out
SEASON_CACHE_TTL = timedelta(hours=24)  # Cache season for 24 hours

# States both leagues report while a game is actually being played.
LIVE_GAME_STATES = ("LIVE", "CRIT")
FINAL_GAME_STATES = ("FINAL", "OFF", "UnofficialFinal")


def build_api(data: Dict[str, Any]) -> Any:
    """Create the API client for a config entry."""
    league = data.get("league")
    if league == "nhl":
        return NHLApi()
    if league in HOCKEYTECH_LEAGUES:
        config = HOCKEYTECH_LEAGUES[league]
        return HockeyTechApi(config["api_key"], config["client_code"])
    # Custom HockeyTech league
    return HockeyTechApi(data.get("key"), data.get("client_code"))


class HockeyGameDataCoordinator(DataUpdateCoordinator):
    """Coordinator to manage hockey game data updates."""

    def __init__(self, hass: HomeAssistant, league: str, team_id: str, api: Any, entry: Optional[ConfigEntry] = None) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"Hockey {league.upper()} Game Data ({team_id})",
            update_interval=DEFAULT_UPDATE_INTERVAL,
        )
        self.league = league
        self.team_id = team_id
        self.api = api
        self.entry = entry
        self._current_season = None
        self._current_season_info: Optional[Dict[str, Any]] = None
        self._team_info: Optional[Dict[str, Any]] = None
        self._divisions: Optional[Dict[str, str]] = None
        self._season_fetch_time: Optional[float] = None
        self._cached_teams: Optional[Dict[str, Any]] = None
        self._game_is_live = False
        self._last_game: Optional[Dict[str, Any]] = None
        self._next_game_start: Optional[datetime] = None
        self._pregame_check_active = False
        # (game id, period) whose clock has read 0:00 while live, and how many
        # consecutive updates have seen it. HockeyTech never says "intermission".
        self._zero_clock_key: Optional[tuple] = None
        self._zero_clock_polls = 0
        # Period an intermission was flagged after, and the clock reading the
        # next period showed when it first appeared (see _flag_intermission).
        self._break_after: Optional[int] = None
        self._break_clock: Optional[str] = None

    async def _async_update_data(self) -> Optional[Dict[str, Any]]:
        """Fetch data from API.

        Any failure raises UpdateFailed so Home Assistant applies retry backoff
        and marks the entity unavailable. Returning None is reserved for the
        legitimate "no game scheduled" case.
        """
        try:
            # Ensure team_id is correct type
            team_id = int(self.team_id) if isinstance(self.team_id, str) and self.team_id.isdigit() else self.team_id

            if self.league == "nhl":
                # _LOGGER.debug(f"NHL Team: {team_id}")
                # One fetch feeds game selection, the previous result and the
                # head-to-head record. It is cached, and a failure is fatal here
                # because everything else depends on it.
                schedule = await self.api.get_team_schedule(team_id)
                game, previous = self._select_games(schedule)

                # Only fetch boxscore if game exists (#7: Avoid unnecessary boxscore calls)
                if not game:
                    _LOGGER.debug(f"No NHL game found for {team_id}")
                    self._game_is_live = False
                    self.update_interval = DEFAULT_UPDATE_INTERVAL
                    return await self._no_game_payload(team_id)

                boxscore = await self.api.boxscore(game['id'])
                if not boxscore:
                    raise UpdateFailed(f"Boxscore unavailable for NHL game {game['id']}")

                last_result = self.api._game_result(previous, team_id) if previous else None
                shootout = await self._fetch_shootout(game['id'], self.api.went_to_shootout(boxscore))
                data = self.api.ha_formatted(boxscore, team_id, standings=await self._fetch_standings(), schedule=schedule, last_result=last_result, shootout=shootout, divisions=await self._fetch_divisions())
                self._identify(data, team_id)
                data["next_game_start"] = self._next_puck_drop(schedule)
                self._last_game = boxscore
                # Check if game is live and update interval accordingly
                await self._update_interval_if_needed(boxscore)
                return data

            # For HockeyTech-based leagues
            # #8: Implement season caching with TTL
            await self._ensure_season_cached()

            schedule = await self.api.get_season_schedule(self._current_season, team_id)
            game, previous = self._select_games(schedule)
            if not game:
                _LOGGER.debug(f"No game found for team {team_id} in season {self._current_season}")
                self._game_is_live = False
                self.update_interval = DEFAULT_UPDATE_INTERVAL
                return await self._no_game_payload(team_id)

            # #6: Only fetch teams if we haven't cached them yet
            if self._cached_teams is None:
                self._cached_teams = await self.api.get_teams_by_season(self._current_season)

            gameData = await self.api.get_game_clock(game['game_id'])
            self._last_game = gameData

            last_result = self.api._game_result(previous, team_id) if previous else None
            shootout = await self._fetch_shootout(game['game_id'], self.api.went_to_shootout(game))
            data = self.api.ha_formatted(gameData, self._cached_teams, team_id, schedule_game=game, shootout=shootout, standings=await self._fetch_standings(), schedule=schedule, season_info=self._current_season_info, last_result=last_result, divisions=await self._fetch_divisions())
            self._identify(data, team_id)
            self._flag_intermission(data)
            data["next_game_start"] = self._next_puck_drop(schedule)
            # Check if game is live and update interval accordingly
            await self._update_interval_if_needed(gameData)
            return data
        except UpdateFailed:
            raise
        except Exception as err:
            # Keep the traceback at debug level; the coordinator logs the
            # UpdateFailed message itself (at error once, then debounced).
            _LOGGER.debug(f"Error fetching game data for {self.team_id}", exc_info=True)
            raise UpdateFailed(
                f"Error fetching {self.league} game data for {self.team_id}: {err}"
            ) from err

    def _flag_intermission(self, data: Dict[str, Any]) -> None:
        """Set isIntermission on a HockeyTech game sitting at 0:00 between periods.

        The clock feed has no intermission flag: it stays "in progress" at
        period N, 00:00 until the next period starts. A single 0:00 reading
        could be the last instant of play (a goal, a review), so the flag needs
        the same period to read 0:00 on two consecutive updates. It clears as
        soon as the clock, the period or the game state moves.
        """
        period = data.get("periodNumber")
        at_zero = (
            data.get("state") == "LIVE"
            and isinstance(period, int) and period > 0
            and data.get("periodType") != "SO"
            and data.get("periodTimeRemaining") == "00:00"
        )
        game = data.get("game_id") or data.get("datetime")
        key = (game, period)
        if not at_zero:
            self._zero_clock_key, self._zero_clock_polls = None, 0
            data["isIntermission"] = self._still_on_break(data, game, period)
            return
        if key == self._zero_clock_key:
            self._zero_clock_polls += 1
        else:
            self._zero_clock_key, self._zero_clock_polls = key, 1
        data["isIntermission"] = self._zero_clock_polls >= 2
        if data["isIntermission"]:
            self._break_after, self._break_clock = (game, period), None
        else:
            self._break_after = self._break_clock = None

    def _still_on_break(self, data: Dict[str, Any], game: Any, period: Any) -> bool:
        """Keep the flag up after the feed moves on to the next period.

        HockeyTech advances the period number 30 s to 8 min into the break and
        shows the fresh clock (20:00) with no shots in it. That stays an
        intermission until the clock moves off its first reading or the period
        records a shot.
        """
        after = self._break_after
        if (not after or after[0] != game or not isinstance(period, int) or period <= after[1]
                or data.get("state") != "LIVE" or data.get("period_sog")):
            self._break_after = self._break_clock = None
            return False
        clock = data.get("periodTimeRemaining")
        if self._break_clock is None:
            self._break_clock = clock
        if clock != self._break_clock:
            self._break_after = self._break_clock = None
            return False
        return True

    async def _ensure_season_cached(self) -> None:
        """Ensure current season is cached, with TTL expiration.

        (#8: Season Caching Incomplete - now properly cached with timestamp)

        A refresh failure is tolerated while a previously cached season is still
        available; having no season at all raises UpdateFailed.
        """
        # Check if season is cached and still valid
        if self._current_season and self._season_fetch_time and not self._cached_season_ended():
            age = time.time() - self._season_fetch_time
            if age < SEASON_CACHE_TTL.total_seconds():
                return  # Cache is still valid

        # Fetch and cache the season
        try:
            season = await self.api.get_current_season()
        except Exception as err:
            if self._current_season:
                _LOGGER.debug(f"Season refresh failed for {self.league}, keeping cached season {self._current_season}: {err}")
                return
            raise UpdateFailed(f"Unable to fetch season list for {self.league}: {err}") from err

        if not season:
            if self._current_season:
                _LOGGER.debug(f"No seasons returned for {self.league}, keeping cached season {self._current_season}")
                return
            raise UpdateFailed(f"No seasons available for {self.league}")

        new_season = season['season_id']
        if self._current_season is not None and new_season != self._current_season:
            # Team ids and logos are per-season, so a rollover invalidates them.
            _LOGGER.debug(f"Season for {self.league} changed {self._current_season} -> {new_season}, clearing team cache")
            self._cached_teams = None
        self._current_season = new_season
        # Kept for the competition tag: HockeyTech marks preseason/playoffs on
        # the season, not on individual games.
        self._current_season_info = season
        self._season_fetch_time = time.time()
        _LOGGER.debug(f"Cached season for {self.league}: {self._current_season}")

    def _cached_season_ended(self) -> bool:
        """Whether the cached season's end date has passed.

        Without this the 24h cache could keep the integration on the preseason
        for most of a day after the regular season has already started.
        """
        end = (self._current_season_info or {}).get("end_date")
        parsed = HockeyTechApi._season_date(end) if end else None
        return bool(parsed and dt_util.utcnow().date() > parsed)

    def _option(self, key: str, default: int) -> int:
        """Read a per-entry option, falling back to the default."""
        try:
            return int((self.entry.options if self.entry else {}).get(key, default))
        except (TypeError, ValueError):
            return default

    def _select_games(self, schedule: Optional[list]):
        """Pick the game to display and the previous result to show beside it.

        Three phases, per the configured thresholds:
          1. a finished game stays the main bug for `linger_hours` after its
             estimated end,
          2. then the next game becomes the main bug with the previous result
             shown alongside it,
          3. and once the next game is within `last_result_hours`, the previous
             result is dropped. That same threshold makes a lingering final
             yield early when the next game is already imminent.

        Returns (game to display, previous result game or None).
        """
        if not schedule:
            return None, None

        linger = timedelta(hours=self._option(OPT_LINGER_HOURS, DEFAULT_LINGER_HOURS))
        cutoff = timedelta(hours=self._option(OPT_LAST_RESULT_HOURS, DEFAULT_LAST_RESULT_HOURS))
        now = dt_util.utcnow()

        live = last_final = upcoming = None
        upcoming_start = last_final_start = None
        for game in schedule:
            kind, start = self.api.game_summary(game)
            if kind == "live" and live is None:
                live = game
            elif kind == "final":
                if start and (last_final_start is None or start >= last_final_start):
                    last_final, last_final_start = game, start
            elif kind == "future" and upcoming is None and start:
                upcoming, upcoming_start = game, start

        if live is not None:
            return live, None

        # A cutoff of zero means "never show the previous result". The main bug
        # must still step aside for an imminent game though, so the yield-early
        # test has the pregame window as a floor.
        show_previous = cutoff > timedelta(0)
        yield_within = max(cutoff, PREGAME_THRESHOLD)

        def within(threshold):
            return upcoming_start is not None and (upcoming_start - now) <= threshold

        if last_final is not None and last_final_start is not None:
            # A game already marked final cannot still be running, so its end is
            # capped at now - otherwise a linger of 0 would still hold the card
            # for the length of the duration estimate.
            ends = min(last_final_start + timedelta(hours=ESTIMATED_GAME_HOURS), now)
            if now < ends + linger and not within(yield_within):
                return last_final, None

        if upcoming is not None:
            previous = last_final if (show_previous and not within(cutoff)) else None
            return upcoming, previous

        # Nothing ahead - keep showing the last result rather than nothing.
        return last_final, None

    def _next_puck_drop(self, schedule: Optional[list]) -> Optional[str]:
        """Scheduled start of the next game not yet under way, as ISO-8601 UTC.

        Read from the schedule already fetched for game selection, so it costs
        no request. Independent of the game on the card, which can still be a
        lingering final.

        A game the feed already calls live still counts until its scheduled
        start has passed: NHL warm-ups and HockeyTech's early flip to "in
        progress" both come well before puck drop, and moving on then would
        skip a time trigger set a few minutes before it. A game still not live
        past its start counts for the estimated length of a game, so a late
        puck drop keeps its time but a postponement cannot pin it forever.
        """
        now = dt_util.utcnow()
        grace = timedelta(hours=ESTIMATED_GAME_HOURS)
        best = None
        for game in schedule or []:
            if game.get("gameScheduleState") in ("CNCL", "PPD"):
                continue
            kind, start = self.api.game_summary(game)
            if start is None or kind == "final":
                continue
            start = dt_util.as_utc(start)
            if kind == "live" and start <= now:
                continue
            if start < now - grace:
                continue
            if best is None or start < best:
                best = start
        return best.isoformat() if best else None

    async def _no_game_payload(self, team_id: Any) -> Dict[str, Any]:
        """State for a team with nothing scheduled.

        Carries the team's identity so the card can still show who it is
        instead of only an entity name.
        """
        await self._fetch_divisions()
        return self._identify(
            {"state": "No data", "team": await self._fetch_team_info(team_id)}, team_id
        )

    async def _fetch_team_info(self, team_id: Any) -> Optional[Dict[str, Any]]:
        """The tracked team's identity, independent of any season or game.

        Season-scoped team lists are no use here: a league between seasons may
        not list the team at all. Supplementary, so a failure yields None
        rather than taking the entity down.
        """
        if self._team_info is not None:
            return self._team_info

        try:
            teams = await self.api.get_teams()
        except Exception as err:
            _LOGGER.debug(f"Team list unavailable for {self.league}: {err}")
            return None

        wanted = str(team_id)
        for team in teams or []:
            if self.league == "nhl":
                if str(team.get("abbr")) != wanted:
                    continue
                logo = team.get("logo")
                # The teams endpoint returns only the light variant, unlike the
                # game payload. Derive its sibling, but only when the URL really
                # has the expected suffix so a format change degrades to no
                # dark logo rather than a broken one.
                logo_dark = (
                    logo[: -len("_light.svg")] + "_dark.svg"
                    if isinstance(logo, str) and logo.endswith("_light.svg")
                    else None
                )
                self._team_info = {
                    "id": None,
                    "name": team.get("common_name") or team.get("name"),
                    "nickname": None,
                    "city": None,
                    "logo": logo,
                    "logo_dark": logo_dark,
                    "abbr": team.get("abbr"),
                }
            else:
                if str(team.get("id")) != wanted:
                    continue
                self._team_info = {
                    "id": team.get("id"),
                    "name": team.get("name"),
                    "nickname": team.get("nickname"),
                    "city": team.get("city"),
                    "logo": team.get("team_logo_url"),
                    "abbr": team.get("code"),
                }
            return self._team_info

        _LOGGER.debug(f"Team {team_id} not found in the {self.league} team list")
        return None

    def _identify(self, data: Optional[Dict[str, Any]], team_id: Any) -> Optional[Dict[str, Any]]:
        """Tag the payload with the league and which side is the tracked team.

        The card needs both to look up team colours, and nothing else in the
        payload says which of home/away is the one being followed.
        """
        if not data:
            return data
        data["league"] = self.league
        # The team's own division, handy for grouping cards on a dashboard.
        division = (self._divisions or {}).get(str(team_id))
        if division:
            data["division"] = division
        colors = resolve_colors(
            self.league, self.team_id, (self.entry.options if self.entry else {})
        )
        if colors:
            data["colors"] = colors
        wanted = str(team_id)
        home, away = data.get("home") or {}, data.get("away") or {}
        # The side is worth publishing on its own: the card styles itself from
        # the tracked team's point of view, and working it out from the
        # abbreviation there would break for any feed that omits one.
        if str(home.get("abbr")) == wanted or str(home.get("id")) == wanted:
            data["tracked_abbr"] = home.get("abbr")
            data["tracked_side"] = "home"
        elif str(away.get("abbr")) == wanted or str(away.get("id")) == wanted:
            data["tracked_abbr"] = away.get("abbr")
            data["tracked_side"] = "away"
        else:
            data["tracked_abbr"] = (data.get("team") or {}).get("abbr")
            data["tracked_side"] = None
        # Both teams' primary colours, for layouts that paint each side.
        sides = matchup_colors(self.league, home, away, data["tracked_side"], colors)
        if sides:
            data["colors"] = {**(data.get("colors") or {}), **sides}
        return data

    async def _fetch_divisions(self) -> Optional[Dict[str, str]]:
        """Division per team, used to spot a divisional matchup.

        Neither league puts a division on the game, so it comes from the team
        list, which both clients cache. Supplementary, so a failure yields None.
        """
        if self._divisions is not None:
            return self._divisions
        try:
            self._divisions = await self.api.get_divisions()
        except Exception as err:
            _LOGGER.debug(f"Divisions unavailable for {self.league}: {err}")
            return None
        return self._divisions

    async def _fetch_shootout(self, game_id: Any, needed: bool) -> Optional[Dict[str, Any]]:
        """Shootout detail, fetched only for games that went to one.

        It is an extra request, so it is skipped for the overwhelming majority
        of games. Supplementary, so a failure yields None rather than taking
        the entity down.
        """
        if not needed:
            return None
        try:
            return await self.api.get_shootout(game_id)
        except Exception as err:
            _LOGGER.debug(f"Shootout detail unavailable for {self.league} game {game_id}: {err}")
            return None

    async def _fetch_standings(self) -> Optional[Dict[str, Dict[str, Any]]]:
        """Season records for every team, or None if unavailable.

        Records are supplementary, so unlike the game data itself a failure
        here is swallowed rather than raised: a standings outage should leave
        the scoreboard working, not take the entity offline.
        """
        try:
            if self.league == "nhl":
                return await self.api.get_standings()
            return await self.api.get_standings_by_season(self._current_season)
        except Exception as err:
            _LOGGER.debug(f"Standings unavailable for {self.league}: {err}")
            return None

    async def _update_interval_if_needed(self, game: Dict[str, Any]) -> None:
        """Adjust the poll interval to how close the game is.

        Hourly by default, every 60s once puck drop is within PREGAME_THRESHOLD,
        and every 15s while the game is live.
        """
        is_live = self.api.is_game_live(game) if self.league == "nhl" else self._is_hockeytech_live(game)

        # Extract game start datetime
        game_start = self._extract_game_start_datetime(game)
        self._next_game_start = game_start

        if is_live:
            if not self._game_is_live:
                _LOGGER.info(f"Game went live for {self.team_id}, switching to {int(LIVE_UPDATE_INTERVAL.total_seconds())}-second updates")
            self._game_is_live = True
            self._pregame_check_active = False
            self.update_interval = LIVE_UPDATE_INTERVAL
            return

        if self._game_is_live and not self._is_game_finished(game):
            # NHL goes LIVE -> OVER -> FINAL: OVER is neither live nor final,
            # and the final score (shootout winner included) only lands with
            # FINAL a few minutes later. Dropping to hourly here held the
            # final/result events back by an hour.
            self.update_interval = LIVE_UPDATE_INTERVAL
            return

        if self._game_is_live:
            # Game is no longer live
            _LOGGER.info(f"Game ended for {self.team_id}, switching back to 1-hour updates")
            self._game_is_live = False
            self._pregame_check_active = False
            self.update_interval = DEFAULT_UPDATE_INTERVAL
            return

        # Not live, and wasn't live: decide between pregame and idle polling.
        if self._is_game_finished(game) or game_start is None:
            self._set_pregame(False)
            return

        time_until_game = (game_start - dt_util.utcnow()).total_seconds()
        if time_until_game <= PREGAME_THRESHOLD.total_seconds():
            # Within the window (or the start time has passed but the feed has
            # not flipped to live yet) - poll often enough to catch puck drop.
            if not self._pregame_check_active:
                _LOGGER.info(f"Game for {self.team_id} starts in {int(time_until_game / 60)} minutes, switching to {int(PREGAME_UPDATE_INTERVAL.total_seconds())}-second updates")
            self._set_pregame(True)
        else:
            next_interval = self._interval_until_pregame(time_until_game)
            if self._pregame_check_active or next_interval != DEFAULT_UPDATE_INTERVAL:
                _LOGGER.debug(
                    f"Game for {self.team_id} is {int(time_until_game / 60)} min away, "
                    f"next check in {int(next_interval.total_seconds() / 60)} min"
                )
            self._pregame_check_active = False
            self.update_interval = next_interval

    @staticmethod
    def _interval_until_pregame(time_until_game: float) -> timedelta:
        """Sleep only up to the moment the pregame window opens.

        Polling hourly would step straight over the 15-minute window about
        three times in four, so the switch to fast polling never happened and
        the game was first noticed on some later hourly tick - up to 44 minutes
        after puck drop for feeds like HockeyTech that have no pregame state.
        Aiming at the window boundary makes the window reachable from any
        starting phase.
        """
        seconds_until_window = time_until_game - PREGAME_THRESHOLD.total_seconds()
        if seconds_until_window >= DEFAULT_UPDATE_INTERVAL.total_seconds():
            return DEFAULT_UPDATE_INTERVAL
        # Floor at the pregame cadence so a boundary landing cannot busy-loop.
        return max(timedelta(seconds=seconds_until_window), PREGAME_UPDATE_INTERVAL)

    def _set_pregame(self, active: bool) -> None:
        """Switch between pregame and idle polling intervals."""
        self._pregame_check_active = active
        self.update_interval = PREGAME_UPDATE_INTERVAL if active else DEFAULT_UPDATE_INTERVAL

    def _is_hockeytech_live(self, game: Dict[str, Any]) -> bool:
        """Check if a HockeyTech game is live."""
        return self._hockeytech_status(game) == GameStatus.LIVE

    @staticmethod
    def _hockeytech_status(game: Dict[str, Any]) -> Optional[str]:
        """Return the status code from a HockeyTech game clock payload."""
        if isinstance(game, dict) and "GC" in game:
            return game["GC"].get("Clock", {}).get("status")
        return None

    def _is_game_finished(self, game: Dict[str, Any]) -> bool:
        """Whether the game has already been played."""
        if self.league == "nhl":
            return isinstance(game, dict) and game.get("gameState") in ("FINAL", "OFF")
        return self._hockeytech_status(game) in (GameStatus.FINAL, GameStatus.UnofficialFinal)

    def _extract_game_start_datetime(self, game: Dict[str, Any]) -> Optional[datetime]:
        """Extract the game start time as an aware UTC datetime, or None."""
        if not isinstance(game, dict):
            return None

        if self.league == "nhl":
            # NHL boxscore carries the start time as ISO-8601 UTC.
            raw = game.get("startTimeUTC")
        else:
            # HockeyTech game clock carries it with a UTC offset.
            raw = game.get("GC", {}).get("Clock", {}).get("game_date_iso_8601")

        if not raw:
            return None

        parsed = dt_util.parse_datetime(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, datetime):
            _LOGGER.debug(f"Could not parse game start time {raw!r} for {self.team_id}")
            return None

        # as_utc() assumes HA's local timezone for a naive value; both feeds are
        # offset-aware, so this only normalises rather than guesses.
        return dt_util.as_utc(parsed)
