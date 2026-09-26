# AI Copilot for Scalable Cell-Culture Bioprocess Design

A hackathon prototype of a **decision-support copilot** for bioprocess engineers. It helps analyse cell-culture bioreactor data and reason about scale-up (e.g. 1 L → 10 L → 100 L → 1000 L).

> This software does **not** control a physical bioreactor. It analyses data you provide (simulated data first; CSV, manual and optional live data later).

## Architecture

```
            React (Vite)
                 │
     ┌───────────┼───────────┐
   Manual       CSV      Simulator (WebSocket)
     └───────────┼───────────┘
                 ↓
              FastAPI
                 ↓
   Validation (Pydantic Observation model)
                 ↓
   Persistence (SQLModel repository)
                 ↓
               SQLite
         experiments ─< observations
                 ↓
         Experiment History
```

```
frontend/   React + Vite (JavaScript)
backend/    FastAPI (Python)
```

In development the Vite dev server proxies `/api/*` to the backend on `http://127.0.0.1:8000`, so no CORS configuration is needed.

## Current status

- **Phase 1:** FastAPI backend with `GET /api/health`; React frontend shows backend status.
- **Phase 2:** Experiment data input — manual entry form and CSV upload, validated by the backend. Data is validated and returned, not yet stored.
- **Phase 3:** Simulated bioreactor — a software-only data source streamed over a WebSocket to a live dashboard.
- **Phase 4:** SQLite storage — experiments and their observations are saved (manual, CSV and simulator), with an Experiment History page.
- **Phase 5:** Process Monitoring — descriptive analysis of a stored experiment (latest values, statistics, trends, data coverage).
- **Phase 6:** Scale-Up Simulator — transparent, illustrative scenario comparison of a stored experiment with a larger (or smaller) target scale.
- **Phase 7:** Anomalies — deterministic, rule-based findings with evidence (prototype ranges, rapid changes, trends, co-occurring changes, data coverage). No AI or machine learning.
- **Phase 8:** AI Analysis — Gemini interprets the deterministic results (Phase 5 analysis, Phase 7 findings, optional Phase 6 scenario). The API key stays on the server.
- **Phase 9:** AI Copilot — ask questions about one selected experiment; answers come from Gemini interpreting the application's deterministic context, with evidence, uncertainties and follow-up questions.
- **Phase 10:** Experiment Comparison — deterministic side-by-side comparison of two stored experiments (B − A), with optional Gemini interpretation.
- **Phase 11:** Report Generation — downloadable PDF experiment report built from the existing results; Gemini is not required.
- **Phase 12:** Bioreactor Visualization — interactive, illustrative stirred-tank animation driven by the existing simulator state.
- **Phase 13:** Bioprocess Command Center — one-screen dashboard aggregating the existing results for a selected experiment.
- **Phase 14:** Advanced Scale-Up Modeling — illustrative engineering estimates (kLa, P/V, tip speed, OTR/OUR, agitation and aeration scaling strategies) inside the Scale-Up page.
- **Phase 15:** Process Forecasting & What-If Scenarios — an Illustrative Process Forecast (exponential/logistic cell density, linear DO/pH/temperature trends) on the new **Forecasting** tab.
- **Phase 16:** Experiment Planning — "What should I test next?": deterministic candidate experiment conditions within allowed ranges on the new **Experiment Planning** tab, with an optional Gemini explanation.
- **Phase 17:** Real-Time Bioprocess Monitoring & Alerts — live alerts from the existing anomaly rules on simulator data (Simulated Bioreactor page and Command Center), a labelled SIMULATED DISTURBANCE for demos, and an optional AI Copilot explanation of an alert.
- **Phase 18:** Alert Investigation — Finding Precedents: exact same-rule matches of an alert/finding in stored experiments, what the stored data showed afterwards, a "Compare with this run" hand-off and optional precedents in the Copilot explanation.
- **Phase 19A:** Demo readiness — deterministic SIMULATED demo seed (`python -m app.demo_seed`), Command Center as the landing page with a navigation-only demo workflow, and live-alert highlighting on the bioreactor and metric cards.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Backend health/status |
| GET | `/api/experiments/schema` | Observation fields (name, unit, type, required); also the CSV column list |
| POST | `/api/experiments/observations` | Validate one observation (JSON). `201` on success, `422` with field errors |
| POST | `/api/experiments/upload` | Upload a CSV (`multipart/form-data`, field `file`). Returns accepted observations and per-row errors |
| WebSocket | `/api/simulator/ws` | Simulated bioreactor stream, optionally saved to an experiment (see below) |

