
# `DeepSkyAgent`🔭

### AstroAgent v2 — AI-Powered Telescope & Astrophotography Planner

> **Evolved from [AstroAgent v1](https://github.com/Master-Atrimoy/AstroAgent/tree/v1.0)** — same adversarial multi-agent core, completely rebuilt stack with a live catalogue, dual-mode UI, GPS location, LLM equipment resolver, and twilight-aware scoring.

---

## What's new in v2

| Feature            | v1 (AstroAgent)              | v2 (DeepSkyAgent)                                                    |
| ------------------ | ---------------------------- | ------------------------------------------------------------------- |
| Frontend           | React + Vite (Node required) | Plain HTML/JS/CSS — no Node                                        |
| Catalogue          | 25 static DSOs               | Live from Vizier/ephem/JPL + 32-object fallback                     |
| Planet positions   | Static RA/Dec                | Computed live via `ephem`                                         |
| Location input     | City search only             | City search + GPS locate-me + Leaflet map                           |
| Equipment          | Preset only                  | Preset + free-text LLM resolver (identifies any scope/camera/mount) |
| Scoring            | Plan Ahead only              | **Two modes** : Right Now (instant) + Plan Ahead (7-night)    |
| Twilight awareness | None                         | Sun altitude via `ephem`— scores for tonight if daytime          |
| Moon penalty       | Flat penalty                 | Enhanced penalty for low surface-brightness objects                 |
| Narrative          | Single LLM call              | Pinned to selected target with hard numbers injected                |
| Fallback           | Error message                | Rich context-aware fallback narrative                               |
| Target browse      | Type to search               | Category chips + browse without typing                              |

---

## Quick start

```powershell
# 1. Ollama (separate terminal)
ollama serve
ollama pull llama3.2       # or mistral, gemma3, llama3.1:8b

# 2. Python env
cd DeepSkyAgent
python -m venv venv
venv\Scripts\activate      # Linux/Mac: source venv/bin/activate
pip install -r requirements.txt

# 3. Config
copy .env.example .env     # Linux/Mac: cp .env.example .env

# 4. Run
python main.py
# → http://localhost:8000
```

---

## How it works

### Shared inputs (both modes)

* **Location** — type a city name or click 📡 to use GPS (reverse-geocoded via Nominatim)
* **Target** — browse by category or search by name/Messier number
* **Equipment** — choose a preset (Pro/Casual/Mobile) or describe your gear in plain English
* **Model** — auto-discovered from your local Ollama instance

### ⚡ Right Now tab

Scores all visible objects for your current location at this moment (or tonight's dark window if currently daytime). Returns a ranked list with score breakdowns, moon warnings, and an Ollama narrative focused on your selected target. Response in ~5–15 seconds.

### 📅 Plan Ahead tab

Runs the full LangGraph agent pipeline — streams progress in real time:

```
TargetAnalystAgent
  ├── Resolves target from live catalogue (RA/Dec, magnitude, angular size)
  └── Resolves equipment: preset lookup or LLM identification from free text

PlanBuilderAgent
  ├── Fetches 7-night hourly weather from Open-Meteo (free, no key)
  ├── Computes moon phase, rise/set, separation via ephem
  ├── Scores each night: cloud(40%) + seeing(30%) + transparency(20%) + altitude(10%) − moon penalty
  ├── Selects best + backup window
  └── Calls Ollama for ISO, sub-length, filter, dew risk

CriticAgent  ← the adversarial loop
  ├── Deterministic checks (no LLM — always correct):
  │   ├── Moon illumination above threshold?
  │   ├── Moon rises mid-session?
  │   ├── Sub-exposure exceeds mount tracking limit?
  │   ├── Integration > 85% of clear window?
  │   ├── Dew risk (temp − dewpoint < 4°)?
  │   └── Target below 30° altitude?
  ├── LLM critique on first loop
  └── Issues found → loops back to PlanBuilder (max 2 loops)
```

Progress collapses into a summary bar when done. Expand/collapse with  **Show log ▼** .

---

## Stack

| Layer                | Tech                                             |
| -------------------- | ------------------------------------------------ |
| API + static serving | FastAPI + uvicorn                                |
| Config               | Hydra (compose API — no CLI decorator needed)   |
| Agent orchestration  | LangGraph StateGraph                             |
| LLM                  | Local Ollama — free, private, no API key        |
| Weather              | Open-Meteo (free, no key)                        |
| Geocoding            | Open-Meteo geocoding + Nominatim reverse geocode |
| Moon & sun math      | ephem                                            |
| Live catalogue       | astroquery → Vizier/Simbad + JPL Horizons       |
| Map                  | Leaflet.js (CDN, free)                           |

---

## Project structure

```
DeepSkyAgent/
├── main.py                        ← single entry point (uvicorn)
├── requirements.txt
├── .env.example
├── conf/                          ← Hydra config
│   ├── config.yaml
│   ├── agent/default.yaml         ← critic thresholds, window days
│   ├── tools/default.yaml         ← API URLs, timeouts, cache TTL
│   └── api/default.yaml
├── backend/
│   ├── agents/
│   │   ├── llm.py                 ← Ollama factory + JSON parser
│   │   ├── equipment_resolver.py  ← LLM identifies scope/camera/mount
│   │   ├── target_analyst.py      ← Agent 1
│   │   ├── plan_builder.py        ← Agent 2
│   │   ├── critic.py              ← Agent 3 + adversarial loop
│   │   └── graph.py               ← LangGraph StateGraph wiring
│   ├── tools/
│   │   ├── weather.py             ← Open-Meteo 7-day hourly forecast
│   │   ├── moon.py                ← ephem: phase, rise/set, separation
│   │   ├── geocoder.py            ← city → lat/lon
│   │   ├── catalogue.py           ← live Vizier/ephem/JPL + fallback
│   │   └── horizons.py            ← altitude math, twilight, scoring helpers
│   ├── schemas/
│   │   ├── astro.py               ← all Pydantic models + equipment presets
│   │   └── state.py               ← LangGraph AstroState TypedDict
│   ├── config/loader.py           ← thread-safe Hydra compose
│   └── api/
│       ├── app.py                 ← FastAPI factory + static file serving
│       └── routes.py              ← all endpoints + SSE streaming
└── static/
    ├── index.html                 ← app shell
    ├── css/
    │   ├── base.css               ← tokens, reset, animations
    │   ├── layout.css             ← header, sidebar, main grid
    │   ├── components.css         ← cards, bars, night grid, plan output
    │   ├── map.css                ← Leaflet overrides
    │   └── tabs.css               ← tab bar + transitions
    └── js/
        ├── api.js                 ← all fetch + SSE calls
        ├── geocoder.js            ← location search + GPS + Leaflet map
        ├── equipment.js           ← preset chips + LLM resolver UI
        ├── catalogue.js           ← target search + category browse
        ├── scorer.js              ← Right Now tab rendering
        ├── planner.js             ← Plan Ahead SSE stream + rendering
        └── app.js                 ← init, tab switching, catalogue polling
```

---

## Hydra config overrides

```powershell
# Stricter moon threshold
python main.py agent.critic.moon_illumination_max_pct=40

# Plan 10 nights ahead
python main.py agent.planner.target_window_days=10

# Different port
python main.py api.port=9000
```

---

## API endpoints

| Method   | Path                         | Description                             |
| -------- | ---------------------------- | --------------------------------------- |
| `GET`  | `/`                        | Web UI                                  |
| `GET`  | `/api/health`              | Ollama + catalogue status               |
| `GET`  | `/api/locations/search?q=` | Geocode city name                       |
| `GET`  | `/api/ollama/models`       | List installed models                   |
| `GET`  | `/api/catalogue`           | Scored catalogue for location           |
| `GET`  | `/api/catalogue/status`    | Live catalogue build status             |
| `GET`  | `/api/catalogue/refresh`   | Trigger background catalogue rebuild    |
| `POST` | `/api/equipment/resolve`   | LLM equipment identification            |
| `POST` | `/api/rightnow`            | Right Now: instant scorer               |
| `POST` | `/api/plan/stream`         | Plan Ahead: SSE-streamed LangGraph plan |
| `GET`  | `/docs`                    | Swagger UI                              |

---

## Troubleshooting

| Issue                          | Fix                                                          |
| ------------------------------ | ------------------------------------------------------------ |
| Header shows 🔴 Ollama offline | Run `ollama serve`in a separate terminal                   |
| No models in dropdown          | Run `ollama pull llama3.2`                                 |
| Narrative timed out            | Normal for large models —`llama3.2`or `phi3`are fastest |
| Catalogue stuck on "building"  | Check internet; fallback (32 objects) always works offline   |
| Plan Ahead very slow           | Use `phi3`or `mistral`for faster reasoning               |

---

## License

MIT — see [LICENSE](https://claude.ai/chat/LICENSE)
