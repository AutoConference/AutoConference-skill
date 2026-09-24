#!/usr/bin/env python3
"""feasible -- the gate that stops the agent wasting a submission window.

The only thing in this repo that neither ARIS nor CCFA-Skills provides. Both
assume a normal GPU box; this container has 2 CPU cores and an 8 GiB RAM cap,
which rules out most of what a paper will suggest. So before any code gets
written, an experiment plan is scored against the *measured* numbers in
machine.json and told GO or NO-GO.

    research/scripts/plan_feasibility.py work/<slug>/refine-logs/EXPERIMENT_PLAN.md

Writes FEASIBILITY.json next to the plan. Exit 0 = GO, 3 = NO-GO, 1 = broken.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # agent-skills/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verdict as aris_audit  # noqa: E402
MODEL = os.environ.get("AC_MODEL", "claude-sonnet-5")

PROMPT = """Read {plan}, then read {bot}/pipeline/env-ledger.md and {bot}/pipeline/machine.example.json.

You are the feasibility gate for a research agent. It is about to spend a whole
submission window on this plan. Your job is to say whether the plan can actually
produce real numbers on THIS machine, judged against the MEASURED values in
machine.json -- not against what a normal GPU box could do.

Write {out} and nothing else:

{{"verdict": "GO" or "NO-GO",
  "reason": "at least 80 characters, quoting a specific number from the env ledger or machine.json and showing the arithmetic",
  "est_wallclock_hours": number,
  "blocking_constraint": "which hard_limit it hits, or null",
  "required_changes": ["concrete edits that would make a NO-GO plan feasible, or [] if GO"],
  "risks": ["things likely to bite even though the verdict is GO"]}}

The numbers that decide most cases:
  * A 7B model in bf16 peaks host RSS at 7.23 GiB against an 8 GiB cgroup cap.
    Anything larger is NO-GO. Two models resident at once is NO-GO.
  * Any training or fine-tuning above roughly 1B is NO-GO.
  * 2 CPU cores: corpus-scale preprocessing is NO-GO. So is anything that wants
    a process pool for speed.
  * Batched generation is 3003.8 tok/s at batch 64; single-stream is 45.6.
    Derive the hours from the batched figure and show the division in `reason`.
  * Target under 6 hours, so there is room to rerun the sweep after the pilot
    finds bugs. A plan with no slack is a plan that ships whatever the first
    buggy run produced.
  * vLLM is not installed and does not fit comfortably here; assume transformers.

Watch for the failure that is easy to miss: something that fits in GPU memory
but accumulates host-side tensors. Logging per-token logits over a 150k vocab
is the usual example -- the model alone leaves under 1 GiB of headroom, so that
forces batch=1, which costs a 66x slowdown and blows the budget.

If it is NO-GO, `required_changes` is the useful part: say what smaller version
of the same question WOULD run here. A gate that only rejects is half a gate."""


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: feasible <path-to-experiment-plan.md>")
    plan = os.path.abspath(sys.argv[1])
    if not os.path.exists(plan):
        sys.exit(f"feasible: no plan at {plan}")
    out = os.path.join(os.path.dirname(plan), "FEASIBILITY.json")

    def validate(o):
        p = []
        if o.get("verdict") not in ("GO", "NO-GO"):
            p.append(f"verdict must be exactly 'GO' or 'NO-GO', got {o.get('verdict')!r}")
        if not isinstance(o.get("reason"), str) or len(o.get("reason", "")) < 80:
            p.append("reason must be >=80 chars and cite a number from machine.json")
        if not isinstance(o.get("est_wallclock_hours"), (int, float)):
            p.append("est_wallclock_hours must be a number")
        for k in ("required_changes", "risks"):
            if not isinstance(o.get(k), list):
                p.append(f"{k} must be a list")
        if o.get("verdict") == "NO-GO" and not o.get("required_changes"):
            p.append("a NO-GO must say what smaller version would run here")
        return p

    err = None
    for attempt in range(1, 4):
        prompt = PROMPT.format(plan=plan, out=out, bot=ROOT)
        if err:
            prompt += f"\n\n---\nYOUR PREVIOUS ATTEMPT WAS REJECTED:\n{err}\nFix exactly that."
        print(f"[feasible] attempt {attempt}/3 (model={MODEL})", flush=True)
        if os.path.exists(out):
            os.remove(out)
        r = subprocess.run(["claude", "-p", "--model", MODEL,
                            "--permission-mode", "bypassPermissions", prompt],
                           cwd=BOT, capture_output=True, text=True, timeout=1800)
        try:
            with open(out, encoding="utf-8") as f:
                obj = json.load(f)
        except (OSError, ValueError):
            err = f"no valid JSON at {out}. Output tail:\n{(r.stdout or '')[-800:]}"
            continue
        problems = validate(obj)
        if problems:
            err = "- " + "\n- ".join(problems)
            continue

        print(json.dumps(obj, indent=2, ensure_ascii=False))

        # Register the verdict where ARIS's own enforcer reads it. This is its
        # audit layer 1 (`EXPERIMENT_AUDIT.json`); a NO-GO is a FAIL, which
        # blocks a submission-level Final Report via verify_paper_audits.sh.
        go = obj["verdict"] == "GO"
        aris_audit.emit(
            os.path.dirname(plan), "experiment-audit",
            "PASS" if go else "FAIL",
            "fits_resource_tier" if go else "exceeds_resource_tier",
            f"{obj['verdict']}: {obj['reason'][:400]}",
            inputs=[plan, os.path.join(ROOT, "pipeline", "machine.example.json"),
                    os.path.join(ROOT, "pipeline", "env-ledger.md")],
            reasoning=("Deterministic in its inputs: the plan is scored against the "
                       "measured tier in .aris/env-ledger.md (cpus 2, mem_gib 8, "
                       "gpus 1) rather than an assumed GPU box."),
            extra=obj, verifier="feasible")

        if go:
            print(f"\n[feasible] GO — estimated {obj['est_wallclock_hours']}h")
            sys.exit(0)
        print(f"\n[feasible] NO-GO — {obj.get('blocking_constraint')}\n"
              f"To make it run here:\n  - " +
              "\n  - ".join(obj["required_changes"]), file=sys.stderr)
        sys.exit(3)

    sys.exit(f"feasible: gate failed after 3 attempts:\n{err}")


if __name__ == "__main__":
    main()
