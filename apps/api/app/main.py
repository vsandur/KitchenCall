from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as core_router
from app.api.routes_livekit import router as livekit_router
from app.api.routes_sessions import orders_router, router as sessions_router
from app.api.routes_telephony import router as telephony_router
from app.config import settings
from app.db.database import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="KitchenCall API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(core_router)
app.include_router(sessions_router)
app.include_router(orders_router)
app.include_router(livekit_router)
app.include_router(telephony_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "kitchencall-api", "docs": "/docs"}
