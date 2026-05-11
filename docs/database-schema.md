# Database Schema

## Core tables

### `teams`

- `id` PK
- `name`
- `abbreviation`
- `conference`
- `coach_name`
- `defensive_scheme_profile` JSONB
- `pace_profile` JSONB

### `players`

- `id` PK
- `team_id` FK -> `teams.id`
- `full_name`
- `position`
- `archetype`
- `usage_baseline`
- `fatigue_curve` JSONB
- `tracking_profile` JSONB

### `games`

- `id` PK
- `status`
- `season`
- `scheduled_at`
- `home_team_id` FK -> `teams.id`
- `away_team_id` FK -> `teams.id`
- `venue`
- `metadata_blob` JSONB

### `possession_events`

- `id` PK
- `game_id` FK -> `games.id`
- `quarter`
- `clock`
- `offense_team_id`
- `defense_team_id`
- `event_type`
- `points_scored`
- `tags` JSONB
- `payload` JSONB
- `created_at`

### `projection_snapshots`

- `id` PK
- `game_id` FK -> `games.id`
- `subject_type` (`player`, `team`, `game`)
- `subject_id`
- `phase` (`quarter`, `halftime`, `final`)
- `mean_projection` JSONB
- `low_projection` JSONB
- `high_projection` JSONB
- `model_version`
- `created_at`

### `coaching_adjustment_logs`

- `id` PK
- `game_id` FK -> `games.id`
- `team_id` FK -> `teams.id`
- `quarter`
- `trigger_type`
- `adjustment_family`
- `explanation`
- `impact_vector` JSONB
- `created_at`

## Recommended supporting tables for production

- `lineup_stints`
  Stores five-man units, minutes, offensive/defensive results, and synergy values.
- `injury_reports`
  Tracks availability, minute caps, and game-time decisions.
- `player_tracking_frames`
  Optional high-volume table for optical/player tracking aggregates.
- `model_registry`
  Stores artifact URI, version, training window, and calibration metrics.
- `feature_store_snapshots`
  Reproducible point-in-time feature values for offline training and debugging.

## Indexing strategy

- Composite index on `projection_snapshots (game_id, subject_type, phase, created_at desc)`
- Composite index on `possession_events (game_id, quarter, created_at desc)`
- Index on `coaching_adjustment_logs (game_id, team_id, quarter)`
- Index on `players (team_id, full_name)`

