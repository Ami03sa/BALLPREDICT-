# BallPredict

BallPredict is a full-stack NBA predictive analytics platform built to behave more like a basketball intelligence engine than a static box-score predictor. It combines live game ingestion, quarter-by-quarter stat forecasting, coaching-adjustment simulation, Monte Carlo outcome modeling, and natural-language basketball insights.

## What is included

- A FastAPI backend with REST and WebSocket interfaces
- A basketball simulation engine that reacts to game state, momentum, fatigue, and coaching tendencies
- A React + TypeScript + Tailwind + Recharts + Framer Motion dashboard
- PostgreSQL/Redis-oriented persistence and caching design
- ML/training pipeline starter code using XGBoost, LightGBM, Bayesian updating, and rolling feature engineering
- Product docs covering architecture, schema, APIs, deployment, data sources, and roadmap

## Monorepo layout

```text
BALLPREDICT-/
├── backend/
│   ├── app/
│   └── tests/
├── frontend/
├── docs/
└── infra/
```

## Quick start

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Local infrastructure

```bash
cd infra
docker compose up --build
```

## Product direction

BallPredict focuses on dynamic in-game adjustment logic such as:

- top-locking elite shooters off movement actions
- pre-rotations and nail help against downhill creators
- switching coverages between drop, hedge, blitz, ICE, and scram-switch counters
- changing pace and substitution patterns based on score state, fatigue, and foul trouble
- redistributing teammate usage when defenses send extra help

This repo contains realistic starter code and architecture for an MVP that can grow into a production system.

See the docs in [`docs/architecture.md`](/Users/amisathish/Desktop/ballpredict%20/BALLPREDICT-/docs/architecture.md), [`docs/database-schema.md`](/Users/amisathish/Desktop/ballpredict%20/BALLPREDICT-/docs/database-schema.md), [`docs/ml-pipeline.md`](/Users/amisathish/Desktop/ballpredict%20/BALLPREDICT-/docs/ml-pipeline.md), and [`docs/roadmap.md`](/Users/amisathish/Desktop/ballpredict%20/BALLPREDICT-/docs/roadmap.md).

