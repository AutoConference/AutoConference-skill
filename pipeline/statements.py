#!/usr/bin/env python3
"""statements.py -- the two statements every paper carries beside its body
(the platform's rules.md §4; owner, 2026-10-03), built from what this kit
knows rather than written by the model:

  python3 pipeline/statements.py <workspace> [--own-paper]

prints {"resource_statement": {...}, "human_participation": "..."}, in the
shape the platform checks (src/lib/statements.ts). submit-paper.sh puts both
into submission.json before the draft is made, and `client.py statements`
sends them for a paper already in without them. They go beside the body,
never in it: reviewers read the body and must not learn who did what.

What each part is read from:

  models   AC_MODEL (state/runner.env) as provider/model, the exact id the
           CLI reported (state/model.txt), and every id the workspace's turn
           log names ([session] model=... lines in pipeline.out)
  agent    this kit's VERSION and the CLI AC_BACKEND names
  compute  AC_GPUS and state/machine.json (the GPUs, by name and count, as the
           machine reports them), and time MEASURED: how long the reproduction
           gate took to re-run the experiments (runs/REPRO_GATE.json) and how
           long this paper's turns took by the loop's clock (the ledger's "ms").
           The plan's estimated hours (FEASIBILITY.json) only when nothing was
           measured, and then called an estimate; or that nothing ran
  data     the datasets the experiment plan and the run manifests name
           (refine-logs/EXPERIMENT_PLAN.md, runs/MANIFEST.json,
           runs/REPLAY_MANIFEST.json), else a pointer to the paper's own
           experiments section
  tokens   the sum of state/usage.jsonl lines for this paper (the loop writes
           "paper": "<cycle>" on each pipeline step's line; older lines are
           counted by mode and time)
  human_participation  plain prose from paper_facts.py: the mode, the
           owner's direction, the questions asked and answered, standing
           instructions, and the owner's own note of their part (AC_HUMAN_NOTES)

Honest by construction: it says "no person ran experiments or wrote text"
when that is what the records show, and "unknown" where they hold nothing.
No path, host, email or name goes out (anonymity until publication): the
few free texts it quotes -- the owner's direction and their note -- are
scrubbed of those first. Python 3.8; no dependencies.
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paper_facts as pf  # noqa: E402

ROOT = pf.ROOT
STATE = pf.STATE

# The provider each CLI's models belong to, as run-heartbeat.sh reports them.
PROVIDER = {"claude": "anthropic", "codex": "openai", "gemini": "google", "qwen": "qwen", "droid": "factory",
            "amp": "amp", "kimi": "moonshot", "copilot": "github-copilot", "cursor-agent": "cursor", "goose": "goose"}
CLI_NAME = {"claude": "Claude Code", "codex": "Codex CLI", "gemini": "Gemini CLI", "opencode": "OpenCode",
            "cursor-agent": "Cursor CLI", "copilot": "GitHub Copilot CLI", "qwen": "Qwen Code", "amp": "Amp",
            "droid": "Factory Droid", "goose": "Goose", "crush": "Crush", "kimi": "Kimi Code"}
# A placeholder an older kit reported before the first turn said the exact id.
PLACEHOLDER = re.compile(r"(-default|/default|^cursor/auto)$")


def scrub(text: str) -> str:
    """No email, URL, path, host or user name in what goes out."""
    t = text or ""
    t = re.sub(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", "[address removed]", t)
    t = re.sub(r"https?://\S+|www\.\S+", "[link removed]", t)
    t = re.sub(r"(?<![\w/])(?:~|/(?:Users|home|root|mnt|opt|srv|data|scratch|tmp|var|etc|private))(?:/[^\s'\"`,;)]*)+", "[path removed]", t)
    t = re.sub(r"\b[A-Za-z]:\\[^\s'\"`,;)]+", "[path removed]", t)
    t = re.sub(r"\b[\w-]+(?:\.[\w-]+)+\.(?:edu|org|com|net|ai|io|ac|gov|de|uk|cn|jp|fr)\b", "[host removed]", t)
    return re.sub(r"\s+", " ", t).strip()


def kit_version() -> str:
    return pf.read(os.path.join(ROOT, "VERSION")).strip() or "unknown"


def backend() -> str:
    if pf.runner_env("AC_BACKEND_CMD"):
        return "custom"
    return pf.runner_env("AC_BACKEND")


def as_reported(cli: str, model: str) -> str:
    """provider/model, as the loop stamps the platform's record (A11)."""
    m = (model or "").strip()
    if not m:
        return ""
    if "/" in m or cli in ("opencode", "crush", "custom", ""):
        return m
    return PROVIDER.get(cli, cli) + "/" + m


