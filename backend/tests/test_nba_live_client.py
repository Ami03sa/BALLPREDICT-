"""Tests for NbaLiveClient — pure/deterministic methods only (no real HTTP)."""
import pytest
from datetime import date
from unittest.mock import AsyncMock, patch
from app.services.providers.nba_live_client import NbaLiveClient, _normalize_name


client = NbaLiveClient()


class TestNormalizeName:
    def test_lowercase(self):
        assert _normalize_name("Stephen Curry") == "stephen curry"

    def test_strips_punctuation(self):
        assert _normalize_name("Luka Dončić") == "luka doni"

    def test_strips_apostrophe(self):
        assert _normalize_name("De'Aaron Fox") == "deaaron fox"

    def test_trailing_whitespace(self):
        assert _normalize_name("  Curry  ") == "curry"


class TestCurrentSeason:
    def test_returns_season_string(self):
        season = client._current_season()
        assert "-" in season
        parts = season.split("-")
        assert len(parts) == 2
        assert len(parts[1]) == 2  # short year format like "25"

    def test_format_matches_yyyy_yy(self):
        season = client._current_season()
        year_part = int(season.split("-")[0])
        today = date.today()
        if today.month >= 10:
            assert year_part == today.year
        else:
            assert year_part == today.year - 1


class TestFetchVegasTotalsNoKey:
    async def test_empty_api_key_returns_empty_dicts(self):
        totals, spreads, event_ids = await client.fetch_vegas_totals("")
        assert totals == {}
        assert spreads == {}
        assert event_ids == {}


class TestFetchPlayerPropsBulkNoKey:
    async def test_empty_api_key_returns_empty(self):
        result = await client.fetch_player_props_bulk("", ["abc"])
        assert result == {}

    async def test_empty_event_ids_returns_empty(self):
        result = await client.fetch_player_props_bulk("somekey", [])
        assert result == {}


class TestParseStatsBoxscore:
    def _make_player_row(self, player_id, name, team_abbr, pts=10, start="G"):
        return {
            "PLAYER_ID": player_id,
            "PLAYER_NAME": name,
            "TEAM_ABBREVIATION": team_abbr,
            "TEAM_ID": 12345,
            "START_POSITION": start,
            "MIN": "24:30",
            "PTS": pts,
            "AST": 4,
            "REB": 5,
            "OREB": 1,
            "DREB": 4,
            "STL": 1,
            "BLK": 0,
            "TO": 2,
            "PF": 2,
            "FG3M": 2,
            "FG3A": 5,
            "FG3_PCT": 0.40,
            "FGM": 5,
            "FGA": 12,
            "FG_PCT": 0.417,
            "FTM": 2,
            "FTA": 3,
            "FT_PCT": 0.667,
            "COMMENT": None,
        }

    def _make_team_row(self, abbr, city="Dallas", name="Mavericks", pts=110):
        return {
            "TEAM_ABBREVIATION": abbr,
            "TEAM_CITY": city,
            "TEAM_NAME": name,
            "PTS": pts,
            "AST": 25,
            "REB": 42,
            "OREB": 8,
            "DREB": 34,
            "STL": 7,
            "BLK": 4,
            "TO": 14,
            "PF": 20,
            "FG3A": 34,
            "FG3M": 13,
            "FGA": 88,
            "FTA": 22,
        }

    def _make_line_score(self, away_abbr, home_abbr, away_pts, home_pts):
        return [
            {"TEAM_ABBREVIATION": away_abbr, "PTS": away_pts},
            {"TEAM_ABBREVIATION": home_abbr, "PTS": home_pts},
        ]

    def _make_result_sets(self, player_rows, team_rows, line_score_rows):
        def to_rs(name, rows):
            if not rows:
                return {"name": name, "headers": [], "rowSet": []}
            headers = list(rows[0].keys())
            return {
                "name": name,
                "headers": headers,
                "rowSet": [[r[h] for h in headers] for r in rows],
            }

        return {
            "resultSets": [
                to_rs("PlayerStats", player_rows),
                to_rs("TeamStats", team_rows),
                to_rs("LineScore", line_score_rows),
            ]
        }

    def test_parses_two_team_boxscore(self):
        player_rows = [
            self._make_player_row(1, "Luka Doncic", "DAL", pts=30, start="F"),
            self._make_player_row(2, "Kyrie Irving", "DAL", pts=22, start="G"),
            self._make_player_row(3, "Stephen Curry", "GSW", pts=28, start="G"),
            self._make_player_row(4, "Draymond Green", "GSW", pts=8, start="F"),
        ]
        team_rows = [
            self._make_team_row("DAL", "Dallas", "Mavericks", 112),
            self._make_team_row("GSW", "Golden State", "Warriors", 108),
        ]
        line_score_rows = self._make_line_score("DAL", "GSW", 112, 108)
        data = self._make_result_sets(player_rows, team_rows, line_score_rows)

        result = client._parse_stats_boxscore(data)

        assert "game" in result
        game = result["game"]
        assert "homeTeam" in game
        assert "awayTeam" in game
        assert game["homeTeam"]["teamTricode"] == "GSW"
        assert game["awayTeam"]["teamTricode"] == "DAL"
        assert game["homeTeam"]["score"] == 108
        assert game["awayTeam"]["score"] == 112
        assert len(game["homeTeam"]["players"]) == 2
        assert len(game["awayTeam"]["players"]) == 2

    def test_empty_data_returns_empty_game(self):
        result = client._parse_stats_boxscore({"resultSets": []})
        assert result == {"game": {}}

    def test_dnp_player_marked_not_played(self):
        row = self._make_player_row(99, "Bench Guy", "DAL", pts=0, start="")
        row["MIN"] = "0:00"
        team_rows = [self._make_team_row("DAL")]
        line_score_rows = self._make_line_score("DAL", "GSW", 100, 95)
        data = self._make_result_sets([row], team_rows, line_score_rows)

        result = client._parse_stats_boxscore(data)
        dal_players = result["game"]["awayTeam"]["players"]
        bench_guy = next((p for p in dal_players if p["name"] == "Bench Guy"), None)
        assert bench_guy is not None
        assert bench_guy["played"] is False


