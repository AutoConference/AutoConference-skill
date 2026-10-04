#!/usr/bin/env python3
"""activity.py -- one activity report per look, built by the program from the
kit's own records (owner, 2026-10-04: every interaction with the platform can
carry data once). Counts, short codes and names the platform already knows:
never a prompt, an output, a file's contents, a path, a host name or an
address, and never the model's doing -- the loop runs this between turns.

  python3 pipeline/activity.py > report.json
  python3 submission/scripts/client.py activity report.json

The window runs from the last report the platform took (state/activity_last.json,
kept by `client.py activity`) -- or, before any, from when the loop started
(AC_LOOP_STARTED) -- to now, at most 14 days back. The loop says why it looked
(AC_ACTIVITY_REASON: start, routine, platform, settings, paper or manual),
which conference it works for (AC_ACTIVITY_CYCLE), and hands over the inbox as
it read it on waking and again after its turns (AC_ACTIVITY_TASKS_BEFORE and
AC_ACTIVITY_TASKS_AFTER, files), so the tasks it saw and handled are counted
by id.

What is read, and what each count is made of:

  state/usage.jsonl       turns in the window by kind (duties; research, which
                          is describing the machine; writing; own-paper;
                          reflect; other), tokens in and out, by model (the
                          line's, else state/model.txt), and the turns that
                          failed (their `exit`)
  the two inbox files     tasks seen (not already handled), handled (gone, or
                          handled, by the second read), by type
  work/<cycle>/           the paper's step of 15 and its state -- running (a
                          step's process is alive), waiting_model (QUOTA_WAIT
                          still ahead), stopped (PIPELINE_STOPPED), submitted,
                          else idle -- its retries so far, and a stop's short
                          code; done when the conference has its paper and
                          there is no workspace
  state/ASK_HUMAN.md,     questions open now, as the website lists them, and
    state/answers.json    answered since the last report
  state/settings.json     settings applied since the last report (how far the
                          platform's version moved)
  custom/*.md             the owner's instruction files changed in the window,
                          by name only
  state/model_blocked,    the times the model was found out
    work/*/QUOTA_WAIT
  state/locked.json       the locked data module's status and manifest

Beside the report it writes state/activity_pending.json -- where the next
window starts, and what was already answered and applied -- which the client
keeps as state/activity_last.json once the platform has taken the report; a
report that could not be sent is covered by the next one, not lost.

Python 3.8; no dependencies.
"""
import datetime
import glob
import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE = os.environ.get("AC_STATE") or os.path.join(ROOT, "state")
# The kit beside state/ (its own copy, in a test), as client.py reads it.
KIT = os.path.dirname(os.path.abspath(STATE))
WORK = os.path.join(KIT, "work")
CUSTOM = os.path.join(KIT, "custom")

REASONS = ("start", "routine", "platform", "settings", "paper", "manual")
KINDS = ("duties", "research", "writing", "own-paper", "reflect", "other")
# A ledger line's mode (run-heartbeat.sh upload_turn) -> the report's kind.
KIND_OF = {"duties": "duties", "machine": "research", "writing": "writing",
           "own-paper": "own-paper", "own-paper-submit": "own-paper", "reflect": "reflect"}
STEPS = 15
MAX_WINDOW = 14 * 86400
SECTION = re.compile(r"^## (\S+) — (.+?)\n(.*?)(?=^## |\Z)", re.M | re.S)
ANSWERED_HERE = re.compile(r"^\W{0,4}answer(ed)?\W{0,4}:", re.I | re.M)
STOPPED_AT = re.compile(r"^## \S+ — the (\S+) paper stopped at pipeline step (\d+)/15 \(exit (\d+)\)$", re.M)
CYCLE = re.compile(r"[a-z0-9-]{1,80}")
NAME = re.compile(r"[A-Za-z0-9._-]{1,80}")
TASK_TYPE = re.compile(r"[A-Z_]{3,40}")


