#!/usr/bin/env python3
"""repro-gate -- re-run the experiments and check the paper's numbers survive.

This stands in for ARIS's cross-model experiment audit. That chain needs a
reviewer from a different model family (GPT via Codex MCP, or Gemini); this
container has no node, so it is unavailable. A deterministic check is a better
substitute than an LLM auditing its own work anyway: it re-executes each script
from a clean directory and diffs what comes out against what was recorded.

Convention -- work/<cycle>/runs/manifest.json:

    {
      "env": {"CUDA_VISIBLE_DEVICES": "0"},
      "experiments": [
        {
          "script": "bench_collapse.py",
          "output": "results/collapse.json",
          "args": ["--seeds", "3"],
          "exact":     ["accuracy", "n_solved", "collapse_point"],
          "tolerant":  {"loss": 0.01},
          "timing":    ["wall_s", "tok_per_s"],
          "timeout_s": 3600
        }
      ]
    }

`exact` fields must come out the same -- these are the numbers a paper may
claim. An integer or a string must match exactly; a float must match to
floating-point precision (relative 1e-9): a sum taken in another order -- a
process pool, a threaded or GPU reduction -- moves the last bits (about 1e-16
of the value), and that is the same number, not a failed reproduction (a
participant's report, 2026-10-03: six fields differing in the 16th digit
failed a paper three times). `tolerant` fields are results that genuinely vary
from run to run (a nondeterministic GPU kernel, thread timing) and may drift
by the given relative amount. `timing` fields measure the machine, not the
result -- wall-clock time, throughput: they are re-measured and reported,
never compared, since a busy machine is not an unreproducible experiment (the
same report: 5.52 s then 7.29 s failed the gate); a paper reports them as
approximate, with the hardware. A `tolerant` field named like a timing
(`wall_s`, `elapsed`, `tok_per_s`, ...) is read as `timing`, so a manifest
written before `timing` existed is judged the same way.
Anything in the recorded output that is listed in none of the three is
reported as UNCLASSIFIED and fails the gate: an unlabelled number is one
nobody decided was reproducible.

Each entry runs alone, in a fresh copy of the workspace without results/
(nor data/, figures/ or any environment), so a script must compute what it
reports. One that reads another entry's results names it in `after` (its
script or its output): that entry runs first, in the same copy, and the
script reads what it re-made -- a slow computation split from the analyses
built on it reproduces as one chain (a tester's report, 2026-10-06: two
analyses reading another entry's output crashed in the gate, which the agent
was never told). `python` names the interpreter to re-run with (a path, or
a command as a list), when it is not this one.

A failed entry says how it failed (`failure`): `mismatch` -- a number came
out different, a finding about the experiment -- or one the agent can repair:
`crashed` (with its `cause`: another entry's output read without `after`, a
module missing, a library built for another CPU architecture...), `timeout`,
`no_output`, `no_recorded_output`, `blocked` (an entry it reads did not run),
`unclassified`, a `manifest` that cannot be read. The last lines printed are
the failures, not the report's tail (a tester's report, 2026-10-06: the stop
note showed timing drifts; the two crashes that stopped the paper were above
them). --summary reads the last report and says it for a person or a turn
(exit 0 = the agent can repair it, 1 = a finding, 2 = no report).

--retry-failed, after a repair: only what failed runs again, with what reads
it, and the rest keeps its verdict -- unless anything else it ran with
changed (another file of the workspace, an entry's script or recorded
output, the manifest's env or python), when every entry runs again. The
fingerprints are in .aris/repro-state.json, which running any earlier step
removes, so a gate run after the experiments changed is always a full one.
An entry that failed and was then taken out of the manifest fails as
`removed`: an experiment that does not reproduce is not dropped to pass.

The paper's printed numbers (submission.json, when there is one; always with
--claims-only) must each trace to a result: by rounding, to a result number of
the metric the paper prints it as when it names one the results declare, or
else literally, by ARIS's evidence_check.py. The gates' own reports
(REPRO_GATE.json) are never evidence. A number the checker could not decide is
"unchecked", never passed.

Exit 0 = PASS, 1 = FAIL, 2 = the manifest or layout is wrong,
3 = UNCHECKED: the cited numbers could not be checked (no paper to read, or the
checker could not run) -- for a person, not a rewrite.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verdict as aris_audit  # noqa: E402

NUM = (int, float)

# A number worth checking: has a decimal point, or is at least three digits.
# Below that the paper is saying "3 seeds" or "Table 2", and demanding those
# appear in a results file produces noise that hides the real failures.
# A number may end its sentence: "reaches 0.81." -- the old pattern refused a
# following "." and so never checked the number a sentence ends on, which is
# where a headline result usually sits (found 2026-10-08). A version, 1.2.3,
# is still not one.
MEANINGFUL = re.compile(r"(?<![\w.])(\d+\.\d+|\d{4,})(?![\w]|\.\d)")
# The sign in front of a printed number, when there is one: ASCII hyphen, the
# Unicode minus, or LaTeX's $-$. A difference table prints "-95.9 [-98.8,-92.6]";
# read without its sign, -95.9 in the results never matched, and every
# negative result in a paper was reported as fabricated.
SIGN_BEFORE = re.compile(r"(?:-|\u2212|\$-\$|\$\u2212\$)$")

# An arXiv id is shaped exactly like a number the paper might claim, and it is
# never a result. Citing arXiv:2506.09250 must not read as claiming 2506.0925.
ARXIV_ID = re.compile(r"(?:arxiv[:\s]*)?(\d{4}\.\d{4,5})(?:v\d+)?", re.I)

# The reference list make_submission.py renders from references.bib (KIT-045):
# its arXiv ids and DOIs are the works the text already cites, so counted
# again they would double the paper's citations; its years, volumes and pages
# are nobody's results. Checks that read the paper's own text read it without.
REF_HEADING = re.compile(r"^(#{1,6})[ \t]*(?:\d+(?:\.\d+)*\.?[ \t]+)?(?:references|bibliography)[ \t]*$", re.I | re.M)


def without_reference_list(md: str) -> str:
    m = REF_HEADING.search(md)
    if not m:
        return md
    nxt = re.compile(r"^#{1,%d}[ \t]" % len(m.group(1)), re.M).search(md, m.end())
    return md[: m.start()] + (md[nxt.start():] if nxt else "")


def blank_reference_list(md: str) -> str:
    """The reference list's characters as spaces (its line breaks kept): read
    as without it, while every other character keeps its offset -- which is
    how the evidence ledger says where each \\ev value stands."""
    m = REF_HEADING.search(md)
    if not m:
        return md
    nxt = re.compile(r"^#{1,%d}[ \t]" % len(m.group(1)), re.M).search(md, m.end())
    end = nxt.start() if nxt else len(md)
    return md[: m.start()] + re.sub(r"[^\n]", " ", md[m.start():end]) + md[end:]



# The gates' own reports sit under runs/ beside the results, and list the very
# numbers a paper printed -- the unsupported ones too, as strings. Read as
# evidence, a second check passed every number the first had found unsupported
# (found 2026-10-05). A report is never evidence.
GATE_OUTPUTS = {"REPRO_GATE.json"}

# What a paper's numbers may come from, and what a gate reads
# (interfaces/evidence-interface.md): the experiments' declared outputs, the
# aggregates and DESIGN.json, this machine -- summaries, each at most
# EVIDENCE_FILE_MAX. Never the raw data beside them: a tester's 834 MB of
# per-prediction JSONL, read whole, took WSL down (2026-10-08), and searched,
# almost any number is somewhere among millions.
EVIDENCE_FILE_MAX = 32 * 1024 * 1024
RAW_FILE_MAX = 8 * 1024 * 1024       # a paper begun before the chain (§6): a raw file read for a number
RAW_TOTAL_MAX = 128 * 1024 * 1024
EVIDENCE_STATE = os.path.join(".aris", "evidence.json")

# What a result number is called, so a paper's number is matched only to a
# result of the metric it is printed as (a tester's report, 2026-10-05: a
# number printed as an accuracy passed because a loss had the same value).
# A key made only of these words names a statistic of something, not a metric:
# its metric is its siblings', its parent's, or the one its file declares.
STAT_WORDS = {
    "mean", "avg", "average", "median", "std", "stdev", "sd", "se", "sem", "var", "variance",
    "ci", "low", "high", "lower", "upper", "lo", "hi", "min", "max", "n", "count", "values",
    "value", "estimate", "est", "point", "uncertainty", "range", "iqr", "overall", "per",
    "split", "paired", "contrast", "delta", "diff", "difference", "gap", "margin", "total",
    "sum", "raw", "result", "results", "summary", "stats", "statistics",
}
ALIASES = {"acc": "accuracy", "accuracies": "accuracy", "err": "error", "ppl": "perplexity"}


def name_tokens(key) -> list:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(key))
    return [ALIASES.get(t, t) for t in re.findall(r"[a-z0-9]+", s.lower())]


def canon(key) -> str:
    return " ".join(name_tokens(key))


def is_stat(key) -> bool:
    toks = name_tokens(key)
    return all(t in STAT_WORDS or t.isdigit() for t in toks)


def entries_of(doc, where: str, out: list, declared: set, keep=None) -> None:
    """Every leaf number in a parsed results file, with the names it is stored
    under: its own key; for a statistic (mean, ci_low, values...), the metric
    beside it or above it; and any metric a dict around it declares
    ("metric": "accuracy", as every aggregate does). `keep`: only the numbers
    it accepts are kept -- the ones that could be a number the paper prints --
    so a check's memory grows with the paper, never with the results."""
    def walk(obj, path: str, parent: str, metrics: frozenset) -> None:
        if isinstance(obj, dict):
            own = {canon(obj[k]) for k in ("metric", "metric_display", "metric_name")
                   if isinstance(obj.get(k), str) and obj[k].strip()}
            declared.update(own)
            metrics = metrics | own
            beside = {canon(k) for k, v in obj.items()
                      if isinstance(v, NUM) and not isinstance(v, bool) and not is_stat(k)}
            for k, v in obj.items():
                p = f"{path}.{k}" if path else str(k)
                if isinstance(v, (dict, list)):
                    walk(v, p, k, metrics)
                elif isinstance(v, NUM) and not isinstance(v, bool):
                    if keep is not None and not keep(v):
                        continue
                    names = set(metrics)
                    if not is_stat(k):
                        names.add(canon(k))
                    elif beside:
                        names |= beside
                    elif parent and not is_stat(parent):
                        names.add(canon(parent))
                    out.append((v, frozenset(n for n in names if n), f"{where}:{p}"))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                p = f"{path}[{i}]"
                if isinstance(v, (dict, list)):
                    walk(v, p, parent, metrics)
                elif isinstance(v, NUM) and not isinstance(v, bool):
                    if keep is not None and not keep(v):
                        continue
                    names = set(metrics)
                    if parent and not is_stat(parent):
                        names.add(canon(parent))
                    out.append((v, frozenset(n for n in names if n), f"{where}:{p}"))
    walk(doc, "", "", frozenset())


def config_files() -> list:
    """This machine's description and the quality bar: a paper legitimately
    states hardware facts and configuration constants that are not results
    (AC_MACHINE, default state/machine.json; interfaces/quality.example.json)."""
    kit = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return [p for p in (os.environ.get("AC_MACHINE") or os.path.join(kit, "state", "machine.json"),
                        os.path.join(kit, "interfaces", "quality.example.json")) if os.path.isfile(p)]


