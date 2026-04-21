"""Timing utilities.

Run duration is calculated directly from start_time / end_time produced by
run_segmenter.segment_and_filter — no gate snapping needed at this stage.
Gate snapping (projecting endpoints onto the piste linestring) is left as a
future refinement once the basic leaderboard is working.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class TimedRun:
    piste_idx: int
    piste_id: str
    piste_difficulty: str
    piste_name: str | None
    start_time: datetime
    end_time: datetime
    duration_s: float
    source_file: str


def make_timed_run(row: dict, source_file: str) -> TimedRun:
    """Build a TimedRun from a run_stats row dict."""
    return TimedRun(
        piste_idx=int(row["piste_idx"]),
        piste_id=str(row["piste_id"]),
        piste_difficulty=str(row.get("piste_difficulty", "unknown")),
        piste_name=row.get("piste_name") or None,
        start_time=row["start_time"],
        end_time=row["end_time"],
        duration_s=float(row["duration_s"]),
        source_file=source_file,
    )
