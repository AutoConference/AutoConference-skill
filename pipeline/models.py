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
  python3 pipeline/models.py --efforts <cli> [<model>]
                                      the efforts that CLI takes for that model
                                      (none given: its own), numbered (KIT-051)
  python3 pipeline/models.py --effort-for <cli> <model> <effort>
                                      the effort a turn passes: <effort> when
                                      they take it, else nothing, and why on stderr

The numbered list is a line per model -- number, the id padded, a few words,
the id -- and a last "enter" line: the number Enter picks. That is the model
the owner already uses in that CLI when it names one (owner, 2026-10-02), or
the one the CLI itself marks as its default; otherwise empty, and Enter
means the CLI's own default. The kit picks no model of its own (owner,
2026-10-03: "the user chooses everything"), and no position in a list is a
recommendation. The efforts' list is the same, its "enter" line always
empty: Enter is the CLI's own effort.
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
# The current Claude family, by name -- no order of preference, and none is
# run unless the owner picks it. A model the account's own cache adds comes
# after these; one missing from both can still be typed by name.
CLAUDE = [
    ("claude-fable-5-1", "Fable 5.1"),
    ("claude-haiku-4-5-20251001", "Haiku 4.5"),
    ("claude-opus-5-5", "Opus 5.5"),
    ("claude-sonnet-5", "Sonnet 5"),
]

# ── The effort an owner may choose (KIT-051) ──────────────────────────────
#
# Offered only where the CLI and the model take it, and only levels seen to
# change a turn (real runs, 2026-10-10): Claude Code 2.1.296 gave each level
# back as the turn's own CLAUDE_EFFORT, its thinking growing with it; Codex
# 0.160.1 recorded each in its session log, and its API refused a level the
# model does not list, failing the turn -- which is why a level is checked
# against the model before every turn (effort_for). No other CLI the kit
# runs has a per-turn setting the kit has seen take effect (OpenCode's
# --variant could not be run here; Gemini CLI keeps thinking in its settings
# files), so they offer none and run at their own setting. None chosen,
# nothing is passed: the turn is what it was before.
EFFORTS = ["low", "medium", "high", "xhigh", "max"]
# Claude Code takes --effort. Opus 5.5, Sonnet 5 and Fable 5.1 take all five
# (Claude Code's own model table, 2.1.296, and the runs above); Haiku 4.5
# none: it ran the same at low and max, with no effort reported. A model
# not here is one whose efforts the kit does not know, and gets none.
CLAUDE_EFFORTS = {
    "claude-fable-5-1": EFFORTS,
    "claude-haiku-4-5-20251001": [],
    "claude-opus-5-5": EFFORTS,
    "claude-sonnet-5": EFFORTS,
}
# A few words for each, in the setup's list; Codex's own words come from its cache.
EFFORT_WORDS = {"low": "quickest, thinks least", "max": "thinks most; slowest, most quota"}


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
        # Only the owner's own setting; none, and Enter is Claude Code's default.
        default = yours
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
        # The owner's own config.toml model, or Codex's default: never the
        # first of the cache.
        default = yours if yours in ids else None
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


LABELS = {"claude": "Claude Code", "codex": "Codex", "gemini": "Gemini CLI", "opencode": "OpenCode",
          "cursor-agent": "Cursor", "copilot": "GitHub Copilot", "qwen": "Qwen Code", "amp": "Amp",
          "droid": "Factory Droid", "goose": "Goose", "crush": "Crush", "kimi": "Kimi Code"}


def _claude_known(model):
    """The effort table's id for a Claude model -- its [1m] and the like
    taken off, with its date or without, or a family's bare alias ("opus")
    read as the model menu reads it -- or None when the table has none."""
    m = re.sub(r"\[[^\]]*\]$", "", (model or "").strip()).lower()
    if m in ("opus", "sonnet", "fable", "haiku"):
        m = next(i for i, _ in CLAUDE if "-" + m + "-" in "-" + i + "-")
    undated = lambda s: re.sub(r"-\d{8}$", "", s)
    return next((k for k in CLAUDE_EFFORTS if m and (m == k or undated(m) == undated(k))), None)


def _claude_own_model():
    """The model Claude Code runs when the kit names none: ANTHROPIC_MODEL,
    else its settings' model; None when neither names one."""
    s = os.environ.get("ANTHROPIC_MODEL") or str((_load(".claude", "settings.json") or {}).get("model") or "")
    return s.split("[")[0].strip() or None


def _codex_home():
    return os.environ.get("CODEX_HOME") or os.path.join(HOME, ".codex")


