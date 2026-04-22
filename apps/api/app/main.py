from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.api.routes_livekit import router as livekit_router
from app.api.routes_sessions import router as sessions_router
from app.api.routes_telephony import router as telephony_router
from app.config import settings
from app.db.database import init_db


def _configure_app_logging() -> None:
    """Ensure `app.*` INFO logs appear (root is often WARNING and would drop them)."""
    log = logging.getLogger("app")
    if getattr(log, "_kc_logging_configured", False):
        return
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    setattr(log, "_kc_logging_configured", True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _configure_app_logging()
    init_db()
    yield


app = FastAPI(title="KitchenCall API", lifespan=lifespan)

# CORS: enable for dashboard during development
_origins = [o.strip() for o in (settings.cors_origins or "").split(",") if o.strip()]
if not _origins:
    # Default to localhost for dev
    _origins = ["http://localhost:5173", "http://127.0.0.1:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(sessions_router)
app.include_router(livekit_router)
app.include_router(telephony_router)
