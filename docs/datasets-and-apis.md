# Datasets and APIs

## Live and near-live sources

- NBA live data feeds
  Good for scoreboard, play-by-play, and active game metadata.
- NBA Stats API
  Useful for box score, tracking aggregates, play types, shot locations, and lineup data.
- pbpstats
  Strong supplemental source for possessions, lineup stints, and event-level parsing.
- Basketball Reference
  Good historical context and sanity checks, though not ideal as the primary machine-ingestion source.

## Historical datasets to prioritize

- player game logs by season
- team game logs by season
- play-by-play possession data
- lineup on/off and 5-man unit stats
- shot location data
- hustle and tracking aggregates
- matchup data
- injury reports and availability history

## Features that materially improve accuracy

- primary defender quality by matchup segment
- time of possession and touch concentration
- transition versus half-court frequency
- late-clock creation burden
- short-rest and travel fatigue
- early foul pickup patterns
- coaching timeout timing and post-timeout efficiency
- offensive rebound follow-up frequency
- corner-three concession rate
- weak-side helper distance from nail and low man

## Practical ingestion plan

1. Start with NBA live scoreboard and box score endpoints.
2. Add historical player/team game logs for offline training.
3. Layer in lineup and tracking features once the base projection loop is stable.
4. Add possession classification and tactical tagging for richer coaching simulation.

## Notes

- Some NBA endpoints are sensitive to headers and rate-limiting behavior.
- For production, add request retry, caching, and backoff logic.
- Preserve raw payloads in object storage for replayable debugging.

