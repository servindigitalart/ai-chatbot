import sys
import traceback
import time

print(f"Starting api.main, Python {sys.version}", flush=True)

try:
    from contextlib import asynccontextmanager

    import structlog
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles

    from core.config import settings
    from core.database import check_connection
    from api.routes import analytics, chat, config, leads, widget

    logger = structlog.get_logger()
    START_TIME = time.time()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            db_ok = await check_connection()
        except Exception as e:
            db_ok = False
            print(f"WARNING: DB check failed at startup: {e}", flush=True)
        logger.info("startup", service="ai-chatbot", db_connected=db_ok)
        yield
        logger.info("shutdown", service="ai-chatbot")

    app = FastAPI(
        title="ai-chatbot",
        version="0.1.0",
        description="MEDPLATFORM AI chatbot engine",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    try:
        app.mount("/static", StaticFiles(directory="widget"), name="static")
    except Exception as e:
        print(f"WARNING: Could not mount static files: {e}", flush=True)

    app.include_router(config.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(leads.router, prefix="/api")
    app.include_router(analytics.router, prefix="/api")
    app.include_router(widget.router, prefix="/api")

    @app.get("/")
    async def root():
        return {
            "status": "ok",
            "service": "ai-chatbot",
            "version": "0.1.0",
            "uptime_seconds": round(time.time() - START_TIME, 1),
        }

except Exception as e:
    print(f"FATAL: Failed to initialize api.main: {e}", flush=True)
    traceback.print_exc()
    from fastapi import FastAPI
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok", "degraded": True}