class TestAsyncMethodsWithMockedHttp:
    """Patch _cdn_get/_stats_get so no real HTTP is made."""

    async def test_fetch_scoreboard(self):
        fake = {"scoreboard": {"games": []}}
        with patch.object(client, "_cdn_get", new_callable=AsyncMock, return_value=fake):
            result = await client.fetch_scoreboard()
        assert result == fake

    async def test_fetch_boxscore_cdn_success(self):
        fake = {"game": {"homeTeam": {"teamTricode": "GSW"}, "awayTeam": {"teamTricode": "DAL"}}}
        with patch.object(client, "_cdn_get", new_callable=AsyncMock, return_value=fake):
            result = await client.fetch_boxscore("0042400301")
        assert "game" in result

    async def test_fetch_boxscore_cdn_fallback_to_stats(self):
        # CDN returns data without required keys → falls back to stats endpoint
        cdn_empty = {"game": {}}
        player_rows = []
        team_rows = []
        line_score_rows = []

        def make_rs(name, rows):
            if not rows:
                return {"name": name, "headers": [], "rowSet": []}
            headers = list(rows[0].keys())
            return {"name": name, "headers": headers, "rowSet": [[r[h] for h in headers] for r in rows]}

        stats_data = {
            "resultSets": [
                make_rs("PlayerStats", player_rows),
                make_rs("TeamStats", team_rows),
                make_rs("LineScore", line_score_rows),
            ]
        }
        with patch.object(client, "_cdn_get", new_callable=AsyncMock, return_value=cdn_empty):
            with patch.object(client, "_stats_get", new_callable=AsyncMock, return_value=stats_data):
                result = await client.fetch_boxscore("0042400301")
        assert result == {"game": {}}

    async def test_fetch_playbyplay(self):
        fake = {"game": {"actions": []}}
        with patch.object(client, "_cdn_get", new_callable=AsyncMock, return_value=fake):
            result = await client.fetch_playbyplay("0042400301")
        assert result == fake

    async def test_fetch_player_season_stats(self):
        fake_data = {
            "resultSets": [
                {
                    "name": "LeagueDashPlayerStats",
                    "headers": ["PLAYER_ID", "PLAYER_NAME", "GP", "MIN", "PTS"],
                    "rowSet": [
                        [1, "Curry", 18, 32.5, 28.0],
                        [2, "Draymond", 18, 30.0, 9.0],
                        [3, "EndOfBench", 2, 8.0, 3.0],  # GP<3, filtered out
                    ],
                }
            ]
        }
        with patch.object(client, "_stats_get", new_callable=AsyncMock, return_value=fake_data):
            result = await client.fetch_player_season_stats(1610612744)
        assert len(result) == 2  # bench guy filtered

    async def test_fetch_team_ratings_success(self):
        fake_data = {
            "resultSets": [
                {
                    "name": "LeagueDashTeamStats",
                    "headers": ["TEAM_NAME", "OFF_RATING", "DEF_RATING", "PACE"],
                    "rowSet": [["Golden State Warriors", 118.5, 112.0, 101.3]],
                }
            ]
        }
        with patch.object(client, "_stats_get", new_callable=AsyncMock, return_value=fake_data):
            result = await client.fetch_team_ratings()
        assert "GSW" in result
        assert result["GSW"]["off_rating"] == pytest.approx(118.5)

    async def test_fetch_team_ratings_exception_returns_empty(self):
        with patch.object(client, "_stats_get", new_callable=AsyncMock, side_effect=Exception("timeout")):
            result = await client.fetch_team_ratings()
        assert result == {}

    async def test_fetch_injury_report_success(self):
        fake_data = {
            "resultSets": [
                {
                    "name": "LeagueInjuryReport",
                    "headers": ["Player_ID", "Current_Status"],
                    "rowSet": [[1234, "Out"], [5678, "Questionable"]],
                }
            ]
        }
        with patch.object(client, "_stats_get", new_callable=AsyncMock, return_value=fake_data):
            result = await client.fetch_injury_report()
        assert result["1234"] == "Out"
        assert result["5678"] == "Questionable"

    async def test_fetch_injury_report_exception_returns_empty(self):
        with patch.object(client, "_stats_get", new_callable=AsyncMock, side_effect=Exception("err")):
            result = await client.fetch_injury_report()
        assert result == {}

    async def test_fetch_team_ratings_skips_unknown_team(self):
        fake_data = {
            "resultSets": [
                {
                    "name": "LeagueDashTeamStats",
                    "headers": ["TEAM_NAME", "OFF_RATING", "DEF_RATING", "PACE"],
                    "rowSet": [
                        ["Golden State Warriors", 118.5, 112.0, 101.3],
                        ["Unknown Franchise", 110.0, 115.0, 99.0],  # triggers continue
                    ],
                }
            ]
        }
        with patch.object(client, "_stats_get", new_callable=AsyncMock, return_value=fake_data):
            result = await client.fetch_team_ratings()
        assert "GSW" in result
        assert len(result) == 1  # Unknown Franchise excluded

    async def test_fetch_boxscore_cdn_exception_falls_back(self):
        # CDN raises → falls back to stats.nba.com
        stats_data = {"resultSets": []}
        with patch.object(client, "_cdn_get", new_callable=AsyncMock, side_effect=Exception("CDN down")):
            with patch.object(client, "_stats_get", new_callable=AsyncMock, return_value=stats_data):
                result = await client.fetch_boxscore("0042400301")
        assert result == {"game": {}}


