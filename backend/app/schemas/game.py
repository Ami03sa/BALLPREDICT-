from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class StatLine(BaseModel):
    points: float = 0
    assists: float = 0
    rebounds: float = 0
    steals: float = 0
    blocks: float = 0
    turnovers: float = 0
    threes_made: float = Field(0, alias="3pm")
    usage_rate: float = 0
    field_goal_pct: float = 0
    three_point_pct: float = 0

    model_config = {"populate_by_name": True}


class ConfidenceBand(BaseModel):
    low: StatLine
    mean: StatLine
    high: StatLine


class CoachingAdjustment(BaseModel):
    title: str
    side: Literal["offense", "defense", "rotation", "pace"]
    trigger: str
    explanation: str
    counters: list[str]
    impact: dict[str, float]


class PlayerProjection(BaseModel):
    player_id: str
    player_name: str
    team_id: str
    quarter: int
    rotation_role: str = "rotation"
    availability_status: str = "available"
    dnp_reason: str | None = None
    live_stats: StatLine
    projected_stats: ConfidenceBand
    momentum_score: float
    fatigue_index: float
    defensive_pressure: float
    hot_factor: float = 1.0
    adjustments: list[CoachingAdjustment]


class TeamProjection(BaseModel):
    team_id: str
    team_name: str
    quarter: int
    score: int = 0
    projected_score: tuple[int, int, int, int]
    final_score_mean: int
    final_score_ci: tuple[int, int]
    pace: float
    offensive_rating: float
    defensive_rating: float
    win_probability: float


class PossessionFeedItem(BaseModel):
    quarter: int
    clock: str
    summary: str
    leverage: Literal["low", "medium", "high"]


class InsightCard(BaseModel):
    title: str
    body: str
    severity: Literal["info", "warning", "advantage"]


class GameSnapshot(BaseModel):
    game_id: str
    status: str
    updated_at: datetime
    quarter: int
    clock: str
    home_team: TeamProjection
    away_team: TeamProjection
    player_projections: list[PlayerProjection]
    possession_feed: list[PossessionFeedItem]
    insights: list[InsightCard]
    win_probability_series: list[dict[str, float]]


class SimulationRequest(BaseModel):
    game_id: str | None = None
    home_team: str
    away_team: str
    pace_delta: float = 0
    strategy_tags: list[str] = Field(default_factory=list)
    simulation_runs: int = 2500


class SeriesSimulationRequest(BaseModel):
    home_team: str
    away_team: str
    games: int = 7
    home_court_edge: float = 2.7
    adjustment_tags: list[str] = Field(default_factory=list)


class SimulationResponse(BaseModel):
    summary: str
    home_win_probability: float
    away_win_probability: float
    projected_score: dict[str, int]
    key_adjustments: list[CoachingAdjustment]
    player_edges: list[InsightCard]


class PlayerQuarterProjection(BaseModel):
    quarter: str
    points: float
    assists: float
    rebounds: float
    threes_made: float


class PlayerDetailResponse(BaseModel):
    game_id: str
    player_id: str
    player_name: str
    team_id: str
    team_name: str
    opponent_team_name: str
    coach_counter_summary: str
    projection: PlayerProjection
    quarter_breakdown: list[PlayerQuarterProjection]
    stat_profile: list[dict[str, float | str]]
    matchup_factors: list[str]
    confidence: dict[str, float]
    player_insights: list[InsightCard]
