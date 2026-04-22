# Powpal — CLAUDE.md

## What This Project Is

A social ski tracking app that fills the gap between Strava/Slopes (which track ski days generally)
and a proper piste-level leaderboard system. Think Strava segments, but for named ski runs at a
resort — with a Waze-style community layer on top.

**The core differentiator:** segment timing on specific named pistes, shared leaderboards in
global/friends/personal contexts, and community-validated map pins (conditions, hazards, photos).

**Current MVP goal:** Accept GPX exports from friends (Slopes app), match them to piste geometry
for a single resort, produce a shared leaderboard map served via GitHub Pages. Friends-first closed
MVP — no public auth, no upload UI. Owner (developer) ingests files manually via CLI.

---

## Current State

- [x] Piste matching logic prototype in a Jupyter notebook
- [x] Basic Folium map served via GitHub Pages
- [x] Conda environment (`powpal`) with core dependencies
- [ ] Refactor notebook into clean Python modules (Phase 1)
- [ ] CLI ingest script (Phase 2)
- [ ] Leaderboard map renderer (Phase 3)
- [ ] Deploy leaderboard HTML to GitHub Pages (Phase 4)
- [ ] FastAPI backend (future — not MVP)
- [ ] Next.js + MapLibre frontend (future — not MVP)

---

## Target Resort

**Vichères-Liddes, Switzerland**
- Piste line data already available as GeoJSON
- This is the sole target resort for MVP — do not generalise prematurely

---

## Tech Stack

### Current environment (conda: `powpal`)
```
geopandas, numpy, shapely, ipykernel, gpxpy, seaborn, folium, pytest
```
- `pyproj` is available as a GeoPandas dependency (not listed explicitly but present)
- Add `fastapi`, `uvicorn`, `sqlalchemy` when backend phase begins

