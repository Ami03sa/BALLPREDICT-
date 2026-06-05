"""
Real-time injury report and confirmed lineup service.

Two data sources, both free and no API key required:

  1. ESPN Game Summary  — per-game injury list with status (Out / Day-To-Day /
                          Questionable / Doubtful) and injury type/return date.
                          Polled once per game_id; refreshed every 20 minutes.

  2. ESPN Team Roster   — full roster with per-player injury records. Used to
                          catch team-wide injury lists even when no game is
                          scheduled today (e.g. early-morning prediction runs).

Outputs
-------
  get_injury_statuses(game_id, home_abbr, away_abbr)
      → dict[player_id, InjuryStatus]

  get_confirmed_starters(espn_game_id)
      → dict[player_id, bool]   # True = confirmed starter
        (populated ~1 hr before tip when ESPN boxscore goes live)

  is_confirmed_out(player_id, game_id, home_abbr, away_abbr)
      → (bool, str | None)       # (is_out, reason_string)
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "nba_training.db"

# ── ESPN abbreviation → our DB abbreviation ──────────────────────────────────
_ESPN_TO_DB: dict[str, str] = {
    "ATL": "ATL", "BKN": "BKN", "BOS": "BOS", "CHA": "CHA", "CHI": "CHI",
    "CLE": "CLE", "DAL": "DAL", "DEN": "DEN", "GS":  "GSW", "HOU": "HOU",
    "IND": "IND", "LAC": "LAC", "LAL": "LAL", "MEM": "MEM", "MIA": "MIA",
    "MIL": "MIL", "MIN": "MIN", "NO":  "NOP", "NY":  "NYK", "OKC": "OKC",
    "ORL": "ORL", "PHI": "PHI", "PHX": "PHX", "POR": "POR", "SA":  "SAS",
    "SAC": "SAC", "TOR": "TOR", "UTAH":"UTA", "WSH": "WAS",
}

# ESPN team abbreviation → ESPN numeric team ID (for roster endpoint)
_ESPN_TEAM_IDS: dict[str, str] = {
    "ATL": "1",  "BKN": "17", "BOS": "2",  "CHA": "30", "CHI": "4",
    "CLE": "5",  "DAL": "6",  "DEN": "7",  "GS":  "9",  "HOU": "10",
    "IND": "11", "LAC": "12", "LAL": "13", "MEM": "29", "MIA": "14",
    "MIL": "15", "MIN": "16", "NO":  "3",  "NY":  "18", "OKC": "25",
    "ORL": "19", "PHI": "20", "PHX": "21", "POR": "22", "SA":  "24",
    "SAC": "23", "TOR": "28", "UTAH":"26", "WSH": "27",
}

# Reverse map: our DB abbreviation → ESPN abbreviation
_DB_TO_ESPN: dict[str, str] = {v: k for k, v in _ESPN_TO_DB.items()}

# Statuses ESPN uses for injured players
_OUT_STATUSES      = {"Out", "Injured Reserve", "Suspended"}
_RISKY_STATUSES    = {"Day-To-Day", "Doubtful", "Questionable"}


@dataclass
class InjuryStatus:
    player_id:   str
    player_name: str
    status:      str          # "Out" / "Day-To-Day" / "Questionable" / "Doubtful"
    injury_type: str = ""
    injury_side: str = ""
    return_date: str = ""
    confirmed_dnp: bool = False   # True only for "Out" / IR

    @property
    def display_reason(self) -> str:
        parts = []
        if self.injury_side:
            parts.append(self.injury_side)
        if self.injury_type:
            parts.append(self.injury_type)
        body = " ".join(parts) if parts else "Injury"
        return f"{self.status} — {body}"


# ── In-memory cache ───────────────────────────────────────────────────────────
@dataclass
class _Cache:
    injuries:   dict[str, InjuryStatus] = field(default_factory=dict)  # player_id → status
    starters:   dict[str, bool]         = field(default_factory=dict)  # player_id → is_starter
    fetched_at: float = 0.0
    game_id:    str   = ""

_CACHE_TTL = 20 * 60   # 20 minutes
_game_cache: dict[str, _Cache] = {}   # game_id → cache


# ── Player name → player_id lookup ───────────────────────────────────────────

def _name_to_id_map(team_abbrs: list[str]) -> dict[str, str]:
    """Query DB for player_name → player_id for the two teams in this game."""
    if not _DB_PATH.exists():
        return {}
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        placeholders = ",".join("?" * len(team_abbrs))
        rows = conn.execute(
            f"""
            SELECT player_id, player_name
            FROM player_game_logs
            WHERE team_abbreviation IN ({placeholders})
            GROUP BY player_id
            """,
            team_abbrs,
        ).fetchall()
        conn.close()
        # Normalise names: lowercase, strip accents approximation
        result = {}
        for pid, name in rows:
            result[name.lower().strip()] = pid
        return result
    except Exception:
        return {}


def _match_name(espn_name: str, name_map: dict[str, str]) -> str | None:
    """Fuzzy-ish match: exact → first+last → last name only."""
    key = espn_name.lower().strip()
    if key in name_map:
        return name_map[key]
    # Try last name only as fallback
    last = key.split()[-1] if key else ""
    for db_name, pid in name_map.items():
        if db_name.endswith(last) and len(last) > 3:
            return pid
    return None


# ── ESPN fetch helpers ────────────────────────────────────────────────────────

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BallPredict/1.0)"}
_TIMEOUT  = 8


def _fetch_game_injuries(espn_game_id: str) -> list[dict]:
    """
    Pull injury list from ESPN game summary.
    Returns list of raw injury dicts: {team_abbr, player_name, status, details}.
    """
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
        f"/summary?event={espn_game_id}"
    )
    try:
        data = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT).json()
    except Exception as e:
        logger.warning("ESPN game summary fetch failed: %s", e)
        return []

    result = []
    for team_section in data.get("injuries", []):
        espn_abbr = team_section.get("team", {}).get("abbreviation", "")
        for inj in team_section.get("injuries", []):
            athlete = inj.get("athlete", {})
            details = inj.get("details", {})
            result.append({
                "team_abbr":    espn_abbr,
                "player_name":  athlete.get("displayName", ""),
                "status":       inj.get("status", ""),
                "injury_type":  details.get("type", ""),
                "injury_side":  details.get("side", ""),
                "return_date":  details.get("returnDate", ""),
            })
    return result


def _fetch_team_roster_injuries(espn_abbr: str) -> list[dict]:
    """
    Pull injury list from ESPN team roster endpoint.
    Catches players on IR / long-term injured that may not appear in game summary.
    """
    team_id = _ESPN_TEAM_IDS.get(espn_abbr)
    if not team_id:
        return []
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
        f"/teams/{team_id}/roster"
    )
    try:
        data = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT).json()
    except Exception as e:
        logger.warning("ESPN roster fetch failed for %s: %s", espn_abbr, e)
        return []

    result = []
    for athlete in data.get("athletes", []):
        for inj in athlete.get("injuries", []):
            result.append({
                "team_abbr":   espn_abbr,
                "player_name": athlete.get("fullName", ""),
                "status":      inj.get("status", "Out"),
                "injury_type": "",
                "injury_side": "",
                "return_date": inj.get("date", ""),
            })
    return result


def _fetch_confirmed_starters(espn_game_id: str, name_map: dict[str, str]) -> dict[str, bool]:
    """
    ESPN boxscore shows starter=True for each player once the lineup is posted
    (~60-90 min before tip-off). Returns {} if lineups aren't up yet.
    """
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
        f"/summary?event={espn_game_id}"
    )
    try:
        data = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT).json()
    except Exception:
        return {}

    starters: dict[str, bool] = {}
    boxscore = data.get("boxscore", {})
    for team_section in boxscore.get("players", []):
        for stat_group in team_section.get("statistics", []):
            for entry in stat_group.get("athletes", []):
                name = entry.get("athlete", {}).get("displayName", "")
                is_starter = bool(entry.get("starter", False))
                pid = _match_name(name, name_map)
                if pid:
                    starters[pid] = is_starter
    return starters


# ── Public API ────────────────────────────────────────────────────────────────

def _espn_game_id_from_nba_id(_nba_game_id: str, home_abbr: str, away_abbr: str) -> str | None:
    """
    Look up the ESPN game id for today's game between these two teams.
    Falls back to None if not found.
    """
    try:
        data = requests.get(
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
            headers=_HEADERS, timeout=_TIMEOUT,
        ).json()
        for event in data.get("events", []):
            competitors = event.get("competitions", [{}])[0].get("competitors", [])
            abbrs = {_ESPN_TO_DB.get(c.get("team", {}).get("abbreviation", ""), "") for c in competitors}
            if home_abbr in abbrs and away_abbr in abbrs:
                return event["id"]
    except Exception as e:
        logger.warning("ESPN scoreboard lookup failed: %s", e)
    return None


def get_injury_statuses(
    game_id:    str,
    home_abbr:  str,
    away_abbr:  str,
) -> dict[str, InjuryStatus]:
    """
    Return a dict of player_id → InjuryStatus for both teams in this game.
    Cached for 20 minutes per game_id.
    """
    cache = _game_cache.get(game_id)
    if cache and (time.time() - cache.fetched_at) < _CACHE_TTL:
        return cache.injuries

    # Build player name → id map for both teams
    name_map = _name_to_id_map([home_abbr, away_abbr])

    # ESPN abbreviations for both teams
    home_espn = _DB_TO_ESPN.get(home_abbr, home_abbr)
    away_espn = _DB_TO_ESPN.get(away_abbr, away_abbr)

    # Find ESPN game id
    espn_game_id = _espn_game_id_from_nba_id(game_id, home_abbr, away_abbr)

    raw: list[dict] = []
    if espn_game_id:
        raw += _fetch_game_injuries(espn_game_id)
    # Always supplement with team roster injuries (catches IR players)
    raw += _fetch_team_roster_injuries(home_espn)
    raw += _fetch_team_roster_injuries(away_espn)

    injuries: dict[str, InjuryStatus] = {}
    for entry in raw:
        pid = _match_name(entry["player_name"], name_map)
        if not pid:
            continue
        status = entry["status"]
        injuries[pid] = InjuryStatus(
            player_id    = pid,
            player_name  = entry["player_name"],
            status       = status,
            injury_type  = entry.get("injury_type", ""),
            injury_side  = entry.get("injury_side", ""),
            return_date  = entry.get("return_date", ""),
            confirmed_dnp= status in _OUT_STATUSES,
        )

    # Fetch confirmed starters if available
    starters: dict[str, bool] = {}
    if espn_game_id:
        starters = _fetch_confirmed_starters(espn_game_id, name_map)

    cache_obj = _Cache(
        injuries   = injuries,
        starters   = starters,
        fetched_at = time.time(),
        game_id    = game_id,
    )
    _game_cache[game_id] = cache_obj

    confirmed_out  = [n for n, s in injuries.items() if s.confirmed_dnp]
    risky          = [n for n, s in injuries.items() if s.status in _RISKY_STATUSES]
    logger.info(
        "Injury report [%s vs %s]: %d out, %d questionable/dtd, %d starters confirmed",
        home_abbr, away_abbr, len(confirmed_out), len(risky), len(starters),
    )
    return injuries


def get_confirmed_starters(game_id: str) -> dict[str, bool]:
    """Return confirmed starters for a game (empty dict if lineups not posted yet)."""
    cache = _game_cache.get(game_id)
    if cache:
        return cache.starters
    return {}


def is_confirmed_out(
    player_id: str,
    game_id:   str,
    home_abbr: str,
    away_abbr: str,
) -> tuple[bool, Optional[str]]:
    """
    Quick check: is this player confirmed out for this game?
    Returns (True, reason_string) or (False, None).
    Used as the primary DNP signal — runs before the DB absence check.
    """
    injuries = get_injury_statuses(game_id, home_abbr, away_abbr)
    status   = injuries.get(player_id)
    if status is None:
        return False, None
    if status.confirmed_dnp:
        return True, status.display_reason
    if status.status in _RISKY_STATUSES:
        # Not confirmed out but flag the risk — caller can show a warning
        return False, f"⚠ {status.display_reason}"
    return False, None