Stored experiments (Phase 4):

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/experiments` | Create an experiment. `201`; `409` if the `experiment_id` already exists |
| GET | `/api/experiments` | List experiments, newest first, each with `observation_count` |
| GET | `/api/experiments/{experiment_id}` | One experiment's metadata + `observation_count` (no observations) |
| DELETE | `/api/experiments/{experiment_id}` | Delete the experiment **and all its observations** |
| GET | `/api/experiments/{experiment_id}/observations?limit=1000` | Its observations ordered by culture time (`limit` 1–10,000, default 1000) |
| GET | `/api/experiments/{experiment_id}/analysis` | Descriptive analysis of all its observations (see Process Monitoring); empty experiments return an empty analysis |
| GET | `/api/experiments/{experiment_id}/anomalies` | Rule-based findings with evidence, severity counts, summary and the monitoring configuration used (read-only) |
| POST | `/api/experiments/{experiment_id}/ai-analysis` | Gemini interpretation (see AI Analysis). Body `{}` or `{"scale_up": {...ScaleUpRequest}}` |
| GET | `/api/ai/status` | `{"configured": true/false}` — whether a Gemini key is set on the server (nothing else) |
| POST | `/api/experiments/{experiment_id}/copilot` | AI Copilot answer. Body `{"message": "...", "scale_up"?: {...}, "ai_analysis"?: {...}}` |
| POST | `/api/experiments/compare` | Deterministic comparison. Body `{"experiment_a_id": "...", "experiment_b_id": "..."}` (must differ). Read-only |
| POST | `/api/experiments/compare/interpret` | Optional Gemini interpretation of that comparison (same body) |
| GET | `/api/experiments/{experiment_id}/report` | PDF report (deterministic sections only) — `application/pdf` download |
| POST | `/api/experiments/{experiment_id}/report` | PDF report with optional sections. Body `{"scale_up"?: {...ScaleUpRequest}, "ai_analysis"?: {...}, "copilot"?: {...}}` |
| POST | `/api/experiments/{experiment_id}/observations` | Validate and save one observation (Phase 2 fields; `experiment_id` in the body is optional but must match the URL) |
| POST | `/api/experiments/{experiment_id}/upload` | Validate a CSV and save its valid rows; returns accepted/rejected counts, row errors and `saved_count` |

Scale-up (Phase 6):

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/scale-up/simulate` | Illustrative scale-up scenario for a stored experiment. Read-only: writes nothing |
| POST | `/api/scale-up/model` | Advanced scale-up modeling (Phase 14): engineering estimates with configurable assumptions. Read-only |
| POST | `/api/experiments/{id}/forecast` | Illustrative process forecast (Phase 15): body `{horizon_hours?, cell_model: exponential\|logistic, carrying_capacity?, scenario?}`. 404 unknown experiment, 422 invalid input. Read-only |
| POST | `/api/experiments/{id}/plan` | Experiment planning (Phase 16): body `{objective, constraints?, max_candidates?}`; deterministic candidate conditions. 404 unknown experiment, 422 invalid input. Read-only, no Gemini |
| POST | `/api/experiments/{id}/plan/interpret` | Optional Gemini explanation of the generated candidates (Phase 16). 503 if Gemini is not configured. Nothing stored |
| POST | `/api/precedents/search` | Finding precedents (Phase 18): body `{type, parameter?, direction?, related_parameters?, exclude_experiment_id?, current?, follow_up_hours?}`; exact same-rule matches in stored experiments + follow-up. 422 invalid input. Read-only, no Gemini |

Errors: `404` unknown experiment, `409` duplicate ID or wrong data source, `422` invalid input, `503` database failure (friendly message, no stack trace).

## CSV format

UTF-8 CSV, max 5 MB / 10,000 rows. The first row is a header; column order doesn't matter.

```
experiment_id,culture_time_hours,temperature_c,ph,dissolved_oxygen_percent,agitation_rpm,cell_density,feed_rate,nutrient_concentration,aeration_rate,notes
```

| Column | Unit | Required |
|---|---|---|
| `experiment_id` | text | yes |
| `culture_time_hours` | h | yes |
| `temperature_c` | °C | yes |
| `ph` | — (0–14) | yes |
| `dissolved_oxygen_percent` | % air saturation | yes |
| `agitation_rpm` | rpm | yes |
| `cell_density` | ×10⁶ viable cells/mL | yes |
| `feed_rate` | mL/h | no |
| `nutrient_concentration` | g/L | no |
| `aeration_rate` | vvm | no |
| `notes` | text | no |

- Empty cells in optional columns are allowed; empty required cells are row errors.
- Validation is type/format only: numbers must be finite, and times, rates, densities and agitation must be ≥ 0. No biological operating limits are enforced yet.
- A missing required column, duplicate column, or unreadable file rejects the whole file (`422`). Invalid rows are reported individually and the valid rows are still accepted. Unknown columns are ignored and listed in the response.
- When uploading **into an experiment**, `experiment_id` is optional: empty cells take the selected experiment, and rows naming a different experiment are rejected (never silently reassigned).
- Example file: [`sample_data/example_observations.csv`](sample_data/example_observations.csv) (its rows belong to `EXP-001`).

## Experiment storage (SQLite)

> **Simulated observations are generated for demonstration, testing, and visualization and are not actual laboratory measurements.**

- **Location:** `backend/data/bioprocess.db`, created automatically (with its tables) when the backend starts. Override with the `BIOPROCESS_DB_URL` environment variable (the tests use a temporary database this way). Database files are git-ignored.
- **Tables:**
  - `experiments` — `id`, `experiment_id` (unique, URL-safe), `name`, `description`, `scale_liters`, `data_source` (`manual` \| `csv` \| `simulated`; e.g. `live` can be added later), `created_at` (UTC), `notes`.
  - `observations` — `id`, `experiment_id` → `experiments.experiment_id` (`ON DELETE CASCADE`), the Phase 2 observation fields, `recorded_at` (UTC).
- **Relationship:** one experiment has many observations. Deleting an experiment deletes its observations in the same transaction, and the foreign key (enforced with `PRAGMA foreign_keys=ON`) prevents orphan observations.
- **Validation stays in one place:** every observation is validated by the Phase 2 `Observation` model before it reaches the database layer (`backend/app/db_models.py`, `backend/app/repository.py`).
- **Data sources are kept separate:** manual and CSV observations can only be saved to MANUAL/CSV experiments, and simulator output only to SIMULATED experiments. The UI labels them MANUAL, CSV and SIMULATED.

**Using it:** on **Experiment Data**, select an experiment or create one with **+ New experiment**, then save observations with **Manual Entry** or **CSV Upload → Upload & Save**. **Experiment History** lists all experiments with observation counts; **View** shows metadata and observations, **Delete** removes an experiment with its observations.

**How simulated observations are saved:** on **Simulated Bioreactor**, choose (or create) a SIMULATED experiment under *Save to experiment* before pressing START, or leave *Don't save (preview only)*. The backend saves each generated observation once, as it is streamed — the browser never re-posts data, so there are no duplicates. A new run needs an empty experiment. If saving fails, the stream continues and the page shows a warning with the number of unsaved observations.

## Process Monitoring (descriptive analysis)

Open **Process Monitoring**, select any stored experiment (or click **Analyze** in Experiment History) to see what was recorded:

- **Header:** name, ID, scale, data source, observation count, culture duration.
- **Summary:** factual sentences generated from the data, e.g. *"8 observations were recorded over 3.5 culture hours"*, *"Cell density changed from 0.50 to 8.40 ×10⁶ cells/mL"*, *"Temperature ranged from 36.50 to 37.20 °C"*.
- **Latest values:** temperature, pH, DO, agitation and cell density at the latest culture time.
- **Trends:** one chart per parameter vs culture time; optional parameters (feed rate, nutrient concentration, aeration rate) only when they have at least two values.
- **Process statistics:** start, final, min, max, average and delta (final − start) per parameter, with the number of values used.
- **Data coverage:** culture-time range, distinct time points, interval between time points, missing optional values, and whether trend charts are possible.

