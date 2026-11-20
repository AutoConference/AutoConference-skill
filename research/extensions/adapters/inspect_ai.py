"""Inspect AI's native exact scorer on already-recorded Agent outputs.

https://inspect.aisi.org.uk/scorers.html ; no LLM judge or model API is called.
"""
from __future__ import annotations

import asyncio
import importlib.metadata
import json
import math
from pathlib import Path

from .common import read_json, safe_output


def probe() -> dict:
    versions = {}
    try:
        versions["inspect-ai"] = importlib.metadata.version("inspect-ai")
        from inspect_ai.scorer import match  # noqa: F401
        from inspect_ai.solver import TaskState  # noqa: F401
        return {"available": True, "reason": "Offline scoring available; supply recorded outputs and reference answers.", "versions": versions}
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return {"available": False, "reason": f"Inspect unavailable: {type(exc).__name__}: {exc}", "versions": versions}


def _records(data, tier):
    rows = data.get("records") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ValueError("records must contain 1..1000 predictions")
    ids = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each prediction must be an object")
        for key in ("id", "input", "output", "target"):
            if not isinstance(row.get(key), str) or len(row[key]) > 16384:
                raise ValueError(f"{key} must be a string no longer than 16384 characters")
        if not row["id"] or row["id"] in ids or not row["target"].strip():
            raise ValueError("record ids must be unique and reference targets nonempty")
        ids.add(row["id"])
        if tier >= 75 and (not isinstance(row.get("group"), str) or not row["group"] or len(row["group"]) > 128):
            raise ValueError("tiers 75/100 require a nonempty group per record")
        if tier == 100 and (not isinstance(row.get("baseline_output"), str) or len(row["baseline_output"]) > 16384):
            raise ValueError("tier 100 requires a baseline_output for every matched record")
        for key in ("tokens", "cost"):
            if key in row and (type(row[key]) not in (int, float) or not math.isfinite(row[key]) or row[key] < 0):
                raise ValueError(f"{key} must be finite and nonnegative when supplied")
    return rows


async def _score(rows, tier):
    from inspect_ai.model import ModelName, ModelOutput
    from inspect_ai.scorer import CORRECT, Target, match
    from inspect_ai.solver import TaskState

    scorer = match(location="exact", ignore_case=False)
    results = []
    for row in rows:
        state = TaskState(model=ModelName("mockllm/recorded"), sample_id=row["id"], epoch=1,
                          input=row["input"], messages=[], output=ModelOutput(completion=row["output"]))
        score = await scorer(state, Target(row["target"]))
        # The native scorer normalizes punctuation, so an empty completion can
        # otherwise match a punctuation-only target. A missing answer is a miss.
        item = {"id": row["id"], "correct": int(bool(row["output"].strip()) and score.value == CORRECT)}
        if tier >= 75:
            item["group"] = row["group"]
        if tier == 100:
            state.output = ModelOutput(completion=row["baseline_output"])
            baseline = await scorer(state, Target(row["target"]))
            item["baseline_correct"] = int(bool(row["baseline_output"].strip()) and baseline.value == CORRECT)
        results.append(item)
    return results


def run(request: dict, workspace: Path) -> dict:
    tier = request.get("tier")
    if type(tier) is not int or tier not in (25, 75, 100):
        raise ValueError("tier must be 25, 75 or 100")
    if request.get("params", {}) != {}:
        raise ValueError("Inspect replay scoring does not accept additional params")
    if not isinstance(request.get("inputs"), dict) or set(request["inputs"]) != {"data"}:
        raise ValueError("inputs must contain exactly data")
    rows = _records(read_json(workspace, request.get("inputs", {}).get("data")), tier)
    results = asyncio.run(_score(rows, tier))
    correct = sum(item["correct"] for item in results)
    metrics = {"records": len(rows), "exact_accuracy": correct / len(rows)}
    groups = {}
    if tier >= 75:
        for item in results:
            entry = groups.setdefault(item["group"], {"count": 0, "correct": 0})
            entry["count"] += 1
            entry["correct"] += item["correct"]
        for entry in groups.values():
            entry["accuracy"] = entry["correct"] / entry["count"]
        metrics["worst_group_accuracy"] = min(group["accuracy"] for group in groups.values())
    if tier == 100:
        baseline_correct = sum(item["baseline_correct"] for item in results)
        wins = sum(item["correct"] > item["baseline_correct"] for item in results)
        losses = sum(item["correct"] < item["baseline_correct"] for item in results)
        metrics.update(baseline_accuracy=baseline_correct / len(rows),
                       paired_accuracy_difference=(correct - baseline_correct) / len(rows),
                       paired_wins=wins, paired_losses=losses)
        for key in ("tokens", "cost"):
            if all(key in row for row in rows):
                metrics[f"total_{key}"] = sum(row[key] for row in rows)
    out = safe_output(workspace, request.get("_output_dir", "runs/extension-runs/inspect_ai") + "/inspect-scores.json")
    out.write_text(json.dumps({"scorer": "inspect_ai.scorer.match(location='exact', ignore_case=False)",
                              "tier": tier, "records": results, "groups": groups}, indent=2, allow_nan=False), encoding="utf-8")
    return {"metrics": metrics, "artifacts": [out.relative_to(workspace.resolve()).as_posix()], "notes": [
        "Offline replay scoring of supplied predictions; no live Agent was run and no model judge was consulted.",
        "Exact reference-answer matching is not a general research-quality or open-ended task evaluator.",
        "Matching uses Inspect's whitespace/punctuation normalization; empty answers are always counted as incorrect.",
        "Token and cost totals, when present, come from input records rather than measurements by this scoring run.",
    ]}
