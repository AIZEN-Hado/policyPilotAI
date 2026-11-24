"""
FastAPI application entry point for PolicyPilotAI.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import router
from app.config import settings
from app.db import init_db

app = FastAPI(
    title="PolicyPilotAI",
    description=(
        "AI-powered insurance policy decision engine using "
        "LangChain + HuggingFace + FAISS + SQLite"
    ),
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.on_event("startup")
async def on_startup() -> None:
    """Create SQLite tables on first run (idempotent)."""
    await init_db()


@app.get("/", tags=["root"])
async def root() -> dict:
    return {
        "message": "Welcome to PolicyPilotAI 🛡️",
        "docs": "/docs",
        "health": "/api/v1/health",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.DEBUG,
    )