How it is calculated (`backend/app/analysis.py`, read-only, from the stored observations):

- Observations are ordered by culture time (then insertion order). *Start*/*final* are the first/last observations that **have a value** for that parameter; optional parameters that were never recorded get no statistics.
- Culture duration = latest − earliest culture time. Gaps between time points are reported, not filled.
- Values are never rounded in calculations; decimals are applied only for display.

This is **descriptive only**: it makes no judgement about process quality and does not detect anomalies, score risk or assess scale-up.

## Bioprocess Command Center

Open **Command Center** (first tab) and select an experiment to see, on one screen: metadata and simulation status (Running / Paused / No live simulation), key metrics (cell density, DO, pH, temperature, agitation, culture time, feed, aeration — "Not available" when missing), a compact Phase 12 bioreactor drawing, process status and factual summary (Phase 5), trend charts ("Insufficient data for trend" below 2 time points), anomaly counts and the most severe findings (Phase 7, existing severity order), a scale-up snapshot for the scenario last run on the Scale-Up page (existing scale-up endpoint, labelled *Scenario calculation*), the AI Analysis and Copilot results already generated in this session (labelled AI-generated), and quick actions that open the existing tabs (new experiment, bioreactor, analysis, scale-up, anomalies, Copilot, comparison, report).

It is a **presentation layer only**: no new calculations, scores or thresholds; it never calls Gemini; live values are used only when the shared simulator run is saving into the selected experiment (the same single WebSocket as the simulator pages), otherwise the last stored observation is shown and labelled as such. Simulated experiments carry a notice. No backend changes.

## Bioreactor Visualization (illustrative)

> **Illustrative simulation — not a real-time physical bioreactor measurement.** Visual elements represent simulated process values and are not calibrated physical measurements.

Open **Bioreactor** to see an animated stirred-tank drawing (SVG + CSS) of the **existing Phase 3 simulator** next to a live data panel (temperature, pH, DO, agitation, cell density, feed, nutrient, aeration, culture time — missing values read "Not available", never 0), a DO gauge, a pH marker and the run status (**Running / Paused / Stopped / Error**).

- **One source of truth:** `useSimulator()` is called once in `App.jsx`; the same state (and the same single WebSocket) feeds the Simulated Bioreactor page, its charts and this view. There is no second simulator, timer or random generator, and no backend change.
- **Visual mappings** (`frontend/src/components/BioreactorVessel.jsx`, symbolic scalings, not physics): impeller turns faster with agitation rpm and stops at 0; mixing arrows follow the impeller; bubbles rise from the sparger with count/speed from aeration (vvm), none at 0; feed drops appear only when feed rate > 0 (the Phase 3 simulator does not produce feed, so this shows "Not available"); cell particles scale with cell density (capped at 100 — *"Cell visualization — illustrative"*, not a cell count); the thermometer uses a 20–45 °C display scale; DO/pH probes are labelled. No kLa, CFD, mixing, heat-transfer or growth model is added.
- **Controls:** ▶ Start / Resume, ⏸ Pause (the existing stop — state is kept), ↻ Reset, using the existing WebSocket protocol. Start here launches a preview run with default initial conditions; initial conditions and saving to an experiment stay on the Simulated Bioreactor tab (both tabs show the same run). **Speed** 0.5×/1×/2×/5× sets how often the simulator steps (`interval_seconds`) for new runs; each step is still 0.5 h of culture time.
- **Scale:** the run's working volume (1/10/100/1000 L for new runs). If the running experiment has a Scale-Up page scenario, source → target and the scale factor are shown. The drawing is the same size at every scale.
- **Accessibility:** labelled SVG with tooltips; all numbers stay as text; animations pause when the simulation is not running and are switched off under `prefers-reduced-motion`.

## Report Generation (PDF)

Open **Report**, select an experiment, review the contents preview, optionally tick **Scale-Up Scenario**, **AI Analysis** and **AI Copilot**, and click **Generate PDF report** — the file (`bioprocess-report-<ID>.pdf`) downloads immediately (**Download again** is available). Reports are generated on demand, **never stored**, and do not modify any data.

**Contents** (`backend/app/report.py`, ReportLab): header (project, title, experiment, name, scale, data source, generated time) · 1 Executive Overview · 2 Experiment Details · 3 Process Statistics (start/final/min/max/average/delta per parameter; a parameter with no observations reads *"Not available: no observations of this parameter"*, never 0) · 4 Process Trends (temperature, pH, DO, agitation, cell density vs culture time from the stored observations; *"Insufficient data for trend"* with fewer than 2 time points; long runs are drawn with every n-th point, noted on the chart) · 5 Data Quality · 6 Anomaly / Findings · 7 Scale-Up Scenario · 8 AI Analysis · 9 AI Copilot · 10 Limitations · page numbers in the footer.

**No new calculations:** every value comes from the existing Phase 5 analysis, Phase 7 findings and Phase 6 scale-up service (the scenario is recomputed on the server from the request). Each section is labelled **OBSERVED DATA**, **DETERMINISTIC CALCULATION**, **SCENARIO ASSUMPTIONS** or **AI INTERPRETATION**.

**Optional sections:**
- *Scale-Up Scenario* — the scenario last simulated on the Scale-Up page for this experiment, or else a scenario keeping the latest values at 10/100/1000 L. Labelled as illustrative; lists what is not calculated (kLa etc.).
- *AI Analysis* / *AI Copilot* — only a result generated **earlier in this browser session** for the same experiment (AI results are not stored). The backend validates the structure and experiment ID, labels it *AI-generated interpretation* / *AI Copilot response*, and never fabricates or regenerates it. Otherwise the report states "AI analysis not included." / "AI Copilot response not included."

**Gemini is not required:** the report never calls Gemini, so it works when Gemini is unconfigured or its quota is exhausted. The API key never appears in reports.

**Dependency:** `reportlab` (added to `backend/requirements.txt`; pulls in Pillow). **Limitations:** built-in PDF fonts (Windows-1252) — symbols such as ⁶, ₂, → are mapped (superscript/subscript/"->"), other rare characters become "?"; at most 100 findings are listed; AI/Copilot sections depend on results kept in the current browser session.

## Experiment Comparison

Open **Experiment Comparison**, choose **Experiment A** and **Experiment B** (two different experiments), and press **Compare Experiments**. **Swap A ↔ B** and **Clear** are available. The comparison is **deterministic** (`backend/app/comparison.py`), **read-only** (nothing is stored, no experiment or observation is modified) and works without Gemini.

- **Built from existing calculations:** Phase 5 statistics and data quality and Phase 7 anomaly findings for each experiment — nothing is recalculated differently.
- **Parameters:** temperature, pH, DO, agitation, cell density, feed rate, nutrient concentration, aeration rate — start, final, min, max, average and delta (switchable in the table). **Difference = B − A.** Percentage difference = (B − A) / |A| × 100, only for start/final/min/max/average, and omitted with an explanation when A is zero or missing.
- **Missing data:** shown as *Not available* with the reason (e.g. "Experiment A has no Feed rate observations") — never converted to zero.
- **Scale:** both working volumes and the scale factor B/A (unavailable if a volume is missing/invalid). Different volumes add the note: *"Different working volumes are being compared. Differences may reflect scale-dependent process behavior and/or differences in operating conditions."* A larger scale is not assumed to be a successful scale-up.
- **Data quality:** observations, duration, culture-time range, distinct and repeated time points, interval range, missing optional values and trend-chart availability — the Phase 5 definitions side by side.
- **Time alignment:** shared culture-time points, points only in A / only in B, and the overlap. Values are compared point by point **only at time points that exist in both experiments** (and occur once in each); a chart shows those shared points only. No interpolation, no synthetic observations.
- **Anomalies:** per experiment — total, by severity, by type, by parameter, and the most severe finding messages. No combined risk score.
- **Summary:** factual sentences only (e.g. "Experiment B used 10× the working volume of Experiment A"). **No winner, ranking or score** and no evaluative wording.
- **Simulated data:** if one or both experiments are simulated, a notice states that differences reflect software-generated data, not laboratory measurements.

**Optional Gemini interpretation** (`backend/app/comparison_ai.py`): **Interpret with Gemini** sends only the calculated comparison — aggregate statistics, differences, data quality, time-alignment counts, anomaly summaries, notices — and **no raw observations or point-by-point values**. The prompt requires Gemini to use only that context, not recalculate values, separate observations from interpretations, avoid causal claims from correlation, declare no winner, avoid "optimal/safe"-type terms, state uncertainty, treat simulated data as simulated, and frame suggestions as investigation points. The answer (overview, key differences, possible interpretations, investigation points, uncertainties) is validated before display. It uses the existing Gemini service; if Gemini is not configured (`503`) or fails (`400`/`429`/`503` → `502` with the code), only the interpretation is unavailable — the deterministic comparison is unaffected. Each interpretation is one Gemini request (free-tier quota applies; `429` is not retried).

## AI Copilot (Gemini)

> **This Copilot is a decision-support prototype. It does not control a physical bioreactor and does not replace scientist or process-engineering judgment.**

Open **AI Copilot**, select an experiment (required — the Copilot always answers about one named experiment), then ask a question or click an example (*Summarize this experiment*, *What changed most?*, *Why did DO decrease?*, *What anomalies were detected?*, *What should I investigate first?*, *What should I check before scale-up?*, *What information is missing?*). Each answer shows **Answer**, **Evidence from the experiment data**, **Uncertainties** and clickable **Suggested follow-up questions**. Optionally include an illustrative scale-up scenario, and — if you ran AI Analysis for the same experiment in this session — that earlier AI analysis. No chat history is stored.

**Deterministic-first architecture** (`backend/app/copilot.py`):

1. Load the experiment; run the Phase 5 analysis and Phase 7 anomaly checks; recompute the Phase 6 scenario on the server if one is supplied.
2. Build a **bounded context** from those results (the same curated input as AI Analysis): metadata, culture duration, statistics (start/final/min/max/average/delta), latest observation, data coverage, factual summary, findings with evidence and the monitoring configuration. At most 40 findings (most severe first; the rest are counted), ≤ 20 points per finding, **no raw observation history**. An earlier AI analysis is included only if supplied and is labelled as AI interpretation, not fact.
3. Send the context plus the question to Gemini with a Copilot system instruction: use only the supplied context; never invent or recalculate measurements, thresholds or missing sensor data; separate observations from interpretations; no causation from correlation alone; state uncertainty; say when a question cannot be answered; no optimal/safe claims unless established; no unsafe biological/medical instructions; never pretend to control a bioreactor; suggestions are investigation points, not commands.
4. Validate the JSON answer (`answer`, `evidence`, `uncertainties`, `suggested_questions`) before returning it.

Gemini is reached only through the existing `gemini_service.py` (same client, 90 s timeout, JSON-schema output, automatic retry of `503` overload). **API key security:** `GEMINI_API_KEY` stays in the backend environment (`backend/.env`, git-ignored); it is never sent to the browser, returned, logged or placed in prompts.

**Errors:** unknown experiment `404`; empty message `422`; Gemini not configured `503`; Gemini `400` (request rejected), `429` (rate limit / quota) and `503` (overloaded, after retries) → `502` with a clear message naming the code; invalid Gemini answer `502`; anything unexpected → a generic `500` without internal details.

**Quota:** on the Gemini **free tier** each question is one request, and the limit is small (at the time of writing 20 requests per day per model — see Google's rate-limit page). When it is reached the Copilot shows the `429 RESOURCE_EXHAUSTED` message; it is not retried automatically. A different model can be configured with `GEMINI_MODEL`.

**Limitations:** answers are AI-generated and only structurally validated — review them before relying on them; context is summarised (statistics + findings), so questions about individual raw readings may not be answerable; simulated experiments contain software-generated values, not laboratory measurements; one question at a time, no stored conversation.

## AI Analysis (Gemini)

> **AI-generated interpretation. Measurements and deterministic findings come from the application; AI interpretations should be reviewed by a scientist.**

Open **AI Analysis**, select an experiment, optionally include an illustrative scale-up scenario, and click **Analyze with Gemini**. The page shows: Process Overview, Observed Patterns, Possible Interpretations (each with its uncertainty), Attention Points, Scale-Up Considerations (only when a scenario was included) and Questions for Further Investigation. Nothing is stored.

**Architecture:** React → FastAPI → Gemini. The browser never talks to Gemini and never sees the key.

- `backend/app/gemini_service.py` — the only module using the SDK ([`google-genai`](https://pypi.org/project/google-genai/), `from google import genai`). Reads `GEMINI_API_KEY`, creates the client lazily, requests JSON matching a fixed schema, validates it, and maps failures to controlled errors. The key is never returned, logged or put in error messages.
- `backend/app/ai_analysis.py` — builds a **controlled input**: experiment metadata and culture duration, Phase 5 statistics / latest observation / data coverage / factual summary, Phase 7 findings with evidence and the monitoring configuration, and (optional) the Phase 6 scenario recomputed on the server. No internal database fields, no raw observation dump. The system instruction tells Gemini to treat the supplied data as fact, never recalculate or invent measurements or thresholds, separate facts from interpretation and uncertainty, use cautious language, and give no safety/risk score or validated-sounding recommendations.
- Model: `gemini-3.8-flash` by default; override with `GEMINI_MODEL`.

**Configure the key** (server-side only; `.env` files are git-ignored):

```bash
# backend/.env   (never commit this file)
GEMINI_API_KEY=your-key-here
```

```bash
cd backend
uvicorn app.main:app --reload --port 8000 --env-file .env
# or set it in the shell instead: PowerShell  $env:GEMINI_API_KEY="..." ; bash  export GEMINI_API_KEY=...
```

**Errors:** unknown experiment `404`; no key configured `503` (the page shows how to configure it and disables the button); Gemini/network failure or a response that does not match the schema `502` — no analysis is shown rather than a repaired or invented one. Process Monitoring, Anomalies and Scale-Up work without Gemini.

**Limitations:** requires internet access and a Gemini API key (usage may be billed by Google); output quality depends on the model and is not verified beyond structural validation; the time series itself is summarised (statistics + findings), not sent point by point; no AI history is stored; no chat yet.

## Advanced Scale-Up Modeling (Phase 14)

> **The advanced scale-up module provides illustrative engineering calculations. It is not a validated industrial bioreactor model.** These calculations are illustrative engineering estimates and do not replace experimentally validated bioreactor design or process-development data.

Shown at the bottom of the **Scale-Up** page (`backend/app/scaleup_modeling.py`, `POST /api/scale-up/model`). Source values are the latest recorded agitation, aeration, DO and cell density of the source experiment; the target uses the selected strategies. Results update automatically when the target scale, a strategy or an assumption changes. Nothing is stored and Gemini is not used.

| Quantity | Formula | Unit |
|---|---|---|
| Power per volume | P/V = Np · ρ · N³ · D⁵ / V (N in rev/s, D in m, V in m³) | W/m³ |
| Impeller tip speed | π · D · N | m/s |
| kLa (estimated) | K · (P/V)^a · vvm^b | 1/h |
| Dissolved O₂ concentration | C = DO% / 100 · C* (*DO concentration conversion assumption*) | mmol/L |
| OTR | kLa · (C* − C) | mmol/L/h |
| OUR | qO2 · X (qO2 in pmol/cell/h, X in 10⁶ cells/mL) | mmol/L/h |
| Oxygen balance | OTR − OUR → "transfer capacity exceeds uptake" / "uptake exceeds transfer capacity" / "approximately balanced" (±10 %) | mmol/L/h |
| Constant RPM | N_t = N_s | rpm |
| Constant tip speed | N_t = N_s · D_s / D_t | rpm |
| Constant P/V | N_t = N_s · (D_s/D_t)^(5/3) · (V_t/V_s)^(1/3) | rpm |
| Constant vvm / constant gas flow | Q_t = vvm · V_t / Q_t = Q_s | L/min |

**Model assumptions (configurable, labelled MODEL ASSUMPTION):** power number 5, liquid density 1000 kg/m³, K = 5 1/h, a = 0.4, b = 0.5, C* = 0.21 mmol/L, qO2 = 0.2 pmol/cell/h. **Impeller diameters are never assumed** — without them P/V, tip speed, kLa, OTR and geometry-based strategies are *Not available*; the "Use example geometry (D ∝ V^1/3)" button fills a labelled geometric-similarity example. Every value is labelled OBSERVED DATA, DERIVED CALCULATION, MODEL ASSUMPTION, SCENARIO RESULT or NOT AVAILABLE. The strategy comparison is not ranked.

**Limitations:** the kLa correlation form and constants are illustrative (not vessel-specific), DO% is converted with a single C*, OUR at the target reuses the source cell density (no growth prediction), no gas hold-up, CO₂, shear, mixing time, heat transfer or CFD.

## Process Forecasting & What-If Scenarios (Phase 15)

> **Phase 15 provides illustrative process forecasting based on historical observations. It is not a validated biological or industrial prediction model.** Forecasts are model-based estimates using historical observations and configurable assumptions. They are not validated biological predictions.

Open **Forecasting**, select an experiment: the backend (`backend/app/forecasting.py`, `POST /api/experiments/{id}/forecast`) fits simple models to the stored observations — a *Model forecast based on available observations and configurable assumptions*. Nothing is stored and Gemini is never called by this page.

| Parameter | Model | Fit |
|---|---|---|
| Cell density | Exponential `X(t) = X0 · exp(mu · t)` | least squares on ln X (positive values only) |
| Cell density | Logistic `X(t) = K / (1 + ((K − X0)/X0) · exp(−mu · t))` | least squares on ln(X/(K − X)); **K is a MODEL ASSUMPTION** (default 2 × observed max; must exceed the observed max) |
| DO, pH, temperature | Linear trend `y = a + b·t` | ordinary least squares |

- **Data sufficiency:** ≥ 3 usable (finite, non-missing) points at ≥ 2 distinct culture times per parameter; otherwise *Insufficient historical data for forecast.* Missing values are skipped, never treated as 0.
- **Horizon:** default 25 % of the observed culture-time span, capped at 100 % of the span (the cap is reported).
- **What-if scenario:** inputs (horizon, target scale, temperature, pH, DO, agitation, aeration, feed) are labelled SCENARIO INPUT. Only the horizon changes the forecast (results then labelled SCENARIO RESULT); the other inputs are recorded only, because no validated biological effect is modelled.
- **Labels:** OBSERVED DATA, MODEL ASSUMPTION, MODEL FORECAST, SCENARIO INPUT, SCENARIO RESULT, NOT AVAILABLE.
- **AI Copilot:** optional checkbox "Include the illustrative process forecast". The browser sends only the forecast *settings*; the backend recomputes the forecast and passes a compact summary (model, parameters, end values, assumptions — no raw point lists) to Gemini, which interprets but never calculates it.
- **Limitations:** extrapolation of simple empirical curves; no mechanistic, substrate, feed, temperature or scale effects; no confidence intervals; not validated for any cell line or bioreactor.

## Experiment Planning (Phase 16)

> **Phase 16 suggests candidate experimental conditions using deterministic design rules. It does not predict biological outcomes, and candidates are not claimed to be optimal or certain to work.** Nothing is applied, saved or created: there is no "apply" or "save as experiment" action.

Open **Experiment Planning**, select a reference experiment, an objective and (optionally) allowed ranges, then click **Generate Candidates** (`backend/app/planning.py`, `POST /api/experiments/{id}/plan`).

- **Reference (OBSERVED DATA):** the final observed value of temperature, pH, DO, agitation, aeration and feed rate. A parameter that was not recorded is NOT AVAILABLE and never invented.
- **Allowed ranges:** a range entered by the user is a USER CONSTRAINT; otherwise the prototype monitoring default (`MonitoringConfig`, a PLANNING ASSUMPTION — not a cell-line limit) is used. Aeration and feed rate have no default and are held at the reference. Ranges must stay within the `Observation` field limits (e.g. pH 0–14, rates ≥ 0). A reference outside the range is clamped and reported.
- **Design rules by objective** (identical input → identical output; up to `max_candidates`, default 5, max 8):

| Objective (UI label) | Candidates |
|---|---|
| Explore conditions related to cell density | baseline repeat + one-at-a-time steps in both directions (step: user value or 10 % of the range); "explores sensitivity of cell density to this parameter" — no direction is claimed to improve it |
| Maintain process stability | baseline repeat + smaller one-at-a-time steps (5 % of the range) |
| Explore operating conditions | centre of the allowed ranges, then low/high of each parameter one at a time |
| Compare candidate conditions | two-level design (4 runs; 2^(3−1) fractional for 3 parameters) over parameters with an entered range only |

- **DERIVED CALCULATION:** change from reference and relative position within the allowed range. **Warnings:** significant anomaly findings in the reference run (a baseline repeat may be appropriate first) and *extrapolation beyond observed conditions* for values outside the reference run's observed range.
- **Explain with AI** (`POST /api/experiments/{id}/plan/interpret`) is called only on click. The backend regenerates the plan and sends only the plan (no observation history) to Gemini, whose output is labelled AI INTERPRETATION. Gemini does not generate or change candidates.
- **Limitations:** no outcome prediction or ML; one-at-a-time designs miss interactions; the comparison design is very small; the reference is a single run; default ranges are generic.

## Demo readiness (Phase 19A)

> **The demo dataset is SIMULATED DEMO DATA generated by the software simulator. It is not laboratory data and must not be presented as experimental measurements.**

**Seed the demo data** (developer/demo command; never run by the application itself, no HTTP endpoint):

```powershell
cd backend
.venv\Scripts\python -m app.demo_seed            # safe: creates missing demo experiments, changes nothing else
.venv\Scripts\python -m app.demo_seed --replace  # rebuilds ONLY the four DEMO-* experiments (e.g. before each rehearsal)
```

It writes to the configured database (`BIOPROCESS_DB_URL`, default `backend/data/bioprocess.db`) with the normal experiment/observation tables, using the existing simulator with fixed seeds (deterministic):

| Experiment | Scale | Content |
|---|---|---|
| `DEMO-1L-BASELINE` | 1 L | seed 101, default setpoints, 192 observations (0–95.5 h) |
| `DEMO-10L-SCALEUP` | 10 L | seed 102, configured agitation 140 rpm, 192 observations. The simulator does not model physical scale effects; differences come from the configured setpoint and seed. |
| `DEMO-1L-DO-EVENT` | 1 L | seed 103, SIMULATED DISTURBANCE DO −35 % air sat. at 24 h (noted in the observation), 192 observations — the precedent for the live DO alert |
| `DEMO-LIVE` | 1 L | empty SIMULATED experiment: the save target for the live simulator run |

Every description starts with `SIMULATED DEMO DATA — generated by the software simulator (seed N); not laboratory measurements.` Without `--replace`, existing demo experiments are left unchanged (and a `DEMO-LIVE` that already holds a live run is reported, not deleted). `--replace` deletes and recreates only those four IDs, and only when the experiment is SIMULATED and carries the marker; if any of the IDs belongs to other data, the command refuses and changes nothing. There is no "delete all".

**Guided workflow.** The app opens on the **Command Center**, which has a collapsible **SIMULATED DEMO WORKFLOW** card: Simulated Bioreactor → inject simulated disturbance → inspect alert → find precedents → compare runs → Scale-Up → Forecasting → Experiment Planning → AI Copilot → Report. Its buttons only navigate; starting the simulator, injecting a disturbance and asking Gemini remain explicit actions on those pages. No experiment is selected automatically (each page keeps its own selection).

**Alert highlighting.** While a live alert is unacknowledged (and the connection is open), the affected parameter is highlighted on the illustrative vessel (DO probe, pH probe, thermometer, motor; Bioreactor page and Command Center, for the displayed run only) and on the matching metric card of the Simulated Bioreactor page. It is derived from the existing live alerts and disappears on acknowledge, reset, a lost connection (stale alerts) or a new run.

## Alert Investigation — Finding Precedents (Phase 18)

> **Precedents are exact same-rule matches in stored data. They show what was recorded, not what caused an event, what will happen in the current run, or what to do. No causal inference is made from these historical observations.**

Open an alert on the **Simulated Bioreactor** page (Live alerts) or a finding on the **Anomalies** page and click **Find precedents** (`backend/app/precedents.py`, `POST /api/precedents/search`; deterministic, read-only, no Gemini, no database changes).

- **Exact matching** (no similarity, scores, ranking or ML): same finding type, same parameter and same direction (range: above/below; sudden change and trend: increased/decreased); co-occurrence: the same set of related parameters (no partial overlap). Findings come from re-running the existing `anomaly.detect()` (prototype default configuration) on each stored experiment.
- **Search scope:** the 100 most recently created experiments (the cap and any skipped experiments are reported). An earlier matching episode in the run being investigated is included and labelled **Earlier in this run**; the finding itself is never its own precedent. Unsaved live runs search stored experiments only. Order is deterministic (same run first, then newest experiment first, then culture time) — not a ranking.
- **What the stored data showed afterwards** (follow-up window: trigger time → +12 h; trigger = episode start for range/trend, interval end for changes): whether the parameter was inside its prototype range at the trigger or returned inside it (and when), the last stored value within the window, and later findings in the window. Nothing is extrapolated: if the stored run ends earlier, this is stated.
- **Compare with this run** opens the existing **Experiment Comparison** page with both experiments preselected (existing comparison endpoint).
- **Explain with AI → Include precedents** (saved runs only, on click): the browser sends only `{"alert": {"alert_id", "include_precedents": true}}`; the backend locates the finding, runs the search and adds a compact summary (≤ 5 precedents; no observations or evidence points) to the Copilot context. Gemini is instructed not to predict recovery, rank runs, claim causation or give settings.
- **Limitations:** exact matching can find nothing on small datasets (no result is not a conclusion); matches use the prototype monitoring defaults; the search re-runs detection per request (~0.7 s for 100 experiments × 200 observations).

## Real-Time Monitoring & Alerts (Phase 17)

> **Live alerts report that a prototype monitoring rule was met. An alert does not prove a biological problem, there is no risk score, and nothing controls the bioreactor — the scientist decides what to investigate.**

- **Detection is not duplicated.** For every simulator step, `backend/app/monitoring.py` (`LiveMonitor`) re-runs the existing `anomaly.detect()` on a bounded window of the run's observations (last 1000, ≈ 500 h at the default step) and compares the result with the previous step. Alerts are session-only: nothing is written to the database (saved runs store their observations as before, so the same findings are available on the **Anomalies** page).
- **Stable alert keys** (anomaly `finding_id`s are index-based): range / trend / data-coverage gap → `type:parameter:start_hours`; sudden change → `change:parameter:end_hours`; co-occurrence → `cooccurrence:end_hours`. A growing episode is one alert: `new` once, then `updated` (e.g. severity ATTENTION → SIGNIFICANT, which asks for acknowledgement again). Data-coverage notes without a culture time (e.g. "parameter never recorded") are not live alerts; they stay on the Anomalies page.
- **Where:** the **Simulated Bioreactor** page shows the Live alerts timeline (severity, culture time, evidence, evidence points, acknowledge) and the **SIMULATED DISTURBANCE** control (software-injected step change, e.g. temperature +3 °C, recorded in the observation `notes`; not a biological intervention). The **Command Center** shows a compact summary (unacknowledged count, latest alerts, link). No new tab.
- **Explain with AI** (only on click, only for runs saved to an experiment): the browser sends only `{"alert": {"alert_id": ...}}` to `POST /api/experiments/{id}/copilot`; the backend re-detects from stored observations, adds the matching finding (≤ 50 evidence points) as `focus_alert` to the existing Copilot context, or returns 404 without calling Gemini. The answer is labelled AI INTERPRETATION.
- **Limitations:** alerts live in the browser session (cleared on reset; marked stale when the connection closes; gone after reload). An episode longer than the 1000-observation window gets a new start and therefore a new key. Detection runs in the simulator loop (~9 ms per step with a full window). Only the simulator is monitored; no real equipment.

## Anomalies (deterministic process checks)

Open **Anomalies** and select an experiment to answer *"Is anything unusual happening in this experiment?"*. Checks run on the stored observations (`backend/app/anomaly.py`); nothing is stored, no AI or machine learning is used, and no risk score is produced. Each finding has a severity, type, parameter, culture time, message and expandable **evidence** (values, times, thresholds/ranges, changes, the observations involved).

**Prototype monitoring configuration** (defaults in `MonitoringConfig`; configurable, **not** universal biological limits for every cell line):

| Parameter | Prototype range | Significant if beyond by | Sudden-change threshold |
|---|---|---|---|
| Temperature | 34–39 °C | > 1 °C | > 1.0 °C |
| pH | 6.5–7.5 | > 0.3 | > 0.3 |
| Dissolved oxygen | 20–100 % air sat. | > 10 | > 15 points |
| Agitation | 0–500 rpm | > 100 rpm | > 50 rpm |
| Cell density | 0–20 ×10⁶ cells/mL | > 5 | > 30 % relative |
| Feed rate, aeration rate, nutrient concentration | — | — | > 30 % relative |

**Rules**

| Type | Rule | Severity |
|---|---|---|
| Parameter outside configured range | Reading outside the prototype range; consecutive out-of-range readings of one parameter are grouped into one finding listing every reading | ATTENTION; SIGNIFICANT if beyond the range by more than the margin |
| Rapid parameter change | Change between consecutive readings above the threshold (relative checks skip a previous value of 0) | ATTENTION; SIGNIFICANT if > 2× the threshold |
| Persistent trend | ≥ 3 consecutive strictly increasing or decreasing readings with a total change ≥ 0.5× the change threshold (filters noise) | INFO |
| Co-occurring changes | Two or more rapid changes over the same observation interval — reported together, no cause inferred | ATTENTION; SIGNIFICANT if ≥ 2 of them are significant |
| Data coverage | < 2 time points, optional parameters not recorded / partly missing, repeated time points, gaps > 3× the median interval | INFO |

INFO / ATTENTION / SIGNIFICANT are display categories, not safety classifications. Findings describe the data; they are not diagnoses. The structured findings (with experiment metadata) are designed to be passed to an AI explanation layer in a later phase.

**Limitations:** fixed default thresholds for all cell lines and processes; consecutive readings are compared regardless of the time between them (large gaps are reported separately); no statistical/ML anomaly models; configuration changes require editing `MonitoringConfig`.

## Scale-Up Simulator (illustrative scenarios)

> **These results are illustrative scenario estimates, not validated predictions for a specific cell line or bioreactor.**

Open **Scale-Up**, select a stored source experiment, choose a target scale (1/10/100/1000 L, 10×/100×/1000×, or any custom positive volume), adjust the scenario settings and press **Simulate scenario**. Settings start from the source's **latest recorded value** of each parameter; **Use source experiment values** resets them. Nothing is saved and the source experiment is not modified.

**Request** (`POST /api/scale-up/simulate`): `source_experiment_id`, `target_scale_liters` (> 0), and optional `target_temperature_c` (20–45), `target_ph` (0–14), `target_dissolved_oxygen_percent`, `target_agitation_rpm`, `target_aeration_vvm`, `target_feed_rate_ml_per_h` (all ≥ 0). Omitted targets are reported as *not specified* — never invented.

**Calculations** (`backend/app/scaleup.py`) — only quantities that follow from definitions:

| Quantity | Formula |
|---|---|
| Scale factor | target volume ÷ source volume |
| Volume increase | target volume − source volume |
| Gas flow | aeration (vvm) × working volume (L) → L/min (× 60 → L/h), for source and target |
| Specific feed | feed rate (mL/h) ÷ working volume (L) |
| Same feed per litre | source feed rate × scale factor |
| Total feed | target feed rate × source culture duration (constant-rate assumption) |
| Parameter change | target − source (and % of source) |

**Parameter treatment** shown for every row:

- **Preserved** — temperature, pH and DO target kept at the source value (the default).
- **Scenario setting** — a user-chosen value: agitation, aeration and feed rate always; any other value that differs from the source.
- **Baseline assumption** — cell density and culture duration are carried over from the source, not predicted.
- **Not available** — neither a source value nor a target was given.

Each row also names what would need **engineering validation** at the target scale; the page lists the main scale-up considerations (oxygen transfer, mixing, heat and mass transfer, shear, gas–liquid behaviour, geometry, impeller configuration, control-loop performance).

**Intentionally not included:** kLa / oxygen transfer rate, power per volume, tip speed, Reynolds number, power consumption, mixing time and any impeller or vessel geometry. The project holds no validated vessel, impeller or cell-line data, so these would be invented numbers; they are future work. No AI, machine learning or risk scoring is used.

## Simulated bioreactor

> **Simulated data is for demonstration, testing, and visualization only and must not be interpreted as actual experimental measurements.**

The simulator is **software-only**: it does not connect to, read from, or control any laboratory equipment. It generates plausible-looking cell-culture time series from a simple illustrative model (`backend/app/simulator.py`):

- **Cell density** follows logistic growth towards a fixed carrying capacity.
- **pH** drifts down slowly as cell density rises; **DO** falls with rising oxygen demand.
- **Temperature** and **agitation** stay near their setpoints with small, smoothed variation.
- **Nutrient concentration** is depleted as the culture grows; aeration is constant.

The model constants are **not** calibrated to any cell line or process. Everything streamed is labelled `"data_source": "simulated"` and the UI shows **Data Source: SIMULATED BIOREACTOR**.

**Using it:** open the **Simulated Bioreactor** tab, optionally set the culture volume (1/10/100/1000 L — metadata only for now) and initial conditions, then press **START**. One observation arrives per second; each second advances culture time by 0.5 h. **STOP** pauses (then **RESUME**), **RESET** discards the run so initial conditions can be changed. The browser keeps the latest 300 observations for the charts.

**WebSocket protocol** (`ws://<host>/api/simulator/ws`, JSON messages). Each connection has its own simulator, which stops when the connection closes.

| Direction | Message |
|---|---|
| client → server | `{"action": "start", "config": {...}, "save_to": "EXP-ID"}` — start a new run (or resume a stopped one); `save_to` is optional |
| client → server | `{"action": "stop"}` / `{"action": "reset"}` |
| client → server | `{"action": "disturb", "parameter": "temperature_c" \| "ph" \| "dissolved_oxygen_percent" \| "agitation_rpm", "offset": number}` — SIMULATED DISTURBANCE (Phase 17); offset limits ±5 °C, ±1 pH, ±50 % air sat., ±300 rpm |
| server → client | `{"type": "status", "status": "simulating" \| "stopped", "data_source": "simulated", "run": {...} \| null}` |
| server → client | `{"type": "observation", "data_source": "simulated", "observation": {...}, "saved": true \| false \| null}` |
| server → client | `{"type": "alert", "event": "new" \| "updated", "alert": {"alert_id", "experiment_id", "saved", "detected_at_hours", "finding"}}` — live alert (Phase 17), sent after the observation that caused it |
| server → client | `{"type": "persistence_error", "message": "..."}` — saving failed; the simulation continues |
| server → client | `{"type": "error", "message": "..."}` |

`config` fields (all optional): `experiment_id`, `volume_liters` (1, 10, 100, 1000), `temperature_c` (default 37), `ph` (7.1), `dissolved_oxygen_percent` (50), `agitation_rpm` (180), `cell_density` (0.5 ×10⁶ cells/mL), `hours_per_step` (0.5), `interval_seconds` (1.0), `seed` (integer, for reproducible runs).

Example streamed observation — the `observation` object uses the same model as manual/CSV input:

```json
{
  "type": "observation",
  "data_source": "simulated",
  "observation": {
    "experiment_id": "SIM-1L-20260924-120000",
    "culture_time_hours": 12.0,
    "temperature_c": 37.03,
    "ph": 7.098,
    "dissolved_oxygen_percent": 49.0,
    "agitation_rpm": 179.1,
    "cell_density": 0.802,
    "feed_rate": null,
    "nutrient_concentration": 5.87,
    "aeration_rate": 0.05,
    "notes": null
  }
}
```

## Prerequisites

- Python 3.11+
- Node.js 20+

## Run the backend

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Check it: http://127.0.0.1:8000/api/health — interactive API docs at http://127.0.0.1:8000/docs

Run tests (from `backend/`): `python -m pytest`

## Run the frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 — the "Backend status" card should show **ONLINE**. If it shows **OFFLINE**, make sure the backend is running on port 8000.

Production build: `npm run build` (output in `frontend/dist/`).

## Legacy prototype

`app.py` and the root `requirements.txt` are an earlier Streamlit prototype, kept for reference. They are not part of the React/FastAPI app. Run with `pip install -r requirements.txt && streamlit run app.py`.
