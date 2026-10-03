#!/usr/bin/env python3
"""models.py -- the agent CLIs on this machine, and the models each offers
its owner, read from the CLI itself rather than from a list that goes stale:
Claude Code's family and any further model its cache says the account has,
Codex's model cache, `opencode models` (the owner's own providers first),
Gemini CLI's own defaults, `cursor-agent models`, Droid's own list, Amp's
modes, and the models the owner configured for Copilot, Qwen Code, Goose,
Crush and Kimi Code.

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
CLIS = ["claude", "codex", "gemini", "opencode", "cursor-agent", "copilot", "qwen", "amp", "droid", "goose", "crush", "kimi"]
# A numbered menu stays readable up to this many; past it, a model is typed by name.
MENU_MAX = 40
# The kit's default first (agent-turn.sh runs it when AC_MODEL is unset), then
# the rest of the current family. A model the account's own cache adds comes
# after these; one missing from both can still be typed by name.
CLAUDE = [
    ("claude-sonnet-5", "balanced; lighter on your quota"),
    ("claude-opus-5-5", "stronger; uses more of it"),
    ("claude-fable-5-1", "most capable; uses the most"),
    ("claude-haiku-4-5-20251001", "fastest and lightest"),
]


def _load(*path):
    try:
        with open(os.path.join(HOME, *path), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _run(cmd, timeout=20):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL).stdout
    except Exception:
        return ""


ANSI = re.compile(r"\x1b\[[0-9;]*m")


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
        # Every model the account's cache lists (owner, 2026-10-03: show all
        # the owner has, not the first few).
        rows = [(m["slug"], str(m.get("description") or "")) for m in cache
                if m.get("visibility") == "list" and m.get("slug")]
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
            # All of them, up to a menu's worth: a provider like OpenRouter
            # lists hundreds, and any of those can still be typed by name.
            rows = [(m, "") for m in (own or found)][:MENU_MAX]
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
    elif cli == "cursor-agent":
        # "<id> - <name> (current, default)", one a line, for this account.
        for line in ANSI.sub("", _run(["cursor-agent", "models"])).splitlines():
            m = re.match(r"^([A-Za-z0-9][\w.:/\[\]=,-]*)(?: - (.*?))?(?: \(([^)]*)\))?\s*$", line.strip())
            if not m or line.strip().startswith(("Available models", "Tip:", "No models")):
                continue
            rows.append((m.group(1), m.group(2) or ""))
            if "current" in (m.group(3) or ""):
                yours = m.group(1)
            if "default" in (m.group(3) or "") and default is None:
                default = m.group(1)
        default = yours or default
    elif cli == "copilot":
        # Its models come from GitHub with each session; auto lets it pick.
        rows = [("auto", "Copilot picks for each turn")]
        mine = os.environ.get("COPILOT_MODEL") or str((_load(".copilot", "config.json") or {}).get("model") or "")
        if mine and mine != "auto":
            rows.insert(0, (mine, ""))
            yours = mine
        default = yours
    elif cli == "qwen":
        s = (_load(".qwen", "settings.json") or {}).get("model")
        mine = os.environ.get("OPENAI_MODEL") or (s.get("name") if isinstance(s, dict) else s) or ""
        if mine:
            rows, yours, default = [(str(mine), "")], str(mine), str(mine)
    elif cli == "amp":
        # Amp picks the model by its mode.
        rows = [("low", "lightest"), ("medium", ""), ("high", ""), ("ultra", "strongest")]
    elif cli == "droid":
        text = ANSI.sub("", _run(["droid", "exec", "--help"]))
        section = None
        for line in text.splitlines():
            if re.match(r"^(Available|Custom) Models:", line):
                section = line
                continue
            m = re.match(r"^  ([A-Za-z0-9][\w.:/-]*)\s{2,}(.*)$", line) if section else None
            if not m:
                if section and line.strip() and not line.startswith("  "):
                    section = None
                continue
            name = m.group(2).strip()
            if "(default)" in name:
                default = m.group(1)
            rows.append((m.group(1), name.replace("(default)", "").strip()))
    elif cli == "goose":
        try:
            with open(os.path.join(HOME, ".config", "goose", "config.yaml"), encoding="utf-8") as f:
                for line in f:
                    m = re.match(r"^GOOSE_MODEL:\s*['\"]?([^'\"\s]+)", line)
                    if m:
                        yours = m.group(1)
        except Exception:
            pass
        yours = os.environ.get("GOOSE_MODEL") or yours
        if yours:
            rows, default = [(yours, "")], yours
    elif cli == "crush":
        cfg = _load(".config", "crush", "crush.json") or {}
        for pid, p in (cfg.get("providers") or {}).items():
            for m in (p or {}).get("models") or []:
                if isinstance(m, dict) and m.get("id"):
                    rows.append((f"{pid}/{m['id']}", str(m.get("name") or "")))
        large = ((cfg.get("models") or {}).get("large") or {})
        if large.get("model"):
            yours = f"{large.get('provider')}/{large['model']}" if large.get("provider") else large["model"]
            if yours not in [r[0] for r in rows]:
                rows.insert(0, (yours, ""))
        default = yours
    elif cli == "kimi":
        try:
            with open(os.path.join(HOME, ".kimi-code", "config.toml"), encoding="utf-8") as f:
                text = f.read()
            for m in re.finditer(r'^\[models\.(?:"([^"]+)"|([A-Za-z0-9_.-]+))\]', text, re.M):
                rows.append((m.group(1) or m.group(2), ""))
            m = re.search(r'^default_model\s*=\s*"([^"]+)"', text, re.M)
            yours = m.group(1) if m else None
        except Exception:
            pass
        default = yours
    return rows[:MENU_MAX], default, yours


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
        clis.append({"id": c, "models": [{"id": i, "desc": d[:120]} for i, d in rows][:MENU_MAX],
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
        sys.exit("usage: models.py <" + "|".join(CLIS) + "> | --json")
