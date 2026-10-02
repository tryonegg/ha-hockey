"""Hockey event platform.

Turns the polled game state into discrete events an automation can trigger on:
pre-game, puck drop, the start and end of each period, goals by either side and
goals taken back on review, power plays and penalty kills, a pulled goalie,
overtime, a shootout, the final whistle and the result.

Feeds call a game in progress before play has started: HockeyTech flips a game
live up to a quarter of an hour before puck drop, and advances the period
number early in each intermission. The start of play is therefore read from
the game clock moving, never from the state or the period number alone.
"""
import logging
from typing import Any, Dict, Optional

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, build_device_info, build_unique_id
from .coordinator import (
    HockeyGameDataCoordinator,
    LIVE_GAME_STATES,
    FINAL_GAME_STATES,
    PREGAME_THRESHOLD,
)

_LOGGER = logging.getLogger(__name__)

EVENT_PREGAME = "pregame"
EVENT_GAME_START = "game_start"
EVENT_PERIOD_START = "period_start"
EVENT_PERIOD_END = "period_end"
EVENT_GOAL = "goal"
EVENT_OPPONENT_GOAL = "opponent_goal"
EVENT_GOAL_OVERTURNED = "goal_overturned"
EVENT_OPPONENT_GOAL_OVERTURNED = "opponent_goal_overturned"
EVENT_POWER_PLAY = "power_play"
EVENT_PENALTY_KILL = "penalty_kill"
EVENT_GOALIE_PULLED = "goalie_pulled"
EVENT_OVERTIME = "overtime"
EVENT_SHOOTOUT = "shootout"
EVENT_FINAL = "final"
EVENT_WIN = "win"
EVENT_LOSS = "loss"

REGULATION_PERIODS = 3


def _clock_seconds(value: Any) -> Optional[int]:
    """Seconds left on an "MM:SS" game clock, or None if unreadable."""
    if not isinstance(value, str) or not value:
        return None
    total = 0
    for part in value.split(":"):
        if not part.isdigit():
            return None
        total = total * 60 + int(part)
    return total


