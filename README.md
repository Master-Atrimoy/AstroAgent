# AstroAgent v1 🔭

### Multi-Agent Astrophotography Planning System

---

## Quick Start

```bash
# 1. Install Ollama + pull a model
ollama pull llama3.1

# 2. Install Python deps
cd astroagent_v2
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Run
python main.py
# → http://localhost:8000
```

---

## How to use it

**Step 1 — Discover models**
Click `⟳` next to the model dropdown. AstroAgent queries your local Ollama instance and populates the dropdown with every installed model, sorted by recommended order. No model is hardcoded.

**Step 2 — Pick a target**
Type a Messier number or common name in the Target field. The autocomplete searches the built-in catalogue of 25+ DSO objects. Quick-access chips (M31, M42, M45…) are shown below the field.

**Step 3 — Resolve your location**
Type any city name. As you type, results are fetched live from the Open-Meteo geocoding API and displayed in a dropdown with coordinates. Click to select. You can also type `lat,lon` directly (e.g. `22.57,88.36`). The resolved coordinates are shown as a tag — click ✕ to change.

**Step 4 — Choose equipment**Three preset categories are available:

- **Pro** — dedicated astro cameras, eq_goto mounts (300s max sub)
- **Casual** — DSLR on goto or manual EQ mounts (60–300s max sub)
- **Mobile** — smartphone + adapter, binoculars (2–4s max sub)
- **Custom** — type your own equipment description

**Step 5 — Generate Plan**
Click Generate Plan. Three agents run in sequence. Progress streams to the screen in real time. The 7-night forecast appears on the right with cloud/moon/seeing scores.

---

## What the agents do

```
TargetAnalystAgent
  ├── Resolves target from DSO catalogue (RA/Dec, magnitude, size)
  ├── Parses equipment → EquipmentProfile (Pydantic validated)
  └── Computes FOV from sensor size + focal length

PlanBuilderAgent
  ├── Fetches 7-night weather from Open-Meteo
  ├── Computes hour-by-hour altitude schedule (astropy or pure math)
  ├── Scores each night: cloud(40%) + seeing(30%) + transparency(20%) + altitude(10%) − moon penalty
  ├── Selects best and backup window
  └── Asks LLM for: ISO, sub-length, filter, dew risk, reasoning (with timeout)

CriticAgent  ← the adversarial loop
  ├── Deterministic checks (no LLM, always correct):
  │   ├── Moon illumination above threshold?
  │   ├── Moon rises mid-session?
  │   ├── Sub-exposure exceeds mount's tracking limit?
  │   ├── Integration time > 85% of window duration?
  │   ├── Dew risk without heater on clear night?
  │   └── Target below 30° altitude?
  ├── LLM critique with slim payload + explicit timeout
  └── If issues found → loops back to PlanBuilder (max_critique_loops times)
```

---

## Configuration (Hydra)

All thresholds live in `conf/`. Override at runtime:

```bash
python main.py agent.critic.moon_illumination_max_pct=40
python main.py agent.planner.target_window_days=14
python main.py ollama.timeout=120
```

**`conf/agent/default.yaml`** key thresholds:

| Key                                  | Default | Meaning                                      |
| ------------------------------------ | ------- | -------------------------------------------- |
| `planner.min_altitude_deg`         | 25.0    | Reject nights where target never clears this |
| `planner.min_session_hours`        | 1.5     | Reject windows shorter than this             |
| `planner.target_window_days`       | 7       | Nights to score                              |
| `critic.moon_illumination_max_pct` | 60.0    | Flag if moon brighter                        |
| `critic.moon_separation_min_deg`   | 30.0    | Flag if moon closer to target                |
| `critic.dew_point_margin_deg`      | 4.0     | Flag if temp−dewpoint below this            |
| `critic.max_critique_loops`        | 2       | Max replanning cycles                        |

---

## API Endpoints

| Method | Path                               | Description                        |
| ------ | ---------------------------------- | ---------------------------------- |
| POST   | `/api/session`                   | Create session                     |
| GET    | `/api/session/{id}`              | Get session state                  |
| GET    | `/api/ollama/models?base_url=…` | Discover installed Ollama models   |
| GET    | `/api/locations/search?q=…`     | Location autocomplete (Open-Meteo) |
| GET    | `/api/targets`                   | DSO catalogue                      |
| GET    | `/api/equipment/presets`         | Equipment preset categories        |
| GET    | `/api/plan?…`                   | SSE streaming plan (EventSource)   |
| POST   | `/api/plan`                      | SSE streaming plan (POST body)     |
| GET    | `/api/docs`                      | Swagger UI                         |

---

## Key architectural decisions

**Lat/lon resolved before SSE starts** — the frontend resolves coordinates via the `/api/locations/search` dropdown, then sends `lat` and `lon` as explicit floats in the plan request. Earlier versions geocoded inside the SSE handler, making error handling impossible mid-stream.

**Ollama timeout is explicit and end-to-end** — `ollama_timeout` flows from the UI dropdown → request body → `run_agent()` → every `call_llm()` call. LLM calls that hang are terminated cleanly.

**All heavy imports inside function bodies** — `langchain`, `langgraph`, `omegaconf`, `astropy`, `ephem` are all imported inside the functions that use them, not at module top-level. The FastAPI app starts instantly even if some packages are slow to import.

**Equipment presets bypass the LLM entirely** — when a user picks a preset, its key (e.g. `pro_sct8`) is sent directly. `TargetAnalystAgent` looks it up in `EQUIPMENT_PRESETS` dict and constructs `EquipmentProfile` without any LLM call. LLM is only used for free-text custom equipment descriptions.

**Pydantic validates every LLM output** — `parse_json_output()` strips markdown fences, extracts the JSON object, and validates against the schema. On validation failure, the fallback path runs — the plan still completes, just without LLM-generated narrative fields.

---

## Project structure

```
astroagent_v2/
├── main.py                         ← entry point
├── requirements.txt
├── conf/
│   ├── config.yaml                 ← root Hydra config
│   ├── agent/default.yaml          ← planner + critic thresholds
│   ├── tools/default.yaml          ← API URLs + timeouts
│   └── api/default.yaml            ← server config
├── backend/
│   ├── agents/
│   │   ├── llm.py                  ← OllamaLLM factory + JSON parser
│   │   ├── target_analyst.py       ← Agent 1 + equipment presets
│   │   ├── plan_builder.py         ← Agent 2 + window scoring
│   │   ├── critic.py               ← Agent 3 + deterministic checks
│   │   └── graph.py                ← LangGraph StateGraph
│   ├── tools/
│   │   ├── horizons.py             ← DSO catalogue + altitude math
│   │   ├── weather.py              ← Open-Meteo weather
│   │   ├── moon.py                 ← Moon phase/separation (ephem/math)
│   │   └── geocoder.py             ← Location search + geocoding
│   ├── schemas/
│   │   ├── astro.py                ← All Pydantic domain schemas
│   │   └── state.py                ← AstroState TypedDict
│   ├── config/loader.py            ← Hydra Compose API (thread-safe)
│   └── api/
│       ├── app.py                  ← FastAPI factory
│       └── routes.py               ← All endpoints + SSE streaming
└── frontend/
    ├── templates/index.html        ← Single-page app
    └── static/
        ├── css/main.css            ← Dark observatory theme
        └── js/app.js               ← Location search, model dropdown,
                                       equipment presets, SSE client
```
