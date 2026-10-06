#!/usr/bin/env python3
"""kill-gate -- what step 13's kill-argument found, read from its file.

    research/scripts/check_kill_argument.py work/<cycle>/KILL_ARGUMENT.json
    research/scripts/check_kill_argument.py KILL_ARGUMENT.json --held-to .kill-argument/attack.json

Step 13 used to go on whenever the model's turn exited cleanly: a
KILL_ARGUMENT.json that said FAIL, or one that did not parse at all, went on to
submission unread (a tester's report, 2026-10-05). This reads the file and
computes the verdict itself, from the points, by the skill's own table
(skills/aris/kill-argument/SKILL.md, "Verdict mapping") -- never from the
verdict the file states, which the turn that wrote it could have graded in the
paper's favour:

    FAIL  a point still_unresolved at critical severity
    WARN  a point still_unresolved at major or minor severity; or none
          unresolved and one partially_answered at critical or major
    PASS  nothing unresolved, and anything partly answered only minor

--held-to judges the re-judging after the author's answer by the attack's
own points: every point the attack made is judged again, under the severity
the attack gave it. A point the re-judging left out counts as still standing;
a severity it lowered, or a point it added, is not taken.

Exit 0 PASS, 1 WARN, 2 FAIL, 3 the file cannot be used: missing, not JSON,
fewer than three points (the skill breaks its attack into three to seven), a
point with no claim or with a ruling or severity outside the skill's, no attack
memo, or a verdict the audit itself gave up on (BLOCKED, ERROR) or that this
pipeline does not take (NOT_APPLICABLE: every paper here is attacked).
"""
from __future__ import annotations

import argparse
import json
import sys

RULINGS = ("answered_by_current_text", "partially_answered", "still_unresolved")
SEVERITIES = ("critical", "major", "minor")
MIN_POINTS = 3


class Unusable(Exception):
    pass


def load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        raise Unusable(f"no {path}")
    except (OSError, ValueError) as e:
        raise Unusable(f"{path} is not JSON ({e})")
    if not isinstance(doc, dict):
        raise Unusable(f"{path} is not a JSON object")
    return doc


def points_of(doc: dict) -> list[dict]:
    details = doc.get("details") if isinstance(doc.get("details"), dict) else {}
    pts = details.get("decomposed_points", doc.get("decomposed_points"))
    if not isinstance(pts, list):
        raise Unusable("no details.decomposed_points list")
    out = []
    for i, p in enumerate(pts):
        if not isinstance(p, dict):
            raise Unusable(f"point {i + 1} is not an object")
        pid = str(p.get("id") or f"P_{i + 1}").strip()
        claim = str(p.get("attack_claim") or "").strip()
        ruling = str(p.get("verdict") or "").strip()
        severity = str(p.get("severity_if_unresolved") or "").strip().lower()
        if not claim:
            raise Unusable(f"{pid} has no attack_claim")
        if ruling not in RULINGS:
            raise Unusable(f"{pid}'s verdict is {ruling or 'missing'}, not one of {', '.join(RULINGS)}")
        if severity not in SEVERITIES:
            raise Unusable(f"{pid}'s severity_if_unresolved is {severity or 'missing'}, not one of {', '.join(SEVERITIES)}")
        out.append({"id": pid, "claim": claim, "ruling": ruling, "severity": severity,
                    "fix": str(p.get("recommended_fix") or "").strip()})
    if len({p["id"] for p in out}) != len(out):
        raise Unusable("two points share an id")
    return out


