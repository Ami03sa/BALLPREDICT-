# Deployment Strategy

## Environments

- `local`
  Docker Compose for backend, frontend, PostgreSQL, and Redis.
- `staging`
  Managed Postgres + Redis, containerized API, and preview frontend deployment.
- `production`
  Autoscaled API service, worker tier, scheduled feature pipelines, and CDN-backed frontend.

## Recommended production topology

### Frontend

- Vercel, Netlify, or CloudFront + S3
- environment-based API/WebSocket URL injection

### Backend API

- Containerized FastAPI deployed to ECS Fargate, Fly.io, Railway, Render, or Kubernetes
- horizontal scaling behind an HTTP load balancer

### Data services

- PostgreSQL for durable snapshots and relational entities
- Redis for hot cache, session-like live state, and pub/sub support
- object storage for model artifacts and large historical exports

### Workers

- background ingestion jobs every 15-60 seconds during live windows
- nightly feature backfills and model retraining
- queue system using Celery, Arq, or Temporal

## WebSocket strategy

- API nodes publish game snapshot deltas to Redis channels
- connected nodes fan out to subscribers by `game_id`
- frontend reconnects with exponential backoff and snapshot refresh fallback

## Observability

- OpenTelemetry traces for ingestion and prediction latency
- Prometheus/Grafana dashboards for queue depth and API p95
- structured logs for model version, feature snapshot id, and tactical trigger path

