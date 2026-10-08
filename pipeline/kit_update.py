#!/usr/bin/env python3
"""kit_update.py -- the kit keeps itself up to date (KIT-048; owner, 2026-10-08).

  python3 pipeline/kit_update.py            # the loop, on every wake, after it reported
  python3 pipeline/kit_update.py --latest X # the same, told the latest version directly

Each wake the loop reports to the platform (client.py sync), and the answer
names the platform's latest kit (state/sync.json, "kit_latest"). When that is
newer than this kit's VERSION, this runs the same `git pull --ff-only` that
./ac's Update runs, and the loop then moves onto the new kit in place: a
paper step in progress runs on (run-heartbeat.sh, kit_moved / move_onto_kit).
Updates come from where the kit was installed from -- its git origin --
exactly as a pull by hand would.

It never forces. A kit whose files its owner changed where the update changes
them too, one with commits of its own, one with no upstream, or one that is
not a git checkout is left as it is, and why is said: in the loop's log, on
the agent's page (state/kit-update.json goes with the machine report), and,
when its owner can do something about it, once per version in
state/ASK_HUMAN.md with the commands that keep their changes. A source that
does not answer is tried again at the next wake, without a note.
AC_AUTO_UPDATE=0 (state/runner.env; on the website, "Kit updates: by hand")
turns it off: its owner then updates with ./ac (u).

Prints one line for the log when there is something to say; always exits 0 --
an update that did not happen must never cost the loop its wake.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE = os.environ.get("AC_STATE") or os.path.join(ROOT, "state")
RECORD = os.path.join(STATE, "kit-update.json")
NOTE_CAUSES = {"edits", "own_commits", "no_upstream", "not_git"}


def version_of(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in (v or "").strip().split("."))


def newer(a: str, b: str) -> bool:
    """a is a later version than b."""
    return bool(a) and version_of(a) > version_of(b)


def kit_version() -> str:
    try:
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def runner_setting(key: str) -> str:
    """The loop's environment first, then state/runner.env (last line wins)."""
    if os.environ.get(key) is not None:
        return os.environ[key]
    found = ""
    try:
        with open(os.path.join(STATE, "runner.env"), encoding="utf-8") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k.strip() == key:
                    found = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return found


def latest_from_sync() -> str:
    try:
        with open(os.path.join(STATE, "sync.json"), encoding="utf-8") as f:
            v = json.load(f).get("kit_latest") or ""
    except (OSError, ValueError, AttributeError):
        return ""
    return v if isinstance(v, str) and re.fullmatch(r"\d+(\.\d+){1,3}", v) else ""


def load_record() -> dict:
    try:
        with open(RECORD, encoding="utf-8") as f:
            r = json.load(f)
        return r if isinstance(r, dict) else {}
    except (OSError, ValueError):
        return {}


def save_record(r: dict) -> None:
    os.makedirs(STATE, exist_ok=True)
    with open(RECORD + ".tmp", "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)
    os.replace(RECORD + ".tmp", RECORD)


def git(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    # Unattended: a source that wants a password fails at once instead of
    # waiting for a person at a terminal that is not there.
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="echo", LC_ALL="C")
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True, timeout=timeout, env=env)