def _codex_config():
    """Codex's own model and provider: the top of its config.toml (a model
    under a [section] -- a profile, a project -- is not the one it runs)."""
    model = provider = None
    try:
        with open(os.path.join(_codex_home(), "config.toml"), encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("["):
                    break
                m = re.match(r'(model|model_provider)\s*=\s*"([^"]*)"', s)
                if m and m.group(1) == "model":
                    model = model or m.group(2)
                elif m:
                    provider = provider or m.group(2)
    except OSError:
        pass
    return model, provider


_CODEX_CACHE = []


def _codex_levels(model):
    """{effort: Codex's own words for it} for each effort the kit offers that
    Codex's model cache lists for this model; None when it has no such model."""
    if not _CODEX_CACHE:
        try:
            with open(os.path.join(_codex_home(), "models_cache.json"), encoding="utf-8") as f:
                _CODEX_CACHE.append((json.load(f) or {}).get("models") or [])
        except Exception:
            _CODEX_CACHE.append([])
    for m in _CODEX_CACHE[0]:
        if isinstance(m, dict) and m.get("slug") == model:
            listed = {}
            for x in m.get("supported_reasoning_levels") or []:
                if isinstance(x, dict) and x.get("effort") in EFFORTS:
                    listed[x["effort"]] = str(x.get("description") or "")
            return listed
    return None


def efforts(cli, model=""):
    """(levels, words, why, model): the efforts this CLI takes for this model,
    in order, a few words for each, why there are none (for a note), and the
    model that was looked up. No model, or "default", is the CLI's own, as the
    CLI names it; one the kit cannot name gets none."""
    model = "" if model in (None, "-", "default") else str(model).strip()
    if cli == "claude":
        m = model or _claude_own_model()
        if not m:
            return [], {}, "the model Claude Code runs by itself is not named in its settings", ""
        k = _claude_known(m)
        if k is None:
            return [], {}, "the kit does not know which efforts Claude Code takes for " + m, m
        if not CLAUDE_EFFORTS[k]:
            return [], {}, "Claude Code takes no effort for " + m, m
        return list(CLAUDE_EFFORTS[k]), dict(EFFORT_WORDS), None, m
    if cli == "codex":
        own, provider = _codex_config()
        if provider and provider != "openai":
            return [], {}, "Codex runs another provider here (" + provider + "), whose efforts the kit cannot check", model
        m = model or own
        if not m:
            return [], {}, "the model Codex runs by itself is not named in its config.toml", ""
        listed = _codex_levels(m)
        if listed is None:
            return [], {}, "Codex's model list here does not have " + m, m
        levels = [e for e in EFFORTS if e in listed]
        if not levels:
            return [], {}, "Codex lists none of the kit's efforts for " + m, m
        return levels, {e: listed[e] for e in levels}, None, m
    return [], {}, "the kit passes no effort to " + LABELS.get(cli, cli or "this CLI"), model


def effort_for(cli, model, effort):
    """(level, note): the effort a turn passes -- the one chosen, when this
    CLI and model take it -- or None and why it is left out. Left out, the
    turn runs at the CLI's own setting; it never fails for it."""
    effort = (effort or "").strip()
    if not effort:
        return None, None
    levels, _, why, m = efforts(cli, model)
    if effort in levels:
        return effort, None
    if effort not in EFFORTS:
        why = "the kit offers " + ", ".join(EFFORTS)
    elif levels:
        why = LABELS.get(cli, cli) + " takes " + ", ".join(levels) + " for " + (m or "its own model")
    return None, "effort " + effort + " left out: " + why + "; this turn runs at the CLI's own setting"


def efforts_numbered(cli, model=""):
    """The efforts' list setup and ./ac show, as numbered() is the models';
    nothing at all when there are none, and then nothing is asked."""
    levels, words, _, _ = efforts(cli, model)
    if not levels:
        return
    w = max(len(e) for e in levels)
    for n, e in enumerate(levels, 1):
        d = (words.get(e) or "").strip()
        d = d if len(d) <= 60 else d[:59].rsplit(" ", 1)[0].rstrip(",;") + "…"
        print(f"{n}\t{e.ljust(w)}\t{d or ' '}\t{e}")
    print("enter\t")


def as_json():
    clis = []
    for c in installed():
        rows, default, yours = options(c)
        models = []
        for i, d in rows[:MENU_MAX]:
            entry = {"id": i, "desc": d[:120]}
            # KIT-051: the efforts it takes, only where it takes some.
            levels = efforts(c, i)[0]
            if levels:
                entry["efforts"] = levels
            models.append(entry)
        cli = {"id": c, "models": models, "default": yours or default}
        # ...and those of the model the CLI runs by itself, for "its own".
        own = efforts(c, "")[0]
        if own:
            cli["efforts"] = own
        clis.append(cli)
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
    a = sys.argv[1:]
    if a == ["--json"]:
        print(json.dumps(as_json()))
    elif len(a) == 1 and a[0] in CLIS:
        numbered(a[0])
    elif len(a) in (2, 3) and a[0] == "--efforts":
        efforts_numbered(a[1], a[2] if len(a) == 3 else "")
    elif len(a) == 4 and a[0] == "--effort-for":
        # For pipeline/agent-turn.sh, before every turn: whatever goes wrong
        # here, the turn runs, at the CLI's own effort.
        try:
            level, note = effort_for(a[1], a[2], a[3])
        except Exception as e:
            level, note = None, "effort " + a[3] + " left out: the kit could not check it (" + type(e).__name__ + \
                "); this turn runs at the CLI's own setting"
        if note:
            print("agent-turn: " + note, file=sys.stderr)
        if level:
            print(level)
    else:
        sys.exit("usage: models.py <" + "|".join(CLIS) + "> | --json | --efforts <cli> [<model>]"
                 " | --effort-for <cli> <model> <effort>")