class TestCdnAndStatsGetDirect:
    """Tests that call _cdn_get/_stats_get directly to cover their HTTP client code."""

    async def test_cdn_get_success(self):
        from unittest.mock import MagicMock
        import httpx

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"ok": True})

        mock_async_client = MagicMock()
        mock_async_client.get = AsyncMock(return_value=mock_response)
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.providers.nba_live_client.httpx.AsyncClient", return_value=mock_async_client):
            result = await client._cdn_get("test/path")
        assert result == {"ok": True}

    async def test_stats_get_success(self):
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"resultSets": []})

        mock_async_client = MagicMock()
        mock_async_client.get = AsyncMock(return_value=mock_response)
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.providers.nba_live_client.httpx.AsyncClient", return_value=mock_async_client):
            result = await client._stats_get("leaguedashteamstats", {"Season": "2024-25"})
        assert result == {"resultSets": []}


class TestFetchPlayerPropsBulk:
    async def test_with_api_key_and_event_ids(self):
        from unittest.mock import MagicMock

        fake_bookmakers = [
            {
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {"name": "Over", "description": "Stephen Curry", "point": 28.5},
                            {"name": "Under", "description": "Stephen Curry", "point": 28.5},
                        ],
                    }
                ]
            }
        ]
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"bookmakers": fake_bookmakers})

        mock_async_client = MagicMock()
        mock_async_client.get = AsyncMock(return_value=mock_response)
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.providers.nba_live_client.httpx.AsyncClient", return_value=mock_async_client):
            result = await client.fetch_player_props_bulk("test_key", ["event1"])
        assert "stephen curry" in result
        assert result["stephen curry"]["pts"] == 28.5

    async def test_with_api_key_exception_returns_empty_player(self):
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(side_effect=Exception("rate limit"))
        mock_response.json = MagicMock(return_value={})

        mock_async_client = MagicMock()
        mock_async_client.get = AsyncMock(return_value=mock_response)
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.providers.nba_live_client.httpx.AsyncClient", return_value=mock_async_client):
            result = await client.fetch_player_props_bulk("test_key", ["event1"])
        assert result == {}


