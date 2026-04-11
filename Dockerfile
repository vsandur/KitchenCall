# Build from repository root (for Render when Root Directory is left blank).
# apps/api/Dockerfile is the same layout but for context=apps/api (e.g. docker compose).
FROM python:3.12-slim
WORKDIR /app

COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/api/app ./app
COPY apps/api/data ./data

ENV KITCHENCALL_MENU_PATH=/app/data/menu.json
ENV KITCHENCALL_DATABASE_PATH=/app/data/kitchencall.db

EXPOSE 8000
CMD ["/bin/sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