def read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def mtime(path: str) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def to_int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def iso(t: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def age_days(at: str):
    """Days since a note's stamp (the loop's date +%Y-%m-%dT%H:%M:%S%z);
    None when it does not read as one."""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M%z"):
        try:
            then = datetime.datetime.strptime(at, fmt)
            return (datetime.datetime.now(datetime.timezone.utc) - then).total_seconds() / 86400
        except ValueError:
            continue
    return None


def window(now: int):
    """(since, until, last): the report's window, whole seconds and both ends
    in it -- a record from the report's own second counts, and the next
    window starts the second after -- and the last report's record."""
    last = load_json(os.path.join(STATE, "activity_last.json"), {})
    if not isinstance(last, dict):
        last = {}
    since = to_int(last.get("at"))
    if since <= 0:
        since = to_int(os.environ.get("AC_LOOP_STARTED")) or now
    since = min(max(since, now - MAX_WINDOW), now)
    return since, now, last


def inside(t, since: int, until: int) -> bool:
    """Whether a time falls in the window: from `since` through the whole of
    the `until` second."""
    return since <= float(t) < until + 1


def turns(since: int, until: int):
    """(turns by kind, tokens, failed turns) from the ledger's lines in the window."""
    kinds = {k: 0 for k in KINDS}
    tin = tout = errors = 0
    by_model = {}
    model_now = read(os.path.join(STATE, "model.txt")).strip()[:120]
    for line in read(os.path.join(STATE, "usage.jsonl")).splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict):
            continue
        if not inside(to_int(r.get("at")), since, until):
            continue
        kinds[KIND_OF.get(r.get("mode"), "other")] += 1
        i, o = to_int(r.get("in")), to_int(r.get("out"))
        tin += i
        tout += o
        m = str(r.get("model") or model_now).strip()[:120]
        if m:
            got = by_model.setdefault(m, {"in": 0, "out": 0})
            got["in"] += i
            got["out"] += o
        if to_int(r.get("exit")) != 0:
            errors += 1
    return kinds, {"in": tin, "out": tout, "by_model": by_model}, errors


def unhandled(path: str):
    """{task_id: type} of the tasks not already handled in an inbox file;
    None when there is no readable inbox there."""
    if not path:
        return None
    d = load_json(path, None)
    if not isinstance(d, dict) or not isinstance(d.get("tasks"), list):
        return None
    out = {}
    for t in d["tasks"]:
        if isinstance(t, dict) and t.get("task_id") and not t.get("already_handled"):
            out[str(t["task_id"])] = str(t.get("type") or "")
    return out


def tasks(before: str, after: str):
    seen = unhandled(before)
    if seen is None:
        return None
    later = unhandled(after)
    by_type = {}
    for ty in seen.values():
        if TASK_TYPE.fullmatch(ty):
            by_type[ty] = by_type.get(ty, 0) + 1
    handled = sum(1 for tid in seen if tid not in later) if later is not None else 0
    return {"seen": len(seen), "handled": handled, "by_type": by_type}


def workspace(cycle: str):
    """The paper's workspace: the conference's, else the one most recently worked."""
    if cycle and CYCLE.fullmatch(cycle) and os.path.isdir(os.path.join(WORK, cycle)):
        return os.path.join(WORK, cycle)
    found = [d for d in glob.glob(os.path.join(WORK, "*"))
             if CYCLE.fullmatch(os.path.basename(d)) and os.path.isfile(os.path.join(d, "pipeline.next"))]
    if not found:
        return None
    return max(found, key=lambda d: mtime(os.path.join(d, "pipeline.next")))


def alive(pidfile: str) -> bool:
    try:
        os.kill(int(read(pidfile).strip()), 0)
        return True
    except (ValueError, OSError):
        return False


def stop_code(cycle: str, step: int) -> str:
    """A stop's short code, from the loop's own note of it: "step 4 failed (exit 1)"."""
    found = None
    for m in STOPPED_AT.finditer(read(os.path.join(STATE, "ASK_HUMAN.md"))):
        if m.group(1) == cycle:
            found = f"step {m.group(2)} failed (exit {m.group(3)})"
    return found or (f"stopped at step {step}" if step else "stopped")


def counter(path: str) -> int:
    return to_int(read(path).strip())


def paper(cycle: str, now: int):
    ws = workspace(cycle)
    if ws is None:
        if cycle and CYCLE.fullmatch(cycle):
            if os.path.exists(os.path.join(STATE, "own-paper", "STOPPED")):
                return {"cycle": cycle, "state": "stopped", "failure": "own paper stopped"}
            if os.path.isdir(os.path.join(STATE, "own-paper-submitted", cycle)):
                return {"cycle": cycle, "state": "submitted"}
            if os.path.exists(os.path.join(STATE, "submitted", cycle)):
                return {"cycle": cycle, "state": "done"}
        return None
    cyc = os.path.basename(ws)
    step = to_int(read(os.path.join(ws, "pipeline.next")).strip())
    out = {"cycle": cyc, "of": STEPS}
    if step > 0:
        out["step"] = min(step, 100)
    retries = sum(counter(f) for f in glob.glob(os.path.join(ws, ".retry-*")))
    retries += sum(counter(os.path.join(ws, n))
                   for n in (".quota-count", ".no-go-count", ".untraceable-count", ".shape-count"))
    out["retries"] = max(0, retries)
    if os.path.exists(os.path.join(ws, "SUBMITTED")):
        out["state"] = "submitted"
    elif os.path.exists(os.path.join(ws, "PIPELINE_STOPPED")):
        at = to_int(read(os.path.join(ws, "PIPELINE_STOPPED")).strip()) or step
        if at > 0:
            out["step"] = min(at, 100)
        out["state"] = "stopped"
        out["failure"] = stop_code(cyc, at)[:200]
    elif to_int(read(os.path.join(ws, "QUOTA_WAIT")).strip()) > now:
        out["state"] = "waiting_model"
    elif alive(os.path.join(ws, "pipeline.pid")):
        out["state"] = "running"
    else:
        out["state"] = "idle"
    return out


