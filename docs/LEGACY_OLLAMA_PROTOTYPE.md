# 🛡️ PolicyPilotAI — Ollama Edition

AI-powered insurance policy decision engine — **100% local, 100% private**.
No API keys. No cloud. Runs entirely on your machine using Ollama.

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Ollama (local GPU inference — GTX 1650 4 GB) |
| RAG Framework | LangChain (`langchain`, `langchain-community`, `langchain-ollama`) |
| Embeddings | HuggingFace SentenceTransformers — `all-MiniLM-L6-v2` (**CPU only**) |
| Vector Store | FAISS (CPU) via LangChain |
| PDF Extraction | pdfplumber + pypdf |
| API | FastAPI + Uvicorn |
| Database | SQLite — SQLAlchemy async + aiosqlite |
| UI | Streamlit |

---

## GTX 1650 (4 GB VRAM) — Model Guide

> Your GPU has 4 GB VRAM. Only use **small quantised models**.

| Model | VRAM | Notes |
|---|---|---|
| `phi3:mini` | ~2.5 GB | ✅ **Default** — best quality for the size |
| `llama3.2:3b` | ~2.3 GB | ✅ Great alternative |
| `gemma:2b` | ~1.5 GB | ✅ Solid choice |
| `tinyllama` | ~0.8 GB | ✅ Fastest — use if phi3 feels slow |
| `mistral:7b` | ~5-6 GB | ❌ **Will OOM** — do not use |
| `llama3:8b` | ~6 GB | ❌ **Will OOM** — do not use |

Embeddings (`all-MiniLM-L6-v2`) run on **CPU** — they use zero VRAM, leaving all 4 GB free for the LLM.

---

## Setup & Quickstart

### Step 1 — Install Ollama

```bash
# Windows: download from https://ollama.com/download
# Linux:
curl -fsSL https://ollama.com/install.sh | sh
```

### Step 2 — Pull a model (phi3:mini recommended for GTX 1650)

```bash
ollama pull phi3:mini
```

### Step 3 — Start Ollama

```bash
ollama serve
# Confirm it's running: http://localhost:11434
```

### Step 4 — Install Python dependencies

```bash
pip install -r requirements.txt
```

### Step 5 — Configure environment

```bash
cp .env.example .env
# .env is already pre-configured for phi3:mini — no changes needed
# unless you want to switch models
```

### Step 6 — Place policy PDFs

```
data/policies/your_policy.pdf
```

### Step 7 — Start the FastAPI backend

```bash
uvicorn app.main:app --reload
# SQLite database created automatically at data/policypilot.db
```

### Step 8 — Ingest PDFs (one-time)

```bash
curl -X POST http://localhost:8000/api/v1/ingest
```

Or use the **⚡ Ingest PDFs** button in the sidebar.

### Step 9 — Launch the UI

```bash
streamlit run ui/streamlit_app.py
# Opens at http://localhost:8501
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/health` | Liveness probe |
| GET | `/api/v1/policies` | List ingested PDFs |
| POST | `/api/v1/ingest` | Trigger ingestion |
| POST | `/api/v1/decide` | Submit a claim → AI decision |
| GET | `/api/v1/history` | All past decisions (from SQLite) |
| GET | `/api/v1/history/{id}` | Single claim by ID |

Swagger UI: http://localhost:8000/docs

---

## Database (SQLite)

File: `data/policypilot.db` — created automatically on first startup.

| Table | Contents |
|---|---|
| `claims` | Every submitted claim |
| `decisions` | AI decision, confidence, reasoning, clauses, model used |
| `audit_log` | Ingestion and decision events |

---

## Switching Models

Edit `.env`:
```
OLLAMA_MODEL=llama3.2:3b
```
Then pull it:
```bash
ollama pull llama3.2:3b
```
Restart the backend — no other changes needed.

---

## Troubleshooting

**CUDA out of memory** → Switch to a smaller model (`tinyllama`) or reduce context: `LLM_NUM_CTX=2048` in `.env`.

**Ollama not detected in sidebar** → Make sure `ollama serve` is running before starting the backend.

**Vector store not found on /decide** → Run `/ingest` first (Step 8).

**First inference is slow** → Normal. Ollama loads the model into VRAM on the first call. Subsequent calls are much faster.

---

## Running Tests

```bash
pytest tests/ -v
# Ollama does NOT need to be running — LLM is mocked in tests
```
