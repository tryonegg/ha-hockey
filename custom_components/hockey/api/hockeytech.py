import aiohttp
import time
import logging
from urllib.parse import urlencode, quote
from cachetools import TTLCache
from dateutil import parser
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

_LOGGER = logging.getLogger(__name__)

class GameStatus:
    FUT = "1"
    LIVE = "2"
    UnofficialFinal = "3"
    FINAL = "4"

class GamePlayByPlayEvent:
    GoalieChange = "goalie_change"
    Faceoff = "faceoff"
    Shot = "shot"
    BlockedShot = "blocked_shot"
    Hit = "hit"
    Penalty = "penalty"
    Goal = "goal"

class HockeyTechApi:
    DEFAULT_TTL = 600        # 10 minutes
    REALTIME_TTL = 15        # 15 seconds
    REQUEST_TIMEOUT = 30     # seconds; without it a stalled feed hangs the coordinator

    REALTIME_TABS = {
        "clock",
        "pxp",
        "pxpverbose",
        "plays",
    }

    TEAMS = None

    def __init__(
        self,
        key: str,
        client_code: str,
        language: str = "en",
        proxy_base_url: str = "",
        session: Optional[aiohttp.ClientSession] = None,
        max_cache_size: int = 1024
    ) -> None:
        self._proxy_base_url = proxy_base_url
        self._modulekit_base_url = "https://lscluster.hockeytech.com/feed/"
        self._gamecenter_base_url = "https://cluster.leaguestat.com/feed/"
        self._key = key
        self._client_code = client_code
        self._language = language
        self._session = session

        # Cache stores raw JSON responses
        self._cache: TTLCache = TTLCache(maxsize=max_cache_size, ttl=self.DEFAULT_TTL)

    # -------------------------
    # URL + Params
    # -------------------------

    def _get_base_params(self, feed: str) -> Dict[str, str]:
        return {
            "feed": feed,
            "key": self._key,
            "fmt": "json",
            "client_code": self._client_code
        }

    def _get_modulekit_params(self, view: str) -> Dict[str, str]:
        params = self._get_base_params("modulekit")
        params.update({"view": view, "lang": self._language})
        return params

    def _get_gamecenter_params(self, game_id: str, tab: str) -> Dict[str, str]:
        params = self._get_base_params("gc")
        params.update({
            "game_id": game_id,
            "tab": tab,
            "lang_code": self._language
        })
        return params

    def _build_url(self, base_url: str, params: Dict[str, str]) -> str:
        query = urlencode(params)
        endpoint = f"{base_url}?{query}"

        if self._proxy_base_url:
            return f"{self._proxy_base_url}{quote(endpoint, safe='')}"
        return endpoint

    # -------------------------
    # Caching Logic
    # -------------------------

    def _is_realtime_request(self, url: str) -> bool:
        """
        Determines if the request should use realtime TTL.
        """
        return any(f"tab={tab}" in url for tab in self.REALTIME_TABS)

    def _get_ttl_for_request(self, url: str) -> int:
        return self.REALTIME_TTL if self._is_realtime_request(url) else self.DEFAULT_TTL

    async def _request(self, url: str) -> Dict[str, Any]:
        """
        Central request handler with per-request TTL caching.
        """
        now = time.time()

        # Cache entry format: (expires_at, data)
        cached = self._cache.get(url)
        if cached:
            expires_at, data = cached
            if expires_at > now:
                # _LOGGER.debug(f"Using cached data for URL: {url}")
                return data
            else:
                del self._cache[url]

        timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
        if self._session is None:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    data = await response.json()
        else:
            async with self._session.get(url, timeout=timeout) as response:
                response.raise_for_status()
                data = await response.json()

        ttl = self._get_ttl_for_request(url)
        self._cache[url] = (now + ttl, data)
        # _LOGGER.debug(f"Fetched and cached data for URL: {url}")
        return data

    # -------------------------
    # Modulekit Endpoints
    # -------------------------

    async def get_daily_schedule(self, fetch_date: str) -> Dict[str, Any]:
        params = self._get_modulekit_params("gamesbydate")
        params["fetch_date"] = fetch_date
        return await self._request(self._build_url(self._modulekit_base_url, params))

    async def get_games_per_day(self, start_date: str, end_date: str) -> Dict[str, Any]:
        params = self._get_modulekit_params("gamesperday")
        params.update({"start_date": start_date, "end_date": end_date})
        return await self._request(self._build_url(self._modulekit_base_url, params))

    async def get_roster(self, season_id: str, team_id: str) -> Dict[str, Any]:
        params = self._get_modulekit_params("roster")
        params.update({"season_id": season_id, "team_id": team_id})
        return await self._request(self._build_url(self._modulekit_base_url, params))

    async def get_scorebar(self, number_of_days_ahead: int, number_of_days_back: int) -> Dict[str, Any]:
        params = self._get_modulekit_params("scorebar")
        params.update({
            "numberofdaysahead": number_of_days_ahead,
            "numberofdaysback": number_of_days_back
        })
        return await self._request(self._build_url(self._modulekit_base_url, params))

    async def get_player_profile_bio(self, player_id: str) -> Dict[str, Any]:
        params = self._get_modulekit_params("player")
        params.update({"player_id": player_id, "category": "profile"})
        return await self._request(self._build_url(self._modulekit_base_url, params))

    async def get_player_profile_media(self, person_id: str) -> Dict[str, Any]:
        params = self._get_modulekit_params("player")
        params.update({"person_id": person_id})
        return await self._request(self._build_url(self._modulekit_base_url, params))

    async def get_player_profile_stats_by_season(self, player_id: str) -> Dict[str, Any]:
        params = self._get_modulekit_params("player")
        params.update({"player_id": player_id, "category": "seasonstats"})
        return await self._request(self._build_url(self._modulekit_base_url, params))

    async def get_standings(self, season_id: str, stat: str = "conference", standing_type: str = "standings") -> Dict[str, Any]:
        params = self._get_modulekit_params("statviewtype")
        params.update({
            "season_id": season_id,
            "stat": stat,
            "type": standing_type
        })
        return await self._request(self._build_url(self._modulekit_base_url, params))

    async def get_seasons(self) -> List[Dict[str, Any]]:
        """Every season the league publishes, newest first."""
        params = self._get_modulekit_params("seasons")
        response = await self._request(self._build_url(self._modulekit_base_url, params))
        return response['SiteKit']['Seasons']

    @staticmethod
    def _season_date(value: Any) -> Optional[Any]:
        """Parse a YYYY-MM-DD season boundary, or None if unusable."""
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None

    @classmethod
    def _is_trackable_season(cls, season: Dict[str, Any]) -> bool:
        """Whether a season is one of the team's own competitions.

        career == 1 covers regular season and playoffs. Preseason is published
        with career == 0 so it has to be matched by name - which also keeps
        one-off events like all-star or prospects games from being selected.
        """
        if str(season.get("career")) == "1":
            return True
        return cls._game_type(season) == "preseason"

    async def get_current_season(self) -> Optional[Dict[str, Any]]:
        """The season in progress, else the next to start, else the most recent.

        HockeyTech splits preseason, regular season and playoffs into separate
        seasons, so the season has to be chosen by date. Taking the newest
        season id instead would always land on the regular season and make
        preseason games invisible, because the regular season is published
        with a higher id before preseason has even finished.
        """
        seasons = [s for s in await self.get_seasons() if self._is_trackable_season(s)]
        if not seasons:
            return None

        today = datetime.now(timezone.utc).date()
        dated = [
            (s, self._season_date(s.get("start_date")), self._season_date(s.get("end_date")))
            for s in seasons
        ]

        in_progress = [(s, st) for s, st, en in dated if st and en and st <= today <= en]
        if in_progress:
            # Latest start wins if two ever overlap.
            return max(in_progress, key=lambda pair: pair[1])[0]

        upcoming = [(s, st) for s, st, _ in dated if st and st > today]
        if upcoming:
            return min(upcoming, key=lambda pair: pair[1])[0]

        finished = [(s, en) for s, _, en in dated if en]
        if finished:
            return max(finished, key=lambda pair: pair[1])[0]

        return seasons[0]

    async def get_teams(self) -> List[Dict[str, Any]]:
        """Every team the league has, independent of any season.

        The teamsbyseason view returns the full league when season_id is
        omitted. Season-scoped lists are the wrong source for a team picker:
        a playoff season only contains the teams that qualified (plus a "TBD"
        placeholder), and a league that has not published its next schedule
        yet would otherwise offer only last season's playoff field.
        """
        params = self._get_modulekit_params("teamsbyseason")
        response = await self._request(self._build_url(self._modulekit_base_url, params))
        teams = response['SiteKit']['Teamsbyseason']
        for team in teams:
            team["nickname"] = self._resolve_nickname(team.get("nickname"), team.get("city"))
        return sorted(teams, key=lambda team: str(team.get("name") or ""))

    async def get_divisions(self) -> Dict[str, str]:
        """Division name per team id."""
        return {
            str(t["id"]): (t.get("division_long_name") or t.get("division_short_name") or "")
            for t in await self.get_teams()
            if t.get("id") and (t.get("division_long_name") or t.get("division_short_name"))
        }

    async def get_teams_by_season(self, season_id: str) -> List[Dict[str, Any]]:
        params = self._get_modulekit_params("teamsbyseason")
        params["season_id"] = season_id
        teams = (await self._request(self._build_url(self._modulekit_base_url, params)))['SiteKit']['Teamsbyseason']
        for team in teams:
            team["nickname"] = self._resolve_nickname(team.get("nickname"), team.get("city"))
        self.TEAMS = teams
        return self.TEAMS
        

    async def get_season_schedule(self, season_id: str, team_id: int = 0) -> Dict[str, Any]:
        params = self._get_modulekit_params("schedule")
        params["season_id"] = season_id
        if team_id:
            params["team_id"] = team_id
        return (await self._request(self._build_url(self._modulekit_base_url, params)))['SiteKit']['Schedule']

    @staticmethod
    def went_to_shootout(schedule_game: Optional[Dict[str, Any]]) -> bool:
        """Whether this game was decided in a shootout."""
        return bool(schedule_game) and str(schedule_game.get("shootout")) == "1"

    async def get_shootout(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Round-by-round shootout attempts, or None if there was no shootout.

        shootoutDetail is ordered by internal record id rather than by round,
        so it is re-sorted. The order the two sides shot within a round is not
        recoverable, which does not matter for a per-team display.
        """
        summary = await self.get_game_summary(game_id)
        section = ((summary or {}).get("GC") or {}).get("Gamesummary") or {}
        detail = section.get("shootoutDetail") or []
        if not detail:
            return None

        rows = []
        for entry in sorted(detail, key=lambda d: (self._as_int(d.get("shot_order")), str(d.get("home")))):
            goalie = f"{entry.get('goalie_first_name') or ''} {entry.get('goalie_last_name') or ''}".strip()
            player = f"{entry.get('first_name') or ''} {entry.get('last_name') or ''}".strip()
            rows.append({
                "round": self._as_int(entry.get("shot_order")),
                "side": "home" if str(entry.get("home")) == "1" else "away",
                "scored": str(entry.get("goal")) == "1",
                "winner": str(entry.get("winning_goal")) == "1",
                "player": player or None,
                "goalie": goalie or None,
            })
        return {
            "home_goals": self._as_int(section.get("homeShootout")),
            "away_goals": self._as_int(section.get("visitorShootout")),
            "attempts": rows,
        }

    def is_game_live(self, game: Dict[str, Any]) -> bool:
        return game['status'] == GameStatus.LIVE

    # -------------------------
    # GameCenter (Realtime-aware)
    # -------------------------

    async def get_game_clock(self, game_id: str) -> Dict[str, Any]:
        params = self._get_gamecenter_params(game_id, "clock")
        return await self._request(self._build_url(self._gamecenter_base_url, params))

    async def get_game_preview(self, game_id: str) -> Dict[str, Any]:
        params = self._get_gamecenter_params(game_id, "preview")
        return await self._request(self._build_url(self._gamecenter_base_url, params))

    async def get_game_play_by_play(self, game_id: str) -> Dict[str, Any]:
        params = self._get_gamecenter_params(game_id, "pxpverbose")
        return await self._request(self._build_url(self._gamecenter_base_url, params))

    async def get_game_summary(self, game_id: str) -> Dict[str, Any]:
        params = self._get_gamecenter_params(game_id, "gamesummary")
        return await self._request(self._build_url(self._gamecenter_base_url, params))

    @staticmethod
    def _team_logo(teams: Optional[List[Dict[str, Any]]], team_id: Any) -> Optional[str]:
        """Look up a team logo, tolerating a missing or stale team list.

        The cached team list can be for a different season than the game, so a
        miss is expected rather than exceptional; return None instead of
        raising StopIteration out of a generator.
        """
        if not teams:
            return None
        match = next(
            (item for item in teams if str(item.get("id")) == str(team_id)),
            None,
        )
        return match.get("team_logo_url") if match else None

    @staticmethod
    def _as_int(value: Any, default: int = 0) -> int:
        """Coerce a HockeyTech numeric string, which may be empty."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _record(cls, row: Dict[str, Any]) -> Dict[str, Any]:
        """Normalise one standings row.

        HockeyTech keeps overtime and shootout losses in separate columns and
        both are worth a point, so `overtime_losses` sums them. Verified
        against a full OHL season: points == 2*wins + ot + so for every team.
        """
        wins = cls._as_int(row.get("wins"))
        losses = cls._as_int(row.get("losses"))
        otl = cls._as_int(row.get("ot_losses"))
        sol = cls._as_int(row.get("shootout_losses"))
        return {
            "record": f"{wins}-{losses}-{otl}-{sol}",
            "wins": wins,
            "losses": losses,
            # Normalised total, plus the split the record string actually shows
            # so each digit can be named.
            "overtime_losses": otl + sol,
            "ot_losses": otl,
            "shootout_losses": sol,
            "points": cls._as_int(row.get("points")),
            "games_played": cls._as_int(row.get("games_played")),
        }

    async def get_standings_by_season(self, season_id: str) -> Dict[str, Dict[str, Any]]:
        """Season records keyed by team id.

        The standings view interleaves divider rows that carry only a heading,
        so rows without a team_id are skipped.
        """
        payload = await self.get_standings(season_id)
        rows = (payload or {}).get("SiteKit", {}).get("Statviewtype") or []
        return {
            str(row["team_id"]): self._record(row)
            for row in rows
            if row.get("team_id")
        }

    @staticmethod
    def _game_type(season_info: Optional[Dict[str, Any]]) -> Optional[str]:
        """Competition this game belongs to.

        HockeyTech splits preseason, regular season and playoffs into separate
        seasons rather than tagging individual games, so the season record is
        what identifies the competition.
        """
        if not season_info:
            return None
        if str(season_info.get("playoff")) == "1":
            return "playoffs"
        name = str(season_info.get("season_name") or "").lower()
        if "pre-season" in name or "preseason" in name or "pre season" in name or "exhibition" in name:
            return "preseason"
        return "regular"

    @classmethod
    def _milestone(
        cls,
        schedule: Optional[List[Dict[str, Any]]],
        schedule_game: Optional[Dict[str, Any]],
        team_id: Any,
        season_info: Optional[Dict[str, Any]],
        divisions: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """The single notable thing about this matchup, if any.

        Preseason and playoffs are separate seasons here, and neither has an
        opener worth tagging, so only the regular season qualifies. The
        schedule is already filtered to the tracked team.

        Priority is fixed and matches how the card shows a single tag: home
        opener, then season opener, then a divisional matchup. A team opening
        at home plays one game that is all three, and it reads as the home
        opener.

        A league with a single division (the PWHL) is never tagged divisional,
        since every game would qualify and the tag would say nothing.
        """
        if schedule and schedule_game and cls._game_type(season_info) == "regular":
            game_id = str(schedule_game.get("game_id"))
            home_games = [g for g in schedule if str(g.get("home_team")) == str(team_id)]
            if home_games and str(home_games[0].get("game_id")) == game_id:
                return "home_opener"
            if str(schedule[0].get("game_id")) == game_id:
                return "season_opener"

        if cls._is_divisional(schedule_game, divisions):
            return "divisional"
        return None

    @staticmethod
    def _is_divisional(schedule_game: Optional[Dict[str, Any]], divisions: Optional[Dict[str, str]]) -> bool:
        """Whether both teams share a division."""
        if not schedule_game or not divisions or len(set(divisions.values())) < 2:
            return False
        home = divisions.get(str(schedule_game.get("home_team")))
        away = divisions.get(str(schedule_game.get("visiting_team")))
        return bool(home) and home == away

    @classmethod
    def game_summary(cls, game: Dict[str, Any]):
        """(kind, start) for a schedule entry, where kind is live/final/future."""
        status = str(game.get("status"))
        if status == GameStatus.LIVE:
            kind = "live"
        elif status in (GameStatus.FINAL, GameStatus.UnofficialFinal):
            kind = "final"
        else:
            kind = "future"
        # date_time_played is the local wall-clock time wrongly marked as UTC
        # ("19:00:00Z" for a 19:00 -05:00 start); GameDateISO8601 carries the
        # real offset, and matches the clock feed.
        raw = game.get("GameDateISO8601") or game.get("date_time_played")
        try:
            start = parser.parse(raw) if raw else None
        except (ValueError, TypeError):
            start = None
        return kind, start

    @classmethod
    def _game_result(cls, game: Dict[str, Any], team_id: Any) -> Optional[Dict[str, Any]]:
        """Compact result of a completed game, or None if it is not final."""
        if game.get("status") not in (GameStatus.FINAL, GameStatus.UnofficialFinal):
            return None

        home, away = str(game.get("home_team")), str(game.get("visiting_team"))
        home_score = cls._as_int(game.get("home_goal_count"))
        away_score = cls._as_int(game.get("visiting_goal_count"))
        tracked_at_home = home == str(team_id)
        won = (home_score > away_score) if tracked_at_home else (away_score > home_score)

        if str(game.get("shootout")) == "1":
            result = "SO"
        elif str(game.get("overtime")) == "1":
            result = "OT"
        else:
            result = "REG"
        return {
            "date": game.get("date_played"),
            "home_abbr": game.get("home_team_code"),
            "away_abbr": game.get("visiting_team_code"),
            "home_score": home_score,
            "away_score": away_score,
            "result": result,
            "tracked_won": won,
        }

    @classmethod
    def _head_to_head(
        cls,
        schedule: Optional[List[Dict[str, Any]]],
        team_id: Any,
        opponent_id: Any,
        schedule_game: Optional[Dict[str, Any]] = None,
        season_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Meetings between the two teams in the competition being shown.

        HockeyTech scopes preseason, regular season and playoffs into separate
        season ids, so the schedule is already the right competition. In the
        playoffs it is narrowed further to the displayed game's series letter:
        the games of the current round. Wins and losses are from the tracked
        team's point of view.

        HockeyTech publishes no series length - the bracket feed has no
        games-to-win - so `needed_to_win` stays None; each game's own
        if_necessary flag is what marks the games a series may not need.
        """
        playoffs = cls._game_type(season_info) == "playoffs"
        letter = str((schedule_game or {}).get("game_letter") or "") if playoffs else ""
        team_id, opponent_id = str(team_id), str(opponent_id)
        wins = losses = played = 0
        meetings = []
        team_abbr = opponent_abbr = None
        for game in schedule or []:
            home, away = str(game.get("home_team")), str(game.get("visiting_team"))
            if {home, away} != {team_id, opponent_id}:
                continue
            if letter and str(game.get("game_letter") or "") != letter:
                continue

            if team_abbr is None:
                if home == team_id:
                    team_abbr, opponent_abbr = game.get("home_team_code"), game.get("visiting_team_code")
                else:
                    team_abbr, opponent_abbr = game.get("visiting_team_code"), game.get("home_team_code")

            # Every meeting on the calendar, played or not, in schedule order,
            # so the whole series can be listed rather than only its history.
            result = cls._game_result(game, team_id)
            if result:
                wins += int(result["tracked_won"])
                losses += int(not result["tracked_won"])
                played += 1
                meetings.append({
                    **result, "played": True, "if_necessary": False,
                    "datetime": game.get("GameDateISO8601"),
                })
            else:
                meetings.append({
                    "date": game.get("date_played"),
                    "datetime": game.get("GameDateISO8601"),
                    "home_abbr": game.get("home_team_code"),
                    "away_abbr": game.get("visiting_team_code"),
                    "home_score": None,
                    "away_score": None,
                    "result": None,
                    "tracked_won": None,
                    "played": False,
                    "if_necessary": playoffs and str(game.get("if_necessary")) == "1",
                })

        return {
            "kind": "playoffs" if playoffs else "season",
            "needed_to_win": None,
            "record": f"{wins}-{losses}",
            "wins": wins,
            "losses": losses,
            "team_abbr": team_abbr,
            "opponent_abbr": opponent_abbr,
            "scheduled": len(meetings),
            "remaining": len(meetings) - played,
            "games": meetings,
        }

    @staticmethod
    def _broadcasts(schedule_game: Optional[Dict[str, Any]]) -> List[str]:
        """Broadcaster names from the schedule entry's `broadcasters` map.

        That map is keyed by feed type (home_video, visiting_webcast, ...) and
        the same broadcaster usually appears under several, so dedupe by name.
        The game clock feed carries none of this, hence the schedule entry.
        """
        if not schedule_game:
            return []
        broadcasters = schedule_game.get("broadcasters")
        if not isinstance(broadcasters, dict):
            return []
        seen, names = set(), []
        for entries in broadcasters.values():
            for entry in entries or []:
                name = (entry.get("name") or "").strip() if isinstance(entry, dict) else ""
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)
        return names

    @staticmethod
    def _resolve_nickname(nickname: Optional[str], city: Optional[str]) -> Optional[str]:
        """Fall back to the team's city when its nickname is just "PWHL".

        Hamilton, Vegas, San Jose and Detroit have no nickname yet, so the
        PWHL feed sends the literal string "PWHL" as the nickname. The city
        is the only other identifying part of the team's name in that case.
        """
        if nickname and nickname.strip().upper() == "PWHL":
            return city or None
        return nickname or None

    @classmethod
    def _team_nickname(cls, team: Dict[str, Any]) -> Optional[str]:
        return cls._resolve_nickname(team.get("team_nickname"), team.get("team_city"))

    @classmethod
    def _period_type(cls, period: Any, period_name: Any, schedule_game: Optional[Dict[str, Any]]) -> str:
        """Map HockeyTech period info onto NHL-style REG / OT / SO.

        The clock feed reports a shootout as period 4 / "OT", exactly like an
        overtime, so SO can only be told apart via the schedule entry's flag.
        """
        if schedule_game and str(schedule_game.get("shootout")) == "1":
            return "SO"

        name = str(period_name or "").strip().lower()
        if "shootout" in name or name == "so":
            return "SO"
        if cls._as_int(period) > 3 or "overtime" in name or name.startswith("ot"):
            return "OT"
        return "REG"

    def ha_formatted(self, game: Dict[str, Any], teams: List[Dict[str, Any]], team: int, schedule_game: Optional[Dict[str, Any]] = None, standings: Optional[Dict[str, Dict[str, Any]]] = None, schedule: Optional[List[Dict[str, Any]]] = None, season_info: Optional[Dict[str, Any]] = None, last_result: Optional[Dict[str, Any]] = None, shootout: Optional[Dict[str, Any]] = None, divisions: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        game = game["GC"]['Clock']
        TrackedTeamGoals = int(game["home_goal_count"]) if team == int(game["home_team"]['team_id']) else int(game["visiting_goal_count"])
        id_to_name = {v: k for k, v in vars(GameStatus).items() if not k.startswith("__")}
        
        isIntermission = False
        # if game['game_clock'] == "00:00" and game['period'] != 0 and game['status'] == GameStatus.LIVE:
        # if game['game_clock'] == "00:00" and game['period'] != 0 and game['status'] == GameStatus.LIVE:
            # if game['period'] <= 3:
                # isIntermission = True
            # elif game['period'] > 3:
            #     if game['period_name'] in ("Intermission", "Overtime Break"):
            #         isIntermission = True
            
        # Format time remaining - remove leading "00:" if present
        time_remaining = game["game_clock"] or None
        if time_remaining and time_remaining.startswith("00:"):
            time_remaining = time_remaining[3:]
        
        home_id = game["home_team"]['team_id']
        away_id = game["visiting_team"]['team_id']
        opponent = away_id if str(team) == str(home_id) else home_id

        # Shots are kept per period, keyed by period number. The current
        # period's count is a clean sign that its play has started: the
        # clock can freeze on some feeds, and the end-of-period stats
        # correction that bumps the totals lands on the period just played.
        shots = game.get("shots_on_goal") or {}
        current = str(game.get("period") or "")
        period_sog = sum(self._as_int((shots.get(side) or {}).get(current)) for side in ("home", "visiting"))

        # The clock feed carries no game id; the schedule entry does.
        game_id = (schedule_game or {}).get("game_id")
        return {
            "state":  id_to_name.get(game["status"]) or None,
            "game_id": str(game_id) if game_id else None,
            "game_type": self._game_type(season_info),
            "milestone": self._milestone(schedule, schedule_game, team, season_info, divisions),
            "shootout": shootout,
            "last_result": last_result,
            "head_to_head": self._head_to_head(schedule, team, opponent, schedule_game, season_info),
            "datetime": game["game_date_iso_8601"] or None,
            "venue": game["venue"] or None,
            "broadcasts": self._broadcasts(schedule_game),
            "home": {
                "id": self._as_int(game["home_team"]['team_id']),
                "name": game["home_team"]['name'] or None,
                "nickname": self._team_nickname(game["home_team"]),
                "city": game["home_team"]['team_city'] or None,
                "logo": self._team_logo(teams, game["home_team"]['team_id']),
                "abbr": game["home_team"]['team_code'] or None,
                "record": (standings or {}).get(str(game["home_team"]['team_id']))
            },
            "away": {
                "id": self._as_int(game["visiting_team"]['team_id']),
                "name": game["visiting_team"]['name'] or None,
                "nickname": self._team_nickname(game["visiting_team"]),
                "city": game["visiting_team"]['team_city'] or None,
                "logo": self._team_logo(teams, game["visiting_team"]['team_id']),
                "abbr": game["visiting_team"]['team_code'] or None,
                "record": (standings or {}).get(str(game["visiting_team"]['team_id']))
            },
            "home_sog": sum(game["shots_on_goal"]['home'].values()),
            "away_sog": sum(game["shots_on_goal"]['visiting'].values()),
            "period_sog": period_sog,
            "home_score":  int(game["home_goal_count"]) or 0,
            "away_score":  int(game["visiting_goal_count"]) or 0,
            "periodNumber": self._as_int(game["period"]),
            "periodName": game["period_name"] or None,
            "periodType": self._period_type(game["period"], game["period_name"], schedule_game),
            "periodTimeRemaining": time_remaining,
            "goal_tracked_team": TrackedTeamGoals,
            # HockeyTech has no on-ice strength: the clock feed's `power_play`
            # block is season totals (opportunities and goals), not who is
            # currently a skater up. Kept None so the card simply omits it.
            "situation": None,
            "specialEvent" : None,
        }
