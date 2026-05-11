from dataclasses import dataclass, field


@dataclass(slots=True)
class PlayerGameState:
    player_id: str
    player_name: str
    team_id: str
    usage_rate: float
    points: float = 0
    assists: float = 0
    rebounds: float = 0
    steals: float = 0
    blocks: float = 0
    turnovers: float = 0
    threes_made: float = 0
    field_goal_pct: float = 0.48
    three_point_pct: float = 0.37
    minutes_played: float = 0
    fatigue_index: float = 0.15
    foul_count: int = 0
    matchup_difficulty: float = 0.5
    momentum_score: float = 0.5
    touch_time: float = 6.2
    drive_frequency: float = 0.18
    paint_touches: float = 4


@dataclass(slots=True)
class TeamGameState:
    team_id: str
    team_name: str
    coach_name: str
    score: int
    pace: float
    offensive_rating: float
    defensive_rating: float
    defensive_rebound_pct: float
    turnover_rate: float
    three_point_rate: float
    free_throw_rate: float
    foul_pressure: float
    bench_depth: float
    adjustment_discipline: float
    players: list[PlayerGameState] = field(default_factory=list)


@dataclass(slots=True)
class GameContext:
    game_id: str
    quarter: int
    clock: str
    home_team: TeamGameState
    away_team: TeamGameState
    score_margin: int
    home_advantage: float
    overtime_probability: float
    momentum: float
    fatigue_pressure: float
    whistle_tightness: float
    playoff_intensity: float
    live_pace_multiplier: float
    injury_risk_flags: list[str] = field(default_factory=list)
    back_to_back: bool = False

