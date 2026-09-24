"""aris_audit -- emit audit verdicts in ARIS's own schema.

Not a new gate. ARIS already defines the contract
(`shared-references/assurance-contract.md`) and already ships the enforcer
(`tools/verify_paper_audits.sh`, which blocks a submission-level Final Report on
a non-zero exit). It also already anticipates the case we are in: its
`model_family()` maps a `reviewer_model` of `deterministic` / `deterministic:*`
to the family `deterministic`, and `run_state.py` accepts a phase when *either*
a cross-model reviewer *or* a deterministic verifier signs off.

So this module exists only to write our deterministic verdicts in the shape that
enforcer already reads. Cross-model review needs Codex MCP, which needs node,
which this container does not have — see `.aris/env-ledger.md`.

    from aris_audit import emit
    emit(paper_dir, "paper-claim-audit", "PASS", "numbers_reproduce",
         "…", inputs=[...], reasoning="…")
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time

VERDICTS = ("PASS", "WARN", "FAIL", "NOT_APPLICABLE", "BLOCKED", "ERROR")

# audit_skill -> the filename verify_paper_audits.sh looks for
ARTIFACT = {
    "paper-claim-audit": "PAPER_CLAIM_AUDIT.json",
    "citation-audit": "CITATION_AUDIT.json",
    "kill-argument": "KILL_ARGUMENT.json",
    "proof-checker": "PROOF_AUDIT.json",
    "experiment-audit": "EXPERIMENT_AUDIT.json",
    "paper-shape": "PAPER_SHAPE_AUDIT.json",
}


def _sha(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return "sha256:" + hashlib.sha256(f.read()).hexdigest()[:32]
    except OSError:
        return "sha256:unreadable"


def emit(paper_dir: str, audit_skill: str, verdict: str, reason_code: str,
         summary: str, inputs=None, reasoning: str = "", extra=None,
         verifier: str = "repro-gate") -> str:
    """Write <paper_dir>/<ARTIFACT[audit_skill]> and return its path."""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}, got {verdict!r}")
    name = ARTIFACT.get(audit_skill)
    if not name:
        raise ValueError(f"unknown audit_skill {audit_skill!r}")

    trace_dir = os.path.join(paper_dir, ".aris", "traces", audit_skill)
    os.makedirs(trace_dir, exist_ok=True)
    doc = {
        "audit_skill": audit_skill,
        "verdict": verdict,
        "reason_code": reason_code,
        "summary": summary,
        "audited_input_hashes": {os.path.relpath(p, paper_dir): _sha(p)
                                 for p in (inputs or []) if os.path.exists(p)},
        "trace_path": os.path.relpath(trace_dir, paper_dir),
        # ARIS's model_family() recognises this prefix as the `deterministic`
        # family, so the verdict is not mistaken for same-family self-review.
        "reviewer_model": f"deterministic:{verifier}",
        "reviewer_reasoning": reasoning or summary,
        "review_independence": "deterministic",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    if extra:
        doc["details"] = extra
    out = os.path.join(paper_dir, name)
    with open(out + ".tmp", "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    os.replace(out + ".tmp", out)
    return out


def resolve_tool(name: str) -> str | None:
    """ARIS helper resolution, per integration-contract.md §2:
    .aris/tools/ -> tools/ -> $ARIS_REPO/tools/."""
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for cand in (os.path.join(here, "skills", "aris", "tools", name),
                 os.path.join(here, ".aris", "tools", name),
                 os.path.join(os.environ.get("ARIS_REPO", ""), "tools", name)):
        if cand and os.path.exists(cand):
            return cand
    return None


def evidence_check(root: str, claims: list) -> dict:
    """Run ARIS's own deterministic evidence pre-check.

    Each claim is {"value": <the number as it appears in the paper>,
                   "source": <results file, relative to root>}.
    Returns its report, or a BLOCKED-shaped dict if the helper is missing.
    """
    tool = resolve_tool("evidence_check.py")
    if not tool:
        return {"available": False, "results": [],
                "note": "evidence_check.py not found on the ARIS helper chain"}
    batch = os.path.join(root, ".aris", "evidence-claims.json")
    os.makedirs(os.path.dirname(batch), exist_ok=True)
    with open(batch, "w", encoding="utf-8") as f:
        json.dump(claims, f)
    # ARIS's checker rereads the results for every claim -- about 90 s per claim
    # on a 4 MB results tree -- so a fixed ten minutes failed a paper with sixteen
    # numbers to check by crashing. The budget scales with the claims, and running
    # out of it is a verdict ("could not check"), not a traceback.
    budget = max(600, 150 * len(claims))
    try:
        r = subprocess.run([sys.executable, tool, root, "--batch", batch],
                           capture_output=True, text=True, timeout=budget)
    except subprocess.TimeoutExpired:
        return {"available": True, "exit": None,
                "results": [dict(c, status="value_not_found",
                                 detail=f"evidence_check.py did not finish in {budget}s")
                            for c in claims]}
    try:
        rep = json.loads(r.stdout)
    except ValueError:
        return {"available": True, "results": [], "error": r.stderr[-500:]}
    rep["available"] = True
    rep["exit"] = r.returncode
    return rep
