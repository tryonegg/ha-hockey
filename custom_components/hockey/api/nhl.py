import datetime
import asyncio
import time
from functools import partial
from dateutil import parser
from nhlpy import NHLClient
import logging
from typing import Any, Dict, List, Optional

_LOGGER = logging.getLogger(__name__)

class NHLApi:
    # nhlpy is synchronous, so calls run in a worker thread. wait_for keeps a
    # stalled request from blocking the coordinator indefinitely.
    REQUEST_TIMEOUT = 30  # seconds

    # The season schedule only changes when games are added/rescheduled, but it
    # is needed on every coordinator update to pick the current game. Cache it
    # so live-game polling does not refetch all ~82 games every 15 seconds.
    SCHEDULE_TTL = 600   # 10 minutes
    STANDINGS_TTL = 600  # 10 minutes; records change at most once a game day
    TEAMS_TTL = 3600     # 1 hour; team membership barely changes within a season

    def __init__(self) -> None:
        self.client = NHLClient()
        # cache key -> (expires_at_monotonic, schedule)
        self._schedule_cache: Dict[str, Any] = {}
        self._standings_cache: Dict[str, Any] = {}
        self._teams_cache: Optional[Any] = None

    async def _call(self, func) -> Any:
        """Run a blocking nhlpy call in a thread, under a timeout.

        Note: a timeout frees the coordinator but cannot kill the worker
        thread, which runs to completion on its own.
        """
        return await asyncio.wait_for(asyncio.to_thread(func), self.REQUEST_TIMEOUT)

    async def _get_season_schedule(self, team: str) -> Dict[str, Any]:
        """Return the team season schedule, cached for SCHEDULE_TTL seconds."""
        season = self.nhl_season_string()
        key = f"{team}:{season}"
        now = time.monotonic()

        cached = self._schedule_cache.get(key)
        if cached and cached[0] > now:
            return cached[1]

        schedule = await self._call(
            partial(self.client.schedule.team_season_schedule, team_abbr=team, season=season)
        )
        if not schedule or 'games' not in schedule:
            raise ValueError(f"Invalid schedule response for team {team}")

        self._schedule_cache[key] = (now + self.SCHEDULE_TTL, schedule)
        return schedule
    
    def is_game_live(self, game: Dict[str, Any]) -> bool:
        return game['gameState'] in('LIVE', 'CRIT', 'PRE')
    
    def nhl_season_string(self, ref_date: Optional[datetime.date] = None) -> str:
        """
        Return the NHL season string for the given reference date.
        
        The NHL season switches on July 1 each year.
        Example:
            • For a date in June 2024 → "20232024"
            • For a date in August 2024 → "20242025"
        
        Parameters
        ----------
        ref_date : datetime.date, optional
            The date to evaluate. If omitted, uses today's date (datetime.date.today()).
        
        Returns
        -------
        str
            The concatenated season string, e.g. "20242025".
        """
        # Use today if no explicit date was supplied
        
        if ref_date is None:
            ref_date = datetime.date.today()

        # Determine the “starting” year of the season
        # Seasons start on July 1, so any month >= July belongs to the next season.
        if ref_date.month >= 7:          # July (7) through December (12)
            start_year = ref_date.year
        else:                            # January (1) through June (6)
            start_year = ref_date.year - 1

        end_year = start_year + 1
        # Concatenate the two years without a separator
        return f"{start_year}{end_year}"

    @staticmethod
    def _broadcasts(game: Dict[str, Any], team: Optional[str] = None) -> List[str]:
        """National networks plus the tracked team's own regional feed.

        The NHL's `market` is relative to the game, not to the tracked team:
        "H" is the home team's regional feed and "A" the away team's. Which one
        the viewer can actually watch therefore depends on which side their
        team is on - filtering on "H" alone would surface the opponent's
        network on every road game. If the team cannot be identified in the
        game, only national feeds are returned.

        Populated only once broadcasters are assigned, so preseason and far-out
        games legitimately return an empty list.
        """
        tracked = str(team or "")
        home_abbr = str((game.get("homeTeam") or {}).get("abbrev") or "")
        away_abbr = str((game.get("awayTeam") or {}).get("abbrev") or "")

        keep = {"N"}
        if tracked and tracked == home_abbr:
            keep.add("H")
        elif tracked and tracked == away_abbr:
            keep.add("A")

        seen, names = set(), []
        for entry in game.get("tvBroadcasts") or []:
            if not isinstance(entry, dict) or entry.get("market") not in keep:
                continue
            name = (entry.get("network") or "").strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        return names

    def ha_formatted(self, game: Dict[str, Any], team: str, standings: Optional[Dict[str, Dict[str, Any]]] = None, schedule: Optional[List[Dict[str, Any]]] = None, last_result: Optional[Dict[str, Any]] = None, shootout: Optional[Dict[str, Any]] = None, divisions: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        # _LOGGER.debug(f"Formatting NHL game data for Home Assistant: {game}")
        TrackedTeamGoals = 0
        if game['gameState'] in('LIVE','FINAL', 'CRIT', 'OFF'):
            TrackedTeamGoals = game['homeTeam']['score'] if team == str(game['homeTeam']['abbrev']) else game['awayTeam']['score']
        home_abbr = game["homeTeam"]['abbrev']
        away_abbr = game["awayTeam"]['abbrev']
        opponent = away_abbr if team == str(home_abbr) else home_abbr
        return {
            "state":  game['gameState'],
            "game_id": str(game['id']) if game.get('id') is not None else None,
            "game_type": self._game_type(game),
            "milestone": self._milestone(schedule, game, team, divisions),
            "shootout": shootout,
            "last_result": last_result,
            "head_to_head": self._head_to_head(schedule, team, opponent, game),
            "datetime": game["startTimeUTC"] or None,
            "venue": game["venue"]['default'] or None,
            "broadcasts": self._broadcasts(game, team),
            "home": {
                "id": int( game["homeTeam"]['id']) or None,
                "name": game["homeTeam"]['commonName']['default'] or None,
                "nickname": None,
                "city": game["homeTeam"]['placeName']['default'] or None,
                "logo": game['homeTeam']['logo'] or None,
                "logo_dark": game['homeTeam'].get('darkLogo') or None,
                "abbr": game["homeTeam"]['abbrev'] or None,
                "record": (standings or {}).get(game["homeTeam"]['abbrev'])
            },
            "away": {
                "id": int( game["awayTeam"]['id']) or None,
                "name": game["awayTeam"]['commonName']['default'] or None,
                "nickname": None,
                "city": game["awayTeam"]['placeName']['default'] or None,
                "logo": game['awayTeam']['logo'] or None,
                "logo_dark": game['awayTeam'].get('darkLogo') or None,
                "abbr": game["awayTeam"]['abbrev'] or None,
                "record": (standings or {}).get(game["awayTeam"]['abbrev'])
            },
            "home_sog": game['homeTeam'].get('sog') if game['gameState'] in('LIVE','FINAL', 'CRIT', 'OFF') else None,
            "away_sog": game['awayTeam'].get('sog') if game['gameState'] in('LIVE','FINAL', 'CRIT', 'OFF') else None,
            "home_score":  game['homeTeam']['score'] if game['gameState'] in('LIVE','FINAL', 'CRIT', 'OFF') else None,
            "away_score":  game['awayTeam']['score'] if game['gameState'] in('LIVE','FINAL', 'CRIT', 'OFF') else None,
            "periodNumber": int(game["periodDescriptor"]['number']) if game['gameState'] in('LIVE','FINAL', 'CRIT', 'OFF') else None,
            "periodName": None,
            "periodType": game['periodDescriptor']['periodType'] if game['gameState'] in('LIVE','FINAL', 'CRIT', 'OFF') else None,
            "periodTimeRemaining": game["clock"]['timeRemaining'] if game['gameState'] in('LIVE','FINAL', 'CRIT', 'OFF') else None,
            "clock_running": game["clock"]['running'] if game['gameState'] in('LIVE','FINAL', 'CRIT', 'OFF') else None,
            "isIntermission": game["clock"]['inIntermission'] if game['gameState'] in('LIVE','FINAL', 'CRIT', 'OFF') else None,
            "situation": self._situation(game),
            "goal_tracked_team": TrackedTeamGoals,
            "specialEvent": game['specialEvent'] if 'specialEvent' in game else None
        }

    @staticmethod
    def _situation(game: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """On-ice strength, present only while a game is actually being played.

        The boxscore carries a `situation` block whenever the skaters are
        uneven or a goalie is pulled; it disappears at even strength and is
        absent entirely from a scheduled or finished game. `situationCode` is
        four digits - away goalie, away skaters, home skaters, home goalie -
        which is enough on its own to name the strength and spot an empty net.
        """
        sit = game.get("situation")
        if not isinstance(sit, dict):
            return None

        code = str(sit.get("situationCode") or "")
        away_goalie = home_goalie = None
        away = home = None
        if len(code) == 4 and code.isdigit():
            away_goalie, away, home, home_goalie = (int(c) for c in code)

        # Fall back to the per-side strength if the code is missing or odd.
        if away is None:
            away = (sit.get("awayTeam") or {}).get("strength")
            home = (sit.get("homeTeam") or {}).get("strength")
        if away is None or home is None:
            return None

        advantage = "home" if home > away else "away" if away > home else None
        descriptors = {
            "home": (sit.get("homeTeam") or {}).get("situationDescriptor") or [],
            "away": (sit.get("awayTeam") or {}).get("situationDescriptor") or [],
        }
        empty_net = None
        if home_goalie == 0:
            empty_net = "home"
        elif away_goalie == 0:
            empty_net = "away"

        # A pulled goalie adds a skater without being a power play, so the
        # extra attacker is discounted before comparing: 6v5 with an empty net
        # is even strength, 6v4 is still a power play. `advantage` keeps the
        # raw skater comparison, which is a different (and also true) fact.
        home_eff = home - (1 if empty_net == "home" else 0)
        away_eff = away - (1 if empty_net == "away" else 0)
        power_play = "home" if home_eff > away_eff else "away" if away_eff > home_eff else None

        return {
            "strength": f"{home}v{away}" if advantage == "home" else f"{away}v{home}",
            "home_skaters": home,
            "away_skaters": away,
            "advantage": advantage,
            "descriptor": (descriptors["home"] or descriptors["away"] or [None])[0],
            "empty_net": empty_net,
            "power_play": power_play,
            "time_remaining": sit.get("timeRemaining"),
        }

    @staticmethod
    def _record(row: Dict[str, Any]) -> Dict[str, Any]:
        """Normalise one standings row.

        The NHL folds shootout losses into otLosses, so points work out as
        2*wins + otLosses and `overtime_losses` needs no adjustment.
        """
        wins = row.get("wins") or 0
        losses = row.get("losses") or 0
        otl = row.get("otLosses") or 0
        return {
            "record": f"{wins}-{losses}-{otl}",
            "wins": wins,
            "losses": losses,
            "overtime_losses": otl,
            "points": row.get("points"),
            "games_played": row.get("gamesPlayed"),
        }

    async def get_standings(self) -> Dict[str, Dict[str, Any]]:
        """Season records keyed by team abbreviation.

        Returns an empty mapping before the season starts: the NHL publishes
        no standings rows until games have actually been played.
        """
        season = self.nhl_season_string()
        now = time.monotonic()
        cached = self._standings_cache.get(season)
        if cached and cached[0] > now:
            return cached[1]

        payload = await self._call(partial(self.client.standings.league_standings, season=season))
        rows = payload.get("standings", []) if isinstance(payload, dict) else (payload or [])
        records = {}
        for row in rows:
            abbrev = (row.get("teamAbbrev") or {}).get("default")
            if abbrev:
                records[abbrev] = self._record(row)

        self._standings_cache[season] = (now + self.STANDINGS_TTL, records)
        return records

    # NHL gameType: 1 preseason, 2 regular season, 3 playoffs.
    GAME_TYPES = {1: "preseason", 2: "regular", 3: "playoffs"}

    @classmethod
    def _game_type(cls, game: Dict[str, Any]) -> Optional[str]:
        """Competition this game belongs to, or None if unrecognised."""
        return cls.GAME_TYPES.get(game.get("gameType"))

    async def get_team_schedule(self, team: str) -> List[Dict[str, Any]]:
        """The team's games this season (served from the schedule cache)."""
        return (await self._get_season_schedule(team)).get("games") or []

    LIVE_STATES = ("LIVE", "CRIT", "PRE")
    FINAL_STATES = ("FINAL", "OFF")

    @staticmethod
    def _is_divisional(game: Dict[str, Any], divisions: Optional[Dict[str, str]]) -> bool:
        """Whether both teams share a division."""
        if not divisions or len(set(divisions.values())) < 2:
            return False
        home = divisions.get((game.get("homeTeam") or {}).get("abbrev"))
        away = divisions.get((game.get("awayTeam") or {}).get("abbrev"))
        return bool(home) and home == away

    @classmethod
    def _milestone(
        cls,
        schedule: Optional[List[Dict[str, Any]]],
        game: Dict[str, Any],
        team: str,
        divisions: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """The single notable thing about this matchup, if any.

        Only regular season games can be openers: an exhibition or playoff
        opener is not what anyone means by "season opener".

        Priority is fixed and matches how the card shows a single tag: home
        opener, then season opener, then a divisional matchup. A team opening
        at home plays one game that is all three, and it reads as the home
        opener.

        A league with a single division (the PWHL) is never tagged divisional,
        since every game would qualify and the tag would say nothing.
        """
        regular = [g for g in schedule or [] if g.get("gameType") == 2]
        game_id = game.get("id")

        if regular and game_id is not None:
            home_games = [g for g in regular if (g.get("homeTeam") or {}).get("abbrev") == team]
            if home_games and home_games[0].get("id") == game_id:
                return "home_opener"
            if regular[0].get("id") == game_id:
                return "season_opener"

        if cls._is_divisional(game, divisions):
            return "divisional"
        return None

    @classmethod
    def game_summary(cls, game: Dict[str, Any]):
        """(kind, start) for a schedule entry, where kind is live/final/future."""
        state = game.get("gameState")
        if state in cls.LIVE_STATES:
            kind = "live"
        elif state in cls.FINAL_STATES:
            kind = "final"
        else:
            kind = "future"
        raw = game.get("startTimeUTC")
        try:
            start = parser.parse(raw) if raw else None
        except (ValueError, TypeError):
            start = None
        return kind, start

    @classmethod
    def _game_result(cls, game: Dict[str, Any], team: str) -> Optional[Dict[str, Any]]:
        """Compact result of a completed game, or None if it has no final score."""
        if game.get("gameState") not in cls.FINAL_STATES:
            return None
        home, away = game.get("homeTeam") or {}, game.get("awayTeam") or {}
        home_score, away_score = home.get("score"), away.get("score")
        if home_score is None or away_score is None:
            return None

        tracked_at_home = home.get("abbrev") == team
        won = (home_score > away_score) if tracked_at_home else (away_score > home_score)
        return {
            "date": game.get("gameDate"),
            "home_abbr": home.get("abbrev"),
            "away_abbr": away.get("abbrev"),
            "home_score": home_score,
            "away_score": away_score,
            "result": (game.get("periodDescriptor") or {}).get("periodType"),
            "tracked_won": won,
        }

    @staticmethod
    def _playoff_round(game: Optional[Dict[str, Any]]) -> Optional[int]:
        """Playoff round of a game, read from its id.

        A playoff id is season, "03", then "0", round, series, game - so
        2025030217 is round 2, series 1, game 7. The boxscore carries no
        seriesStatus, so the id is the one thing it and the schedule share.
        """
        gid = str((game or {}).get("id") or "")
        if len(gid) == 10 and gid[4:6] == "03" and gid[7].isdigit():
            return int(gid[7])
        return None

    @classmethod
    def _head_to_head(
        cls,
        schedule: Optional[List[Dict[str, Any]]],
        team: str,
        opponent: str,
        game: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Meetings between the two teams in the competition being shown.

        A playoff game gets its playoff series: every game of the current round,
        played or still to come. Anything else gets the regular-season series.
        Preseason is never counted, so a preseason card describes the season
        ahead rather than a handful of exhibitions. Wins and losses are from the
        tracked team's point of view.
        """
        playoffs = (game or {}).get("gameType") == 3
        round_ = cls._playoff_round(game) if playoffs else None
        wins = losses = played = 0
        needed = None
        meetings = []
        for g in schedule or []:
            if playoffs:
                if g.get("gameType") != 3:
                    continue
                # Two teams meet in one round a year at most, so this is belt
                # and braces - but it keeps a malformed pairing out.
                if round_ is not None and cls._playoff_round(g) != round_:
                    continue
            elif g.get("gameType") != 2:
                continue
            if g.get("gameScheduleState") == "CNCL":
                continue
            home, away = g.get("homeTeam") or {}, g.get("awayTeam") or {}
            sides = {home.get("abbrev"), away.get("abbrev")}
            if team not in sides or opponent not in sides:
                continue

            needed = (g.get("seriesStatus") or {}).get("neededToWin") or needed

            # Every meeting on the calendar, played or not, in schedule order,
            # so the whole series can be listed rather than only its history.
            result = cls._game_result(g, team)
            if result:
                wins += int(result["tracked_won"])
                losses += int(not result["tracked_won"])
                played += 1
                meetings.append({**result, "played": True, "datetime": g.get("startTimeUTC")})
            else:
                meetings.append({
                    "date": g.get("gameDate"),
                    "datetime": g.get("startTimeUTC"),
                    "home_abbr": home.get("abbrev"),
                    "away_abbr": away.get("abbrev"),
                    "home_score": None,
                    "away_score": None,
                    "result": None,
                    "tracked_won": None,
                    "played": False,
                })

        # A series ends the moment the leader reaches neededToWin, so only the
        # games up to that point are certain; the rest are "if necessary". The
        # list is chronological, so a game's position is its game number.
        certain = played + needed - max(wins, losses) if playoffs and needed else None
        for number, m in enumerate(meetings, 1):
            m["if_necessary"] = certain is not None and not m["played"] and number > certain

        return {
            "kind": "playoffs" if playoffs else "season",
            "needed_to_win": needed if playoffs else None,
            "record": f"{wins}-{losses}",
            "wins": wins,
            "losses": losses,
            "team_abbr": team,
            "opponent_abbr": opponent,
            "scheduled": len(meetings),
            "remaining": len(meetings) - played,
            "games": meetings,
        }

    @staticmethod
    def went_to_shootout(game: Dict[str, Any]) -> bool:
        """Whether this game was decided in a shootout."""
        return (game.get("periodDescriptor") or {}).get("periodType") == "SO"

    async def get_shootout(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Round-by-round shootout attempts, or None if there was no shootout.

        The NHL returns a flat list of alternating attempts, so the round is
        derived by counting each side's attempts. A shootout stops the moment
        it is decided, so the last round can hold a single attempt.
        """
        story = await self._call(partial(self.client.game_center.game_story, game_id=game_id))
        attempts = ((story or {}).get("summary") or {}).get("shootout") or []
        if not attempts:
            return None

        home_abbr = (story.get("homeTeam") or {}).get("abbrev")
        counts = {"home": 0, "away": 0}
        goals = {"home": 0, "away": 0}
        rows = []
        for attempt in attempts:
            side = "home" if (attempt.get("teamAbbrev") or {}).get("default") == home_abbr else "away"
            counts[side] += 1
            scored = attempt.get("result") == "goal"
            if scored:
                goals[side] += 1
            first = (attempt.get("firstName") or {}).get("default") or ""
            last = (attempt.get("lastName") or {}).get("default") or ""
            rows.append({
                "round": counts[side],
                "side": side,
                "scored": scored,
                "winner": bool(attempt.get("gameWinner")),
                "player": f"{first} {last}".strip() or None,
                "goalie": None,
            })
        return {"home_goals": goals["home"], "away_goals": goals["away"], "attempts": rows}

    async def get_teams(self) -> List[Dict[str, Any]]:
        now = time.monotonic()
        if self._teams_cache and self._teams_cache[0] > now:
            return self._teams_cache[1]
        try:
            teams = await self._call(self.client.teams.teams)
            if not teams:
                _LOGGER.error("No teams returned from NHL API")
                return []
            teams = sorted(teams, key=lambda t: t["name"])
        except Exception as e:
            _LOGGER.error(f"Error fetching NHL teams: {e}")
            return []
        self._teams_cache = (now + self.TEAMS_TTL, teams)
        return teams

    async def get_divisions(self) -> Dict[str, str]:
        """Division name per team abbreviation.

        The NHL puts no division on the game itself, so a divisional matchup is
        worked out by comparing the two teams' divisions.
        """
        return {
            t["abbr"]: ((t.get("division") or {}).get("name") or "")
            for t in await self.get_teams()
            if t.get("abbr") and (t.get("division") or {}).get("name")
        }

    async def boxscore(self, id: str) -> Optional[Dict[str, Any]]:
        """Fetch the boxscore. Errors propagate to the coordinator."""
        return await self._call(partial(self.client.game_center.boxscore, game_id=id))
