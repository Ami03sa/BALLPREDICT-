from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    abbreviation: Mapped[str] = mapped_column(String(8), index=True)
    conference: Mapped[str] = mapped_column(String(16))
    coach_name: Mapped[str] = mapped_column(String(120))
    defensive_scheme_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    pace_profile: Mapped[dict] = mapped_column(JSON, default=dict)


class Player(Base):
    __tablename__ = "players"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    full_name: Mapped[str] = mapped_column(String(120), index=True)
    position: Mapped[str] = mapped_column(String(8))
    archetype: Mapped[str] = mapped_column(String(64))
    usage_baseline: Mapped[float] = mapped_column(Float)
    fatigue_curve: Mapped[dict] = mapped_column(JSON, default=dict)
    tracking_profile: Mapped[dict] = mapped_column(JSON, default=dict)

    team: Mapped["Team"] = relationship()


class Game(Base):
    __tablename__ = "games"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    status: Mapped[str] = mapped_column(String(24), index=True)
    season: Mapped[str] = mapped_column(String(16), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    home_team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    venue: Mapped[str] = mapped_column(String(120))
    metadata_blob: Mapped[dict] = mapped_column(JSON, default=dict)

    home_team: Mapped["Team"] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped["Team"] = relationship(foreign_keys=[away_team_id])


class PossessionEvent(Base):
    __tablename__ = "possession_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), index=True)
    quarter: Mapped[int] = mapped_column(Integer, index=True)
    clock: Mapped[str] = mapped_column(String(8))
    offense_team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    defense_team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    event_type: Mapped[str] = mapped_column(String(64))
    points_scored: Mapped[int] = mapped_column(Integer, default=0)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ProjectionSnapshot(Base):
    __tablename__ = "projection_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), index=True)
    subject_type: Mapped[str] = mapped_column(String(16))
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    phase: Mapped[str] = mapped_column(String(24), index=True)
    mean_projection: Mapped[dict] = mapped_column(JSON)
    low_projection: Mapped[dict] = mapped_column(JSON)
    high_projection: Mapped[dict] = mapped_column(JSON)
    model_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class CoachingAdjustmentLog(Base):
    __tablename__ = "coaching_adjustment_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), index=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    quarter: Mapped[int] = mapped_column(Integer)
    trigger_type: Mapped[str] = mapped_column(String(64), index=True)
    adjustment_family: Mapped[str] = mapped_column(String(64))
    explanation: Mapped[str] = mapped_column(Text)
    impact_vector: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

