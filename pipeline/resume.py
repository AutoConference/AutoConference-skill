#!/usr/bin/env python3
"""resume -- a paper step the model's limit cut off is resumed, not redone.

    pipeline/resume.py save   <workspace> <step> <started-epoch> [why]
    pipeline/resume.py check  <workspace> <step>
    pipeline/resume.py forget <workspace> <from-step>

When a step's model runs out (a usage limit, no credit, its server down: the
heartbeat's QUOTA_WAIT), the loop runs the same step again once the model is
back. Run again from the top, unprompted, an experiment step rewrote results it
had already finished -- and a second cut-off could leave a finished file half
rewritten (a tester's report, 2026-10-05). So, from the heartbeat:

  save    at the cut-off: every file the step had written or changed since it
          started is copied, as it was, into .interrupted/step-<N>-<time>/
          (files up to 64 MB, 512 MB in all; larger ones are listed, not
          copied), and refine-logs/RESUME-step-<N>.md tells the next attempt
          what is there -- run-pipeline.sh puts it in front of that attempt;
  check   after the step next succeeds: no result under runs/ that a cut-off
          attempt had written may be gone, or be less than 90% of its size,
          unless refine-logs/DECISIONS.md names it with the reason. Exit 1
          otherwise, which fails the step like any other: tried again, told
          what went missing and where its copy is. On a pass the note goes,
          and the copies too unless one was replaced with a reason (they are
          then the record of what was replaced);
  forget  when the loop sends a paper back to an earlier step, the notes and
          copies of the steps it will redo.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import sys
import time

MAX_FILE = 64 * 2**20
MAX_TOTAL = 512 * 2**20
# The loop's own bookkeeping and everything that is not the step's work.
SKIP_DIRS = {".claude", ".aris", ".git", "__pycache__", ".interrupted", ".kill-argument",
             "node_modules", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
             ".ruff_cache", ".ipynb_checkpoints", ".submission-build"}
SKIP_FILES = {"pipeline.next", "pipeline.pid", "pipeline.log", "QUOTA_WAIT", "PIPELINE_STOPPED",
              ".step-prompts", ".quota-count", ".quota-noted", ".no-go-count", ".untraceable-count",
              ".shape-count", ".attachments.json"}
# What a result is: what check guards. A plan or a log may shrink for good reasons.
RESULT = re.compile(r"\.(json|jsonl|csv|tsv|npy|npz|pt|pth|pkl|pickle|parquet|h5|hdf5|safetensors)$", re.I)
SHRUNK = 0.9


def changed_since(ws: str, since: float) -> list[tuple[str, int]]:
    out = []
    for dirpath, dirnames, names in os.walk(ws):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                       and not os.path.isfile(os.path.join(dirpath, d, "pyvenv.cfg"))
                       and not os.path.isdir(os.path.join(dirpath, d, "conda-meta"))]
        for name in names:
            rel = os.path.relpath(os.path.join(dirpath, name), ws)
            if name in SKIP_FILES or name.startswith(".retry-") or \
                    re.match(r"refine-logs/(RETRY|RESUME)-step-\d+\.md$", rel):
                continue
            try:
                st = os.stat(os.path.join(dirpath, name))
            except OSError:
                continue
            if st.st_mtime >= since - 1:
                out.append((rel, st.st_size))
    return sorted(out)


def kb(n: int) -> str:
    return f"{n / 1024:.1f} KB" if n < 2**20 else f"{n / 2**20:.1f} MB"


def save(ws: str, step: int, started: float, why: str) -> None:
    files = changed_since(ws, started)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dest = os.path.join(ws, ".interrupted", f"step-{step}-{stamp}")
    os.makedirs(dest, exist_ok=True)
    total, listed = 0, []
    for rel, size in files:
        copied = False
        if size <= MAX_FILE and total + size <= MAX_TOTAL:
            try:
                os.makedirs(os.path.dirname(os.path.join(dest, rel)), exist_ok=True)
                shutil.copy2(os.path.join(ws, rel), os.path.join(dest, rel))
                copied, total = True, total + size
            except OSError:
                pass
        listed.append({"path": rel, "size": size, "copied": copied})
    with open(os.path.join(dest, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump({"step": step, "started": started, "interrupted": time.time(), "why": why,
                   "files": listed}, f, indent=2)
    rel_dest = os.path.relpath(dest, ws)
    lines = [f"# Step {step} was interrupted, not failed", "",
             f"The last attempt at this step stopped at {time.strftime('%Y-%m-%d %H:%M %Z')} because "
             f"the model was not available ({why or 'its limit'}), partway through.", ""]
    if listed:
        lines += [f"It had written or changed these files; each is kept as it was in {rel_dest}/:", ""]
        for e in listed[:40]:
            lines.append(f"- {e['path']} ({kb(e['size'])}{'' if e['copied'] else ', too large to copy'})")
        if len(listed) > 40:
            lines.append(f"- and {len(listed) - 40} more (their list: {rel_dest}/MANIFEST.json)")
        lines.append("")
    else:
        lines += ["It had not written any file yet.", ""]
    lines += ["Resume it: look at what is already there, keep what is complete and right, and do only "
              "what is missing. Re-running a finished part spends your owner's time and quota for "
              "nothing. If you replace or remove a finished result anyway, say why in "
              "refine-logs/DECISIONS.md, naming the file: when this step ends, the pipeline checks "
              "that no result under runs/ the interrupted attempt wrote has gone or shrunk without "
              "a reason written there."]
    os.makedirs(os.path.join(ws, "refine-logs"), exist_ok=True)
    with open(os.path.join(ws, "refine-logs", f"RESUME-step-{step}.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"resume: step {step} cut off; {len(listed)} file(s) it wrote kept in {rel_dest}"
          f" ({sum(e['copied'] for e in listed)} copied, {kb(total)})")


def saved(ws: str, step: int) -> list[str]:
    return sorted(glob.glob(os.path.join(ws, ".interrupted", f"step-{step}-*")))


def check(ws: str, step: int) -> int:
    best: dict[str, tuple[int, str, bool]] = {}
    for d in saved(ws, step):
        try:
            m = json.load(open(os.path.join(d, "MANIFEST.json"), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for e in m.get("files") or []:
            p, size = e.get("path", ""), int(e.get("size") or 0)
            if p.startswith("runs/") and RESULT.search(p) and size >= best.get(p, (-1,))[0]:
                best[p] = (size, os.path.relpath(os.path.join(d, p), ws), bool(e.get("copied")))
    try:
        reasons = open(os.path.join(ws, "refine-logs", "DECISIONS.md"), encoding="utf-8").read()
    except OSError:
        reasons = ""
    problems, explained = [], []
    for p, (size, copy, copied) in sorted(best.items()):
        full = os.path.join(ws, p)
        now = os.path.getsize(full) if os.path.exists(full) else None
        if now is not None and now >= SHRUNK * size:
            continue
        what = "is gone" if now is None else f"is {kb(now)} now"
        if p in reasons or os.path.basename(p) in reasons:
            explained.append(p)
            print(f"resume: {p} was {kb(size)} when step {step} was cut off and {what}; "
                  f"refine-logs/DECISIONS.md says why")
            continue
        where = f"its copy as it was is {copy}" if copied else "it was too large to copy"
        problems.append(f"{p} was {kb(size)} when step {step} was cut off and {what} ({where})")
    if problems:
        print(f"resume: step {step} lost results its interrupted attempt had written:")
        for p in problems:
            print(f"  - {p}")
        print("resume: put each back from its copy, or say in refine-logs/DECISIONS.md, naming the "
              "file, why the new one replaces it.")
        return 1
    note = os.path.join(ws, "refine-logs", f"RESUME-step-{step}.md")
    if os.path.exists(note):
        os.remove(note)
    if not explained:
        for d in saved(ws, step):
            shutil.rmtree(d, ignore_errors=True)
    print(f"resume: step {step} kept every result its interrupted attempt(s) had written"
          + (f"; {len(explained)} replaced with a reason, copies kept in .interrupted/" if explained else ""))
    return 0


def forget(ws: str, start: int) -> None:
    for d in glob.glob(os.path.join(ws, ".interrupted", "step-*-*")):
        m = re.match(r"step-(\d+)-", os.path.basename(d))
        if m and int(m.group(1)) >= start:
            shutil.rmtree(d, ignore_errors=True)
    for f in glob.glob(os.path.join(ws, "refine-logs", "RESUME-step-*.md")):
        m = re.search(r"RESUME-step-(\d+)\.md$", f)
        if m and int(m.group(1)) >= start:
            os.remove(f)


def main() -> int:
    a = sys.argv[1:]
    if len(a) >= 4 and a[0] == "save":
        save(a[1], int(a[2]), float(a[3]), a[4] if len(a) > 4 else "")
        return 0
    if len(a) == 3 and a[0] == "check":
        return check(a[1], int(a[2]))
    if len(a) == 3 and a[0] == "forget":
        forget(a[1], int(a[2]))
        return 0
    print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
