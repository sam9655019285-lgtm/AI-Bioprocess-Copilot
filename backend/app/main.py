import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from .ai_api import router as ai_router
from .db import init_db
from .experiments import router as experiments_router
from .forecasting_api import router as forecasting_router
from .report_api import router as report_router
from .scaleup_api import router as scaleup_router
from .simulator_api import router as simulator_router
from .storage_api import router as storage_router

APP_VERSION = "0.1.0"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()  # creates backend/data/bioprocess.db and tables if missing
    yield


app = FastAPI(title="AI Bioprocess Copilot API", version=APP_VERSION, lifespan=lifespan)
# experiments_router first: its fixed paths (/schema, /upload, /observations) must win over /{experiment_id}.
app.include_router(experiments_router)
app.include_router(storage_router)
app.include_router(simulator_router)
app.include_router(scaleup_router)
app.include_router(ai_router)
app.include_router(report_router)
app.include_router(forecasting_router)


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(_request: Request, exc: SQLAlchemyError):
    logger.exception("Database error", exc_info=exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Database error: the operation could not be completed. Please try again."},
    )


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "ai-bioprocess-copilot-backend",
        "version": APP_VERSION,
        # No physical bioreactor is connected; data sources are added in later phases.
        "data_source": "none",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
