"""
Pydantic-Settings configuration for PolicyPilotAI — Ollama Edition.

GPU NOTE — GTX 1650 (4 GB VRAM):
    Models that SAFELY fit in 4 GB at 4-bit quantisation:
      ✅  phi3:mini        (3.8B  — ~2.5 GB VRAM)  ← DEFAULT, best quality
      ✅  llama3.2:3b      (3.2B  — ~2.3 GB VRAM)  ← good alternative
      ✅  tinyllama        (1.1B  — ~0.8 GB VRAM)  ← fastest, lowest quality
      ✅  gemma:2b         (2.0B  — ~1.5 GB VRAM)
      ❌  mistral:7b       (~5-6 GB) — will OOM on 4 GB
      ❌  llama3:8b        (~6 GB)   — will OOM on 4 GB

    Embeddings run on CPU (all-MiniLM-L6-v2) so they don't use VRAM at all.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Ollama LLM ────────────────────────────────────────────────────────────
    # Ollama server URL (default: local)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    # Model to use — must be pulled first: `ollama pull phi3:mini`
    OLLAMA_MODEL: str = "phi3:mini"
    # Generation parameters
    LLM_TEMPERATURE: float = 0.1
    LLM_NUM_CTX: int = 4096        # context window (tokens)
    LLM_NUM_GPU: int = 99          # layers to offload to GPU (99 = all)
    LLM_NUM_THREAD: int = 6        # CPU threads for non-GPU layers

    # ── Embeddings — local SentenceTransformers (CPU only, no VRAM used) ─────
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"

    # ── Vector store ──────────────────────────────────────────────────────────
    FAISS_INDEX_PATH: str = "data/vectors/faiss_index"
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 64
    TOP_K_RESULTS: int = 5

    # ── FastAPI ───────────────────────────────────────────────────────────────
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    DEBUG: bool = True

    # ── File paths ────────────────────────────────────────────────────────────
    POLICY_PDF_DIR: str = "data/policies"
    OUTPUT_DIR: str = "data/outputs"

    # ── Database — SQLite (created automatically on first run) ────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///data/policypilot.db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