def raw_matches(runs: str, keep, skip: set) -> tuple:
    """A paper begun before the evidence chain (interfaces/evidence-interface.md
    §6): the results files under runs/ that are not evidence, read for the
    numbers `keep` accepts only. A file over RAW_FILE_MAX is not read, nor
    anything past RAW_TOTAL_MAX in all: a raw file is data, and the paper's
    numbers belong in its summaries. Returns (entries, declared, skipped)."""
    out, declared, skipped, total = [], set(), [], 0
    for dirpath, dirnames, names in os.walk(runs):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__" and not d.startswith("."))
        for name in sorted(names):
            if not name.endswith((".json", ".jsonl")) or name in GATE_OUTPUTS:
                continue
            path = os.path.join(dirpath, name)
            where = os.path.relpath(path, os.path.dirname(os.path.abspath(runs)))
            if where in skip or os.path.islink(path):
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if size > RAW_FILE_MAX or total + size > RAW_TOTAL_MAX:
                skipped.append(f"{where} ({size / 1048576:.1f} MiB)")
                continue
            total += size
            try:
                with open(path, encoding="utf-8") as f:
                    if name.endswith(".jsonl"):
                        for line in f:
                            line = line.strip()
                            if line:
                                entries_of(json.loads(line), where, out, declared, keep)
                    else:
                        entries_of(json.load(f), where, out, declared, keep)
            except (OSError, ValueError, RecursionError):
                continue
    return out, declared, skipped


def rounds_to(value: str, pool: list) -> bool:
    """Does any result number round to what the paper printed, at the precision
    the paper printed it? A paper that writes 0.067 for 0.06666... is being
    normal, not unsupported."""
    try:
        want = float(value)
    except ValueError:
        return False
    dp = len(value.split(".")[1]) if "." in value else 0
    return any(round(float(n), dp) == round(want, dp) for n in pool
               if isinstance(n, NUM) and not isinstance(n, bool))


# Deliberately no `is_derived` helper. An earlier version accepted any number that
# was a ratio or difference of two pool values; measured against this repo's own
# example (a 1652-number pool) it accepted all 100 two-decimal values from 0.00 to
# 0.99, plus 3.14 and 99.9. A rule that accepts everything is not a check. Upstream
# AutoConference's paper-writing skill states the correct rule, and we adopt it:
# a gain computed from two tabled values is still untraceable -- put the derived
# value in a table or drop it from the prose.

CITATION_NEAR = re.compile(r"arxiv[:\s]*\d{4}\.\d{4,5}", re.I)

# Author-year citations -- "(Cohen et al., 2021; Damian et al., 2023)" and
# "Wilson (1927)" -- which is how paper-writing's papers cite once rendered.
# The year in one is the cited work's, never a claim about this experiment; the
# check was built on papers that cited by arXiv id and read every such year as
# a fabricated result. Also a year range written in prose ("2025–2026").
_AUTHOR = r"[A-Z][A-Za-z'\-]+(?: et al\.)?(?:,? (?:and|&) [A-Z][A-Za-z'\-]+)?"
_YEAR = r"(?:19|20)\d{2}[a-z]?"
CITATION_SPANS = [
    re.compile(r"\([^()]*?" + _AUTHOR + r",? " + _YEAR + r"[^()]*\)"),   # (Author, 2020; ...)
    re.compile(_AUTHOR + r" \(" + _YEAR + r"(?:[,;][^()]*)?\)"),          # Author (2020)
    re.compile(r"(?<!\d)(?:19|20)\d{2}\s*[–—-]\s*(?:19|20)\d{2}(?!\d)"),   # 2025–2026
]
YEAR = re.compile(r"(?:19|20)\d{2}")

# Standard constants a methods section prints and no experiment produces: the
# normal quantiles behind 90/95/99% intervals, pi, e.
CONSTANTS = [1.959964, 1.644854, 2.575829, 3.14159265, 2.71828183]


class PaperUnreadable(Exception):
    pass


def words_of(text: str) -> list:
    return [ALIASES.get(t, t) for t in re.findall(r"[a-z0-9]+", text.lower())]


def _same_word(w: str, t: str) -> bool:
    if w == t:
        return True
    a, b = (w, t) if len(w) >= len(t) else (t, w)   # one may be the plural of the other
    return a in (b + "s", b + "es") or (b.endswith("y") and a == b[:-1] + "ies")


def named_in(phrase: str, words: list) -> bool:
    p = phrase.split()
    if not p:
        return False
    return any(all(_same_word(words[i + j], p[j]) for j in range(len(p)))
               for i in range(len(words) - len(p) + 1))


def read_with(text: str, start: int, end: int) -> str:
    """The words a printed number is read with: in a table, its column's
    header and the table's caption; in prose, its sentence."""
    ls = text.rfind("\n", 0, start) + 1
    le = text.find("\n", end)
    le = len(text) if le < 0 else le
    if text[ls:le].lstrip().startswith("|"):
        lines = text[:le].split("\n")
        i = len(lines) - 1
        while i > 0 and lines[i - 1].lstrip().startswith("|"):
            i -= 1
        header = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        col = text[ls:start].count("|") - 1
        head = header[col] if 0 <= col < len(header) else ""
        before = "\n".join(lines[:i]).rstrip()
        caption = before[before.rfind("\n\n") + 2:] if "\n\n" in before else before
        return head + "\n" + caption[-400:]
    a = max([start - 300] + [text.rfind(s, 0, start) for s in (". ", "? ", "! ", "\n\n", "\n|")])
    ends = [i for i in (text.find(s, end) for s in (". ", "? ", "! ", "\n\n")) if i >= 0]
    b = min(ends + [end + 300])
    return text[max(0, a):b]


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_state(work: str) -> dict:
    """What each gate verified, by hash (EVIDENCE_STATE): the declared outputs
    step 10 re-made, the files the aggregation replay re-made, its script and
    the manifest it ran from."""
    try:
        with open(os.path.join(work, EVIDENCE_STATE), encoding="utf-8") as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(work: str, section: str, value) -> None:
    st = load_state(work)
    st[section] = value
    os.makedirs(os.path.join(work, ".aris"), exist_ok=True)
    tmp = os.path.join(work, EVIDENCE_STATE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1, sort_keys=True)
    os.replace(tmp, os.path.join(work, EVIDENCE_STATE))


def aggregation_of(man: dict):
    """The manifest's `aggregation` entry, checked; None when it has none (a
    paper begun before the evidence chain)."""
    agg = man.get("aggregation")
    if agg is None:
        return None
    if not isinstance(agg, dict) or not isinstance(agg.get("script"), str) or not agg["script"]:
        raise ManifestError("`aggregation` must be {\"script\": \"aggregate.py\", \"outputs\": [\"aggregate__*.json\", "
                            "\"DESIGN.json\"]}: the script that writes the aggregates from the declared outputs")
    outs = agg.get("outputs")
    if isinstance(outs, str):
        outs = [outs]
    if not isinstance(outs, list) or not outs or not all(isinstance(o, str) and o for o in outs):
        raise ManifestError("`aggregation.outputs` names the files aggregate.py writes, relative to runs/ "
                            "(\"aggregate__*.json\", \"DESIGN.json\")")
    for o in outs + [agg["script"]]:
        if not contained(o):
            raise ManifestError(f"`aggregation`: {o} must be a path inside runs/")
    return {**agg, "outputs": outs}


def within(root: str, path: str) -> bool:
    """`path` is a file under `root` once every link on the way is followed:
    a linked folder under runs/ must not bring another tree's files in."""
    r = os.path.realpath(root)
    return os.path.realpath(path).startswith(r + os.sep)


def aggregation_outputs(runs: str, agg: dict) -> list:
    """The files under runs/ the aggregation writes, as runs/-relative paths."""
    import glob
    found = set()
    for pat in agg["outputs"]:
        for p in glob.glob(os.path.join(runs, pat)):
            if os.path.isfile(p) and not os.path.islink(p) and within(runs, p):
                found.add(os.path.relpath(p, runs))
    return sorted(found)


def evidence_files(work: str, runs: str, man: dict, aggregation: dict | None = None) -> tuple:
    """What a paper's numbers may come from (interfaces/evidence-interface.md):
    the declared outputs step 10 verified, the files the aggregation replay
    verified, this machine's description. Returns (files, legacy, notes):
    each file {rel, path, role}; `legacy` when the manifest has no aggregation
    (a paper begun before the chain: its aggregates count, unverified); notes
    say what was left out and why. `aggregation`: the hashes a replay made
    just now, which step 14 trusts over what .aris/evidence.json says."""
    state = load_state(work)
    if aggregation is not None:
        state = {**state, "aggregation": aggregation}
    files, notes, seen = [], [], set()
    try:
        agg = aggregation_of(man)
    except ManifestError as e:
        agg, notes = None, notes + [str(e)]
    legacy = agg is None

    def add(rel: str, role: str, verified) -> None:
        path = os.path.join(work, rel)
        if rel in seen or not os.path.isfile(path) or os.path.islink(path):
            return
        if not within(runs, path):
            notes.append(f"{rel} is not a file under runs/: not evidence")
            return
        seen.add(rel)
        size = os.path.getsize(path)
        if size > EVIDENCE_FILE_MAX:
            notes.append(f"{rel} is {size / 1048576:.0f} MiB: not a summary, so not read as evidence "
                         f"(interfaces/evidence-interface.md, link 1)")
            return
        if verified is not None and verified != sha256_of(path):
            notes.append(f"{rel} changed after it was verified ({role}): not evidence until the gate verifies it again")
            return
        files.append({"rel": rel, "path": path, "role": role})

    declared = state.get("declared") or {}
    for e in man.get("experiments") or []:
        if isinstance(e, dict) and isinstance(e.get("output"), str):
            rel = "runs/" + e["output"].lstrip("/")
            add(rel, "declared output", None if legacy and rel not in declared else declared.get(rel, ""))
    if legacy:
        for rel in sorted(glob_rel(runs, "aggregate__*.json")) + (["DESIGN.json"] if os.path.isfile(os.path.join(runs, "DESIGN.json")) else []):
            add("runs/" + rel, "aggregate (unverified: begun before the evidence chain)", None)
    else:
        verified = (state.get("aggregation") or {}).get("outputs") or {}
        for rel in aggregation_outputs(runs, agg):
            add("runs/" + rel, "aggregation output", verified.get("runs/" + rel, ""))
    for p in config_files():
        rel = os.path.basename(p)
        if rel not in seen:
            seen.add(rel)
            files.append({"rel": rel, "path": p, "role": "configuration"})
    return files, legacy, notes


def glob_rel(runs: str, pattern: str) -> list:
    import glob
    return [os.path.relpath(p, runs) for p in glob.glob(os.path.join(runs, pattern))
            if os.path.isfile(p) and not os.path.islink(p) and within(runs, p)]


def ev_format(value, places=None, pct: bool = False) -> str:
    """What \\ev prints (interfaces/evidence-interface.md §2), as
    paper-writing/scripts/make_paper_data.py writes it: an integer as it is;
    any other number to `places` decimals -- 3 by default, 1 for a percentage
    -- rounded half up from the number as the file writes it."""
    from decimal import ROUND_HALF_UP, Decimal
    d = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    if pct:
        d *= 100
        places = 1 if places is None else places
    elif places is None:
        if isinstance(value, int):
            return str(value)
        places = 3
    q = d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    s = format(q, "f")
    return s[1:] if s.startswith("-") and q == 0 else s


def field_value(doc, field):
    for k in field:
        if isinstance(doc, dict) and isinstance(k, str) and k in doc:
            doc = doc[k]
        elif isinstance(doc, list) and isinstance(k, int) and not isinstance(k, bool) and 0 <= k < len(doc):
            doc = doc[k]
        else:
            return None
    return doc if isinstance(doc, NUM) and not isinstance(doc, bool) and math.isfinite(doc) else None


LEDGER_MAX = 8 * 1024 * 1024
EV_PLACES = {False: range(0, 5), True: range(0, 3)}    # what \\ev and \\evpct take


