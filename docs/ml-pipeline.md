# ML Pipeline

## Prediction targets

BallPredict should train separate targets for:

- player points
- assists
- rebounds
- steals
- blocks
- turnovers
- threes made
- usage rate
- shooting efficiency
- team offensive rating by quarter
- team score by quarter
- win probability

## Recommended feature groups

### Player form

- rolling 3/5/10 game averages
- exponential weighted recent performance
- on/off splits
- touch time and time of possession
- drive frequency and paint touches
- catch-and-shoot versus pull-up mix
- foul drawing rate
- transition frequency

### Opponent context

- opponent defensive rating
- opponent pace
- rim deterrence
- pick-and-roll coverage tendencies
- help frequency
- opponent foul rate
- defender matchup archetype

### Team and lineup context

- projected starting lineup
- live five-man unit synergy
- spacing quality score
- screen-navigation quality
- offensive rebounding pressure
- bench scoring reliability

### Game-state context

- quarter and score differential
- home/away
- back-to-back or 3-in-4 nights
- altitude/travel if relevant
- foul trouble
- hot hand state
- clutch time flag
- playoff intensity

## Modeling stack

### Offline models

- XGBoost regressors for core box-score outcomes
- LightGBM regressors for fast retraining and broader feature sweeps
- classification model for double-team probability, foul-out risk, and overtime probability

### Online updating

- Bayesian updating on player usage, efficiency, and assist opportunity rates
- rolling state-space updates for pace and possession quality
- Monte Carlo possession simulation for uncertainty intervals

## Training workflow

1. Ingest historical game logs, lineups, and tracking aggregates.
2. Build point-in-time features for each player-game and quarter-game sample.
3. Split data by date to prevent leakage.
4. Train per-target models and calibrate intervals.
5. Store artifacts in a registry with feature schema hash.
6. Re-run calibration weekly and after large roster changes.

## Evaluation metrics

- MAE and RMSE for continuous stats
- pinball loss for quantiles
- Brier score for win probability and overtime probability
- calibration curves for projected intervals
- drift alerts for outlier teams or lineup compositions

