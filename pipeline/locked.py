#!/usr/bin/env python3
"""locked.py -- the kit's locked data module (owner, 2026-10-04).

  python3 pipeline/locked.py check      # the loop, at its start and on every wake
  python3 pipeline/locked.py --write    # the kit's maintainers: LOCKED.json from the files as they are
  python3 pipeline/locked.py --verify   # read-only: exit 1 when a file no longer hashes as listed

The conference needs the record of how each paper was made -- the turns the
loop uploads, the two statements, the survey, the activity report -- and the
platform checks what arrives. That record is only worth keeping while the
program that writes it is the one that was published, so the files that
collect it are locked: LOCKED.json at the kit's root names each with its
sha256. Everything else in the kit stays the owner's to change (custom/,
research/, paper-writing/, skills/, the other references, WORKFLOW.md,
run-pipeline.sh, the reproduction gate, docs/).

`check` hashes every listed file. One that differs is put back from the kit's
own git history (`git checkout HEAD -- <that path>`, one path at a time; never
custom/, never anything else) and the owner is told in state/ASK_HUMAN.md --
one note per file per day: which file, that it is part of the locked module,
that it was put back, and that their own instructions belong in custom/. One
that cannot be put back (a kit copied without .git, a kit inside another
repository, git failing) is reported `modified`, with the same note, and the
platform does not send a paper from such a kit to review until it is. The
result is state/locked.json: {"status": ok|restored|modified, "manifest" (the
sha256 of LOCKED.json, first 16 hex -- what the platform knows a published
kit's manifest by), "checked_at", "restored": [...], "modified": [...]};
submission/scripts/client.py sends it with every request (X-AC-Locked), and
pipeline/activity.py puts it in the activity report.

On stdout: the status on the first line, then one line per file put back
("restored <path>") or left changed ("modified <path>"), for the loop to log
and -- when the loop's own file was put back -- to start again on.

Python 3.8; no dependencies.
"""
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE = os.environ.get("AC_STATE") or os.path.join(ROOT, "state")
MANIFEST = os.path.join(ROOT, "LOCKED.json")
RESULT = os.path.join(STATE, "locked.json")
NOTED = os.path.join(STATE, "locked-noted.json")

# The locked files, which --write hashes. `check` takes its list from
# LOCKED.json: once published, the manifest is the one source.
LOCKED_FILES = [
    "AGENTS.md",
    "pipeline/activity.py",
    "pipeline/agent-turn.sh",
    "pipeline/locked.py",
    "pipeline/paper_facts.py",
    "pipeline/render_stream.py",
    "pipeline/run-heartbeat.sh",
    "pipeline/statements.py",
    "pipeline/submit-paper.sh",
    "pipeline/turn_upload.py",
    "submission/references/survey.md",
    "submission/scripts/client.py",
]


def sha256_of(path: str):
    """The file's sha256 with its line endings as LF, or None when it is not
    there. An editor, or git's autocrlf, that saved a file with CRLF must not
    read as a change: a paper is held out of review on `modified`."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def manifest_id() -> str:
    """What the platform knows a published kit's manifest by."""
    return (sha256_of(MANIFEST) or "")[:16]


def safe_path(p) -> bool:
    """A path the manifest may name: inside the kit, relative, no tricks."""
    if not isinstance(p, str) or not p or p.startswith(("/", "\\")) or ":" in p:
        return False
    return ".." not in p.replace("\\", "/").split("/")


def read_manifest() -> dict:
    """{"<path>": "<sha256>"} from LOCKED.json; raises when it is not one."""
    with open(MANIFEST, encoding="utf-8") as f:
        m = json.load(f)
    files = m.get("files") if isinstance(m, dict) else None
    if not isinstance(files, dict) or not files:
        raise ValueError("LOCKED.json names no files")
    return {p: str(h) for p, h in files.items() if safe_path(p)}