### MVP stack (no backend server needed yet)
- **Processing:** Python scripts, not a web server
- **Database:** SQLite (local, via Python's built-in `sqlite3` or SQLAlchemy)
- **Map output:** Folium → self-contained HTML file
- **Hosting:** GitHub Pages (commit generated HTML, push, done)

### Future stack (post-MVP)
- **Backend:** FastAPI + SQLAlchemy + PostgreSQL/PostGIS
- **Frontend:** Next.js + MapLibre GL JS + Tailwind
- **Hosting:** Railway/Render (API) + Vercel (frontend)

---

## Repository Structure (target)

```
powpal/
├── CLAUDE.md
├── README.md
├── environment.yml
├── users.json                       # Manual user → display name + colour mapping
├── data/
│   ├── raw/
│   │   ├── pistes/
│   │   │   └── vicheres_liddes.geojson   # Piste line data for target resort
│   │   └── tracks/                       # Friends' raw GPX exports (gitignored)
│   │       └── *.gpx
│   ├── interim/                          # Intermediate pipeline outputs (gitignored)
│   │   └── *.parquet                     # Enriched/segmented trackpoints
│   └── processed/
│       ├── powpal.db                     # SQLite leaderboard database (gitignored)
│       └── index.html                    # Generated map — committed for GitHub Pages
├── backend/                              # Future: FastAPI app (not MVP)
│   └── .gitkeep
├── frontend/                             # Future: Next.js app (not MVP)
│   └── .gitkeep
├── notebooks/
│   └── piste_matching_v1.ipynb           # Original R&D notebook — keep for reference
├── scripts/
│   ├── ingest.py                         # CLI: python ingest.py --user alice file.gpx
│   └── render_map.py                     # Reads DB, outputs data/processed/index.html
├── powpal/                               # Main Python package
│   ├── __init__.py
│   ├── gpx_parser.py                     # Phase 1: parse + enrich GPX trackpoints
│   ├── run_segmenter.py                  # Phase 1: filter lifts, split into runs
│   ├── piste_matcher.py                  # Phase 1: match runs to piste geometries
│   ├── timing.py                         # Phase 1: gate snapping, calculate timings
│   └── leaderboard.py                    # Phase 3: aggregate best times, rankings
└── tests/
    ├── test_gpx_parser.py
    ├── test_run_segmenter.py
    ├── test_piste_matcher.py
    └── fixtures/
        └── sample_track.gpx              # Short real GPX clip for tests
```

---

## GPX Ingestion (`powpal/gpx_parser.py`)

### Source data
- All friends use the **Slopes** app
- Export path: Logbook → select day → Share → Export GPX
- Slopes exports include `lat`, `lon`, `ele`, and `<time>` (UTC) at ~1 sample/second
- Confirm friends export **per day** (not full season) to avoid large mixed files

### Core data structure
```python
@dataclass
class TrackPoint:
    lat: float
    lon: float
    elevation: float
    timestamp: datetime  # timezone-aware UTC from gpxpy
```

### Enrichment (added to each point after parsing)
- `speed_ms`: horizontal speed in m/s (requires projection to EPSG:3857 first)
- `ele_delta`: elevation change from previous point
- `dt`: seconds since previous point
- Project to EPSG:3857 (Web Mercator) for all distance calculations — never use degrees

### Edge cases to handle
| Issue | How to handle |
|---|---|
| `pt.time is None` | Drop the point |
| Duplicate timestamps (`dt == 0`) | Set `dt = 0.001` to avoid division by zero |
| `pt.elevation is None` | Interpolate from neighbours or drop |
| GPS outage in lifts | Gap in track or straight-line junk — both are useful lift signals |
| Mixed tz-aware/naive datetimes | gpxpy returns aware UTC; be consistent throughout |
| Long stationary periods (lunch etc.) | Handled by segmenter, not parser |

### Sanity check on ingest
Always run `validate_gpx_stats()` on each file before processing:
- Flags corrupt exports (zero elevation range, impossibly high speeds)
- Reports: n_points, duration_hours, elevation_range_m, max_speed_kmh, mean_speed_kmh

---

## Processing Pipeline

```
GPX file + username
  → gpx_parser.py       — parse trackpoints, enrich with speed/ele_delta/dt
  → run_segmenter.py    — mask lift segments, split into individual descents
  → piste_matcher.py    — match each descent to a named piste (STRtree spatial index)
  → timing.py           — snap start/end to piste gates, calculate duration
  → SQLite DB           — store as Run records, keyed to user + piste
```

### Run segmentation logic (run_segmenter.py)
Primary signals for lift detection:
- **Ascending elevation** (`ele_delta > 0` sustained over N points)
- **Slow horizontal speed** (< ~2 m/s)
- **GPS gap** (no points for > 30 seconds — enclosed lifts kill GPS)

Segment boundaries:
- Lift → descent transition = start of a run
- Long stationary period (> ~60s at near-zero speed) = potential segment boundary
- End of file = end of last run

### Piste matching logic (piste_matcher.py)
- Load piste GeoJSON → GeoDataFrame (GeoPandas)
- Build `STRtree` spatial index over piste geometries for fast candidate lookup
- For each descent segment: find candidate pistes within buffer distance
- Score candidates by Hausdorff distance or buffer overlap percentage
- Accept match if score exceeds configurable threshold
- Unmatched segments = off-piste (store separately, don't add to leaderboard)

### Timing logic (timing.py)
- Snap run start/end points to nearest point on matched piste geometry
- Calculate `duration_seconds = end_timestamp - start_timestamp`
- Store: `(user_id, piste_id, date, duration_seconds, source_file)`

---

## Database Schema (SQLite)

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE,           -- e.g. 'alice'
    display_name TEXT,          -- e.g. 'Alice'
    colour TEXT                 -- hex colour for map, e.g. '#E63946'
);

CREATE TABLE pistes (
    id INTEGER PRIMARY KEY,
    resort TEXT,                -- 'vicheres-liddes'
    name TEXT,                  -- piste name from GeoJSON
    difficulty TEXT,            -- 'blue' | 'red' | 'black'
    geometry TEXT               -- WKT linestring
);

CREATE TABLE runs (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    piste_id INTEGER REFERENCES pistes(id),
    run_date DATE,
    duration_seconds REAL,
    source_file TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Leaderboard query: best time per user per piste
-- SELECT user_id, piste_id, MIN(duration_seconds) as best_time
-- FROM runs GROUP BY user_id, piste_id
```

---

## User Identity (MVP)

No auth. No accounts. Owner assigns users manually.

**`users.json`** — maintained by hand:
```json
[
  {"slug": "alice", "display_name": "Alice", "colour": "#E63946"},
  {"slug": "bob",   "display_name": "Bob",   "colour": "#457B9D"},
  {"slug": "charlie", "display_name": "Charlie", "colour": "#2A9D8F"}
]
```

**CLI usage:**
```bash
python scripts/ingest.py --user alice data/raw/tracks/alice_vicheres_jan14.gpx
python scripts/ingest.py --user bob   data/raw/tracks/bob_vicheres_jan14.gpx
```

---

## Map Output

- Generated by `scripts/render_map.py` using **Folium** (already in environment)
- Output: `data/processed/index.html` — self-contained, no server needed
- Map layers:
  1. Base map tiles (OpenStreetMap or similar)
  2. Piste lines coloured by difficulty (blue/red/black)
  3. Leaderboard popup on piste click: ranked list of best times with user colours
- Commit `web/index.html` to repo → GitHub Pages serves it automatically

---

## Development Principles

1. **Algorithm correctness over feature breadth.** Piste matching and timing must feel right to a
   skier. Cut features before cutting accuracy.
2. **One resort only (for now).** All code targets Vichères-Liddes. No premature generalisation.
3. **Notebooks are for R&D.** Proven logic goes into `powpal/` modules with pytest tests.
4. **No server for MVP.** Everything runs as local Python scripts. FastAPI comes later.
5. **Keep geospatial logic in Python.** Owner has an earth observation background — lean into
   GeoPandas/Shapely, don't push spatial logic into SQL or JavaScript.
6. **Test with real data early.** Use a short real GPX clip as a test fixture. Synthetic data
   misses the noise patterns that matter.

---

## Running Locally

```bash
# Activate environment
conda activate powpal

# Ingest a GPX file
python scripts/ingest.py --user alice data/raw/tracks/alice_vicheres_jan14.gpx

# Regenerate the map
python scripts/render_map.py --output data/processed/index.html

# Run tests
pytest tests/

# Deploy: commit generated map and push
git add data/processed/index.html && git commit -m "update leaderboard map" && git push
```

---

## Key External Resources

- [gpxpy docs](https://github.com/tkrajina/gpxpy) — GPX parsing
- [Shapely docs](https://shapely.readthedocs.io/) — geometry operations
- [GeoPandas docs](https://geopandas.org/) — spatial dataframes, STRtree index
- [Folium docs](https://python-visualization.github.io/folium/) — map rendering
- [OSM piste tagging](https://wiki.openstreetmap.org/wiki/Piste_Maps) — piste GeoJSON conventions
- [EPSG:3857](https://epsg.io/3857) — Web Mercator, use for all distance calculations
- [EPSG:4326](https://epsg.io/4326) — WGS84, what GPX files use natively

---

## Open Questions / Future Decisions

- [ ] Does the existing piste GeoJSON have `name` and `difficulty` attributes? If not, needs manual
      labelling before piste matching produces useful leaderboard entries
- [ ] What does the current GitHub Pages map show? (Useful starting point for the renderer)
- [ ] Mapbox vs MapLibre when moving to Next.js frontend (MapLibre = free/open, Mapbox = billed)
- [ ] SQLite → Postgres migration: use SQLAlchemy from day one to make this painless later
- [ ] How to handle off-piste runs — store but exclude from leaderboard, or ignore entirely?
