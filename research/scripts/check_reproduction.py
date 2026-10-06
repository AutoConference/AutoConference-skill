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
import json
import math
import os
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
MEANINGFUL = re.compile(r"(?<![\w.])(\d+\.\d+|\d{4,})(?![\w.])")
# The sign in front of a printed number, when there is one: ASCII hyphen, the
# Unicode minus, or LaTeX's $-$. A difference table prints "-95.9 [-98.8,-92.6]";
# read without its sign, -95.9 in the results never matched, and every
# negative result in a paper was reported as fabricated.
SIGN_BEFORE = re.compile(r"(?:-|\u2212|\$-\$|\$\u2212\$)$")

# An arXiv id is shaped exactly like a number the paper might claim, and it is
# never a result. Citing arXiv:2506.09250 must not read as claiming 2506.0925.
ARXIV_ID = re.compile(r"(?:arxiv[:\s]*)?(\d{4}\.\d{4,5})(?:v\d+)?", re.I)


# The gates' own reports sit under runs/ beside the results, and list the very
# numbers a paper printed -- the unsupported ones too, as strings. Read as
# evidence, a second check passed every number the first had found unsupported
# (found 2026-10-05). A report is never evidence.
GATE_OUTPUTS = {"REPRO_GATE.json"}

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


def entries_of(doc, where: str, out: list, declared: set) -> None:
    """Every leaf number in a parsed results file, with the names it is stored
    under: its own key; for a statistic (mean, ci_low, values...), the metric
    beside it or above it; and any metric a dict around it declares
    ("metric": "accuracy", as every aggregate does)."""
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
                    names = set(metrics)
                    if parent and not is_stat(parent):
                        names.add(canon(parent))
                    out.append((v, frozenset(n for n in names if n), f"{where}:{p}"))
    walk(doc, "", "", frozenset())


