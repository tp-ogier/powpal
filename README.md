# PowPal

A shared leaderboard for ski runs at Vichères-Liddes. Friends export their GPS tracks from the Slopes app, you ingest them with a single command, and a clickable map shows everyone's best times per piste.

---

## How it works

1. Friends export a GPX file from the Slopes app (Logbook → select day → Share → Export GPX)
2. You drop the file in `data/raw/tracks/<user>/` and run the ingest script
3. The pipeline matches every descent to a named piste, runs quality filters, and records the time
4. You run the render script to regenerate the leaderboard map
5. Commit and push — GitHub Pages serves the updated map automatically

---

## Setup

Clone the repo and create the conda environment:

```bash
git clone <repo-url>
cd powpal
conda env create -f environment.yml
conda activate powpal
pip install -e .
```

---

## Adding a new friend

Open `users.json` and add an entry:

```json
[
  {"slug": "theo",  "display_name": "Theo",  "colour": "#E63946"},
  {"slug": "colin", "display_name": "Colin", "colour": "#457B9D"},
  {"slug": "dom",   "display_name": "Dom",   "colour": "#2A9D8F"},
  {"slug": "alice", "display_name": "Alice", "colour": "#F4A261"}
]
```

- **slug** — used on the command line (`--user alice`), lowercase, no spaces
- **display_name** — shown on the leaderboard map
- **colour** — hex colour for their leaderboard entry

`data/raw/tracks/` is gitignored, so raw GPX files are never committed.

---

## Ingesting GPX files

Ingest a single file:

```bash
conda activate powpal
python scripts/ingest.py --user alice data/raw/tracks/alice/alice_vicheres_feb12.gpx
```

Or ingest an entire directory (user slug is inferred from the folder name):

```bash
python scripts/ingest.py --dir data/raw/tracks/alice/

# override the inferred user slug
python scripts/ingest.py --user alice --dir data/raw/tracks/alice/
```

The script prints a summary as it runs:

```
Parsing alice_vicheres_feb12.gpx...
  {'n_points': 2341, 'duration_hours': 6.1, 'elevation_range_m': 612.4, ...}
  Assigning nearest piste to each point...
  Segmenting and filtering runs...
  Found 38 valid runs, 12 rejected
  Stored: La Combette — 187s (312 pts)
  Stored: blue piste — 143s (201 pts)
  ...
Done. Ingested 1 file(s) for user 'alice'.
```

**Do not ingest the same file twice** — there is no duplicate check and it will add extra rows to the database.

### How runs are detected

The pipeline:

1. Parses the GPX and validates the track stats
2. Assigns every GPS point to its nearest piste using a spatial join
3. Splits the track into candidate runs: a new run starts when there is a time gap of more than 3 minutes or the nearest piste changes
4. Filters out non-runs using four checks (all must pass):
   - More than 10 GPS points
   - At least 25 m of net elevation drop
   - Fewer than 5 points more than 70 m from the matched piste
   - At least one point within 40 m of each end of the piste linestring (i.e. the run covers the full piste)

Runs that fail any filter are saved to the `rejected_runs` table with the reason recorded, rather than discarded silently. This is useful for debugging mismatches.

### Deleting old data

To remove runs before a given date (e.g. data from a previous season):

```bash
python scripts/ingest.py --purge-before 2025-09-01
```

You will be shown a breakdown of what will be deleted and asked to confirm. All GPS track points associated with the deleted runs are removed automatically.

---

## Regenerating the map

```bash
python scripts/render_map.py
```

This reads the database and writes `docs/index.html`. Open that file directly in a browser to preview it. The file is self-contained — no server needed.

### Map features

- **Piste lines** coloured by difficulty — click any line for a popup showing the top 5 best times on that piste
- **Leaderboard panel** — three tabs comparing everyone's stats for the selected date range:
  - **Days** — total ski days recorded
  - **Runs** — total number of runs recorded
  - **Medals** — Olympic-style gold / silver / bronze count (fastest time on each piste)
- **Date slider** — filter all data to a specific date range; the scale is proportional to the real calendar and ski days with data are marked with ticks
- **Centre button** (🎯) — recentres the map on the resort
- **Mobile layout** — on small screens the leaderboard and date filter collapse into a bottom sheet, accessible via a tab bar at the bottom of the screen

Piste colours:

| Colour | Difficulty |
|--------|------------|
| Blue   | Easy       |
| Red    | Intermediate |
| Black  | Advanced   |

---

## Exploring data in QGIS

To export the full database to a GeoPackage for inspection in QGIS:

```bash
python scripts/export_qgis.py
# writes to data/processed/powpal_qgis.gpkg

python scripts/export_qgis.py --output ~/Desktop/ski.gpkg
```

The GeoPackage contains five layers:

| Layer | Geometry | Contents |
|-------|----------|----------|
| `pistes` | LineString | Piste geometries from the source GeoJSON |
| `runs` | LineString | One line per valid run, with user, piste, duration, and date |
| `track_points` | Point | Individual GPS points for every valid run |
| `rejected_runs` | LineString | Runs that failed a quality filter, with `filter_reason` column |
| `rejected_track_points` | Point | GPS points for rejected runs |

The `filter_reason` values are:

| Value | Meaning |
|-------|---------|
| `too_few_points` | Fewer than 10 GPS points |
| `insufficient_elevation_drop` | Less than 25 m net elevation drop |
| `too_many_far_points` | 5 or more points more than 70 m from the piste |
| `endpoint_not_reached` | Track doesn't reach within 40 m of both ends of the piste |

In QGIS: Layer → Add Layer → Add Vector Layer → select the `.gpkg` file.

---

## Deploying to GitHub Pages

Once you are happy with the map:

```bash
git add docs/index.html
git commit -m "update leaderboard map"
git push
```

GitHub Pages serves `docs/index.html` from the `docs/` folder on the `main` branch. No server, no build step. Check Settings → Pages in the repo to confirm the source is configured correctly.

The database (`data/processed/powpal.db`) is gitignored and stays local.

---

## Running the tests

```bash
conda activate powpal
pytest tests/
```

Tests use the real GPX file in `tests/fixtures/` and the real piste GeoJSON, so they catch genuine matching issues rather than synthetic edge cases.

---

## Project structure

```
powpal/
├── users.json                 # Friend list — edit this to add people
├── data/
│   ├── raw/
│   │   ├── pistes/
│   │   │   └── vicheres_liddes.geojson   # Piste geometry (committed)
│   │   └── tracks/                       # GPX exports from friends (gitignored)
│   │       └── <user>/
│   │           └── *.gpx
│   └── processed/
│       ├── powpal.db                     # SQLite leaderboard database (gitignored)
│       └── powpal_qgis.gpkg              # QGIS export (gitignored)
├── docs/
│   └── index.html                        # Generated map (committed, served by GitHub Pages)
├── powpal/                               # Python package
│   ├── gpx_parser.py                     # Parse + validate GPX files
│   ├── piste_matcher.py                  # Spatial join: point → nearest piste
│   ├── run_segmenter.py                  # Split track into runs, apply quality filters
│   ├── timing.py                         # Run timing data structures
│   └── leaderboard.py                    # Best-time queries and season meta-stats
├── scripts/
│   ├── ingest.py                         # CLI ingest pipeline
│   ├── render_map.py                     # Map renderer → docs/index.html
│   └── export_qgis.py                    # Export DB to GeoPackage for QGIS
└── tests/
    └── fixtures/
        └── Slopes_A_day_snowboarding_at_Vichères_Liddes.gpx
```
