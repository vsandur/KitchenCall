# Build from repository root (for Render when Root Directory is left blank).
# apps/api/Dockerfile is the same layout but for context=apps/api (e.g. docker compose).
FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg espeak-ng \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt apps/api/requirements-telephony.txt .
RUN pip install --no-cache-dir -r requirements-telephony.txt

COPY apps/api/app ./app
COPY apps/api/data ./data

ENV KITCHENCALL_MENU_PATH=/app/data/menu.json
ENV KITCHENCALL_DATABASE_PATH=/app/data/kitchencall.db
# Phone ordering: cloud STT (deepgram/openai) + ffmpeg/espeak TTS
# Set KITCHENCALL_STT_API_KEY in Render env vars
ENV KITCHENCALL_TWILIO_STREAM_STT_BACKEND=deepgram

EXPOSE 8000
CMD ["/bin/sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
