#!/bin/bash

python scripts/ingest.py --purge-before 2026-11-01

sqlite3 data/processed/powpal.db "PRAGMA foreign_keys = ON; DELETE FROM track_points WHERE run_id NOT IN (SELECT id FROM runs);"

python scripts/ingest.py --dir data/raw/tracks/bo/
python scripts/ingest.py --dir data/raw/tracks/colin/
python scripts/ingest.py --dir data/raw/tracks/dom/
python scripts/ingest.py --dir data/raw/tracks/gabby/
python scripts/ingest.py --dir data/raw/tracks/klaudia/
python scripts/ingest.py --dir data/raw/tracks/theo/
python scripts/ingest.py --dir data/raw/tracks/theo_g/
python scripts/ingest.py --dir data/raw/tracks/wanying/