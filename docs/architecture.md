# BallPredict Architecture

## Product goal

BallPredict is designed as an in-game basketball intelligence engine with three major responsibilities:

1. Ingest live and historical NBA context.
2. Forecast player and team outcomes by quarter, half, and final game state.
3. Simulate coaching counters that reshape those forecasts as the game evolves.

## High-level system

```text
NBA Live Data / Historical Data / Tracking Data
                |
                v
        Ingestion + Feature Jobs
                |
                v
     PostgreSQL <-> Redis Feature Cache
                |
                v
      FastAPI Prediction Orchestrator
                |
      -------------------------------
      |             |               |
      v             v               v
 Game State    Coaching Engine    ML Ensemble
 Engine        + Rule Simulator   + Bayesian Updates
      \             |             /
       \            |            /
        -------- Monte Carlo -----
                |
                v
 REST API + WebSocket Streams + Insight Generation
                |
                v
      React Live Analytics Dashboard
```

## Backend modules

- `app/api/routes`
  Exposes live game, simulation, and health endpoints.
- `app/services/live_game_service.py`
  Orchestrates snapshots, ingestion stubs, and simulation entry points.
- `app/services/projection_service.py`
  Converts internal game context into frontend-ready projections.
- `app/simulation/state.py`
  Shared in-memory game model for players, teams, and game context.
- `app/simulation/coaching_engine.py`
  Encodes coverage changes, pace control, rotation shifts, and tactical counters.
- `app/simulation/prediction_engine.py`
  Combines rules, pressure adjustments, and Monte Carlo score generation.
- `app/workers/train_models.py`
  Starter training pipeline for player-stat models.

## Modeling approach

BallPredict should use a layered modeling strategy instead of a single model:

- Pre-game priors
  Rolling form, matchup history, rest, injuries, likely rotations, and travel/fatigue.
- Possession-level live updates
  Score margin, shot quality, foul pressure, lineups, and pace drift.
- Tactical state machine
  Detects hot players, on-ball mismatches, overhelp triggers, bench vulnerability, and late-game variance.
- Bayesian re-centering
  Moves predictions toward current evidence without overreacting to one quarter.
- Monte Carlo simulation
  Samples possession outcomes under current tactical assumptions to generate intervals.

## Coaching simulator logic

The coaching engine should support more than broad labels like "double team." It should encode specific counters including:

- high pick-and-roll blitz
- drop-to-touch switching
- hedge-and-recover
- ICE side pick-and-roll
- top-locking shooters
- lock-and-trail on movement actions
- pre-switching screeners
- scram switching smalls out of the post
- peel switching on drives
- nail help and gap shrink
- low-man tagging the roller
- full-front post denial
- zone shifts after timeouts
- bench staggering
- offense slowing into matchup hunting
- inverted screening actions to punish switches

## Scalability notes

- Use Redis for last-known projections, lineup features, and WebSocket fanout support.
- Push heavy ingestion/training jobs into background workers such as Celery, RQ, Arq, or Temporal.
- Version features and models so projections can be replayed and audited after games.
- Persist snapshots and tactical explanations for user-facing "why did this change?" history.