def verify_ledger(work: str, files: list, parts: dict) -> tuple:
    """The values the paper printed with \\ev (evidence-ledger.json), each
    re-read from the file and field the converter recorded, and found in the
    paper's text exactly where the ledger says it stands (`parts`: the
    abstract and the body as submitted). Returns ({(part, offset): digits} for
    each value so found -- a number typed by hand anywhere else is checked
    like any other, even where it is equal to one -- and the entries that are
    not sourced)."""
    path = os.path.join(work, "evidence-ledger.json")
    try:
        if os.path.getsize(path) > LEDGER_MAX:
            return {}, [{"value": None, "why": "evidence-ledger.json is larger than any paper's ledger: render the paper again (step 11c)"}]
        with open(path, encoding="utf-8") as f:
            ledger = json.load(f)
    except FileNotFoundError:
        return {}, []
    except (OSError, ValueError, RecursionError) as e:
        return {}, [{"value": None, "why": f"evidence-ledger.json cannot be read ({e.__class__.__name__}): render the paper again (step 11c)"}]
    allowed = {f["rel"]: f for f in files}
    docs: dict = {}
    sourced, bad = {}, []
    for e in (ledger.get("entries") if isinstance(ledger, dict) else None) or []:
        if not isinstance(e, dict):
            continue
        printed, rel = str(e.get("printed", "")), str(e.get("file") or "")
        key = str(e.get("key"))[:200]
        claim = f"\\ev{{{key}}}"
        rel = os.path.normpath(rel).replace("\\", "/") if rel else rel
        if rel not in allowed:
            bad.append({"value": printed, "claim": claim,
                        "why": (f"{claim} came from {rel or 'no file'}, which is not evidence the gates verified"
                                f" -- an aggregate, DESIGN.json or a declared output")})
            continue
        if rel not in docs:
            try:
                with open(allowed[rel]["path"], encoding="utf-8") as f:
                    docs[rel] = json.load(f)
            except (OSError, ValueError, RecursionError):
                docs[rel] = None
        field = e.get("field") if isinstance(e.get("field"), list) else []
        value = field_value(docs[rel], field[:64])
        places, pct = e.get("places", "d"), e.get("pct") is True
        if places != "d" and not (isinstance(places, (int, str)) and str(places).isdigit() and int(places) in EV_PLACES[pct]):
            bad.append({"value": printed, "claim": claim, "why": f"{claim}: {places!r} is not a precision \\ev prints"})
            continue
        try:
            want = None if value is None else ev_format(value, None if places == "d" else int(places), pct)
        except (ValueError, TypeError, ArithmeticError):
            want = None
        if want is None or want != printed:
            bad.append({"value": printed, "claim": claim,
                        "why": (f"{claim} printed {printed}, and {rel} holds "
                                f"{'no such number' if value is None else repr(value)} there"
                                f"{'' if value is None else ' (' + str(want) + ' at that precision)'}: "
                                f"paper/data/evidence.tex is stale or was edited -- run make_paper_data.py --evidence again")})
            continue
        at = e.get("at")
        if not isinstance(at, list) or not at:
            bad.append({"value": printed, "claim": claim,
                        "why": f"{claim}: the ledger does not say where it is printed -- render the paper again (step 11c)"})
            continue
        for spot in at[:10_000]:
            ok = (isinstance(spot, list) and len(spot) == 2 and spot[0] in parts
                  and isinstance(spot[1], int) and not isinstance(spot[1], bool) and spot[1] >= 0)
            if ok:
                ok = parts[spot[0]][spot[1]:spot[1] + len(printed)] == printed
            if not ok:
                bad.append({"value": printed, "claim": claim,
                            "why": (f"{claim}: the paper does not print {printed} where the ledger says it does -- "
                                    f"submission.json or evidence-ledger.json was changed after the paper was "
                                    f"rendered: render it again (step 11c)")})
                break
            neg = printed.startswith("-")
            sourced[(spot[0], spot[1] + (1 if neg else 0))] = printed[1:] if neg else printed
    return sourced, bad


def build_claims(workdir: str, submission_path: str, man: dict | None = None, aggregation: dict | None = None) -> tuple:
    """Split the paper's printed numbers into (to check literally,
    matched_by_rounding, printed_as_another_metric, the chain's own report).

    Along the evidence chain (interfaces/evidence-interface.md): a value the
    paper printed with \\ev is re-read from its file and field (the ledger).
    Every other number is looked up in the evidence only -- the declared
    outputs, the aggregates, DESIGN.json, this machine -- never the raw data
    beside them, and only the numbers the paper prints are collected, so the
    check's memory grows with the paper and never with the results.

    ARIS's evidence_check.py is the checker of record for what is left, but it
    searches literally, so it cannot see that 0.067 came from
    0.06666666666666667. Anything it would miss for that reason is resolved
    here instead of being reported as a fabricated number -- but only by a
    result of the metric the paper prints it as. Where the paper names a metric
    the results declare (an aggregate's `metric`) beside the number -- its
    sentence, or its table column and caption -- a result of another metric
    that happens to round to it does not count; the number is reported, with
    what the results do hold it as. Where the paper names none, any evidence
    number will do.
    """
    try:
        with open(submission_path, encoding="utf-8") as f:
            sub = json.load(f)
    except FileNotFoundError:
        raise PaperUnreadable("there is no submission.json to check")
    except (OSError, ValueError) as e:
        raise PaperUnreadable(f"submission.json cannot be read ({e})")
    if not isinstance(sub, dict):
        raise PaperUnreadable("submission.json is not a JSON object")
    abstract, body = str(sub.get("abstract", "")), str(sub.get("body_md", ""))
    cited_ids = {m.group(1) for m in ARXIV_ID.finditer(abstract + "\n" + body)}
    # A number in the reference list (a year, a volume, pages, a DOI) is the
    # cited work's: the numbers checked are the paper's own text's. Blanked,
    # not cut, so each character keeps the offset the ledger knows it by.
    text = abstract + "\n" + blank_reference_list(body)
    runs = os.path.join(workdir, "runs")
    files, legacy, notes = evidence_files(workdir, runs, man or {}, aggregation)
    sourced, ledger_bad = verify_ledger(workdir, files, {"abstract": abstract, "body": body})

    def where(pos: int) -> tuple:
        return ("abstract", pos) if pos < len(abstract) else ("body", pos - len(abstract) - 1)

    spans = [m.span() for rx in CITATION_SPANS for m in rx.finditer(text)]

    def in_citation(pos: int) -> bool:
        return any(a <= pos < b for a, b in spans)

    # The numbers to look for, before anything is read: each printed number,
    # as printed, at the precision it was printed with.
    found = []
    for m in MEANINGFUL.finditer(text):
        v = m.group(1)
        if v in cited_ids:
            continue
        if YEAR.fullmatch(v) and in_citation(m.start()):
            continue    # this occurrence is a cited work's year; others still count
        neg = bool(SIGN_BEFORE.search(text[max(0, m.start() - 3):m.start()]))
        key = ("-" if neg else "") + v
        if sourced.get(where(m.start())) == v:
            continue    # printed with \ev just here, and re-read from its field
        found.append((m, v, neg, key))
    wanted: dict = {}
    for _, v, _, _ in found:
        try:
            want = float(v)
        except ValueError:
            continue
        dp = len(v.split(".")[1]) if "." in v else 0
        wanted.setdefault(dp, set()).update({round(want, dp), round(-want, dp)})

    def keep(n) -> bool:
        try:
            f = float(n)
        except (TypeError, ValueError, OverflowError):
            return False
        if not math.isfinite(f):
            return False
        return any(round(f, dp) in vals for dp, vals in wanted.items())

    entries, declared = [], set()
    for ev in files:
        try:
            with open(ev["path"], encoding="utf-8") as f:
                if ev["path"].endswith(".jsonl"):
                    for line in f:
                        line = line.strip()
                        if line:
                            entries_of(json.loads(line), ev["rel"], entries, declared, keep)
                else:
                    entries_of(json.load(f), ev["rel"], entries, declared, keep)
        except (OSError, ValueError, RecursionError) as e:
            notes.append(f"{ev['rel']} could not be read ({e.__class__.__name__}): not evidence")
    vocab = declared | {n for _, names, _ in entries for n in names}
    by_dp: dict = {}

    def candidates(value: str) -> list:
        """Evidence numbers that round to `value` at the precision it is printed."""
        try:
            want = float(value)
        except ValueError:
            return []
        dp = len(value.split(".")[1]) if "." in value else 0
        if dp not in by_dp:
            idx: dict = {}
            for e in entries:
                idx.setdefault(round(float(e[0]), dp), []).append(e)
            by_dp[dp] = idx
        return by_dp[dp].get(round(want, dp), [])

    # Each place a number is printed is read on its own: the same value may be
    # a cited work's in one sentence, an accuracy in another, a loss in a third.
    claims, rounded, other_metric = [], [], []
    literal, plain, judged = set(), set(), set()
    for m, v, neg, key in found:
        ctx = text[max(0, m.start() - 70):m.end() + 30].replace("\n", " ")
        # A number inside a sentence that cites another paper is that paper's
        # number, not a claim about this experiment.
        if CITATION_NEAR.search(ctx):
            rounded.append({"value": v, "matched": "belongs_to_a_cited_work"})
            continue
        if rounds_to(v, CONSTANTS):
            rounded.append({"value": v, "matched": "a_standard_constant"})
            continue
        cands = candidates("-" + v) if neg else candidates(v) + candidates("-" + v)
        if not cands:
            if key not in literal:
                literal.add(key)
                claims.append({"value": v, "source": "runs/**/*.json", "claim": ctx})
            continue
        words = words_of(read_with(text, m.start(), m.end()))
        named = {d for d in declared if named_in(d, words)}
        if not named:
            if key not in plain:
                plain.add(key)
                rounded.append({"value": key, "matched": "rounded_to_a_result_number", "found_at": cands[0][2]})
            continue
        here = {n for n in vocab if named_in(n, words)}
        if (key, frozenset(here)) in judged:
            continue
        judged.add((key, frozenset(here)))
        fit = [e for e in cands if not e[1] or e[1] & here]
        if fit:
            rounded.append({"value": key, "matched": "rounded_to_a_result_of_the_metric_named",
                            "metric": sorted(named), "found_at": fit[0][2]})
            continue
        held = sorted({n for e in cands for n in e[1]})
        other_metric.append({"value": key, "claim": ctx, "status": "other_metric",
                             "why": (f"printed as {' / '.join(sorted(named))}; the evidence holds {key} only as "
                                     f"{', '.join(held[:6])} ({', '.join(e[2] for e in cands[:3])})")})
    rounded = list({(r["value"], r["matched"]): r for r in rounded}.values())

    # A paper begun before the chain: what the evidence does not carry may be
    # in a small raw results file, as the old check allowed -- said, not failed.
    in_raw, skipped = [], []
    if legacy and claims:
        wanted.clear()
        for c in claims:
            dp = len(c["value"].split(".")[1]) if "." in c["value"] else 0
            wanted.setdefault(dp, set()).update({round(float(c["value"]), dp), round(-float(c["value"]), dp)})
        raw, _, skipped = raw_matches(runs, keep, {f["rel"] for f in files})
        rest = []
        for c in claims:
            dp = len(c["value"].split(".")[1]) if "." in c["value"] else 0
            hit = next((e for e in raw if round(float(e[0]), dp) == round(float(c["value"]), dp)), None)
            if hit:
                in_raw.append({"value": c["value"], "found_at": hit[2],
                               "why": "found only in a raw results file: the evidence (aggregates, DESIGN.json, "
                                      "declared outputs) does not carry it -- allowed for a paper begun before the "
                                      "evidence chain, not after"})
            else:
                rest.append(c)
        claims = rest

    chain = {
        "mode": "legacy (begun before the evidence chain)" if legacy else "evidence chain",
        "evidence_files": [{"file": f["rel"], "role": f["role"]} for f in files],
        "printed_with_ev": len(sourced),
        "ledger_problems": ledger_bad,
        "notes": notes,
        "found_only_in_raw_files": in_raw,
        "raw_files_not_read": skipped[:20],
        "_files": files,
    }
    return claims, rounded, other_metric, chain


def evidence_root(workdir: str, files: list) -> str:
    """The evidence as the literal search may read it, linked into
    .aris/evidence-root/ under the same relative paths: the declared outputs,
    the aggregates, DESIGN.json -- never the raw data beside them."""
    root = os.path.join(workdir, ".aris", "evidence-root")
    shutil.rmtree(root, ignore_errors=True)
    for f in files:
        if not f["rel"].startswith("runs/"):
            continue
        dst = os.path.join(root, f["rel"])
        if not os.path.abspath(dst).startswith(os.path.abspath(root) + os.sep):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            os.link(f["path"], dst)
        except OSError:
            shutil.copy2(f["path"], dst)
    os.makedirs(os.path.join(root, "runs"), exist_ok=True)
    return root