class TestFetchVegasTotalsWithKey:
    async def test_with_api_key_and_events(self):
        from unittest.mock import MagicMock

        fake_events = [
            {
                "id": "event1",
                "home_team": "Golden State Warriors",
                "away_team": "Dallas Mavericks",
                "bookmakers": [
                    {
                        "markets": [
                            {
                                "key": "totals",
                                "outcomes": [{"name": "Over", "point": 225.5}],
                            },
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": "Golden State Warriors", "point": -6.5},
                                ],
                            },
                        ]
                    }
                ],
            }
        ]
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=fake_events)

        mock_async_client = MagicMock()
        mock_async_client.get = AsyncMock(return_value=mock_response)
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.providers.nba_live_client.httpx.AsyncClient", return_value=mock_async_client):
            totals, spreads, event_ids = await client.fetch_vegas_totals("test_key")
        assert ("GSW", "DAL") in totals
        assert totals[("GSW", "DAL")] == pytest.approx(225.5)

    async def test_with_unknown_team_skipped(self):
        from unittest.mock import MagicMock

        fake_events = [
            {
                "id": "e1",
                "home_team": "Unknown FC",  # not in name_to_tc → continue
                "away_team": "Dallas Mavericks",
                "bookmakers": [],
            },
        ]
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=fake_events)

        mock_async_client = MagicMock()
        mock_async_client.get = AsyncMock(return_value=mock_response)
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.providers.nba_live_client.httpx.AsyncClient", return_value=mock_async_client):
            totals, spreads, _ = await client.fetch_vegas_totals("test_key")
        assert totals == {}

    async def test_exception_returns_empty_tuple(self):
        from unittest.mock import MagicMock

        mock_async_client = MagicMock()
        mock_async_client.get = AsyncMock(side_effect=Exception("connection error"))
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.providers.nba_live_client.httpx.AsyncClient", return_value=mock_async_client):
            totals, spreads, event_ids = await client.fetch_vegas_totals("test_key")
        assert totals == {}
        assert spreads == {}
        assert event_ids == {}


class TestFetchVegasTotalsEspn:
    def _make_espn_event(self, home_abbr="GSW", away_abbr="DAL", total=225.5, spread=-6.5):
        return {
            "competitions": [
                {
                    "competitors": [
                        {"homeAway": "home", "team": {"abbreviation": home_abbr}},
                        {"homeAway": "away", "team": {"abbreviation": away_abbr}},
                    ],
                    "odds": [{"overUnder": total, "spread": spread}],
                }
            ]
        }

    async def test_cdn_returns_espn_data(self):
        espn_data = {"events": [self._make_espn_event()]}
        with patch.object(client, "_cdn_get", new_callable=AsyncMock, return_value=espn_data):
            totals, spreads = await client.fetch_vegas_totals_espn()
        assert ("GSW", "DAL") in totals

    async def test_cdn_fails_httpx_direct_success(self):
        from unittest.mock import MagicMock

        espn_data = {"events": [self._make_espn_event()]}
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=espn_data)
        mock_async_client = MagicMock()
        mock_async_client.get = AsyncMock(return_value=mock_response)
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)

        with patch.object(client, "_cdn_get", new_callable=AsyncMock, side_effect=Exception("cdn fail")):
            with patch("app.services.providers.nba_live_client.httpx.AsyncClient", return_value=mock_async_client):
                totals, spreads = await client.fetch_vegas_totals_espn()
        assert ("GSW", "DAL") in totals

    async def test_both_fail_returns_empty(self):
        from unittest.mock import MagicMock

        mock_async_client = MagicMock()
        mock_async_client.get = AsyncMock(side_effect=Exception("httpx fail"))
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)

        with patch.object(client, "_cdn_get", new_callable=AsyncMock, side_effect=Exception("cdn fail")):
            with patch("app.services.providers.nba_live_client.httpx.AsyncClient", return_value=mock_async_client):
                totals, spreads = await client.fetch_vegas_totals_espn()
        assert totals == {}
        assert spreads == {}

    async def test_event_missing_competitors_skipped(self):
        espn_data = {"events": [{"competitions": [{"competitors": [], "odds": []}]}]}
        with patch.object(client, "_cdn_get", new_callable=AsyncMock, return_value=espn_data):
            totals, _ = await client.fetch_vegas_totals_espn()
        assert totals == {}

    async def test_event_no_odds_skipped(self):
        espn_data = {
            "events": [
                {
                    "competitions": [
                        {
                            "competitors": [
                                {"homeAway": "home", "team": {"abbreviation": "GSW"}},
                                {"homeAway": "away", "team": {"abbreviation": "DAL"}},
                            ],
                            "odds": [],  # empty → skip
                        }
                    ]
                }
            ]
        }
        with patch.object(client, "_cdn_get", new_callable=AsyncMock, return_value=espn_data):
            totals, _ = await client.fetch_vegas_totals_espn()
        assert totals == {}
