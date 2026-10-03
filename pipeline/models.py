#!/usr/bin/env python3
"""models.py -- the agent CLIs on this machine, and the models each offers
its owner, read from the CLI itself rather than from a list that goes stale:
Claude Code's three and any further model its cache says the account has,
Codex's model cache, `opencode models` (the owner's own providers first), and
Gemini CLI's own defaults.

  python3 pipeline/models.py <cli>    the numbered list setup and ./ac show
  python3 pipeline/models.py --json   every CLI here, for the platform (KIT-008)

The numbered list is a line per model -- number, the id padded, a few words,
the id -- and a last "enter" line: the number Enter picks. That is the model
the owner already uses in that CLI when it names one (owner, 2026-10-02),
else the kit's own default; empty, for the CLI's own default.
"""
import json
import os
import re
import shutil
import subprocess
import sys

HOME = os.path.expanduser("~")
CLIS = ["claude", "codex", "gemini", "opencode"]
# The kit's default first (agent-turn.sh runs it when AC_MODEL is unset).
CLAUDE = [
    ("claude-sonnet-5", "balanced; lighter on your quota"),
    ("claude-opus-5-5", "strongest; uses more of it"),
    ("claude-haiku-4-5-20251001", "fastest and lightest"),
]


def _load(*path):
    try:
        with open(os.path.join(HOME, *path), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def options(cli):
    """(rows, default, yours): rows of (id, description); the id Enter picks;
    the id the owner already uses in that CLI, if it names one."""
    rows, default, yours = [], None, None
    if cli == "claude":
        rows = list(CLAUDE)
        for o in (_load(".claude.json") or {}).get("additionalModelOptionsCache") or []:
            v = str(o.get("value") or "").split("[")[0]
            if v and v not in [r[0] for r in rows]:
                rows.append((v, str(o.get("description") or o.get("label") or "").split("·")[-1].strip()))
        s = str((_load(".claude", "settings.json") or {}).get("model") or "").split("[")[0]
        yours = next((i for i, _ in rows if s and (s == i or ("-" + s + "-") in ("-" + i + "-"))), None)
        default = yours or rows[0][0]
    elif cli == "codex":
        cache = (_load(".codex", "models_cache.json") or {}).get("models") or []
        rows = [(m["slug"], str(m.get("description") or "")) for m in cache
                if m.get("visibility") == "list" and m.get("slug")][:6]
        try:
            with open(os.path.join(HOME, ".codex", "config.toml"), encoding="utf-8") as f:
                for line in f:
                    m = re.match(r' *model *= *"([^"]+)"', line)
                    if m:
                        yours = m.group(1)
                        break
        except Exception:
            pass
        ids = [r[0] for r in rows]
        default = yours if yours in ids else (ids[0] if ids else None)
    elif cli == "opencode":
        try:
            out = subprocess.run(["opencode", "models"], capture_output=True, text=True, timeout=20).stdout
            found = [l.strip() for l in out.splitlines() if "/" in l.strip()]
            # The owner's own providers -- an API account, or a model this
            # machine serves -- and only those when there are any; OpenCode's
            # built-in free models otherwise.
            own = [m for m in found if not m.startswith("opencode/")]
            rows = [(m, "") for m in (own or found)][:10]
        except Exception:
            rows = []
    elif cli == "gemini":
        try:
            exe = shutil.which("gemini") or ""
            d = os.path.dirname(os.path.realpath(exe))
            text = "".join(open(os.path.join(d, f), encoding="utf-8", errors="ignore").read()
                           for f in os.listdir(d) if f.endswith(".js"))
            names = dict(re.findall(r'((?:PREVIEW|DEFAULT)_GEMINI(?:_FLASH)?_MODEL) = "([a-z0-9.-]+)"', text))
            for key, what in (("PREVIEW_GEMINI_MODEL", "pro, preview"), ("DEFAULT_GEMINI_MODEL", "pro"),
                              ("PREVIEW_GEMINI_FLASH_MODEL", "flash, preview"), ("DEFAULT_GEMINI_FLASH_MODEL", "flash")):
                if names.get(key, "none") != "none" and names[key] not in [r[0] for r in rows]:
                    rows.append((names[key], what))
        except Exception:
            rows = []
    return rows, default, yours


def gpus_available():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=10).stdout
        return ",".join(l.strip() for l in out.splitlines() if l.strip()) or None
    except Exception:
        return None


def installed():
    return [c for c in CLIS if shutil.which(c)]


def as_json():
    clis = []
    for c in installed():
        rows, default, yours = options(c)
        clis.append({"id": c, "models": [{"id": i, "desc": d[:120]} for i, d in rows][:12],
                     "default": yours or default})
    return {"clis": clis, "gpus_available": gpus_available()}


def numbered(cli):
    rows, default, yours = options(cli)
    w = min(max([len(i) for i, _ in rows] + [8]), 26)
    room = max(20, 70 - w)

    def fit(t, n):
        # Cut at a word, not inside one.
        return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0].rstrip(",;") + "…"

    for n, (i, d) in enumerate(rows, 1):
        mine = " (your default)" if i == yours else ""
        # Never an empty field: the menu reads these with IFS=tab, which runs
        # two tabs together, and the id would show again as its description.
        print(f"{n}\t{i.ljust(w)}\t{(fit(d, room - len(mine)) + mine).strip() or ' '}\t{i}")
    ids = [i for i, _ in rows]
    print("enter\t" + (str(ids.index(default) + 1) if default in ids else ""))


if __name__ == "__main__":
    if sys.argv[1:] == ["--json"]:
        print(json.dumps(as_json()))
    elif len(sys.argv) == 2 and sys.argv[1] in CLIS:
        numbered(sys.argv[1])
    else:
        sys.exit("usage: models.py <claude|codex|gemini|opencode> | --json")