def result_entries(runs: str) -> tuple:
    """Every leaf number in every results file -- (value, names, where) -- so
    a paper's ROUNDED figure can be matched against the full-precision value it
    came from, and the metrics the results declare."""
    out, declared = [], set()
    # Walk the whole results tree, not two fixed directories: the sweep decides its
    # own layout and CALIBRATION.json sitting one level up was being missed.
    for dirpath, dirnames, names in os.walk(runs):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in sorted(names):
            if not name.endswith((".json", ".jsonl")) or name in GATE_OUTPUTS:
                continue
            path = os.path.join(dirpath, name)
            where = os.path.relpath(path, os.path.dirname(os.path.abspath(runs)))
            try:
                if name.endswith(".jsonl"):
                    with open(path, encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                entries_of(json.loads(line), where, out, declared)
                else:
                    with open(path, encoding="utf-8") as f:
                        entries_of(json.load(f), where, out, declared)
            except (OSError, ValueError):
                continue
    # A paper legitimately states hardware facts and configuration constants that
    # are not experimental results: the machine description (AC_MACHINE, default
    # state/machine.json) and the quality bar. Treat those as sources too rather
    # than reporting them as unsupported claims. (These were looked for under a
    # config/ directory that the reorganised kit no longer has.)
    kit = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for path in (os.environ.get("AC_MACHINE") or os.path.join(kit, "state", "machine.json"),
                 os.path.join(kit, "interfaces", "quality.example.json")):
        try:
            with open(path, encoding="utf-8") as f:
                entries_of(json.load(f), os.path.basename(path), out, set())
        except (OSError, ValueError):
            pass
    return out, declared


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


def build_claims(workdir: str, submission_path: str) -> tuple:
    """Split the paper's printed numbers into (to check literally,
    matched_by_rounding, printed_as_another_metric).

    ARIS's evidence_check.py is the checker of record, but it searches literally,
    so it cannot see that 0.067 came from 0.06666666666666667. Anything it would
    miss for that reason is resolved here instead of being reported as a
    fabricated number -- but only by a result of the metric the paper prints it
    as. Where the paper names a metric the results declare (an aggregate's
    `metric`) beside the number -- its sentence, or its table column and
    caption -- a result of another metric that happens to round to it does not
    count; the number is reported, with what the results do hold it as. Where
    the paper names none, any result number will do, as before.
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
    text = "\n".join(str(sub.get(k, "")) for k in ("abstract", "body_md"))
    cited_ids = {m.group(1) for m in ARXIV_ID.finditer(text)}
    entries, declared = result_entries(os.path.join(workdir, "runs"))
    vocab = declared | {n for _, names, _ in entries for n in names}
    by_dp: dict = {}

    def candidates(value: str) -> list:
        """Results that round to `value` at the precision it is printed."""
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

    spans = [m.span() for rx in CITATION_SPANS for m in rx.finditer(text)]

    def in_citation(pos: int) -> bool:
        return any(a <= pos < b for a, b in spans)

    # Each place a number is printed is read on its own: the same value may be
    # a cited work's in one sentence, an accuracy in another, a loss in a third.
    claims, rounded, other_metric = [], [], []
    literal, plain, judged = set(), set(), set()
    for m in MEANINGFUL.finditer(text):
        v = m.group(1)
        if v in cited_ids:
            continue
        if YEAR.fullmatch(v) and in_citation(m.start()):
            continue    # this occurrence is a cited work's year; others still count
        # A signed number must match with its sign; an unsigned one may be a
        # magnitude ("regret falls by 95.9"), so either sign will do.
        neg = bool(SIGN_BEFORE.search(text[max(0, m.start() - 3):m.start()]))
        key = ("-" if neg else "") + v
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
                rounded.append({"value": key, "matched": "rounded_to_a_result_number"})
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
                             "why": (f"printed as {' / '.join(sorted(named))}; the results hold {key} only as "
                                     f"{', '.join(held[:6])} ({', '.join(e[2] for e in cands[:3])})")})
    rounded = list({(r["value"], r["matched"]): r for r in rounded}.values())
    return claims, rounded, other_metric


def evidence_root(workdir: str) -> str:
    """runs/ as the literal search may read it: every results file but the
    gates' own reports (GATE_OUTPUTS), linked into .aris/evidence-root/."""
    root = os.path.join(workdir, ".aris", "evidence-root")
    shutil.rmtree(root, ignore_errors=True)
    runs = os.path.join(workdir, "runs")
    for dirpath, dirnames, names in os.walk(runs):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in names:
            if not name.endswith((".json", ".jsonl")) or name in GATE_OUTPUTS:
                continue
            src = os.path.join(dirpath, name)
            dst = os.path.join(root, "runs", os.path.relpath(src, runs))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
    os.makedirs(os.path.join(root, "runs"), exist_ok=True)
    return root


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


def run_one(runs: str, exp: dict, env: dict, report: list) -> bool:
    script = exp["script"]
    out_rel = exp["output"]
    recorded_path = os.path.join(runs, out_rel)
    if not os.path.exists(recorded_path):
        report.append({"script": script, "verdict": "FAIL",
                       "why": f"no recorded output at {out_rel}"})
        return False
    with open(recorded_path, encoding="utf-8") as f:
        recorded = json.load(f)

    # A clean copy of the WHOLE workspace, not just runs/: the sweep code has
    # lived in runs/scripts/ on one run and in a sibling code/ on the next, and
    # a gate that only copies runs/ silently fails on the second layout. Copying
    # the tree also preserves the ../runs/ paths those scripts compute from
    # __file__. Recorded results are dropped so a script that quietly reads its
    # own previous output fails here rather than in review.
    work = os.path.dirname(os.path.abspath(runs))
    tmp = tempfile.mkdtemp(prefix="reprogate-")
    try:
        for dirpath, dirnames, filenames in os.walk(work):
            dirnames[:] = [d for d in dirnames if not skipped_dir(dirpath, d)]
            rel = os.path.relpath(dirpath, work)
            dst = tmp if rel == "." else os.path.join(tmp, rel)
            os.makedirs(dst, exist_ok=True)
            for fn in filenames:
                if fn.endswith(".json.tmp") or fn.endswith(".pyc"):
                    continue
                try:
                    shutil.copy2(os.path.join(dirpath, fn), os.path.join(dst, fn))
                except OSError:
                    pass
        # the output must be produced by the re-run, not inherited from it
        stale = os.path.join(tmp, "runs", out_rel)
        if os.path.exists(stale):
            os.remove(stale)
        os.makedirs(os.path.join(tmp, "runs", os.path.dirname(out_rel) or "."),
                    exist_ok=True)

        # scripts are named relative to runs/ by convention, but may sit anywhere
        # in the tree; resolve against runs/ first, then the workspace root.
        cand = [os.path.join(tmp, "runs", script), os.path.join(tmp, script)]
        script_abs = next((c for c in cand if os.path.exists(c)), cand[0])
        cmd = [sys.executable, script_abs] + [str(x) for x in exp.get("args", [])]
        t0 = time.time()
        proc = subprocess.run(cmd, cwd=os.path.dirname(script_abs) or tmp,
                              env=dict(os.environ, **env),
                              capture_output=True, text=True,
                              timeout=exp.get("timeout_s", 3600))
        dt = time.time() - t0
        if proc.returncode != 0:
            report.append({"script": script, "verdict": "FAIL",
                           "why": f"exit {proc.returncode}",
                           "stderr_tail": proc.stderr[-1200:]})
            return False
        fresh_path = os.path.join(tmp, "runs", out_rel)
        if not os.path.exists(fresh_path):
            report.append({"script": script, "verdict": "FAIL",
                           "why": f"the re-run produced no {out_rel}"})
            return False
        with open(fresh_path, encoding="utf-8") as f:
            fresh = json.load(f)
    except subprocess.TimeoutExpired:
        report.append({"script": script, "verdict": "FAIL",
                       "why": f"timed out after {exp.get('timeout_s', 3600)}s"})
        return False
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
    entry = {"script": script, "verdict": verdict, "rerun_wall_s": round(dt, 1),
             "checked": checked, "problems": problems}
    if float_noise:
        entry["float_precision_matches"] = float_noise
    if measured:
        entry["timing"] = measured[:20]
    report.append(entry)
    return verdict == "PASS"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir", help="work/<cycle>  (must contain runs/manifest.json)")
    ap.add_argument("--only", help="run just this script name")
    ap.add_argument("--claims-only", action="store_true",
                    help="skip the re-run; only check that the paper's cited "
                         "numbers appear in runs/results/ (needs submission.json)")
    a = ap.parse_args()

    runs = os.path.join(a.workdir, "runs")
    # The sweep code is written fresh each run and has picked both spellings, so
    # accept either rather than failing on a filename.
    # REPLAY_MANIFEST.json is the replay contract: script -> output -> which
    # fields must reproduce. The sweep also writes a MANIFEST.json describing the
    # run (models, levels, caps, cells) -- a different, useful document that
    # happens to want the same name. Prefer the unambiguous name, accept the
    # others, and require the replay fields either way.
    man_path = next((p for p in (os.path.join(runs, n) for n in
                                 ("REPLAY_MANIFEST.json", "replay_manifest.json",
                                  "manifest.json", "MANIFEST.json"))
                     if os.path.exists(p)), None)
    if not man_path:
        print(f"repro-gate: no REPLAY_MANIFEST.json under {runs}. Step 5 must "
              f"declare, per script, which output it writes and which fields must "
              f"reproduce exactly.", file=sys.stderr)
        sys.exit(2)
    with open(man_path, encoding="utf-8") as f:
        man = json.load(f)

    exps = man.get("experiments", [])
    if a.only:
        exps = [e for e in exps if e["script"] == a.only]
    if not exps:
        aris_audit.emit(a.workdir, "paper-claim-audit", "BLOCKED",
                        "no_replay_manifest",
                        f"{os.path.basename(man_path)} declares no `experiments`, so "
                        f"nothing can be replayed. This is not a pass: an unverifiable "
                        f"run is BLOCKED, per ARIS's assurance contract.",
                        inputs=[man_path],
                        reasoning="Deterministic: the replay contract is absent.")
        print(f"repro-gate: BLOCKED -- {os.path.basename(man_path)} has no "
              f"`experiments` list, so no script can be replayed and no number can "
              f"be verified. It looks like a run-provenance manifest, not a replay "
              f"manifest. Step 5 must write runs/REPLAY_MANIFEST.json with, per "
              f"script: script, output, exact[], tolerant{{}}.", file=sys.stderr)
        sys.exit(2)

    report, allok = [], True
    if a.claims_only:
        print("repro-gate: --claims-only, skipping the execution replay")
    else:
        for exp in exps:
            print(f"repro-gate: re-running {exp['script']} ...", flush=True)
            ok = run_one(runs, exp, man.get("env", {}), report)
            # A replay whose only problem is drift -- every exact field matched,
            # only `tolerant` fields moved past their bound -- runs once more
            # before it fails: a result that varies run to run can land outside
            # its band once. (Timing no longer fails at all: see `timing`.)
            last = report[-1] if report else {}
            if not ok and last.get("problems") and \
                    all(p.get("kind") == "outside_tolerance" for p in last["problems"]):
                print(f"repro-gate: only tolerant fields drifted; running {exp['script']} once more", flush=True)
                first = report.pop()
                ok = run_one(runs, exp, man.get("env", {}), report)
                report[-1]["first_attempt"] = {"verdict": first["verdict"], "problems": first["problems"]}
            allok &= ok

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
        try:
            claims, rounded, other_metric = build_claims(a.workdir, sub_path)
        except PaperUnreadable as e:
            claims, rounded, other_metric = [], [], []
            unchecked.append({"value": None, "status": "not_checked", "detail": str(e)})
            print(f"repro-gate: {e}")
        print(f"repro-gate: {len(rounded)} paper figure(s) matched a result number "
              f"by rounding; {len(other_metric)} printed as a metric the results do not "
              f"hold them as; {len(claims)} still to verify literally")
        bad = list(other_metric)
        if claims:
            mirror = evidence_root(a.workdir)
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
                  f"{len(bad) - len(other_metric)} unsupported, {len(unchecked)} could not be checked")
        if not claims:
            evidence = {"available": not unchecked, "results": []}
        evidence = {**evidence, "rounded_matches": rounded, "other_metric": other_metric}
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
                      if e.get("script") != "(paper)"]
        if prior_exps:
            result["experiments"] = prior_exps + [r for r in report
                                                  if r.get("script") == "(paper)"]
            # the replay verdict still stands; this pass can only add claim failures
            replay_ok = all(e.get("verdict") == "PASS" for e in prior_exps)
            result["verdict"] = ("FAIL" if not (allok and replay_ok)
                                 else "UNCHECKED" if unchecked else "PASS")
            result["replay_from"] = prior.get("generated_at", "earlier full run")
    result["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    result["mode"] = "claims_only" if a.claims_only else "full"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    # Hand the verdict to ARIS's own enforcer in its own schema. This fills the
    # paper-claim-audit slot, which normally wants a zero-context cross-model
    # reviewer; we have no second model family here, and ARIS's contract already
    # allows a deterministic verifier to stand in.
    nprob = sum(len(r.get("problems", [])) for r in report)
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
    print(f"\nrepro-gate: {result['verdict']} -> {out}")
    print(f"repro-gate: ARIS verdict -> {audit}")
    sys.exit(1 if result["verdict"] == "FAIL" else 3 if result["verdict"] == "UNCHECKED" else 0)


if __name__ == "__main__":
    main()