def is_checkout() -> bool:
    try:
        r = git("rev-parse", "--show-toplevel", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and os.path.realpath(r.stdout.strip()) == os.path.realpath(ROOT)


def why_refused(out: str) -> tuple[str, str]:
    """git's refusal as (cause, words for the owner)."""
    if "would be overwritten" in out:
        files = [ln.strip() for ln in out.splitlines()
                 if ln.startswith(("\t", "    ")) and ln.strip() and not ln.strip().startswith(("Please", "Aborting"))]
        shown = ", ".join(files[:5]) + (f" and {len(files) - 5} more" if len(files) > 5 else "")
        return "edits", f"you changed kit files the update changes too: {shown or 'see git status'}"
    if re.search(r"Not possible to fast-forward|diverg|non-fast-forward", out, re.I):
        return "own_commits", "the kit here has commits of its own that its source does not have"
    if re.search(r"no tracking information|no such ref was fetched|couldn't find remote ref", out, re.I):
        return "no_upstream", "the kit here does not follow a branch of its source"
    if re.search(r"Could not resolve|unable to access|Connection|timed out|Network|Operation not permitted|"
                 r"could not read Username|Authentication failed|Repository not found|"
                 r"Could not read from remote repository|does not appear to be a git repository", out, re.I):
        return "unreachable", "its source did not answer"
    last = next((ln.strip() for ln in reversed(out.splitlines()) if ln.strip()), "git failed")
    return "git", last[:300]


def note_once(r: dict, latest: str, cause: str, why: str) -> None:
    """One note per version for its owner, with the way through that keeps
    their changes; the website lists it with the loop's other notes."""
    if cause not in NOTE_CAUSES or r.get("noted_for") == f"{latest}:{cause}":
        return
    here = ROOT
    how = {
        "edits": (f"To update and keep your changes: `cd {here} && git stash && git pull && git stash pop`. "
                  "Your own instructions belong in `custom/`, which updates never touch."),
        "own_commits": (f"To update on top of your commits: `cd {here} && git pull --rebase`; or, to go back to the "
                        f"published kit, `cd {here} && git fetch && git reset --hard @{{u}}` (your commits are then gone)."),
        "no_upstream": f"To follow the published kit again: `cd {here} && git branch --set-upstream-to=origin/main && git pull`.",
        "not_git": "This copy of the kit is not a git checkout, so it cannot update itself: install the kit again from the website.",
    }[cause]
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    title = f"the kit could not update itself to {latest}"
    body = (f"Kit {latest} is out and this agent runs {kit_version() or 'an older kit'}. It did not update by itself: "
            f"{why}. {how} Or turn automatic updates off on the agent's page and update with `./ac` (u) when you like.")
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, "ASK_HUMAN.md"), "a", encoding="utf-8") as f:
        f.write(f"\n## {stamp} — {title}\n\n{body}\n")
    r["noted_for"] = f"{latest}:{cause}"


def run(latest: str) -> str:
    """Does what the wake calls for; returns the log's line ("" for none)."""
    r = load_record()
    now = kit_version()
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    base = {"version": now, "latest": latest or r.get("latest") or "", "auto": True}

    if runner_setting("AC_AUTO_UPDATE").strip() in ("0", "off", "no", "false"):
        save_record({**base, "auto": False, "state": "off", "checked_at": stamp,
                     **({"noted_for": r["noted_for"]} if r.get("noted_for") else {})})
        return f"kit update: off (AC_AUTO_UPDATE=0); {latest} is out" if newer(latest, now) else ""
    if not newer(latest, now):
        if r.get("state") != "current" or r.get("version") != now:
            keep = {k: r[k] for k in ("from", "to", "updated_at") if k in r}
            save_record({**base, **keep, "state": "current", "checked_at": stamp})
        return ""
    if not is_checkout():
        out = {**base, "state": "blocked", "cause": "not_git", "why": "this copy of the kit is not a git checkout",
               "checked_at": stamp, **({"noted_for": r["noted_for"]} if r.get("noted_for") else {})}
        note_once(out, latest, "not_git", out["why"])
        save_record(out)
        return f"kit update: {latest} is out, but {out['why']}"
    try:
        p = git("pull", "-q", "--ff-only")
        out_text, ok = (p.stdout or "") + (p.stderr or ""), p.returncode == 0
    except subprocess.TimeoutExpired:
        out_text, ok = "Connection timed out", False
    except OSError as e:
        out_text, ok = f"git could not run: {e}", False
    after = kit_version()
    if ok and after and after != now:
        save_record({**base, "version": after, "state": "updated", "from": now, "to": after,
                     "updated_at": stamp, "checked_at": stamp})
        return f"kit update: updated {now} -> {after}; the loop moves onto it in place"
    if ok:
        # The source has nothing newer yet (it is published a little after the
        # platform says so): the next wake looks again.
        save_record({**base, "state": "waiting", "cause": "source_behind",
                     "why": f"its source has no kit newer than {now} yet", "checked_at": stamp,
                     **({"noted_for": r["noted_for"]} if r.get("noted_for") else {})})
        return f"kit update: {latest} is out; its source has nothing newer than {now} yet"
    cause, why = why_refused(out_text)
    rec = {**base, "state": "waiting" if cause == "unreachable" else "blocked", "cause": cause, "why": why,
           "checked_at": stamp, **({"noted_for": r["noted_for"]} if r.get("noted_for") else {})}
    note_once(rec, latest, cause, why)
    save_record(rec)
    return f"kit update: {latest} is out, not updated: {why}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--latest", default="", help="the latest kit version (default: state/sync.json)")
    a = ap.parse_args()
    try:
        line = run(a.latest or latest_from_sync())
    except Exception as e:  # never the loop's wake
        line = f"kit update: skipped ({type(e).__name__}: {e})"
    if line:
        print(line, flush=True)  # the loop's log() stamps it


if __name__ == "__main__":
    main()