def own_checkout() -> bool:
    """Whether the kit is its own git checkout -- the clone setup makes. A
    copy without .git has no history to put a file back from; a kit inside
    another repository (this kit's own development tree) is not restored
    either: there a checkout would undo a maintainer's edit."""
    try:
        r = subprocess.run(["git", "-C", ROOT, "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    if r.returncode != 0:
        return False
    try:
        return os.path.realpath(r.stdout.strip()) == os.path.realpath(ROOT)
    except OSError:
        return False


def restore(path: str) -> bool:
    """Put one locked file back from HEAD -- the index too, so a change the
    owner staged goes with it. True when git did it."""
    try:
        r = subprocess.run(["git", "-C", ROOT, "checkout", "HEAD", "--", path],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def note(path: str, put_back: bool) -> None:
    """One note per file per day in state/ASK_HUMAN.md, in the owner's words:
    which file, what it is part of, what became of it, and where their own
    instructions go. The website lists it as the loop's other notes."""
    try:
        with open(NOTED, encoding="utf-8") as f:
            noted = json.load(f)
        if not isinstance(noted, dict):
            noted = {}
    except (OSError, ValueError):
        noted = {}
    today = time.strftime("%Y-%m-%d")
    if noted.get(path) == today:
        return
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    part = (f"`{path}` is part of the locked data module the conference requires: these files keep "
            "the record of how each paper is made (the turns the loop uploads, the two statements, "
            "the survey's facts, the activity report), and the platform checks what arrives. ")
    yours = ("Your own instructions belong in `custom/` -- `custom/all.md`, `custom/step-<N>.md`, "
             "`custom/review.md`, `custom/chair.md` -- which nothing here touches; AGENTS.md and "
             "WORKFLOW.md say what each is for, and everything else in the kit is yours to change.")
    if put_back:
        title = f"{path} was changed, and put back"
        body = part + "The kit put the published file back. " + yours
    else:
        title = f"{path} was changed, and could not be put back"
        body = (part + "The kit could not put it back (this copy is not a git clone of the kit, or git "
                "failed), and until it is, the platform will not send this agent's papers to review. "
                "To put it back: `git pull` in the kit's directory, or install the kit again. " + yours)
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, "ASK_HUMAN.md"), "a", encoding="utf-8") as f:
        f.write(f"\n## {stamp} — {title}\n\n{body}\n")
    noted[path] = today
    with open(NOTED + ".tmp", "w", encoding="utf-8") as f:
        json.dump(noted, f, indent=2)
    os.replace(NOTED + ".tmp", NOTED)


def check() -> int:
    restored, modified = [], []
    try:
        files = read_manifest()
    except (OSError, ValueError):
        files = None
        # The manifest itself, gone or broken, comes back the same way.
        if own_checkout() and restore("LOCKED.json"):
            try:
                files = read_manifest()
            except (OSError, ValueError):
                files = None
    if files is None:
        print("locked: LOCKED.json is missing or not a manifest; the locked files cannot be checked",
              file=sys.stderr)
        modified.append("LOCKED.json")
    else:
        changed = [p for p in sorted(files) if sha256_of(os.path.join(ROOT, p)) != files[p]]
        can = own_checkout() if changed else False
        for p in changed:
            if can and restore(p) and sha256_of(os.path.join(ROOT, p)) == files[p]:
                restored.append(p)
            else:
                modified.append(p)
    status = "modified" if modified else ("restored" if restored else "ok")
    for p in restored:
        note(p, True)
    for p in modified:
        note(p, False)
    result = {
        "status": status,
        "manifest": manifest_id(),
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "restored": restored,
        "modified": modified,
    }
    os.makedirs(STATE, exist_ok=True)
    with open(RESULT + ".tmp", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    os.replace(RESULT + ".tmp", RESULT)
    print(status)
    for p in restored:
        print("restored " + p)
    for p in modified:
        print("modified " + p)
    return 0


def write() -> int:
    files = {}
    for p in LOCKED_FILES:
        h = sha256_of(os.path.join(ROOT, p))
        if h is None:
            print(f"locked: no such file: {p}", file=sys.stderr)
            return 1
        files[p] = h
    with open(MANIFEST + ".tmp", "w", encoding="utf-8") as f:
        json.dump({"version": 1, "files": files}, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(MANIFEST + ".tmp", MANIFEST)
    print(f"LOCKED.json: {len(files)} files, manifest {manifest_id()}")
    return 0


def verify() -> int:
    """Read-only, for publishing: a kit whose files no longer hash as its
    LOCKED.json lists would be `modified` on every machine that installs it,
    and none of its agents' papers would go to review. Puts nothing back."""
    try:
        files = read_manifest()
    except (OSError, ValueError):
        print("locked: LOCKED.json is missing or not a manifest", file=sys.stderr)
        return 1
    stale = [p for p in sorted(files) if sha256_of(os.path.join(ROOT, p)) != files[p]]
    unlisted = sorted(set(LOCKED_FILES) - set(files))
    for p in stale:
        print(f"locked: {p} does not hash as LOCKED.json lists", file=sys.stderr)
    for p in unlisted:
        print(f"locked: {p} is locked but not in LOCKED.json", file=sys.stderr)
    if stale or unlisted:
        print("locked: run python3 pipeline/locked.py --write, then commit LOCKED.json", file=sys.stderr)
        return 1
    print(f"LOCKED.json: {len(files)} files match, manifest {manifest_id()}")
    return 0


def main(argv) -> int:
    if argv == ["check"]:
        return check()
    if argv == ["--write"]:
        return write()
    if argv == ["--verify"]:
        return verify()
    print("usage: locked.py check | --write | --verify", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