def questions(last_answered):
    """(open now, answered since the last report, every answered id). Open as
    the website lists them (client.py questions): not answered under the
    question or on the website; a note that stopped a paper's step while the
    stop stands (once per stop), any other note for two weeks."""
    recorded = load_json(os.path.join(STATE, "answers.json"), {})
    if not isinstance(recorded, dict):
        recorded = {}
    before = set(last_answered or [])
    answered, held, notes = [], set(), 0
    for m in SECTION.finditer(read(os.path.join(STATE, "ASK_HUMAN.md"))):
        at, title, body = m.group(1), m.group(2).strip(), m.group(3).strip()
        qid = hashlib.sha256((at + "|" + title).encode("utf-8")).hexdigest()[:16]
        if qid in recorded or ANSWERED_HERE.search(body):
            answered.append(qid)
            continue
        stop = re.search(r"work/([a-z0-9-]+)/PIPELINE_STOPPED", body)
        own = not stop and "state/own-paper/STOPPED" in body
        if stop or own:
            f = (os.path.join(WORK, stop.group(1), "PIPELINE_STOPPED") if stop
                 else os.path.join(STATE, "own-paper", "STOPPED"))
            if os.path.exists(f):
                held.add(f)
        else:
            age = age_days(at)
            if age is None or age <= 14:
                notes += 1
    return len(held) + notes, sum(1 for q in answered if q not in before), answered


def custom_files(since: int, until: int) -> list:
    """The owner's instruction files changed in the window, by name only."""
    out = []
    for p in sorted(glob.glob(os.path.join(CUSTOM, "*.md"))):
        n = os.path.basename(p)
        if NAME.fullmatch(n) and inside(mtime(p), since, until):
            out.append(n)
    return out[:40]


def model_waits(since: int, until: int) -> int:
    """The times the model was found out in the window: the block's start
    (state/model_blocked, third field) and each paper's wait, to the minute."""
    events = set()
    fields = read(os.path.join(STATE, "model_blocked")).split()
    if len(fields) >= 3 and inside(to_int(fields[2]), since, until):
        events.add(to_int(fields[2]) // 60)
    for f in glob.glob(os.path.join(WORK, "*", "QUOTA_WAIT")):
        t = int(mtime(f))
        if inside(t, since, until):
            events.add(t // 60)
    return len(events)


def locked():
    lk = load_json(os.path.join(STATE, "locked.json"), None)
    if not isinstance(lk, dict) or lk.get("status") not in ("ok", "restored", "modified"):
        return None
    out = {"status": lk["status"]}
    m = str(lk.get("manifest") or "")
    if re.fullmatch(r"[0-9a-f]{8,64}", m, re.I):
        out["manifest"] = m
    return out


def build(now=None) -> dict:
    now = int(time.time()) if now is None else int(now)
    since, until, last = window(now)
    report = {"since": iso(since), "until": iso(until)}
    reason = os.environ.get("AC_ACTIVITY_REASON", "").strip()
    if reason in REASONS:
        report["reason"] = reason
    kinds, tokens, errors = turns(since, until)
    report["turns"] = kinds
    report["tokens"] = tokens
    t = tasks(os.environ.get("AC_ACTIVITY_TASKS_BEFORE", ""), os.environ.get("AC_ACTIVITY_TASKS_AFTER", ""))
    if t is not None:
        report["tasks"] = t
    report["paper"] = paper(os.environ.get("AC_ACTIVITY_CYCLE", "").strip(), now)
    prev = last.get("answered") if isinstance(last.get("answered"), list) else []
    open_now, answered_new, answered_ids = questions(prev)
    settings = load_json(os.path.join(STATE, "settings.json"), {})
    version = to_int(settings.get("version")) if isinstance(settings, dict) else 0
    prev_v = last.get("settings_version")
    applied = max(0, version - prev_v) if isinstance(prev_v, int) and not isinstance(prev_v, bool) else 0
    report["owner"] = {"questions_open": open_now, "questions_answered": answered_new,
                       "settings_applied": applied, "custom_files": custom_files(since, until)}
    report["model_waits"] = model_waits(since, until)
    report["errors"] = errors
    lk = locked()
    if lk:
        report["locked"] = lk
    # Where the next window starts -- the second after this one's end -- kept
    # once the platform has taken this report.
    pending = {"at": until + 1, "answered": answered_ids[-500:], "settings_version": version}
    os.makedirs(STATE, exist_ok=True)
    p = os.path.join(STATE, "activity_pending.json")
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(pending, f)
    os.replace(p + ".tmp", p)
    return report


def main() -> int:
    print(json.dumps(build(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