def usable(doc: dict, need_memo: bool = True, min_points: int = MIN_POINTS) -> list[dict]:
    stated = str(doc.get("verdict") or "").strip().upper()
    if stated in ("BLOCKED", "ERROR"):
        raise Unusable(f"the audit reports {stated} ({doc.get('reason_code') or 'no reason given'}): it did not complete")
    if stated == "NOT_APPLICABLE":
        raise Unusable("NOT_APPLICABLE is not a verdict here: this pipeline attacks every paper")
    pts = points_of(doc)
    if len(pts) < min_points:
        raise Unusable(f"{len(pts)} point(s); the skill breaks its attack into {MIN_POINTS} to 7")
    if need_memo:
        details = doc.get("details") if isinstance(doc.get("details"), dict) else {}
        memo = str(details.get("attack_memo", doc.get("attack_memo")) or "")
        if len(memo.split()) < 20:
            raise Unusable("no attack memo (details.attack_memo)")
    return pts


def verdict(pts: list[dict]) -> tuple[str, str]:
    unresolved = [p for p in pts if p["ruling"] == "still_unresolved"]
    partial = [p for p in pts if p["ruling"] == "partially_answered"]
    if any(p["severity"] == "critical" for p in unresolved):
        return "FAIL", "unresolved_critical"
    if unresolved:
        return "WARN", "unresolved_major_or_minor"
    if any(p["severity"] in ("critical", "major") for p in partial):
        return "WARN", "partial_critical_or_repeated_major"
    if partial:
        return "PASS", "defense_survives_with_minor_partial_only"
    return "PASS", "defense_survives"


def held_to(pts: list[dict], attack: list[dict]) -> tuple[list[dict], list[str]]:
    """The re-judged points, on the attack's own points and severities."""
    by_id = {p["id"]: p for p in pts}
    merged, notes = [], []
    for a in attack:
        p = by_id.get(a["id"])
        if p is None:
            notes.append(f"{a['id']} was not judged again: it still stands")
            merged.append({**a, "ruling": "still_unresolved"})
            continue
        if p["severity"] != a["severity"]:
            notes.append(f"{a['id']}: severity kept at the attack's {a['severity']} (the re-judging said {p['severity']})")
        merged.append({**a, "ruling": p["ruling"], "fix": p["fix"] or a["fix"]})
    extra = sorted(set(by_id) - {a["id"] for a in attack})
    if extra:
        notes.append(f"not the attack's points, so not counted: {', '.join(extra)}")
    return merged, notes


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="KILL_ARGUMENT.json")
    ap.add_argument("--held-to", help="the attack's own KILL_ARGUMENT.json, as step 13a wrote it")
    a = ap.parse_args()
    try:
        doc = load(a.file)
        notes: list[str] = []
        if a.held_to:
            attack = usable(load(a.held_to))
            # The re-judging's own count does not matter: the attack's points
            # are judged, and one it left out still stands.
            pts, notes = held_to(usable(doc, need_memo=False, min_points=1), attack)
        else:
            pts = usable(doc)
    except Unusable as e:
        print(f"kill-argument: cannot be used -- {e}")
        print("kill-argument: step 13 must leave KILL_ARGUMENT.json in the skill's schema, with "
              f"{MIN_POINTS} to 7 points under details.decomposed_points, each with id, attack_claim, "
              "verdict and severity_if_unresolved.")
        sys.exit(3)

    v, reason = verdict(pts)
    stated = str(doc.get("verdict") or "").strip().upper()
    counts = {r: sum(p["ruling"] == r for p in pts) for r in RULINGS}
    print(f"kill-argument: {v} ({reason}), computed from {len(pts)} points: "
          + ", ".join(f"{n} {r}" for r, n in counts.items()))
    if stated and stated != v:
        print(f"kill-argument: the file itself says {stated}; the points say {v}, and the points decide")
    for n in notes:
        print(f"kill-argument: {n}")
    for p in pts:
        if p["ruling"] == "answered_by_current_text":
            continue
        line = f"  {p['id']} {p['ruling']}, {p['severity']}: {p['claim'][:300]}"
        if p["fix"]:
            line += f"\n      fix: {p['fix'][:300]}"
        print(line)
    sys.exit({"PASS": 0, "WARN": 1, "FAIL": 2}[v])


if __name__ == "__main__":
    main()
