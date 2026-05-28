"""Compare eval summaries across iteration steps and optional live logs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gametime.evaluate.live_analysis import analyze_live_logs


ITERATION_LABELS = {
    "summary_before_phase_features.json": "before_step1",
    "summary_before_multi_pace.json": "after_step1_phase",
    "summary_before_pregame_join.json": "after_step2_pace",
    "summary_before_2025_refresh.json": "after_step3_pregame",
}


def _phase_map(summary: dict[str, Any]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in summary.get("by_phase", []):
        phase = row["game_phase"]
        out[phase] = {
            "mae_total": float(row["mae_total"]),
            "bias_total": float(row["bias_total"]),
            "n": int(row["n"]),
        }
    return out


def build_iteration_report(
    eval_dir: str | Path,
    *,
    live_log_dir: str | Path | None = None,
    live_report_dir: str | Path | None = None,
    pregame_summary_path: str | Path | None = None,
) -> dict[str, Any]:
    eval_dir = Path(eval_dir)
    snapshots: list[dict[str, Any]] = []

    for path in sorted(eval_dir.glob("summary*.json")):
        if path.name == "summary.json":
            label = "current"
        else:
            label = ITERATION_LABELS.get(path.name, path.stem)
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if data.get("status") != "ok":
            continue
        overall = data.get("overall", {})
        snapshots.append(
            {
                "label": label,
                "file": path.name,
                "mae_total_final": overall.get("mae_total_final"),
                "bias_total": overall.get("bias_total"),
                "early_mae": _phase_map(data).get("early", {}).get("mae_total"),
                "early_bias": _phase_map(data).get("early", {}).get("bias_total"),
                "crunch_mae": _phase_map(data).get("crunch", {}).get("mae_total"),
            }
        )

    report: dict[str, Any] = {
        "status": "ok",
        "holdout_comparisons": snapshots,
        "north_star": {
            "metric": "early_phase_mae_and_bias",
            "targets": {"early_mae": 10.0, "early_bias_abs": 1.5, "overall_mae": 8.5},
        },
    }

    if pregame_summary_path and Path(pregame_summary_path).exists():
        pg = json.loads(Path(pregame_summary_path).read_text())
        test = pg.get("test_metrics", {})
        report["pregame_test"] = {
            "total_mae": test.get("total_mae"),
            "margin_mae": test.get("margin_mae"),
            "winner_accuracy": test.get("winner_accuracy"),
        }

    if live_log_dir is not None:
        live_out = Path(live_report_dir or eval_dir / "live_iteration")
        live = analyze_live_logs(live_log_dir, live_out)
        report["live_logs"] = live
        if live.get("status") == "ok":
            live_phases = {r["game_phase"]: r for r in live.get("by_phase", [])}
            early = live_phases.get("early", {})
            report["live_early"] = {
                "mae_total": early.get("mae_total"),
                "bias_total": early.get("bias_total"),
                "n": early.get("n"),
            }

    return report


def write_iteration_report(report_dir: str | Path, report: dict[str, Any]) -> Path:
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    out = report_dir / "iteration1_report.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    return out