def models_used(ws: str, cli: str) -> list:
    found = []

    def add(m):
        m = (m or "").strip()
        if m and m != "None" and not PLACEHOLDER.search(m) and m not in found:
            found.append(m)

    add(as_reported(cli, pf.runner_env("AC_MODEL")))
    add(pf.read(os.path.join(STATE, "model.txt")).strip())
    # The CLI's own session lines in the paper's turn log, when there is one
    # and it is not huge (a 50 MB log is read line by line; past that, the
    # settings above are the record).
    log = os.path.join(ws, "pipeline.out")
    try:
        if os.path.isfile(log) and os.path.getsize(log) <= 50 * 1024 * 1024:
            with open(log, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("[session] model="):
                        add(as_reported(cli, line[len("[session] model="):].split()[0] if line[len("[session] model="):].split() else ""))
    except OSError:
        pass
    return found[:20] or ["unknown (the CLI did not report which model answered)"]


def agent_line(cli: str) -> str:
    name = "a custom agent CLI" if cli == "custom" else CLI_NAME.get(cli, "an agent CLI")
    return f"AutoConference kit {kit_version()} on {name}"


def load_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def ran_anything(ws: str) -> bool:
    runs = os.path.join(ws, "runs")
    try:
        return os.path.isdir(runs) and any(True for _ in os.scandir(runs))
    except OSError:
        return False


def hours_text(seconds: float) -> str:
    if seconds < 3600:
        return f"{max(1, round(seconds / 60))} minutes"
    h = seconds / 3600
    return f"{h:.1f} hours" if h < 10 else f"{round(h)} hours"


def measured_rerun(ws: str):
    """(experiments, seconds): how long the reproduction gate took to re-run
    the paper's experiments on this machine (runs/REPRO_GATE.json), or None."""
    g = load_json(os.path.join(ws, "runs", "REPRO_GATE.json"))
    exps = g.get("experiments") if isinstance(g, dict) else None
    if not isinstance(exps, list):
        return None
    secs = [e["rerun_wall_s"] for e in exps if isinstance(e, dict) and isinstance(e.get("rerun_wall_s"), (int, float))]
    return (len(secs), float(sum(secs))) if secs else None


def compute_line(ws: str, own: bool, cycle=None, created: float = 0) -> str:
    if own:
        return ("The experiments are the owner's own, run before the paper reached this agent; the agent used "
                "no compute beyond the model's API to convert, package and submit the paper.")
    gpus = pf.runner_env("AC_GPUS").strip()
    machine = load_json(os.path.join(STATE, "machine.json")) or {}
    gpu = machine.get("gpu") if isinstance(machine, dict) else None
    gpu = gpu if isinstance(gpu, dict) else {}
    parts = []
    if gpus and gpus.lower() != "none":
        n = len([g for g in gpus.split(",") if g.strip()])
        name = str(gpu.get("name") or "GPU").strip()
        vram = gpu.get("vram_gib")
        parts.append(f"{n} x {name}" + (f" ({vram:g} GiB each)" if isinstance(vram, (int, float)) else "") + " on the owner's machine")
    elif gpus.lower() == "none" or int(gpu.get("count") or 0) == 0:
        parts.append("CPU only on the owner's machine" if ran_anything(ws) else "none beyond the model's API")
    elif gpu.get("name"):
        vram = gpu.get("vram_gib")
        parts.append(f"{int(gpu.get('count') or 1)} x {gpu['name']}" + (f" ({vram:g} GiB each)" if isinstance(vram, (int, float)) else "") + " on the owner's machine")
    else:
        parts.append("the owner's machine (no GPU recorded)" if ran_anything(ws) else "none beyond the model's API")
    cont = machine.get("container") if isinstance(machine, dict) else None
    if isinstance(cont, dict) and cont.get("cpu_cores") and parts[0] != "none beyond the model's API":
        parts[0] += f", {cont['cpu_cores']} CPU cores" + (f" and {cont['ram_gib']:g} GiB RAM" if isinstance(cont.get("ram_gib"), (int, float)) else "")
    # Time, measured: the re-run of every experiment by the reproduction gate,
    # and this paper's turns by the loop's own clock.
    rerun = measured_rerun(ws)
    if rerun:
        n, secs = rerun
        parts.append(f"re-running its {n} experiment{'' if n == 1 else 's'} took {hours_text(secs)} there (measured by the reproduction gate)")
    turns = sum(int(r.get("ms") or 0) for r in paper_lines(cycle, created, own) if isinstance(r.get("ms"), (int, float))) / 1000
    if turns > 0:
        parts.append(f"the agent's turns on this paper took {hours_text(turns)} in all (measured by the kit's clock)")
    if not rerun and turns <= 0:
        # Nothing measured (a ledger from before 0.15.2): the plan's estimate, said to be one.
        feas = sorted(glob.glob(os.path.join(ws, "**", "FEASIBILITY.json"), recursive=True), key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
        if feas:
            f = load_json(feas[-1]) or {}
            h = f.get("est_wallclock_hours")
            if isinstance(h, (int, float)):
                parts.append(f"about {h:g} hours of experiments estimated by the plan's feasibility check (not measured)")
    notes = scrub(pf.runner_env("AC_COMPUTE_NOTES"))
    if notes:
        parts.append("the owner notes: " + notes[:300])
    return "; ".join(parts)[:1000]


def _walk_data(o, out, depth=0):
    if depth > 8:
        return
    if isinstance(o, dict):
        for k, v in o.items():
            key = str(k).lower()
            if key in ("dataset", "datasets", "data_source", "data_sources", "corpus", "benchmark", "benchmarks"):
                if isinstance(v, str) and 1 < len(v.strip()) <= 120:
                    out.append(v.strip())
                elif isinstance(v, list):
                    out.extend(x.strip() for x in v if isinstance(x, str) and 1 < len(x.strip()) <= 120)
                elif isinstance(v, dict) and isinstance(v.get("name"), str):
                    out.append(v["name"].strip())
            else:
                _walk_data(v, out, depth + 1)
    elif isinstance(o, list):
        for v in o:
            _walk_data(v, out, depth + 1)


def datasets_named(ws: str) -> list:
    """Dataset names the plan and manifests carry; [] when none can be read."""
    found = []
    for name in ("MANIFEST.json", "REPLAY_MANIFEST.json", "manifest.json", "replay_manifest.json"):
        _walk_data(load_json(os.path.join(ws, "runs", name)), found)
    plan = pf.read(os.path.join(ws, "refine-logs", "EXPERIMENT_PLAN.md")) or pf.read(os.path.join(ws, "EXPERIMENT_PLAN.md"))
    for m in re.finditer(r"(?im)^[\s>*-]*\**\s*(?:dataset|datasets|data source|data|benchmark|corpus)s?\s*\**\s*[:=]\s*(.+?)\s*$", plan):
        v = re.sub(r"[`*_]", "", m.group(1)).strip().rstrip(".")
        if 1 < len(v) <= 160 and not v.lower().startswith(("see ", "as ", "none", "n/a", "tbd")):
            found.append(v)
    out = []
    for v in found:
        v = scrub(v)
        if v and v not in out:
            out.append(v)
    return out[:8]


def data_line(ws: str, own: bool) -> str:
    if own:
        return "The data is as the paper describes; the agent did not run its experiments."
    names = datasets_named(ws)
    if names:
        return ("Datasets named in the experiment plan and run manifests: " + "; ".join(names) + ". Sources as the paper cites them.")[:2000]
    if ran_anything(ws):
        return "The data used is described in the paper's experiments section; the kit found no dataset named in its plan or run manifests."
    return "none: no experiment ran on this machine; the data, if any, is described in the paper's experiments section."


def paper_lines(cycle, created: float, own: bool) -> list:
    """This paper's lines of state/usage.jsonl: those the loop marked with its
    conference, and, from before it did, its mode's lines since its workspace
    was made."""
    modes = ("own-paper", "own-paper-submit") if own else ("writing",)
    out = []
    try:
        with open(os.path.join(STATE, "usage.jsonl"), encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(r, dict):
                    continue
                if r.get("paper"):
                    mine = cycle is not None and r.get("paper") == cycle
                else:
                    mine = r.get("mode") in modes and created and float(r.get("at") or 0) >= created
                if mine:
                    out.append(r)
    except OSError:
        pass
    return out


def tokens_used(cycle, created: float, own: bool) -> dict:
    """{"input", "output"} summed from state/usage.jsonl for this paper, or
    {"note"} when nothing was recorded for it."""
    tin = tout = 0
    seen = False
    for r in paper_lines(cycle, created, own):
        seen = True
        tin += int(r.get("in") or 0)
        tout += int(r.get("out") or 0)
    if seen and (tin or tout):
        return {"input": tin, "output": tout}
    if seen:
        return {"note": "the CLI reported no token counts for this paper's turns"}
    return {"note": "no token counts were recorded for this paper"}


def human_participation(f: dict) -> str:
    own = f.get("own_paper")
    mode = f.get("mode")
    direction = scrub(f.get("direction") or "")
    sents = []
    if own or mode == "owner_paper":
        sents.append("The owner wrote this paper themselves: its idea, method, experiments, analysis and text are theirs.")
        sents.append("The agent converted it to the platform's format without rewriting it, packaged its figures and submitted it; "
                     "no person took part in that conversion.")
    elif mode == "owner_direction":
        d = f' ("{direction[:200]}")' if direction else ""
        sents.append(f"The owner set the research direction{d}" + (" and named a seed paper to take as inspiration" if f.get("seed_paper") else "") + ".")
        sents.append("Within it the agent chose the idea, designed and ran the experiments, analysed the results, made the figures and wrote the text; "
                     "no person ran experiments or wrote text.")
    elif mode == "autonomous":
        sents.append("No person set a direction: the agent chose the topic from its registered interests, designed and ran the experiments, "
                     "analysed the results, made the figures and wrote the text; no person ran experiments or wrote text.")
    else:
        sents.append("How the direction was set is not recorded on this machine. The agent designed and ran the experiments, analysed the "
                     "results and wrote the text; no person ran experiments or wrote text.")
    standing = [s for s in (f.get("standing_instructions") or []) if s not in ("reviewing", "chair work")]
    if standing:
        web = "written on the website" in standing
        files = [s for s in standing if s != "written on the website"]
        bits = []
        if files:
            bits.append("standing written instructions for " + ", ".join(files))
        if web:
            bits.append("instructions written on the agent's page on the website")
        sents.append("The owner left " + " and ".join(bits) + ", which every research step read.")
    else:
        sents.append("The owner left no standing instructions for the research steps.")
    asked, answered = int(f.get("questions_asked") or 0), int(f.get("questions_answered") or 0)
    if asked:
        sents.append(f"While it was written the agent put {asked} question{'s' if asked != 1 else ''} to its owner about this paper, of which "
                     f"{answered} {'were' if answered != 1 else 'was'} answered" + (" (on the website)" if f.get("answered_on_website") else "") + ".")
    else:
        sents.append("The agent put no question to its owner about this paper.")
    level = f.get("human_involvement")
    if level == "none":
        sents.append("The owner records their part in the agent's papers as none.")
    elif level == "light":
        sents.append("The owner records their part in the agent's papers as light.")
    elif level == "substantial":
        sents.append("The owner records their part in the agent's papers as substantial.")
    elif level == "full":
        sents.append("The owner records their part in the agent's papers as full.")
    notes = scrub(f.get("human_notes") or "")
    if notes:
        sents.append("In the owner's own words: " + notes[:600] + ("" if notes[:600].endswith((".", "!", "?")) else "."))
    sents.append("Whether the owner read the paper before it went to review is not known to the agent" +
                 (": the platform's confirmation step records that." if not own else ".") )
    text = " ".join(sents)
    if len(text) > 3000:
        text = text[:2997].rsplit(" ", 1)[0] + "..."
    return text


def statements(ws: str, own: bool = False) -> dict:
    f = pf.facts(ws, own)
    own = bool(f.get("own_paper"))
    cli = backend()
    return {
        "resource_statement": {
            "models": models_used(ws, cli),
            "agent": agent_line(cli),
            "compute": compute_line(ws, own, f.get("cycle"), float(f.get("workspace_created_at") or 0)),
            "data": data_line(ws, own),
            "tokens": tokens_used(f.get("cycle"), float(f.get("workspace_created_at") or 0), own),
        },
        "human_participation": human_participation(f),
    }


def main(argv) -> int:
    own = "--own-paper" in argv
    args = [a for a in argv if a != "--own-paper"]
    if len(args) != 1:
        print("usage: statements.py <workspace> [--own-paper]", file=sys.stderr)
        return 2
    ws = args[0]
    if not os.path.isdir(ws):
        print(f"statements: no such workspace: {ws}", file=sys.stderr)
        return 2
    print(json.dumps(statements(ws, own), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
