# Claude Code Project Guide

Hackathon prototype: AI Copilot for Scalable Cell-Culture Bioprocess Design. A decision-support tool — it never controls a real bioreactor, and must not imply knowledge of physical equipment beyond the data provided.

## Structure

- `backend/` — FastAPI (Python). Entry point: `backend/app/main.py`. Endpoints live under `/api`.
  - `app/models.py` — Pydantic `Observation` model (single source of truth for fields, units, validation).
  - `app/experiments.py` — `/api/experiments/*` routes; `app/csv_import.py` — CSV parsing/validation.
  - `app/simulator.py` — simulated bioreactor model (software-only, seedable); `app/simulator_api.py` — `/api/simulator/ws` WebSocket.
  - `app/db.py` — SQLite engine/`init_db`/`get_session` (DB at `backend/data/bioprocess.db`, override with `BIOPROCESS_DB_URL`); `app/db_models.py` — tables; `app/repository.py` — queries; `app/storage_api.py` — stored-experiment routes.
  - `app/analysis.py` — descriptive experiment analysis (service layer behind `GET /api/experiments/{id}/analysis`); no evaluation/AI.
  - `app/scaleup.py` + `app/scaleup_api.py` — illustrative scale-up scenarios (`POST /api/scale-up/simulate`); read-only, definitional calculations only (scale factor, vvm gas flow, feed per litre). Do not add kLa/P/V/tip-speed/geometry without validated data.
  - `app/anomaly.py` — deterministic rule-based findings with evidence (`GET /api/experiments/{id}/anomalies`); thresholds in `MonitoringConfig` are prototype defaults. No AI/ML, no risk score, no causal claims; findings are structured for a later AI-explanation phase.
  - `app/gemini_service.py` — the ONLY Gemini SDK (`google-genai`) boundary; key from `GEMINI_API_KEY` (server-side only, never returned/logged). `app/ai_analysis.py` — controlled input + prompt; `app/ai_api.py` — `POST /api/experiments/{id}/ai-analysis`, `GET /api/ai/status`. Tests override `get_generator`; never make real Gemini calls in tests.
  - `app/copilot.py` — AI Copilot (`POST /api/experiments/{id}/copilot`): bounded deterministic context (reuses `ai_analysis.build_ai_input`, ≤40 findings, no raw history) + Copilot prompt; calls `gemini_service.generate_structured` (never a second Gemini client). Tests override `get_copilot_generator`. Decision-support prototype only.
  - `app/comparison.py` — deterministic two-experiment comparison (`POST /api/experiments/compare`; B − A; reuses Phase 5/7; point-by-point only at shared time points; no winner/score; read-only). `app/comparison_ai.py` — optional Gemini interpretation (`POST /api/experiments/compare/interpret`) from the aggregate comparison only (no raw observations); tests override `get_comparison_generator`.
  - `app/report.py` + `app/report_api.py` — PDF report (`GET|POST /api/experiments/{id}/report`, ReportLab): presentation of existing Phase 5/6/7 results; optional AI/Copilot sections only from client-supplied, validated session results; never calls Gemini; nothing stored. Tests decode PDF streams (ASCII85+Flate) with the stdlib.
  - Never call the real Gemini API in tests or repeated dev checks (free-tier quota is ~20 requests/day/model); browser tests mock AI endpoints via CDP Fetch against a keyless backend.
  - Tests use a temp DB via `tests/conftest.py`; they must never touch the dev DB.
- `sample_data/` — example CSV files.
- `frontend/` — React + Vite (JavaScript). API calls go through `frontend/src/api.js` using relative `/api/...` URLs (proxied by Vite to port 8000). Components in `frontend/src/components/`; form fields are rendered from `/api/experiments/schema`. `src/useSimulator.js` owns the simulator WebSocket; charts use Recharts. All pages stay mounted (hidden) so state survives tab switches.
- Simulator state: `useSimulator()` is called ONCE in `App.jsx` (single WebSocket) and passed as `sim` to `SimulatedBioreactor` and `BioreactorVisualization` (Phase 12). Never open a second simulator connection or add a second simulation model in the frontend; the Bioreactor view only maps existing values to illustrative SVG/CSS animation (`BioreactorVessel.jsx`).
- `CommandCenter.jsx` (Phase 13) aggregates existing APIs/state only (analysis, anomalies, scale-up endpoint, shared `sim`, session AI results); navigation via `onNavigate`. Never add calculations, scores or automatic Gemini calls there.
- `app.py`, root `requirements.txt` — legacy Streamlit prototype, kept for reference only.

## Commands

- Backend install: `cd backend && python -m venv .venv && .venv\Scripts\python -m pip install -r requirements.txt`
- Backend run: `cd backend && .venv\Scripts\python -m uvicorn app.main:app --reload --port 8000` (add `--env-file .env` to load `GEMINI_API_KEY` from `backend/.env`)
- Backend tests: `cd backend && .venv\Scripts\python -m pytest` (run Python from `backend/` — at the repo root, `import app` picks up the legacy `app.py`)
- Frontend install/run: `cd frontend && npm install && npm run dev` (http://localhost:5173)
- Frontend build: `cd frontend && npm run build`

## Working principles

- Build incrementally in small phases; avoid unnecessary abstractions.
- Data sources in order: simulated → CSV/manual → optional live (read-only interface).
- AI outputs should explain observations and risks, with confidence/evidence.
- Planned additions: SQLite storage, pandas/NumPy/scikit-learn analysis, Recharts for charts.
