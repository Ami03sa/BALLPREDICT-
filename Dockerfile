FROM python:3.11-slim

WORKDIR /app/backend

COPY backend /app/backend
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -e .

EXPOSE 8080

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