def json_leaves(obj, prefix=""):
    """Every leaf of a JSON document -- numbers, strings, booleans, nulls --
    by dotted path: an aggregate is compared whole, its labels too."""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(json_leaves(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        if not obj:
            out[prefix + "[]"] = "[]"
        for i, v in enumerate(obj):
            out.update(json_leaves(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


CODE_EXT = (".py", ".sh", ".r", ".R", ".jl", ".m", ".c", ".cc", ".cpp", ".h", ".hpp", ".cu", ".js", ".ts",
            ".toml", ".yaml", ".yml", ".cfg", ".ini", ".txt", ".lock")


def replay_aggregation(work: str, runs: str, man: dict, python_cmd: list) -> dict:
    """Link 2 of the chain: run aggregate.py again in a clean copy that holds
    the code and the experiments' declared outputs -- as step 10 verified
    them -- and nothing else from runs/, and compare every file it writes with
    the one there, every leaf. An aggregate cannot carry a number its inputs
    do not produce, and none is made by hand."""
    base = {"script": "(aggregation)", "output": "aggregate__*.json, DESIGN.json"}
    try:
        agg = aggregation_of(man)
    except ManifestError as e:
        return {**base, "verdict": "FAIL", "failure": "manifest", "why": str(e),
                "hint": "fix the manifest's `aggregation` entry (interfaces/evidence-interface.md §1)."}
    if agg is None:
        return {**base, "verdict": "FAIL", "failure": "no_aggregation",
                "why": "the manifest names no `aggregation`: the aggregates were not made by a script the gate can re-run",
                "hint": ("write runs/aggregate.py, which writes every runs/aggregate__*.json and runs/DESIGN.json from "
                         "the declared outputs, run it, and add to runs/REPLAY_MANIFEST.json: \"aggregation\": "
                         "{\"script\": \"aggregate.py\", \"outputs\": [\"aggregate__*.json\", \"DESIGN.json\"]}.")}
    base["script"] = agg["script"]
    outs = aggregation_outputs(runs, agg)
    if not outs:
        return {**base, "verdict": "FAIL", "failure": "no_recorded_output",
                "why": f"no file under runs/ matches {', '.join(agg['outputs'])}",
                "hint": "run aggregate.py, so the files it writes are there to compare with."}
    # Every aggregate, and DESIGN.json, is the script's: one written by hand
    # beside it would be evidence nobody re-made.
    stray = sorted({r for r in glob_rel(runs, "aggregate__*.json") + (["DESIGN.json"] if os.path.isfile(os.path.join(runs, "DESIGN.json")) else [])} - set(outs))
    if stray:
        return {**base, "verdict": "FAIL", "failure": "unmade",
                "why": f"{', '.join(stray[:5])} {'is' if len(stray) == 1 else 'are'} not among what aggregate.py writes",
                "hint": "every aggregate and DESIGN.json comes from aggregate.py: list it in `aggregation.outputs` and write it there."}
    declared = {"runs/" + e["output"].lstrip("/") for e in man.get("experiments") or [] if isinstance(e, dict) and isinstance(e.get("output"), str)}
    verified = load_state(work).get("declared") or {}
    for rel in sorted(declared):
        path = os.path.join(work, rel)
        if rel in verified and os.path.isfile(path) and sha256_of(path) != verified[rel]:
            return {**base, "verdict": "FAIL", "failure": "evidence_changed",
                    "why": f"{rel} changed after step 10 verified it",
                    "hint": "a declared output is the experiment's, as re-made: run step 10 again rather than edit it."}
    problems = []
    for rel in outs:
        if not rel.endswith(".json"):
            continue
        try:
            with open(os.path.join(runs, rel), encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        for inp in (doc.get("primary_inputs") or []) if isinstance(doc, dict) else []:
            p = os.path.normpath(str(inp)).replace("\\", "/")
            p = p if p.startswith("runs/") else "runs/" + p
            if p not in declared:
                problems.append({"kind": "undeclared_input", "key": f"{rel}: primary_inputs", "value": str(inp)})
    if problems:
        return {**base, "verdict": "FAIL", "failure": "undeclared_input", "problems": problems[:20],
                "why": f"an aggregate combines {problems[0]['value']}, which no experiment declares as its output",
                "hint": ("aggregate from the experiments' declared outputs -- the files step 10 re-made -- and list "
                         "those in primary_inputs. Raw data beside them (predictions, logits) is summarised by the "
                         "experiment into its declared output.")}

    tmp = tempfile.mkdtemp(prefix="reprogate-agg-")
    try:
        copy_workspace(work, tmp)
        # runs/ in the copy: its code only, then the declared outputs as verified.
        for dirpath, dirnames, names in os.walk(os.path.join(tmp, "runs")):
            for name in names:
                if not name.endswith(CODE_EXT) or name in MANIFEST_NAMES:
                    os.remove(os.path.join(dirpath, name))
        for rel in sorted(declared):
            src = os.path.join(work, rel)
            if os.path.isfile(src):
                dst = os.path.join(tmp, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
        man_src = next((os.path.join(runs, n) for n in MANIFEST_NAMES if os.path.exists(os.path.join(runs, n))), None)
        if man_src:
            shutil.copy2(man_src, os.path.join(tmp, "runs", os.path.basename(man_src)))
        script_abs = script_path(os.path.join(tmp, "runs"), agg["script"])
        if not os.path.isfile(script_abs):
            return {**base, "verdict": "FAIL", "failure": "crashed", "why": f"there is no {agg['script']}",
                    "hint": "aggregate.py sits in runs/ (or the path the manifest names), with the experiments' code."}
        cmd = list(python_cmd) + [script_abs] + [str(x) for x in agg.get("args", [])]
        t0 = time.time()
        try:
            proc = subprocess.run(cmd, cwd=os.path.dirname(script_abs) or tmp, env=dict(os.environ, **(man.get("env") or {})),
                                  capture_output=True, text=True, timeout=agg.get("timeout_s", 900))
        except subprocess.TimeoutExpired:
            return {**base, "verdict": "FAIL", "failure": "timeout", "why": f"timed out after {agg.get('timeout_s', 900)}s",
                    "hint": "aggregation reads summaries; a longer timeout_s only if it truly takes that long."}
        dt = time.time() - t0
        if proc.returncode != 0:
            d = diagnose(proc.stderr, {}, "aggregate__*.json", python_cmd)
            return {**base, "verdict": "FAIL", "failure": "crashed", "why": f"exit {proc.returncode}" + (f": {d['last']}" if d["last"] else ""),
                    "cause": d["cause"], "hint": ("it runs with only the code and the declared outputs under runs/: "
                                                  "it reads nothing else. " + d["hint"]),
                    "stderr_tail": (proc.stderr or "")[-1200:]}
        made = aggregation_outputs(os.path.join(tmp, "runs"), agg)
        for rel in sorted(set(outs) - set(made)):
            problems.append({"kind": "vanished", "keys": [rel]})
        for rel in sorted(set(made) - set(outs)):
            problems.append({"kind": "appeared", "keys": [rel]})
        for rel in sorted(set(outs) & set(made)):
            try:
                with open(os.path.join(runs, rel), encoding="utf-8") as f:
                    old = json_leaves(json.load(f))
                with open(os.path.join(tmp, "runs", rel), encoding="utf-8") as f:
                    new = json_leaves(json.load(f))
            except (OSError, ValueError) as e:
                problems.append({"kind": "unreadable", "key": rel, "value": str(e)})
                continue
            for k in sorted(set(old) - set(new))[:10]:
                problems.append({"kind": "vanished", "keys": [f"{rel}: {k}"]})
            for k in sorted(set(new) - set(old))[:10]:
                problems.append({"kind": "appeared", "keys": [f"{rel}: {k}"]})
            for k in sorted(set(old) & set(new)):
                a, b = old[k], new[k]
                if isinstance(a, NUM) and isinstance(b, NUM) and not isinstance(a, bool) and not isinstance(b, bool):
                    if not same_number(a, b)[0]:
                        problems.append({"kind": "exact_mismatch", "key": f"{rel}: {k}", "recorded": a, "rerun": b})
                elif a != b:
                    problems.append({"kind": "exact_mismatch", "key": f"{rel}: {k}", "recorded": a, "rerun": b})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    entry = {**base, "verdict": "PASS" if not problems else "FAIL", "rerun_wall_s": round(dt, 1),
             "checked": {"files": len(outs)}, "problems": problems[:40]}
    if problems:
        entry["failure"] = "aggregate_mismatch"
        entry["hint"] = ("what aggregate.py writes from the declared outputs is not what is under runs/: an aggregate "
                         "edited by hand, or made from other files. Run aggregate.py and let it write them.")
    else:
        verified_now = {"runs/" + rel: sha256_of(os.path.join(runs, rel)) for rel in outs}
        save_state(work, "aggregation", {
            "outputs": verified_now,
            "script": sha256_of(script_path(runs, agg["script"])) if os.path.isfile(script_path(runs, agg["script"])) else None,
        })
        entry["_outputs"] = verified_now
    return entry


def flatten(obj, prefix=""):
    """Every leaf number in a nested structure, keyed by dotted path."""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}[{i}]"))
    elif isinstance(obj, NUM) and not isinstance(obj, bool):
        out[prefix] = obj
    return out


# A field named like a measurement of the machine: wall-clock time, a rate per
# second, latency. Only ever applied to fields the manifest already called
# `tolerant` -- never to an `exact` one -- so a result is never let off by its
# name.
TIMING_NAME = re.compile(
    r"^(?:wall|wall_?time|wall_?clock|elapsed|runtime|run_?time|duration|latency|"
    r"throughput|seconds|secs|time)$"
    r"|^(?:wall|elapsed|runtime|duration|latency|throughput)_"
    r"|(?:_s|_sec|_secs|_seconds|_ms|_us|_ns|_min|_mins|_minutes|_hours|_time|"
    r"_per_s|_per_sec|_per_second|_latency|_throughput)$", re.I)

# Floating-point precision for an `exact` float: far above summation-order
# noise (~1e-16), far below any digit a paper prints.
FLOAT_REL = 1e-9
FLOAT_ABS = 1e-12


def classify(key: str, exact: list, tolerant: dict, timing: list = ()):
    """Match a dotted path against the manifest's field names."""
    leaf = key.split(".")[-1].split("[")[0]
    for name in exact:
        if leaf == name or key == name:
            return "exact", None
    for name in timing:
        if leaf == name or key == name:
            return "timing", None
    for name, tol in tolerant.items():
        if leaf == name or key == name:
            return ("timing", None) if TIMING_NAME.search(leaf) else ("tolerant", tol)
    return "unclassified", None


def same_number(a, b) -> tuple:
    """(equal, only_to_float_precision) for an `exact` field: an integer must
    be equal; a float, equal to floating-point precision. Two NaNs are the
    same result."""
    if a == b:
        return True, False
    if isinstance(a, float) or isinstance(b, float):
        if math.isnan(a) and math.isnan(b):
            return True, False
        if math.isclose(a, b, rel_tol=FLOAT_REL, abs_tol=FLOAT_ABS):
            return True, True
    return False, False


# What the clean copy leaves behind: the kit's and the agent's own tooling,
# recorded results (a script must make its output, not inherit it), and any
# environment -- a virtual environment, a conda env, node_modules, tool
# caches. An environment is not the experiment: the copy runs with this
# interpreter, and copying one costs gigabytes per script. Worse, a script that
# walked the workspace counted a setuptools `.pth` inside `.venv` as a model
# file, and the copy carried the same file along, so the wrong count
# "reproduced" (a user's report, 2026-10-04). Left out, it no longer does.
SKIP = {".claude", ".aris", ".git", "__pycache__", "archive-v1", "figures",
        "results", "data", ".venv", "venv", "node_modules", ".tox",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", ".ipynb_checkpoints",
        # the pipeline's own copies: what an interrupted step had written
        # (pipeline/resume.py), and step 13's attack
        ".interrupted", ".kill-argument"}


def skipped_dir(parent: str, name: str) -> bool:
    """A directory the clean copy leaves out: one named in SKIP, or any
    environment whatever its name (a venv's pyvenv.cfg, a conda env's
    conda-meta)."""
    if name in SKIP:
        return True
    d = os.path.join(parent, name)
    return os.path.isfile(os.path.join(d, "pyvenv.cfg")) or os.path.isdir(os.path.join(d, "conda-meta"))


# How a crash reads, so a failed entry says why and what would fix it: the
# turn that repairs the gate (run-pipeline.sh, step 10) and its owner's note
# both start from this. An architecture error comes first: it arrives inside
# an ImportError, often with a path in quotes.
ARCH_ERROR = re.compile(
    r"incompatible architecture|have '[\w.-]+', need '[\w.-]+'|wrong ELF class|Exec format error|"
    r"bad CPU type|cannot execute binary file|wrong architecture", re.I)
LOAD_ERROR = re.compile(
    r"Library not loaded|Symbol not found|cannot open shared object file|undefined symbol|"
    r"DLL load failed|dlopen\(", re.I)
NO_MODULE = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")
NO_FILE = re.compile(r"No such file or directory: '([^']+)'")

# What a failure is. A `mismatch` is a finding about the experiment; the rest
# kept the gate from comparing at all, and the agent can repair them.
REPAIRABLE = {"crashed", "timeout", "no_output", "no_recorded_output", "blocked",
              "unclassified", "manifest", "output_too_large", "no_aggregation", "unmade",
              "undeclared_input", "evidence_changed", "aggregate_mismatch"}
FAILURE_WORDS = {
    "crashed": "crashed before it finished",
    "timeout": "ran out of its time",
    "no_output": "finished but wrote no output",
    "no_recorded_output": "has no recorded output to compare with",
    "blocked": "did not run: an entry it reads failed",
    "unclassified": "has numbers nobody classified",
    "manifest": "the replay manifest cannot be used",
    "mismatch": "came out different",
    "removed": "was taken out of the manifest after it failed",
    "unsupported_claim": "the paper prints numbers no result holds",
    "output_too_large": "writes an output too large to be a run's summary",
    "no_aggregation": "has no aggregation script to re-run",
    "unmade": "has an aggregate aggregate.py does not write",
    "undeclared_input": "aggregates from a file no experiment declares",
    "evidence_changed": "reads evidence that changed after it was verified",
    "aggregate_mismatch": "writes aggregates different from the ones under runs/",
}


def runs_relative(path: str) -> str:
    """A path a script failed to open, relative to runs/ when it is under it."""
    p = path.replace("\\", "/")
    i = p.rfind("/runs/")
    if i >= 0:
        return p[i + len("/runs/"):]
    if p.startswith("runs/"):
        return p[len("runs/"):]
    while p.startswith("./"):
        p = p[2:]
    return p


def diagnose(stderr: str, outputs: dict, own: str, python_cmd: list) -> dict:
    """Why a script crashed, from what it printed: a cause, the line that
    says it, and what would fix it. `outputs` maps every entry's output to its
    script, so reading another entry's results is named as such."""
    tail = (stderr or "")[-8000:]
    lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]
    last = lines[-1][:300] if lines else ""
    interp = " ".join(python_cmd)
    machine = platform.machine() or "this machine's"
    if ARCH_ERROR.search(tail):
        return {"cause": "foreign_architecture", "last": last,
                "hint": (f"a compiled library or program it loads was built for another CPU architecture "
                         f"than this machine's ({machine}) -- built under Rosetta, say, or copied from "
                         f"another machine. Rebuild or reinstall it here, or remove the cache it came "
                         f"from; or name the interpreter the experiment ran with as \"python\" in the manifest.")}
    if LOAD_ERROR.search(tail):
        return {"cause": "library_load", "last": last,
                "hint": f"a compiled library could not be loaded: rebuild or reinstall it for {interp}."}
    m = NO_MODULE.search(tail)
    if m:
        return {"cause": "missing_module", "last": last,
                "hint": (f"the gate runs scripts with {interp}, which has no module {m.group(1)}: install it "
                         f"for that interpreter, or name the interpreter the experiment ran with as "
                         f"\"python\" in the manifest.")}
    found = list(NO_FILE.finditer(tail))
    if found:
        path = found[-1].group(1)
        rel = runs_relative(path)
        other = next((s for o, s in outputs.items() if o != own and (o == rel or rel.endswith("/" + o))), None)
        if other is None:
            base = os.path.basename(rel)
            hits = {s for o, s in outputs.items() if o != own and os.path.basename(o) == base}
            other = next(iter(hits)) if len(hits) == 1 else None
        if other:
            return {"cause": "reads_another_entrys_output", "last": last, "reads": other,
                    "hint": (f"it reads {rel}, which {other} writes. Each entry re-runs alone, in a copy "
                             f"without results/, in no set order: name that entry in its manifest entry -- "
                             f"\"after\": [\"{other}\"] -- so it runs first, in the same copy; or compute "
                             f"what it needs itself.")}
        if "/results/" in "/" + rel:
            return {"cause": "reads_recorded_results", "last": last,
                    "hint": (f"it reads {rel}, a results file the clean copy does not have: a script computes "
                             f"everything it reports. A results file another entry writes is read through "
                             f"\"after\".")}
        return {"cause": "missing_file", "last": last,
                "hint": (f"it reads {path}, which the clean copy does not have: data/, figures/ and any "
                         f"environment are left out of it. A script makes or fetches what it needs, or "
                         f"reads it from a folder that is copied.")}
    return {"cause": "crashed", "last": last,
            "hint": (f"run it as the gate does -- in a clean copy, from its folder, with {interp} -- and fix "
                     f"why it fails, without changing what it computes.")}


def copy_workspace(work: str, tmp: str) -> None:
    runs_dir = os.path.join(work, "runs")
    for dirpath, dirnames, filenames in os.walk(work):
        dirnames[:] = [d for d in dirnames if not skipped_dir(dirpath, d)]
        rel = os.path.relpath(dirpath, work)
        dst = tmp if rel == "." else os.path.join(tmp, rel)
        os.makedirs(dst, exist_ok=True)
        in_runs = os.path.abspath(dirpath).startswith(os.path.abspath(runs_dir))
        for fn in filenames:
            if fn.endswith(".json.tmp") or fn.endswith(".pyc"):
                continue
            # A large recorded file under runs/ (per-instance data) never feeds
            # a re-run -- runs/results/ is left out for the same reason -- and
            # copying it for every entry is what made a big study's gate crawl.
            if in_runs and not fn.endswith(CODE_EXT):
                try:
                    if os.path.getsize(os.path.join(dirpath, fn)) > EVIDENCE_FILE_MAX:
                        continue
                except OSError:
                    continue
            try:
                shutil.copy2(os.path.join(dirpath, fn), os.path.join(dst, fn))
            except OSError:
                pass


def script_path(runs: str, script: str) -> str:
    """Scripts are named relative to runs/ by convention, but may sit anywhere
    in the tree; resolved against runs/ first, then the workspace root."""
    work = os.path.dirname(os.path.abspath(runs))
    cand = [os.path.join(runs, script), os.path.join(work, script)]
    return next((c for c in cand if os.path.exists(c)), cand[0])


def run_one(runs: str, exp: dict, env: dict, python_cmd: list, deps: dict | None = None,
            keep: str | None = None, outputs: dict | None = None) -> tuple:
    """Re-run one entry in a clean copy and diff what it makes against what
    was recorded. `deps`: the re-made outputs of the entries it runs after
    (output -> file), put in its copy first. `keep`: a folder to keep its own
    re-made output in, for the entries that read it. Returns (the report's
    entry, the kept output or None)."""
    script = exp["script"]
    out_rel = exp["output"]
    base = {"script": script, "output": out_rel}
    recorded_path = os.path.join(runs, out_rel)
    if os.path.isfile(recorded_path) and os.path.getsize(recorded_path) > EVIDENCE_FILE_MAX:
        mib = os.path.getsize(recorded_path) / 1048576
        return {**base, "verdict": "FAIL", "failure": "output_too_large",
                "why": f"its output {out_rel} is {mib:.0f} MiB, past the {EVIDENCE_FILE_MAX >> 20} MiB a run's summary may take",
                "hint": ("the declared output is the run's summary -- its metrics and settings, every number compared "
                         "on a re-run. Write per-instance data (predictions, logits, labels) to another file beside it, "
                         "not declared; the summary carries what is computed from it "
                         "(interfaces/evidence-interface.md, link 1).")}, None
    try:
        with open(recorded_path, encoding="utf-8") as f:
            recorded = json.load(f)
    except (OSError, ValueError) as e:
        why = f"no recorded output at {out_rel}" if not os.path.exists(recorded_path) else f"the recorded {out_rel} cannot be read ({e})"
        return {**base, "verdict": "FAIL", "failure": "no_recorded_output", "why": why,
                "hint": ("the manifest names an output step 5 did not write there: point it at the results "
                         "file the script writes. If the experiment never ran, the gate cannot make it.")}, None

    # A clean copy of the WHOLE workspace, not just runs/: the sweep code has
    # lived in runs/scripts/ on one run and in a sibling code/ on the next, and
    # a gate that only copies runs/ silently fails on the second layout. Copying
    # the tree also preserves the ../runs/ paths those scripts compute from
    # __file__. Recorded results are dropped so a script that quietly reads its
    # own previous output fails here rather than in review.
    work = os.path.dirname(os.path.abspath(runs))
    tmp = tempfile.mkdtemp(prefix="reprogate-")
    kept = None
    try:
        copy_workspace(work, tmp)
        # the output must be produced by the re-run, not inherited from it
        stale = os.path.join(tmp, "runs", out_rel)
        if os.path.exists(stale):
            os.remove(stale)
        os.makedirs(os.path.join(tmp, "runs", os.path.dirname(out_rel) or "."), exist_ok=True)
        # What it runs `after`: their outputs as this replay re-made them.
        for rel, src in (deps or {}).items():
            dst = os.path.join(tmp, "runs", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

        script_abs = script_path(os.path.join(tmp, "runs"), script)
        cmd = list(python_cmd) + [script_abs] + [str(x) for x in exp.get("args", [])]
        t0 = time.time()
        proc = subprocess.run(cmd, cwd=os.path.dirname(script_abs) or tmp,
                              env=dict(os.environ, **env),
                              capture_output=True, text=True,
                              timeout=exp.get("timeout_s", 3600))
        dt = time.time() - t0
        if proc.returncode != 0:
            d = diagnose(proc.stderr, outputs or {}, out_rel, python_cmd)
            entry = {**base, "verdict": "FAIL", "failure": "crashed",
                     "why": f"exit {proc.returncode}" + (f": {d['last']}" if d["last"] else ""),
                     "cause": d["cause"], "hint": d["hint"],
                     "stderr_tail": (proc.stderr or "")[-1200:]}
            if d.get("reads"):
                entry["reads"] = d["reads"]
            return entry, None
        fresh_path = os.path.join(tmp, "runs", out_rel)
        if not os.path.exists(fresh_path):
            return {**base, "verdict": "FAIL", "failure": "no_output",
                    "why": f"the re-run produced no {out_rel}",
                    "hint": (f"it exited 0 and wrote nothing at runs/{out_rel}: a script writes its output where "
                             f"the manifest says (relative to runs/), making the folder if it is missing."),
                    "stdout_tail": (proc.stdout or "")[-600:]}, None
        with open(fresh_path, encoding="utf-8") as f:
            fresh = json.load(f)
        if keep:
            kept = os.path.join(keep, hashlib.sha256(out_rel.encode()).hexdigest()[:16], os.path.basename(out_rel))
            os.makedirs(os.path.dirname(kept), exist_ok=True)
            shutil.copy2(fresh_path, kept)
    except subprocess.TimeoutExpired:
        return {**base, "verdict": "FAIL", "failure": "timeout",
                "why": f"timed out after {exp.get('timeout_s', 3600)}s",
                "hint": ("a larger timeout_s in its manifest entry if the experiment simply takes that long "
                         "here; never a smaller experiment.")}, None
    except ValueError as e:
        return {**base, "verdict": "FAIL", "failure": "no_output",
                "why": f"the re-run's {out_rel} is not JSON ({e})",
                "hint": "a script writes its output as one JSON document."}, None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    old, new = flatten(recorded), flatten(fresh)
    exact = exp.get("exact", [])
    tolerant = exp.get("tolerant", {})
    timing = exp.get("timing", [])
    if isinstance(timing, dict):
        timing = list(timing)
    problems, checked = [], {"exact": 0, "tolerant": 0, "timing": 0}
    measured, float_noise = [], 0

    missing = sorted(set(old) - set(new))
    added = sorted(set(new) - set(old))
    if missing:
        problems.append({"kind": "vanished", "keys": missing[:20]})
    if added:
        problems.append({"kind": "appeared", "keys": added[:20]})

    for k in sorted(set(old) & set(new)):
        kind, tol = classify(k, exact, tolerant, timing)
        a, b = old[k], new[k]
        if kind == "exact":
            checked["exact"] += 1
            equal, noise = same_number(a, b)
            float_noise += noise
            if not equal:
                problems.append({"kind": "exact_mismatch", "key": k,
                                 "recorded": a, "rerun": b})
        elif kind == "timing":
            # Re-measured and reported, never compared.
            checked["timing"] += 1
            denom = abs(a) if a else 1.0
            measured.append({"key": k, "recorded": a, "rerun": b,
                             "drift": round(abs(b - a) / denom, 4)})
        elif kind == "tolerant":
            checked["tolerant"] += 1
            denom = abs(a) if a else 1.0
            drift = abs(b - a) / denom
            if drift > tol:
                problems.append({"kind": "outside_tolerance", "key": k,
                                 "recorded": a, "rerun": b,
                                 "drift": round(drift, 4), "allowed": tol})
        else:
            problems.append({"kind": "unclassified", "key": k, "value": a})

    verdict = "PASS" if not problems else "FAIL"
    entry = {**base, "verdict": verdict, "rerun_wall_s": round(dt, 1),
             "checked": checked, "problems": problems}
    if problems:
        if all(p["kind"] == "unclassified" for p in problems):
            entry["failure"] = "unclassified"
            entry["hint"] = ("name each number in exact, tolerant or timing by what it is: exact for a "
                             "computation with fixed seeds, tolerant (with a band) only if it really varies "
                             "run to run, timing only for wall-clock time and throughput.")
        else:
            entry["failure"] = "mismatch"
    if float_noise:
        entry["float_precision_matches"] = float_noise
    if measured:
        entry["timing"] = measured[:20]
    return entry, kept


class ManifestError(Exception):
    pass


def after_of(exp: dict) -> list:
    a = exp.get("after", [])
    return [a] if isinstance(a, str) else a


def contained(p: str) -> bool:
    """A manifest path names a file of this workspace: relative, and never
    climbing out of it ("..")."""
    q = p.replace("\\", "/")
    return bool(q) and not q.startswith("/") and not re.match(r"^[A-Za-z]:", q) and ".." not in q.split("/")


def check_entries(exps: list) -> None:
    for i, e in enumerate(exps):
        if not isinstance(e, dict) or not isinstance(e.get("script"), str) or not e["script"] \
                or not isinstance(e.get("output"), str) or not e["output"]:
            raise ManifestError(f"entry {i + 1} of `experiments` needs a \"script\" and an \"output\", both strings.")
        # An output outside runs/ would be read as evidence from anywhere on
        # this machine, and a script outside the workspace is not this paper's.
        if not contained(e["output"]) or not contained(e["script"]):
            raise ManifestError(f"{e['script']}: \"script\" and \"output\" are paths inside the workspace, the "
                                f"output relative to runs/ -- not absolute, and with no \"..\".")
        a = after_of(e)
        if not isinstance(a, list) or not all(isinstance(x, str) and x for x in a):
            raise ManifestError(f"{e['script']}: \"after\" is a list of the entries whose output it reads, "
                                f"each named by its script or its output.")


def dependencies(exps: list) -> list:
    """For each entry, the entries it runs after (indices), named by script or
    output -- or, failing that, by a file name only one entry has."""
    deps = []
    for e in exps:
        mine = set()
        for name in after_of(e):
            hits = {j for j, o in enumerate(exps) if name in (o["script"], o["output"])}
            if not hits:
                hits = {j for j, o in enumerate(exps)
                        if os.path.basename(name) in (os.path.basename(o["script"]), os.path.basename(o["output"]))}
                if len(hits) > 1:
                    hits = set()
            if not hits:
                raise ManifestError(f"{e['script']}: \"after\" names {name}, which is no entry's script or output.")
            mine |= hits
        deps.append(mine)
    return deps


def run_order(exps: list, deps: list) -> list:
    """Indices in an order where every entry comes after those it reads; the
    manifest's own order otherwise. A circle is a manifest error."""
    done, order, visiting = set(), [], []

    def visit(i: int) -> None:
        if i in done:
            return
        if i in visiting:
            loop = visiting[visiting.index(i):] + [i]
            raise ManifestError("entries read each other's output in a circle: "
                                + " -> ".join(exps[j]["script"] for j in loop) + ".")
        visiting.append(i)
        for j in sorted(deps[i]):
            visit(j)
        visiting.pop()
        done.add(i)
        order.append(i)

    for i in range(len(exps)):
        visit(i)
    return order


def closure(start: set, deps: list) -> set:
    """`start` and everything it reads, however indirectly."""
    out, todo = set(), list(start)
    while todo:
        i = todo.pop()
        if i not in out:
            out.add(i)
            todo.extend(deps[i])
    return out


def interpreter(man: dict, work: str) -> list:
    """The command scripts re-run with: the manifest's `python` -- a path (an
    environment's interpreter, say, which the clean copy leaves out and is run
    where it is) or a command as a list -- else this interpreter."""
    p = man.get("python")
    if p in (None, "", []):
        return [sys.executable]
    cmd = [p] if isinstance(p, str) else p
    if not isinstance(cmd, list) or not all(isinstance(x, str) and x for x in cmd):
        raise ManifestError("\"python\" is the interpreter to re-run with: a path, or a command as a list.")
    exe = os.path.expanduser(cmd[0])
    if os.path.isabs(exe):
        found = exe
    elif os.sep in exe or "/" in exe:
        found = os.path.join(work, exe)
    else:
        found = shutil.which(exe)
    if not found or not os.path.isfile(found) or not os.access(found, os.X_OK):
        raise ManifestError(f"\"python\" names {cmd[0]}, which is not a program this machine can run.")
    return [os.path.abspath(found)] + cmd[1:]


# What a retry compares, kept beside ARIS's own state (.aris/ is never copied).
STATE = os.path.join(".aris", "repro-state.json")
MANIFEST_NAMES = ("REPLAY_MANIFEST.json", "replay_manifest.json", "manifest.json", "MANIFEST.json")
# Written at the workspace's top by the gates and the loop between two runs of
# the gate, never read by an experiment: the audits' verdict files, notes, and
# the loop's own marks (dotfiles, pipeline.*, PIPELINE_STOPPED and the like).
AUDIT_FILES = {"PAPER_CLAIM_AUDIT.json", "CITATION_AUDIT.json", "KILL_ARGUMENT.json",
               "PROOF_AUDIT.json", "EXPERIMENT_AUDIT.json", "PAPER_SHAPE_AUDIT.json"}
# What an agent CLI may keep in the folder it works in, during a repair turn.
CLI_DIRS = {".codex", ".gemini", ".cursor", ".opencode", ".qwen", ".kimi", ".goose",
            ".crush", ".factory", ".amp"}


def file_sha(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return "unreadable"
    return h.hexdigest()


def entry_fingerprint(runs: str, exp: dict) -> str:
    """An entry as the manifest states it, its script and its recorded output."""
    h = hashlib.sha256(json.dumps(exp, sort_keys=True).encode())
    h.update(file_sha(script_path(runs, exp["script"])).encode())
    h.update(file_sha(os.path.join(runs, exp["output"])).encode())
    return h.hexdigest()


def shared_fingerprint(work: str, own_scripts: set) -> str:
    """Every other file the clean copy carries, so a repair that changed one --
    a module two scripts import, a cache -- runs every entry again."""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(work):
        top = os.path.abspath(dirpath) == os.path.abspath(work)
        dirnames[:] = sorted(d for d in dirnames
                             if not skipped_dir(dirpath, d) and not (top and (d == "refine-logs" or d in CLI_DIRS)))
        rel_dir = os.path.relpath(dirpath, work)
        for fn in sorted(filenames):
            if fn.endswith((".json.tmp", ".pyc")):
                continue
            if top and (fn.startswith(".") or fn.startswith("pipeline.") or fn in AUDIT_FILES
                        or fn.endswith(".md") or re.fullmatch(r"[A-Z][A-Z_]*", fn)):
                continue
            if rel_dir == "runs" and (fn in GATE_OUTPUTS or fn in MANIFEST_NAMES):
                continue
            p = os.path.join(dirpath, fn)
            if os.path.abspath(p) in own_scripts:
                continue
            h.update(os.path.join(rel_dir, fn).encode() + b"\0" + file_sha(p).encode() + b"\n")
    return h.hexdigest()


def manifest_fingerprint(man: dict) -> str:
    return hashlib.sha256(json.dumps({"env": man.get("env", {}), "python": man.get("python")},
                                     sort_keys=True).encode()).hexdigest()


def fingerprints(work: str, runs: str, man: dict, exps: list) -> dict:
    own = {os.path.abspath(script_path(runs, e["script"])) for e in exps}
    return {"manifest": manifest_fingerprint(man), "shared": shared_fingerprint(work, own),
            "entries": [{"script": e["script"], "output": e["output"], "fingerprint": entry_fingerprint(runs, e)}
                        for e in exps]}


def plan_retry(work: str, runs: str, man: dict, exps: list, deps: list, now: dict) -> tuple:
    """After a failed run: ((indices to run again, the earlier report's
    entries to keep by index, when that report was made) -- or None, every
    entry running --, the failed entries since taken out of the manifest, and
    why every entry runs)."""
    try:
        with open(os.path.join(runs, "REPRO_GATE.json"), encoding="utf-8") as f:
            prior = json.load(f)
        with open(os.path.join(work, STATE), encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return None, [], "there is no earlier run to go on from"
    if prior.get("verdict") != "FAIL" or prior.get("mode") not in ("full", "retry"):
        return None, [], "the last run did not fail"
    prior_by = {(e.get("script"), e.get("output")): e for e in prior.get("experiments") or []
                if e.get("script") not in ("(paper)", "(manifest)")}
    # Taken out, whatever else changed: an entry that failed is gone when
    # neither its script nor its output is any entry's now (a corrected output
    # path, or a renamed script, keeps it).
    scripts, outs = {e["script"] for e in exps}, {e["output"] for e in exps}
    removed = [e for (sc, ou), e in prior_by.items()
               if e.get("verdict") != "PASS" and sc not in scripts and ou not in outs]
    if state.get("manifest") != now["manifest"]:
        return None, removed, "the manifest's env or python changed"
    if state.get("shared") != now["shared"]:
        return None, removed, "files besides the entries' own scripts changed"
    before = {(s.get("script"), s.get("output")): s.get("fingerprint") for s in state.get("entries") or []}
    rerun, keep = set(), {}
    for i, (e, fp) in enumerate(zip(exps, now["entries"])):
        key = (e["script"], e["output"])
        p = prior_by.get(key)
        if p and p.get("verdict") == "PASS" and before.get(key) == fp["fingerprint"]:
            keep[i] = p
        else:
            rerun.add(i)
    # What reads an entry that runs again runs again; what it reads runs too.
    grew = True
    while grew:
        grew = False
        for i in list(keep):
            if deps[i] & rerun or closure(deps[i], deps) & rerun:
                rerun.add(i)
                del keep[i]
                grew = True
        need = closure(rerun, deps)
        for i in need - rerun:
            rerun.add(i)
            keep.pop(i, None)
            grew = True
    return (rerun, keep, prior.get("generated_at", "the earlier run")), removed, ""


def failures_of(experiments: list) -> list:
    out = []
    for e in experiments:
        if e.get("verdict") == "PASS":
            continue
        kind = e.get("failure") or ("unsupported_claim" if e.get("script") == "(paper)" else "mismatch")
        f = {"script": e.get("script"), "failure": kind}
        for k in ("why", "cause", "hint", "reads", "stderr_tail"):
            if e.get(k):
                f[k] = e[k]
        if kind in ("mismatch", "unclassified"):
            f["problems"] = (e.get("problems") or [])[:4]
        elif kind == "unsupported_claim":
            # Only the values: the step-14 go-back reads every unsupported_claim
            # in the report, and a second copy here would list each twice.
            f["values"] = [p.get("value") for p in (e.get("problems") or [])[:10]]
        out.append(f)
    return out


def summarize(result: dict, markdown: bool) -> tuple:
    """What failed, for a person or a turn: (text, exit code) -- 0 the agent
    can repair it, 1 a finding, 3 nothing failed."""
    fails = result.get("failures") or failures_of(result.get("experiments") or [])
    if result.get("verdict") == "PASS":
        return "The reproducibility gate passed.", 3
    kinds = {f["failure"] for f in fails}
    exps = [e for e in result.get("experiments") or [] if e.get("script") not in ("(paper)", "(manifest)")]
    passed = sum(e.get("verdict") == "PASS" for e in exps)
    if result.get("verdict") == "UNCHECKED":
        head, code = "the paper's cited numbers could not be checked -- for a person, not a rewrite.", 1
    elif not fails:
        head, code = "it failed; runs/REPRO_GATE.json says how.", 1
    elif kinds - REPAIRABLE:
        head = ("a number did not reproduce: a finding about the experiment, which the gate does not repair. "
                "Fix the experiment (step 5), not the paper.") if "mismatch" in kinds else \
               ("an entry that failed was taken out of the manifest: an experiment that does not reproduce "
                "is not dropped to pass.") if "removed" in kinds else \
               "the paper prints numbers no result holds."
        code = 1
    else:
        n = len([f for f in fails if f["script"] != "(manifest)"])
        head = ("the replay manifest cannot be used, so nothing was re-run." if kinds == {"manifest"} else
                f"{n} experiment(s) could not be re-run or compared, so nothing was compared for "
                f"{'it' if n == 1 else 'them'}: this is not a finding about the numbers. The agent can repair it.")
        code = 0
    lines = [f"**The reproducibility gate (step 10): {head}**" if markdown else f"repro-gate: {head}", ""]
    shown = fails[:6] if markdown else fails[:5]
    for f in shown:
        what = FAILURE_WORDS.get(f["failure"], f["failure"])
        why = f": {f['why']}" if f.get("why") else ""
        if markdown:
            lines.append(f"- `{f['script']}` {what}{why}")
            if f.get("hint"):
                lines.append(f"  {f['hint']}")
            for p in f.get("problems") or []:
                if p.get("kind") == "exact_mismatch":
                    lines.append(f"  - `{p['key']}`: recorded {p['recorded']}, re-run {p['rerun']}")
                elif p.get("kind") == "outside_tolerance":
                    lines.append(f"  - `{p['key']}`: recorded {p['recorded']}, re-run {p['rerun']} "
                                 f"(moved {p['drift']}, allowed {p['allowed']})")
                elif p.get("kind") == "unclassified":
                    lines.append(f"  - `{p['key']}` ({p.get('value')}) is in none of exact, tolerant, timing")
                elif p.get("kind") in ("vanished", "appeared"):
                    lines.append(f"  - {p['kind']}: {', '.join(p.get('keys', [])[:5])}")
            tail = [ln for ln in (f.get("stderr_tail") or "").splitlines() if ln.strip()][-6:]
            if tail:
                lines += ["  ```"] + [f"  {ln}" for ln in tail] + ["  ```"]
        else:
            lines.append(f"  FAIL {f['script']}: {what}{why}"[:400])
            if f.get("hint"):
                lines.append(f"       {f['hint']}"[:400])
    if len(fails) > len(shown):
        lines.append(f"{'- ' if markdown else '  '}and {len(fails) - len(shown)} more: runs/REPRO_GATE.json")
    if exps:
        lines += ["", f"{passed} of {len(exps)} experiment(s) reproduced"
                      + (f"; the scripts ran with {result['interpreter']} on {result['machine']}."
                         if result.get("interpreter") else ".")]
    return "\n".join(lines), code


def write_report(runs: str, result: dict) -> str:
    out = os.path.join(runs, "REPRO_GATE.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return out


def manifest_failure(runs: str, why: str, claims_only: bool) -> None:
    """A manifest that cannot be used: said in the report, for the turn that
    repairs it -- never over a full run's report from --claims-only."""
    print(f"repro-gate: {why}", file=sys.stderr)
    if not claims_only and os.path.isdir(runs):
        write_report(runs, {
            "verdict": "FAIL", "mode": "full", "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "experiments": [],
            "failures": [{"script": "(manifest)", "failure": "manifest", "why": why,
                          "hint": ("step 5 writes runs/REPLAY_MANIFEST.json: per script, the output it writes "
                                   "and which of its numbers are exact, tolerant or timing.")}]})
    sys.exit(2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir", help="work/<cycle>  (must contain runs/REPLAY_MANIFEST.json)")
    ap.add_argument("--only", help="run just this script (and the entries it runs after)")
    ap.add_argument("--aggregation", action="store_true",
                    help="re-run the manifest's `aggregation` (aggregate.py) in a clean copy holding the code and the "
                         "declared outputs only, and compare every file it writes (link 2 of the evidence chain)")
    ap.add_argument("--claims-only", action="store_true",
                    help="skip the re-run; only check that the paper's cited "
                         "numbers appear in runs/results/ (needs submission.json)")
    ap.add_argument("--retry-failed", action="store_true",
                    help="after a failed run: re-run only what failed (and what reads it), unless "
                         "anything else changed")
    ap.add_argument("--summary", action="store_true",
                    help="say what the last run found, and exit 0 if the agent can repair it, "
                         "1 if it is a finding, 2 if there is no report, 3 if it passed")
    a = ap.parse_args()

    runs = os.path.join(a.workdir, "runs")
    work = os.path.dirname(os.path.abspath(runs))
    if a.summary:
        try:
            with open(os.path.join(runs, "REPRO_GATE.json"), encoding="utf-8") as f:
                result = json.load(f)
        except (OSError, ValueError):
            print("The reproducibility gate left no report (runs/REPRO_GATE.json): see its output.")
            sys.exit(2)
        text, code = summarize(result, markdown=True)
        print(text)
        sys.exit(code)

    # The sweep code is written fresh each run and has picked both spellings, so
    # accept either rather than failing on a filename.
    # REPLAY_MANIFEST.json is the replay contract: script -> output -> which
    # fields must reproduce. The sweep also writes a MANIFEST.json describing the
    # run (models, levels, caps, cells) -- a different, useful document that
    # happens to want the same name. Prefer the unambiguous name, accept the
    # others, and require the replay fields either way.
    man_path = next((p for p in (os.path.join(runs, n) for n in MANIFEST_NAMES)
                     if os.path.exists(p)), None)
    if not man_path:
        manifest_failure(runs, f"no REPLAY_MANIFEST.json under {runs}. Step 5 must declare, per script, "
                               f"which output it writes and which fields must reproduce exactly.", a.claims_only)
    try:
        with open(man_path, encoding="utf-8") as f:
            man = json.load(f)
    except (OSError, ValueError) as e:
        manifest_failure(runs, f"{os.path.basename(man_path)} cannot be read ({e}).", a.claims_only)
    if not isinstance(man, dict):
        manifest_failure(runs, f"{os.path.basename(man_path)} is not a JSON object.", a.claims_only)

    exps = man.get("experiments", [])
    if not isinstance(exps, list) or not exps:
        aris_audit.emit(a.workdir, "paper-claim-audit", "BLOCKED",
                        "no_replay_manifest",
                        f"{os.path.basename(man_path)} declares no `experiments`, so "
                        f"nothing can be replayed. This is not a pass: an unverifiable "
                        f"run is BLOCKED, per ARIS's assurance contract.",
                        inputs=[man_path],
                        reasoning="Deterministic: the replay contract is absent.")
        manifest_failure(runs, f"BLOCKED -- {os.path.basename(man_path)} has no "
                               f"`experiments` list, so no script can be replayed and no number can "
                               f"be verified. It looks like a run-provenance manifest, not a replay "
                               f"manifest. Step 5 must write runs/REPLAY_MANIFEST.json with, per "
                               f"script: script, output, exact[], tolerant{{}}.", a.claims_only)
    try:
        check_entries(exps)
        deps = dependencies(exps)
        order = run_order(exps, deps)
        # --claims-only runs no script, so it needs no interpreter.
        python_cmd = [sys.executable] if a.claims_only else interpreter(man, work)
    except ManifestError as e:
        manifest_failure(runs, f"{os.path.basename(man_path)}: {e}", a.claims_only)

    if a.only and not any(e["script"] == a.only for e in exps):
        print(f"repro-gate: no entry runs {a.only}", file=sys.stderr)
        sys.exit(2)
    if a.aggregation:
        entry = replay_aggregation(work, runs, man, interpreter(man, work))
        entry.pop("_outputs", None)
        out = os.path.join(runs, "REPRO_GATE.json")
        try:
            with open(out, encoding="utf-8") as f:
                prior = json.load(f)
        except (OSError, ValueError):
            prior = {}
        prior = prior if isinstance(prior, dict) else {}
        exps_prior = [e for e in (prior.get("experiments") or []) if isinstance(e, dict)
                      and e.get("script") not in ("(paper)", "(aggregation)") and not e.get("aggregation")]
        entry["aggregation"] = True
        result = {**prior, "experiments": exps_prior + [entry]}
        replay_ok = all(e.get("verdict") == "PASS" for e in exps_prior)
        result["verdict"] = "PASS" if entry["verdict"] == "PASS" and replay_ok else "FAIL"
        result["failures"] = failures_of(result["experiments"])
        result["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        result["mode"] = "aggregation"
        write_report(runs, result)
        print(json.dumps(entry, indent=2)[:3000])
        if entry["verdict"] != "PASS":
            print()
            print(summarize(result, markdown=False)[0])
        print(f"\nrepro-gate: aggregation {entry['verdict']} -> {out}")
        sys.exit(0 if entry["verdict"] == "PASS" else 1)
    report, allok, mode, retried = [], True, "full", None
    if a.claims_only:
        print("repro-gate: --claims-only, skipping the execution replay")
    else:
        now = fingerprints(work, runs, man, exps)
        wanted = set(range(len(exps)))
        kept_from, keep, removed = None, {}, []
        if a.only:
            wanted = closure({i for i, e in enumerate(exps) if e["script"] == a.only}, deps)
            mode = "only"
        elif a.retry_failed:
            plan, removed, why = plan_retry(work, runs, man, exps, deps, now)
            if plan:
                wanted, keep, kept_from = plan
                mode = "retry"
                retried = [exps[i]["script"] for i in sorted(wanted)]
                print(f"repro-gate: running again what failed ({len(wanted)} of {len(exps)}); "
                      f"{len(keep)} kept from {kept_from}", flush=True)
            else:
                print(f"repro-gate: every entry runs ({why})", flush=True)
        env = man.get("env", {})
        outputs = {e["output"]: e["script"] for e in exps}
        readers = set().union(*(closure(deps[i], deps) for i in wanted)) if wanted else set()
        scratch = tempfile.mkdtemp(prefix="reprogate-keep-")
        made, entries = {}, {}
        try:
            for i in order:
                if i not in wanted:
                    continue
                exp = exps[i]
                missing = sorted(j for j in closure(deps[i], deps) - {i} if j not in made)
                if missing:
                    entries[i] = {"script": exp["script"], "output": exp["output"], "verdict": "FAIL",
                                  "failure": "blocked",
                                  "why": f"it runs after {exps[missing[0]]['script']}, which did not run to the end",
                                  "hint": "repair the entry it reads; this one runs once that one does."}
                    allok = False
                    continue
                feed = {exps[j]["output"]: made[j] for j in closure(deps[i], deps) - {i}}
                print(f"repro-gate: re-running {exp['script']} ...", flush=True)
                entry, kept = run_one(runs, exp, env, python_cmd, feed, scratch if i in readers else None, outputs)
                # A replay whose only problem is drift -- every exact field matched,
                # only `tolerant` fields moved past their bound -- runs once more
                # before it fails: a result that varies run to run can land outside
                # its band once. (Timing no longer fails at all: see `timing`.)
                if entry["verdict"] != "PASS" and entry.get("problems") and \
                        all(p.get("kind") == "outside_tolerance" for p in entry["problems"]):
                    print(f"repro-gate: only tolerant fields drifted; running {exp['script']} once more", flush=True)
                    first = entry
                    entry, kept = run_one(runs, exp, env, python_cmd, feed, scratch if i in readers else None, outputs)
                    entry["first_attempt"] = {"verdict": first["verdict"], "problems": first["problems"]}
                if kept:
                    made[i] = kept
                entries[i] = entry
                allok &= entry["verdict"] == "PASS"
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        for i, e in keep.items():
            entries[i] = {**e, "kept": True, "kept_from": e.get("kept_from") or kept_from}
            allok &= e.get("verdict") == "PASS"
        report = [entries[i] for i in range(len(exps)) if i in entries]
        for e in removed:
            report.append({"script": e.get("script"), "output": e.get("output"), "verdict": "FAIL",
                           "failure": "removed",
                           "why": f"in the run before, it {FAILURE_WORDS.get(e.get('failure'), 'failed')}",
                           "hint": ("an experiment that does not reproduce is not dropped to pass the gate; "
                                    "dropped, its results and every claim on them go too -- step 5 again.")})
            allok = False
        if not a.only:
            os.makedirs(os.path.join(work, ".aris"), exist_ok=True)
            with open(os.path.join(work, STATE), "w", encoding="utf-8") as f:
                json.dump({**now, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, f, indent=1)
            # Link 1 of the evidence chain: the declared outputs this replay
            # re-made, by hash -- evidence only while they stay as verified.
            save_state(work, "declared", {
                "runs/" + e["output"].lstrip("/"): sha256_of(os.path.join(runs, e["output"]))
                for e in report if e.get("verdict") == "PASS" and isinstance(e.get("output"), str)
                and os.path.isfile(os.path.join(runs, e["output"]))})

    # Second half of the job, and ARIS already owns it: do the numbers the paper
    # prints actually appear in the results files? `evidence_check.py` answers
    # that mechanically, so we call it rather than re-deriving it.
    #
    # It fails closed (a tester's report, 2026-10-05). A number counts only
    # when the checker confirmed it ("verified"); one it found nowhere is
    # unsupported; and one it could not decide -- the checker missing,
    # crashed, out of time, answering something unreadable, or silent about it
    # -- is "unchecked": never a pass, and not the paper's fault either, so
    # the verdict is UNCHECKED (exit 3), for a person, not a rewrite. Without
    # submission.json, --claims-only has nothing to check: UNCHECKED too.
    evidence = {"available": False}
    unchecked: list = []
    sub_path = os.path.join(a.workdir, "submission.json")
    if os.path.exists(sub_path) or a.claims_only:
        chain: dict = {"_files": []}
        # Link 2 again, now (interfaces/evidence-interface.md): what this check
        # reads is what the declared outputs make today -- not what
        # .aris/evidence.json says was made, which is a file like any other.
        fresh = None
        try:
            agg_spec = aggregation_of(man)
        except ManifestError:
            agg_spec = None    # build_claims says why in its notes
        if agg_spec is not None:
            try:
                agg_entry = replay_aggregation(work, runs, man, interpreter(man, work) if a.claims_only else python_cmd)
            except ManifestError as e:
                agg_entry = {"script": agg_spec["script"], "output": "aggregate__*.json, DESIGN.json", "verdict": "FAIL",
                             "failure": "manifest", "why": str(e)}
            fresh = {"outputs": agg_entry.pop("_outputs", None) or {}}
            report.append({**agg_entry, "aggregation": True})
            if agg_entry.get("verdict") != "PASS":
                allok = False
                print(f"repro-gate: the aggregates are not what aggregate.py makes from the results: {agg_entry.get('why')}")
        try:
            claims, rounded, other_metric, chain = build_claims(a.workdir, sub_path, man, fresh)
        except PaperUnreadable as e:
            claims, rounded, other_metric = [], [], []
            unchecked.append({"value": None, "status": "not_checked", "detail": str(e)})
            print(f"repro-gate: {e}")
        files = chain.pop("_files", [])
        print(f"repro-gate: {chain.get('mode', 'evidence chain')}: {len(files)} evidence file(s); "
              f"{chain.get('printed_with_ev', 0)} value(s) printed with \\ev and re-read from their field"
              f"{'; ' + str(len(chain.get('ledger_problems') or [])) + ' that do not match' if chain.get('ledger_problems') else ''}")
        for n in (chain.get("notes") or [])[:6]:
            print(f"repro-gate: note: {n}")
        print(f"repro-gate: {len(rounded)} paper figure(s) matched an evidence number "
              f"by rounding; {len(other_metric)} printed as a metric the evidence does not "
              f"hold them as; {len(claims)} still to verify literally")
        bad = list(other_metric) + list(chain.get("ledger_problems") or [])
        if claims:
            mirror = evidence_root(a.workdir, files)
            try:
                evidence = aris_audit.evidence_check(mirror, claims)
            finally:
                shutil.rmtree(mirror, ignore_errors=True)
            answered = {}
            for r in evidence.get("results") or []:
                if isinstance(r, dict):
                    answered.setdefault(str(r.get("value")), r)
            why_not = evidence.get("error") or evidence.get("note") or "the checker returned nothing for it"
            for c in claims:
                r = answered.get(c["value"])
                status = r.get("status") if r else None
                if status == "verified":
                    continue
                if status in ("path_missing", "value_not_found"):
                    bad.append({**c, **r})
                else:
                    unchecked.append({**c, "status": status or "not_checked",
                                      "detail": (r or {}).get("detail") or why_not})
            print(f"repro-gate: evidence check on {len(claims)} cited number(s): "
                  f"{len(bad) - len(other_metric) - len(chain.get('ledger_problems') or [])} unsupported, "
                  f"{len(unchecked)} could not be checked")
        if not claims:
            evidence = {"available": not unchecked, "results": []}
        evidence = {**evidence, "rounded_matches": rounded, "other_metric": other_metric, "chain": chain}
        for w in (chain.get("found_only_in_raw_files") or [])[:10]:
            print(f"repro-gate: warning: {w['value']} is found only in {w['found_at']} -- {w['why']}")
        if not claims and not other_metric and not unchecked:
            evidence["note"] = "every printed figure traced to a result number"
        if bad:
            allok = False
            report.append({"script": "(paper)", "verdict": "FAIL",
                           "problems": [{"kind": "unsupported_claim", **b} for b in bad[:20]]})
        if unchecked:
            evidence["unchecked"] = unchecked[:20]
            for u in unchecked[:10]:
                print(f"repro-gate: could not check {u.get('value') or 'the paper'}: {u.get('detail')}")

    result = {
        "verdict": "PASS" if allok and not unchecked else ("FAIL" if not allok else "UNCHECKED"),
        "workdir": os.path.abspath(a.workdir),
        "experiments": report,
        "evidence_check": evidence,
        "note": ("Every number a paper claims must appear under an `exact` field "
                 "that matched (a float to floating-point precision), or a "
                 "`tolerant` field within its band. `timing` fields are re-measured "
                 "and reported, never compared. UNCLASSIFIED means nobody decided "
                 "whether it reproduces."),
    }
    out = os.path.join(runs, "REPRO_GATE.json")
    # --claims-only performs no execution replay, so its `experiments` list is
    # empty. Writing that over a full run's report destroys the only record that
    # the numbers were re-derived -- and a reviewer who opens the artifact the
    # paper cites and finds "experiments": [] reasonably reads it as fabrication.
    # So the claims pass MERGES into the existing report instead of replacing it.
    if a.claims_only and os.path.exists(out):
        try:
            with open(out, encoding="utf-8") as f:
                prior = json.load(f)
        except (OSError, ValueError):
            prior = {}
        # Only the replay's own entries carry over. A "(paper)" entry is an
        # earlier claims pass's verdict on an earlier paper; keeping it meant
        # one failed check could never be passed again, however the paper was
        # fixed.
        prior_exps = [e for e in (prior.get("experiments") or [])
                      if e.get("script") != "(paper)" and not e.get("aggregation")]
        if prior_exps:
            result["experiments"] = prior_exps + [r for r in report
                                                  if r.get("script") == "(paper)" or r.get("aggregation")]
            # the replay verdict still stands; this pass can only add claim failures
            replay_ok = all(e.get("verdict") == "PASS" for e in prior_exps)
            result["verdict"] = ("FAIL" if not (allok and replay_ok)
                                 else "UNCHECKED" if unchecked else "PASS")
            result["replay_from"] = prior.get("generated_at", "earlier full run")
            for k in ("interpreter", "machine"):
                if prior.get(k):
                    result[k] = prior[k]
    else:
        result["interpreter"] = " ".join(python_cmd)
        result["machine"] = platform.machine() or "unknown"
    result["failures"] = failures_of(result["experiments"])
    result["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    result["mode"] = "claims_only" if a.claims_only else mode
    if retried is not None:
        result["retried"] = retried
    write_report(runs, result)

    # Hand the verdict to ARIS's own enforcer in its own schema. This fills the
    # paper-claim-audit slot, which normally wants a zero-context cross-model
    # reviewer; we have no second model family here, and ARIS's contract already
    # allows a deterministic verifier to stand in.
    nprob = sum(len(r.get("problems", [])) or (r.get("verdict") != "PASS") for r in report)
    # A check that could not run is ERROR in ARIS's terms -- submission-blocking,
    # and never mistaken for a FAIL the paper can be rewritten out of.
    audit = aris_audit.emit(
        a.workdir, "paper-claim-audit",
        "FAIL" if not allok else "ERROR" if unchecked else "PASS",
        ("reproduction_or_citation_failure" if not allok
         else "cited_numbers_not_checked" if unchecked else "numbers_reproduce_and_are_cited"),
        (f"Re-ran {len(report)} experiment(s) from a clean copy of runs/ and diffed "
         f"every leaf number against the recorded results; "
         f"{'all matched' if allok else f'{nprob} problem(s) found'}. "
         f"Cited-number check: "
         f"{'not run (no submission.json yet)' if not evidence.get('available') and not unchecked else str(len(evidence.get('results', []))) + ' checked'}"
         f"{f', {len(unchecked)} could not be checked' if unchecked else ''}."),
        inputs=[man_path, sub_path] + [os.path.join(runs, e["output"])
                                       for e in exps if os.path.exists(os.path.join(runs, e["output"]))],
        reasoning=("Deterministic: execution replay plus a literal search for each cited "
                   "value in the results file it claims to come from. No model judgement "
                   "is involved, so this verdict is reproducible by anyone with the repo."),
        extra={"experiments": report, "evidence_check": evidence})

    print(json.dumps(result, indent=2)[:4000])
    # What failed comes last, so the end of this output -- which is what a
    # stopped step shows its owner -- names it (a tester's report, 2026-10-06:
    # the end was timing drifts, and the two crashes were above them).
    if result["verdict"] != "PASS":
        print()
        print(summarize(result, markdown=False)[0])
    print(f"\nrepro-gate: {result['verdict']} -> {out}")
    print(f"repro-gate: ARIS verdict -> {audit}")
    sys.exit(1 if result["verdict"] == "FAIL" else 3 if result["verdict"] == "UNCHECKED" else 0)


if __name__ == "__main__":
    main()