def _total(data: Dict[str, Any], home_key: str, away_key: str) -> Optional[int]:
    """Sum of a home/away pair, or None if either side is missing."""
    home, away = data.get(home_key), data.get(away_key)
    if not isinstance(home, int) or not isinstance(away, int):
        return None
    return home + away


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up the hockey event entity from a config entry."""
    data = config_entry.data
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    async_add_entities([
        HockeyGameEvent(
            data.get("league"), data.get("team_id"), config_entry.title, data, coordinator
        ),
    ])
    return True


class HockeyGameEvent(CoordinatorEntity, EventEntity):
    """Fires an event whenever something happens in the tracked team's game."""

    _attr_event_types = [
        EVENT_PREGAME,
        EVENT_GAME_START,
        EVENT_PERIOD_START,
        EVENT_PERIOD_END,
        EVENT_GOAL,
        EVENT_OPPONENT_GOAL,
        EVENT_GOAL_OVERTURNED,
        EVENT_OPPONENT_GOAL_OVERTURNED,
        EVENT_POWER_PLAY,
        EVENT_PENALTY_KILL,
        EVENT_GOALIE_PULLED,
        EVENT_OVERTIME,
        EVENT_SHOOTOUT,
        EVENT_FINAL,
        EVENT_WIN,
        EVENT_LOSS,
    ]
    # Gives the event types readable labels in the automation editor.
    _attr_translation_key = "game_events"

    def __init__(
        self,
        league: str,
        team_id: str,
        team_name: str,
        data: Dict[str, Any],
        coordinator: HockeyGameDataCoordinator,
    ) -> None:
        super().__init__(coordinator)
        self._league = league
        self._team_id = team_id
        self._attr_unique_id = f"hockey_event_{build_unique_id(league, team_id, data.get('client_code'))}"
        self._attr_name = f"{league.upper()}_{team_name} Events"
        self._attr_has_entity_name = False
        self._attr_icon = "mdi:hockey-puck"
        self._attr_device_info = build_device_info(league, team_id, team_name, data.get("client_code"))
        self._reset(None)

    def _reset(self, key: Optional[str]) -> None:
        """Forget the previous game's detection state."""
        self._game_key = key
        self._fired: set = set()
        self._seen_state: Optional[str] = None
        # Last accepted score per side, and a drop waiting to be confirmed.
        self._seen_score: Dict[str, Optional[int]] = {"team": None, "opponent": None}
        self._pending_drop: Dict[str, Optional[int]] = {"team": None, "opponent": None}
        # The period number being watched, the highest clock reading seen in
        # it (its starting value) and the goals on the board when it appeared.
        self._period: Optional[int] = None
        self._period_clock: Optional[int] = None
        self._period_goals: Optional[int] = None
        # Highest period whose play has been seen under way; 0 before puck drop.
        self._underway = 0
        self._ended: set = set()
        self._seen_power_play: Optional[str] = None
        self._seen_empty_net: Optional[str] = None
        self._pull_reported = False
        # Whether the game reached overtime level (None until an OT period is
        # seen), and whether a level overtime ran out - which means a shootout.
        self._regulation_tied: Optional[bool] = None
        self._ot_expired_tied = False

    def _tracked_is_home(self, data: Dict[str, Any]) -> bool:
        """Whether the tracked team is the home side of this game."""
        home = data.get("home") or {}
        wanted = str(self._team_id)
        return str(home.get("abbr")) == wanted or str(home.get("id")) == wanted

    def _sides(self, data: Dict[str, Any]):
        """(tracked side, opponent side) as "home"/"away"."""
        return ("home", "away") if self._tracked_is_home(data) else ("away", "home")

    def _scores(self, data: Dict[str, Any]):
        """(tracked, opponent) scores, or (None, None) if not yet posted."""
        home, away = data.get("home_score"), data.get("away_score")
        if home is None or away is None:
            return None, None
        return (home, away) if self._tracked_is_home(data) else (away, home)

    def _event_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Shared payload attached to every event.

        Deliberately not called _context: Entity already uses that attribute
        for the Home Assistant Context object, and shadowing it makes every
        state write fail.
        """
        tracked, opponent = self._scores(data)
        home, away = data.get("home") or {}, data.get("away") or {}
        return {
            "game_id": data.get("game_id"),
            "team": (home if self._tracked_is_home(data) else away).get("abbr"),
            "opponent": (away if self._tracked_is_home(data) else home).get("abbr"),
            "team_score": tracked,
            "opponent_score": opponent,
            "period": data.get("periodNumber"),
            "game_state": data.get("state"),
            "game_type": data.get("game_type"),
        }

    def _fire(self, event_type: str, data: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> None:
        """Emit one event and write it, so each is a distinct state change."""
        payload = self._event_payload(data)
        if extra:
            payload.update(extra)
        self._trigger_event(event_type, payload)
        self.async_write_ha_state()

    def _is_pregame(self, data: Dict[str, Any]) -> bool:
        """Within the pre-game window, and the puck not yet dropped.

        Not tied to the feed's state: HockeyTech marks a game live up to a
        quarter of an hour before puck drop, which used to swallow this event.
        """
        if self._underway or data.get("state") in FINAL_GAME_STATES:
            return False
        start = dt_util.parse_datetime(data.get("datetime") or "")
        if start is None:
            return False
        until = (dt_util.as_utc(start) - dt_util.utcnow()).total_seconds()
        return 0 <= until <= PREGAME_THRESHOLD.total_seconds()

    @staticmethod
    def _is_overtime(data: Dict[str, Any]) -> bool:
        """Whether the period shown is an overtime (a shootout is not)."""
        period_type = data.get("periodType")
        if period_type == "SO":
            return False
        period = data.get("periodNumber")
        return period_type == "OT" or (isinstance(period, int) and period > REGULATION_PERIODS)

    @staticmethod
    def _looks_started(data: Dict[str, Any]) -> bool:
        """Best guess from a single update whether play has begun.

        Only for a game first seen live (after a restart, say), where there is
        no earlier update to watch the clock move against.
        """
        period = data.get("periodNumber")
        if isinstance(period, int) and period > 1:
            return True
        if data.get("clock_running") or data.get("isIntermission"):
            return True
        return bool(_total(data, "home_score", "away_score") or _total(data, "home_sog", "away_sog"))

    def _watch_period(self, data: Dict[str, Any]) -> None:
        """Start watching the period currently shown."""
        self._period = data.get("periodNumber")
        self._period_clock = _clock_seconds(data.get("periodTimeRemaining"))
        self._period_goals = _total(data, "home_score", "away_score")

    def _period_under_way(self, data: Dict[str, Any]) -> bool:
        """Whether play has started in the period shown.

        The clock counting down is the signal. It is compared with the highest
        reading seen in the period because feeds reset it upwards at a period
        change, and a jump straight to zero is a clock nobody ran. Clocks also
        freeze, so a shot or a goal in the period counts too.
        """
        if data.get("isIntermission"):
            return False
        if data.get("clock_running") is True:
            return True
        clock = _clock_seconds(data.get("periodTimeRemaining"))
        if clock and self._period_clock and clock < self._period_clock:
            return True
        if data.get("period_sog"):
            return True
        goals = _total(data, "home_score", "away_score")
        return goals is not None and self._period_goals is not None and goals > self._period_goals

    def _decided_in(self, data: Dict[str, Any], tracked: Optional[int], opponent: Optional[int]) -> Optional[str]:
        """How a finished game was decided: REG, OT or SO.

        Overtime needs a level game and ends on a one-goal margin, as does a
        shootout, so anything else was settled in regulation - even when a feed
        shows an OT period played out in a decided exhibition. A level overtime
        that ran out means a shootout, which HockeyTech's clock feed otherwise
        reports exactly like overtime.
        """
        if not isinstance(tracked, int) or not isinstance(opponent, int):
            return None
        if self._regulation_tied is False or abs(tracked - opponent) != 1:
            return "REG"
        if data.get("periodType") == "SO" or self._ot_expired_tied:
            return "SO"
        if self._regulation_tied or self._is_overtime(data):
            return "OT"
        return "REG"

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data or {}

        # A payload without a game (nothing scheduled) carries no events.
        if not data.get("home") or not data.get("away"):
            self._game_key = None
        else:
            # The game id, where the feed has one, is the game's identity; a
            # new game resets detection.
            key = data.get("game_id") or data.get("datetime")
            if key != self._game_key:
                self._reset(key)
                self._baseline(data)
            else:
                self._detect(data)
        super()._handle_coordinator_update()

    def _baseline(self, data: Dict[str, Any]) -> None:
        """Take in a game seen for the first time, without firing anything.

        Without this a restart mid-game would replay events that already
        happened.
        """
        state = data.get("state")
        live = state in LIVE_GAME_STATES
        tracked, opponent = self._scores(data)
        situation = data.get("situation") or {}
        ours, _ = self._sides(data)

        self._seen_state = state
        self._seen_score = {"team": tracked, "opponent": opponent}
        if isinstance(data.get("periodNumber"), int):
            self._watch_period(data)
        self._seen_power_play = situation.get("power_play")
        self._seen_empty_net = situation.get("empty_net")
        self._pull_reported = self._seen_empty_net == ours

        if state in FINAL_GAME_STATES or (live and self._looks_started(data)):
            period = data.get("periodNumber")
            self._underway = period if isinstance(period, int) else 1
            self._fired.update((EVENT_PREGAME, EVENT_GAME_START))
            if data.get("isIntermission") or _clock_seconds(data.get("periodTimeRemaining")) == 0:
                self._ended.add(self._underway)
        if live and self._is_overtime(data):
            # Sudden death: while overtime is live the score is still the one
            # regulation ended with.
            self._regulation_tied = isinstance(tracked, int) and tracked == opponent
        if live and data.get("periodType") == "SO":
            self._fired.add(EVENT_SHOOTOUT)

    def _detect(self, data: Dict[str, Any]) -> None:
        """Compare one update with what was seen before and fire the changes."""
        state = data.get("state")
        live = state in LIVE_GAME_STATES
        period = data.get("periodNumber")
        clock = _clock_seconds(data.get("periodTimeRemaining"))
        tracked, opponent = self._scores(data)

        if isinstance(period, int) and period != self._period:
            # A later period number means the one being watched is over,
            # whether or not an update caught its clock at zero.
            left = self._period
            if live and isinstance(left, int) and period > left and 1 <= left <= self._underway and left not in self._ended:
                self._ended.add(left)
                self._fire(EVENT_PERIOD_END, data, {"period": left})
            self._watch_period(data)
        elif clock is not None:
            self._period_clock = clock if self._period_clock is None else max(self._period_clock, clock)

        if EVENT_PREGAME not in self._fired and self._is_pregame(data):
            self._fired.add(EVENT_PREGAME)
            self._fire(EVENT_PREGAME, data)

        # A shootout is not a period of play: its clock never runs, and the
        # score only moves once it is decided.
        if (live and isinstance(period, int) and period > self._underway
                and data.get("periodType") != "SO" and self._period_under_way(data)):
            self._underway = period
            if EVENT_GAME_START not in self._fired:
                self._fired.add(EVENT_GAME_START)
                self._fire(EVENT_GAME_START, data)
            else:
                self._fire(EVENT_PERIOD_START, data)

        self._track_score("team", tracked, state, data)
        self._track_score("opponent", opponent, state, data)
        self._special_teams(data, live, tracked, opponent)

        if (live and isinstance(period, int) and period == self._underway and period not in self._ended
                and (data.get("isIntermission") or clock == 0)):
            self._ended.add(period)
            self._fire(EVENT_PERIOD_END, data)

        if live and self._is_overtime(data):
            level = isinstance(tracked, int) and tracked == opponent
            if self._regulation_tied is None:
                self._regulation_tied = level
                # Level is what makes it overtime: feeds also play out an OT
                # period in some decided exhibition games.
                if level:
                    self._fire(EVENT_OVERTIME, data)
            # Outside the playoffs, a level overtime that runs out is settled
            # by a shootout.
            if (level and clock == 0 and isinstance(period, int) and period <= self._underway
                    and data.get("game_type") != "playoffs"):
                self._ot_expired_tied = True

        # HockeyTech reports a shootout exactly like overtime while it is being
        # played, so only the NHL can announce one live.
        if (live and data.get("league") == "nhl" and data.get("periodType") == "SO"
                and EVENT_SHOOTOUT not in self._fired):
            self._fired.add(EVENT_SHOOTOUT)
            self._fire(EVENT_SHOOTOUT, data)

        if state in FINAL_GAME_STATES and self._seen_state not in FINAL_GAME_STATES:
            result = {"decided_in": self._decided_in(data, tracked, opponent)}
            if EVENT_FINAL not in self._fired:
                self._fired.add(EVENT_FINAL)
                self._fire(EVENT_FINAL, data, result)
            if isinstance(tracked, int) and isinstance(opponent, int) and tracked != opponent:
                outcome = EVENT_WIN if tracked > opponent else EVENT_LOSS
                if outcome not in self._fired:
                    self._fired.add(outcome)
                    self._fire(outcome, data, result)

        self._seen_state = state

    def _track_score(self, side: str, value: Optional[int], state: Optional[str], data: Dict[str, Any]) -> None:
        """Fire one event per goal scored, or per goal taken back, for one side.

        One event per goal keeps counting automations right when two land
        inside a single poll. A drop only counts once a second update agrees:
        a stale response from a CDN edge can briefly carry an older score,
        which would otherwise read as a goal overturned and then scored again.
        A final score is authoritative, so a drop there counts at once.
        """
        if not isinstance(value, int):
            return
        # No score yet means the game had not started when it was first seen.
        seen = self._seen_score[side] or 0
        field = "team_score" if side == "team" else "opponent_score"
        if value > seen:
            scored = EVENT_GOAL if side == "team" else EVENT_OPPONENT_GOAL
            for score in range(seen + 1, value + 1):
                self._fire(scored, data, {field: score})
        elif value < seen:
            if self._pending_drop[side] != value and state not in FINAL_GAME_STATES:
                self._pending_drop[side] = value
                return
            overturned = EVENT_GOAL_OVERTURNED if side == "team" else EVENT_OPPONENT_GOAL_OVERTURNED
            for score in range(seen - 1, value - 1, -1):
                self._fire(overturned, data, {field: score})
        self._pending_drop[side] = None
        self._seen_score[side] = value

    def _special_teams(
        self, data: Dict[str, Any], live: bool, tracked: Optional[int], opponent: Optional[int]
    ) -> None:
        """Power play, penalty kill and a pulled goalie.

        NHL only in practice: HockeyTech publishes no on-ice strength, so its
        situation is always None.
        """
        situation = data.get("situation") or {}
        power_play = situation.get("power_play")
        empty_net = situation.get("empty_net")
        ours, theirs = self._sides(data)

        if live and power_play != self._seen_power_play:
            if power_play == ours:
                self._fire(EVENT_POWER_PLAY, data, {"strength": situation.get("strength")})
            elif power_play == theirs:
                self._fire(EVENT_PENALTY_KILL, data, {"strength": situation.get("strength")})
        self._seen_power_play = power_play

        # A delayed penalty is also played with the net empty, for seconds at a
        # time. Still empty on a second update, in the third, while trailing,
        # is the pull an automation is after.
        if empty_net != ours:
            self._pull_reported = False
        elif (live and not self._pull_reported and self._seen_empty_net == ours
                and data.get("periodNumber") == REGULATION_PERIODS
                and isinstance(tracked, int) and isinstance(opponent, int) and tracked < opponent):
            self._pull_reported = True
            self._fire(EVENT_GOALIE_PULLED, data)
        self._seen_empty_net = empty_net
