#!/usr/bin/env python3
"""preflight-tokens -- refuse a sweep whose generation cap is too small.

A generation cap is a measurement instrument, and an uncalibrated instrument
produces a curve that describes itself. The first run of this pipeline capped at
512 tokens on a graph-colouring task whose answers needed more, truncated 9 of 15
samples, and reported a "capability collapse" that was mostly the cap. Two cells
had every sample truncated, so the accuracy printed for them was a property of
the configuration and nothing else.

So before the sweep: calibrate (step 4 measures the p95 completion length of
generations that actually reached EOS), then check here that the cap the sweep
will use clears it. A reasoning model gets its own cap; sharing one with an
instruct model guarantees one of the two is mismeasured.

    research/scripts/check_calibration.py work/<slug> quality.json

Exit 0 = sized from the task, 4 = too small, 2 = no calibration to check.
"""
from __future__ import annotations

import json
import os
import sys


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("usage: preflight-tokens.py <workdir> <quality.json>")
    work, qpath = sys.argv[1], sys.argv[2]
    q = json.load(open(qpath, encoding="utf-8"))
    floor = q["token_budget"]["floor"]

    cal_path = os.path.join(work, "runs", "CALIBRATION.json")
    if not os.path.exists(cal_path):
        print(f"preflight: no {cal_path} — step 4 must measure the task's answer "
              f"length before the sweep can be sized", file=sys.stderr)
        sys.exit(2)
    try:
        cal = json.load(open(cal_path, encoding="utf-8"))
    except ValueError as e:
        print(f"preflight: {cal_path} is not valid JSON ({e})", file=sys.stderr)
        sys.exit(2)

    # A p95 is only a p95 if enough generations finished to have a distribution.
    # The first real calibration produced n_completed=1 of 16 for the reasoning
    # model: its completion lengths are RIGHT-CENSORED at the calibration cap, so
    # "2 x p95" extrapolates from a single observation and the true p95 is
    # unknown and probably far above the cap that was used. The honest response is
    # to raise the calibration cap and measure again, not to trust the number.
    MIN_COMPLETIONS = 5
    MIN_COMPLETION_RATE = 0.5

    per_model = cal.get("per_model") or {}
    if not per_model:
        print("preflight: CALIBRATION.json has no per_model measurements",
              file=sys.stderr)
        sys.exit(2)

    problems, ok_rows = [], []
    for model, d in per_model.items():
        cap = d.get("recommended_cap")
        p95 = d.get("p95_completion_tokens")
        n, done = d.get("n"), d.get("n_completed")

        if done == 0 or cap in (None, 0):
            problems.append(
                f"{model}: nothing reached EOS during calibration"
                + (f" ({done}/{n} completed)" if n else "")
                + ". The task's answers do not fit a context this pipeline can "
                  "afford, so no cap will rescue it. Change the task — a shorter "
                  "answer format, or a smaller hardest level — not the cap.")
            continue
        if cap < floor:
            problems.append(f"{model}: recommended_cap {cap} is below the {floor} floor")
            continue
        if n and done is not None and done < MIN_COMPLETIONS:
            problems.append(
                f"{model}: only {done}/{n} generations reached EOS during calibration, "
                f"so the reported p95 ({p95}) rests on {done} observation"
                f"{'s' if done != 1 else ''}. The completion-length distribution is "
                f"right-censored at the calibration cap: the true p95 is unknown and "
                f"is probably well above it, so 2x this number is an extrapolation, "
                f"not a measurement. Raise the CALIBRATION cap (not the sweep cap) "
                f"until at least {MIN_COMPLETIONS} generations finish, then re-measure.")
            continue
        if n and done is not None and done / n < MIN_COMPLETION_RATE:
            problems.append(
                f"{model}: {done}/{n} = {done/n:.0%} of calibration generations "
                f"reached EOS, below the {MIN_COMPLETION_RATE:.0%} floor. A cap "
                f"inferred from the minority that happened to finish is biased "
                f"downward -- the ones that did not finish are exactly the long ones.")
            continue
        if p95 and cap < 2 * p95:
            problems.append(
                f"{model}: cap {cap} is under 2x the p95 completion length "
                f"({p95}), so a normal-length answer at the hard end will be cut off")
            continue
        ok_rows.append(f"  {model}: {done}/{n} reached EOS, p95 completion {p95} tok "
                       f"-> cap {cap} (floor {floor})")

    for r in ok_rows:
        print(r)
    if problems:
        print("\npreflight FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("\nA cap below the task's own answer length measures the cap, not the "
              "model. This is the exact failure that made the previous paper "
              "unusable.", file=sys.stderr)
        sys.exit(4)

    print("\npreflight: every cap is sized from the task")
    sys.exit(0)


if __name__ == "__main__":
    main()
