import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import analytics, chat, config, leads, widget
from core.config import settings
from core.database import check_connection

logger = structlog.get_logger()
START_TIME = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_ok = await check_connection()
    logger.info("startup", service="ai-chatbot", db_connected=db_ok)
    yield
    logger.info("shutdown", service="ai-chatbot")


app = FastAPI(
    title="ai-chatbot",
    version="0.1.0",
    description="MEDPLATFORM AI chatbot engine",
    lifespan=lifespan,
)

# CORS — wide open for widget (runs on any clinic website)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve widget files statically
app.mount("/static", StaticFiles(directory="widget"), name="static")

app.include_router(config.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(leads.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(widget.router, prefix="/api")


@app.get("/")
async def health():
    return {
        "status": "ok",
        "service": "ai-chatbot",
        "version": "0.1.0",
        "uptime_seconds": round(time.time() - START_TIME, 1),
    }


@app.get("/health")
async def health_detail():
    db_ok = await check_connection()
    return {
        "status": "ok" if db_ok else "degraded",
        "checks": {
            "database": {"status": "ok" if db_ok else "error"},
            "gemini": {
                "status": "configured" if settings.gemini_api_key else "not_configured"
            },
            "email_marketing": {"status": "reachable"},
        },
    }
