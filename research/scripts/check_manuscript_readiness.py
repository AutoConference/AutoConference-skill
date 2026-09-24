#!/usr/bin/env python3
"""Read-only evidence inventory for the Bound-to-Disagree manuscript gate.

    python3 scripts/check_manuscript_readiness.py [ROOT] [--json]

Checks three things about every row that asserts something about the method:
it aggregates more than one seed, it names the module it removed, and it names
a preserved run it was measured against. Only the first of those was ever
enforced, which made a sweep over seeds the cheapest row that could pass.

Read-only. Never writes to the workspace.

Exit codes: 0 the gate passed, 1 the gate blocked, 2 it could not run at all
(no results.tsv here) — which is a mistake about the path, not about the
evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = {
    "commit",
    "hypothesis",
    "varied",
    "how",
    "contrast",
    "metric",
    "seeds",
    "spread",
    "status",
    "tuning",
    "notes",
    "evidence",
}
# Where this arm's hyperparameters came from.
#
# Remove a module and keep the baseline's settings, and the variant runs on
# hyperparameters tuned for a system that still had the module — so a loss is
# the module's contribution confounded with how badly those settings suit the
# smaller system. Re-tune instead and two things changed, not one. Both designs
# are defensible and they answer different questions: what the module
# contributes to THIS configuration, versus what it contributes to the best
# system buildable without it. A grid that mixes them answers neither.
#
# The worst case is the cheapest one: a full method tuned over months of
# development and an ablation run once with those settings. That asymmetry
# inflates every module's apparent contribution, and it is the default path.
#
# Nothing here can verify what was actually done — the same limit `how` has.
# What it can do is refuse a grid that will not say, and refuse one that answers
# both questions at once.
# `derived` is the third policy, and the vocabulary was short of it one day
# after it was added. A differentially private grid re-solves the privacy
# equation for each arm at fixed epsilon: the VALUES differ per arm and no
# search happened, so it is neither inherited nor retuned. What is held constant
# is the rule. Recording that as `retuned` would invent a search budget that
# does not exist; as `inherited` it would claim values that were not used.
TUNING_VALUES = {"inherited", "retuned", "derived", "none"}
# What was done to the module named in `varied`.
#
# `varied` alone cannot carry this. Setting a regulariser's weight to 0.0 and
# setting it to 0.2 are both "varied=regularisation", and only the first is an
# ablation — so a module could be discharged by a dose-response sweep that never
# removed anything. Observed in a planning run: six interior points were filed
# against two modules whose removal rows the same plan did contain, which was
# honest, and nothing in the ledger would have distinguished it from a plan that
# swept in place of removing.
HOW_VALUES = {"removed", "replaced", "swept", "none"}
# Only these discharge a module. A sweep is a legitimate claim about the
# module's setting; it is not evidence that the module is load-bearing.
COVERING_HOW = {"removed", "replaced"}
# Statuses that assert something about the METHOD. Each needs a module named in
# `varied` and a resolvable `contrast`, not merely more than one seed. Before
# those two conditions existed, seeds>1 was the whole bar, so a sweep over seeds
# was the cheapest row that could pass and the record filled with them.
# `off-constraint` is here because a constrained metric — goodput *at fixed
# fairness*, accuracy *at fixed epsilon* — can be left rather than lost. The
# variant finished; it is simply outside the region where the metric means what
# its name says. A validation across 33 ideas found two studies forced to record
# that as `crash` with `metric=nan`, which is for runs that did not finish, so
# the record could not tell a failed run from a successful one that moved off
# the axis.
#
# It discharges its module, and should: a part whose absence puts the system
# outside the metric's feasible region is load-bearing more clearly than a small
# delta would show. It owes the same module, `how` and baseline contrast as any
# other claim; what it does not owe is a comparable number.
CLAIM_STATUSES = {"keep", "baseline", "no-effect", "off-constraint"}
# A seed-stability observation. Legitimate, recorded, and barred from being a
# headline claim: it is a property of the pipeline, not of the method.
VARIANCE_STATUS = "variance"
# A run that is neither the method nor an ablation of it, recorded so the other
# rows have something to be read against: what the trivial behaviour scores on a
# metric that can be satisfied degenerately, the chance level, or the baseline's
# own value for a constraint the metric is defined inside.
#
# Both came from an advice audit. On a metric maximised by emitting nothing, the
# degeneracy rule tells you a "removal improved it" row may be an artefact and
# stops there — an agent observed that it "fixes the sign but not the
# attribution" and built the missing probe itself. And a constrained metric
# assumes the full method clears the constraint, which nothing in the ledger
# could state.
REFERENCE_STATUS = "reference"
# A row written before its run, which SKILL.md demands twice and the status
# vocabulary could not express. Six agents in a validation across 33 ideas each
# invented `planned` independently, as did an unrelated agent before them: the
# doctrine's first rule had no way to be recorded in the doctrine's own schema.
#
# A planned row is checked for shape — it names a module, says what will be done
# to it, and names the run it will be measured against — and exempt from every
# check that needs a file, because by definition none exists yet. It discharges
# no module: what is planned is not what is done.
PLANNED_STATUS = "planned"
# Statuses whose rows cite no evidence on disk, for opposite reasons: the run
# has not happened, or it happened and produced nothing citable.
NO_EVIDENCE_EXPECTED = {PLANNED_STATUS, "crash", "unverifiable"}
ABLATION_PLAN = "ablation-plan.tsv"
ABLATION_PLAN_COLUMNS = {"module", "source", "removal", "ablatable", "reason"}
AFFIRMATIVE = {"yes", "y", "true", "1"}
# Strings that occupy the `reason` cell without saying anything. The check that
# a reason merely exists is satisfied by "n/a", and an adversarial sweep found
# that "declare every module un-ablatable, reason n/a" passed the gate with zero
# ablations run. Length is a blunt instrument and it is the only one available:
# nothing here can judge whether a sentence is true, only whether it is a
# sentence.
NON_REASONS = {"", "-", "--", "n/a", "na", "none", "no", "tbd", "todo", "?", "x", "unknown"}
MIN_REASON_CHARS = 25
# Field names an aggregate may use to list the raw runs it combines.
#
# `primary_inputs` is the one the contract actually specifies
# (interfaces/evidence-interface.md, and REQUIRED in
# make_paper_data.py), and it was missing here — so an aggregate written to the
# documented schema was rejected as having no input manifest. Every test fixture
# happened to use `source_runs`, so the suite never noticed. The other three stay
# because legacy aggregates in the workspace use them.
INPUT_KEYS = ("primary_inputs", "source_runs", "source_files", "inputs", "raw_inputs")
PRIMARY_MANIFEST_KEYS = {
    "run_id",
    "method",
    "source_script",
    "source_commit",
    "command",
    "dataset",
    "split_seed",
    "trajectory_seed",
    "full_config",
    "started_at",
    "completed_at",
    "raw_result_path",
}


class Report:
    """Findings with a severity, copied from paper-writing/scripts/check_paper_structure.py.

    Only `error` blocks. The gate had no severity concept — every finding was
    fatal — which is untenable for an agent that runs unattended and cannot be
    rescued: a note about a thin sentence must not wedge a run the way a wrong
    number should.
    """

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def add(self, severity: str, code: str, message: str, where: str = "") -> None:
        self.items.append({"severity": severity, "code": code, "message": message, "where": where})

    def error(self, code, message, where=""):
        self.add("error", code, message, where)

    def warn(self, code, message, where=""):
        self.add("warning", code, message, where)

    def note(self, code, message, where=""):
        self.add("advisory", code, message, where)

    @property
    def blocking(self) -> int:
        return sum(1 for i in self.items if i["severity"] == "error")


def parse_number(cell: str) -> float | None:
    """A finite float, or None.

    Non-finite values must not come back as numbers. `float("nan")` parses
    happily and then compares False to everything, so a NaN would slip through
    every tolerance check silently — and `nan` is exactly what a crash row
    carries by contract.
    """
    try:
        value = float((cell or "").strip())
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def ledger_tolerance(cell: str) -> float:
    """How far the ledger and the artifact may differ before it is a mistake.

    Derived from the cell's own precision rather than a constant. `0.187`
    asserts the true value lies in [0.1865, 0.1875), so honest rounding passes
    and a genuine second-decimal error does not. A fixed epsilon has to be
    either too tight for three decimals or too loose for two; there is no value
    that is right for both.
    """
    decimals = len((cell or "").strip().partition(".")[2])
    return 0.5 * 10 ** -decimals + 1e-9


def aggregate_mean(doc: Any) -> float | None:
    if not isinstance(doc, dict):
        return None
    overall = doc.get("overall")
    if not isinstance(overall, dict):
        return None
    return parse_number(str(overall.get("mean")))


def aggregate_spread(doc: Any) -> float | None:
    """max − min over every raw value the aggregate lists, which is what the
    ledger's `spread` column means."""
    if not isinstance(doc, dict):
        return None
    per_split = doc.get("per_split")
    if not isinstance(per_split, dict):
        return None
    values: list[float] = []
    for entry in per_split.values():
        if isinstance(entry, dict):
            for raw in entry.get("values") or []:
                number = parse_number(str(raw))
                if number is not None:
                    values.append(number)
    if len(values) < 2:
        return None
    return max(values) - min(values)


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def evidence_kind(value: Any) -> str:
    if isinstance(value, dict) and isinstance(value.get("config"), dict):
        return "primary"
    return "derived"


def has_input_manifest(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(isinstance(value.get(key), list) and value[key] for key in INPUT_KEYS)


def run_identifiers(evidence: str) -> set[str]:
    """Every name a `contrast` may legitimately use to point at this evidence.

    Runs are preserved as `runs/<label>__<commit>.json`, aggregates as
    `runs/aggregate__<method>.json`, so both the full stem and the part before
    `__` are names a human would reach for. Accept either; an ambiguous choice
    is a readability problem for the author, not something this gate can fix.
    """
    names: set[str] = set()
    for part in evidence.split(";"):
        stem = Path(part.strip()).stem
        if not stem:
            continue
        names.add(stem)
        before, sep, after = stem.partition("__")
        names.add(before)
        # `aggregate__<method>.json` is the interface's own naming, so for those
        # the meaningful name is the half AFTER the separator — the method. The
        # half before it is the literal word "aggregate", identical for every
        # aggregate in a run and therefore identifying nothing. Six ideas in a
        # validation wrote `contrast=<method>`, which is the natural thing, and
        # were blocked by a gate that offered only the useless half.
        if sep and before == "aggregate" and after:
            names.add(after)
    return names


def read_ablation_plan(root: Path) -> tuple[list[dict[str, str]], list[str]]:
    """The declared module list: what the method is made of.

    Returned as (rows, problems). A missing plan is a problem rather than an
    empty plan: "we never wrote down what the modules are" and "the method has
    no modules" must not produce the same verdict.
    """
    path = root / ABLATION_PLAN
    if not path.is_file():
        return [], [f"{ABLATION_PLAN} not found; declare the method's modules before claiming any of them contribute"]
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        missing = sorted(ABLATION_PLAN_COLUMNS - set(reader.fieldnames or []))
        if missing:
            return [], [f"{ABLATION_PLAN} missing columns: {', '.join(missing)}"]
        return list(reader), []


def inspect(root: Path) -> dict[str, Any]:
    results_path = root / "results.tsv"
    with results_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        columns = set(reader.fieldnames or [])
        missing_columns = sorted(REQUIRED_COLUMNS - columns)
        if missing_columns:
            raise ValueError(f"results.tsv missing columns: {', '.join(missing_columns)}")
        rows = list(reader)

    rep = Report()
    status_counts = Counter(row["status"] for row in rows)
    primary_rows: list[dict[str, Any]] = []
    derived_rows: list[dict[str, Any]] = []
    primary_seeds: Counter[str] = Counter()
    ablated_modules: Counter[str] = Counter()
    swept_modules: Counter[str] = Counter()
    tuning_policies: dict[str, list[str]] = {}
    aggregates_by_row: dict[int, list[Any]] = {}
    aggregates_by_name: dict[str, list[Any]] = {}
    recomputed: list[dict[str, Any]] = []

    # Every name any row's evidence can be referred to by. Built first, over all
    # rows, because a `contrast` legitimately points backwards at a run recorded
    # on an earlier line and forwards at nothing.
    known_runs: set[str] = set()
    baseline_runs: set[str] = set()
    baseline_seeds: set[str] = set()
    for row in rows:
        names = run_identifiers(row.get("evidence") or "")
        known_runs |= names
        if (row.get("status") or "").strip() == "baseline":
            baseline_runs |= names
            baseline_seeds.add((row.get("seeds") or "").strip())

    # ── row-level checks ─────────────────────────────────────────────────────
    # Deliberately NOT inside the per-evidence-file loop below. They used to be,
    # and that loop only reaches the seeds test on the `primary` branch — so a
    # claim row citing an aggregate (which is `derived`, and which is what a
    # claim row normally cites) was never checked for seeds at all. The bar the
    # ledger documented and the bar the gate applied were different bars.
    for index, row in enumerate(rows, start=2):
        status = (row.get("status") or "").strip()
        label = f"line {index} ({row.get('commit', '?')})"
        varied = (row.get("varied") or "").strip()
        contrast = (row.get("contrast") or "").strip()

        tuning = (row.get("tuning") or "").strip().lower() or "none"
        single_module = bool(varied) and varied != "none" and "+" not in varied
        how = (row.get("how") or "none").strip() or "none"
        if how not in HOW_VALUES:
            rep.error(
                "invalid_how_values",
                f"how={how!r}; must be one of {', '.join(sorted(HOW_VALUES))}",
                label,
            )

        if status == PLANNED_STATUS:
            # The shape is checkable now; the numbers are not. Checking it now
            # is the whole point of pre-registration — a plan whose rows cannot
            # become claims is worth knowing about before the runs, not after.
            # A planned row naming no module is the planned baseline, which is
            # correct and needs nothing else.
            if single_module and how == "none":
                rep.error(
                    "claim_rows_naming_no_module",
                    f"planned row names module {varied!r} but `how` is none; say whether it "
                    f"will be removed, replaced, or swept",
                    label,
                )
            if single_module and how != "none" and contrast and contrast != "-":
                if contrast not in known_runs:
                    rep.error(
                        "claim_rows_with_unresolved_contrast",
                        f"contrast={contrast!r} names no run, planned or preserved",
                        label,
                    )

        if status in CLAIM_STATUSES or status == PLANNED_STATUS:
            if tuning not in TUNING_VALUES:
                rep.error(
                    "invalid_tuning_value",
                    f"tuning={tuning!r}; must be one of {', '.join(sorted(TUNING_VALUES))} — "
                    f"where this arm's hyperparameters came from",
                    label,
                )
            elif status != "baseline":
                tuning_policies.setdefault(tuning, []).append(label)

        if status in CLAIM_STATUSES:
            try:
                seeds = int(row.get("seeds") or 0)
            except ValueError:
                seeds = 0
            # `off-constraint` can be analytic rather than measured: removing
            # gradient clipping makes epsilon unbounded by the definition of the
            # mechanism, not by observation. An agent pointed out that the gate
            # was making it burn five runs to restate a theorem.
            if seeds <= 1 and status != "off-constraint":
                rep.error("single_run_rows_marked_as_claims", "one run is an anecdote; a claim aggregates more than one seed", label)
            # The baseline is the full method, so it removes nothing and is
            # measured against nothing. Every other claim status owes both.
            if status != "baseline" and (not varied or varied == "none"):
                rep.error(
                    "claim_rows_naming_no_module",
                    f"status={status} names no module in `varied`; a run that changed "
                    f"nothing is not evidence about the method (use status=variance)",
                    label,
                )
            elif status != "baseline" and how == "none":
                rep.error(
                    "claim_rows_naming_no_module",
                    f"names module {varied!r} but `how` is none; say whether it was "
                    f"removed, replaced, or swept",
                    label,
                )
            if status != "baseline":
                if not contrast or contrast == "-":
                    rep.error("claim_rows_with_unresolved_contrast", "no `contrast`", label)
                elif contrast not in known_runs:
                    rep.error(
                        "claim_rows_with_unresolved_contrast",
                        f"contrast={contrast!r} names no preserved run",
                        label,
                    )
                # A single-module row is measured against the FULL method or it
                # is measuring something else. Contrast it against another
                # ablation and the recorded number is "A removed vs B removed"
                # while the column heading still says "what A contributes" — and
                # when B is load-bearing, that arithmetic flips the sign: a
                # module that costs 0.008 to remove reads as improving the
                # metric by 0.045. Both rows look identical in the table.
                #
                # Interactions are exempt: comparing `A+B` against `B` alone is
                # the right reference for what A adds on top of B. Naming one
                # module while measuring against a modified context is the case
                # this refuses — say `A+B` if that is what you ran.
                elif single_module and how != "none":
                    if not baseline_runs:
                        rep.error(
                            "rows_not_measured_against_the_full_method",
                            f"no row with status=baseline exists, so there is no full "
                            f"method to measure {varied!r} against",
                            label,
                        )
                    elif contrast not in baseline_runs:
                        rep.error(
                            "rows_not_measured_against_the_full_method",
                            f"contrast={contrast!r} is not the baseline; a single-module "
                            f"row must be measured against the full method "
                            f"({', '.join(sorted(baseline_runs))})",
                            label,
                        )
            # The baseline is the reference every other row is read against, so
            # it cannot also be one of the things being measured. Left
            # unchecked, a single row could be both "the full method" and
            # "coreset removed" — discharging the module against itself.
            if status == "baseline" and (
                (varied and varied != "none") or how != "none"
            ):
                rep.error(
                    "baseline_rows_that_also_ablate",
                    f"a baseline row is the full method; it cannot also report "
                    f"varied={varied!r} how={how!r}",
                    label,
                )

            # Same seeds on both sides, or the delta and the spread are not
            # commensurable. The skill asks for the ablation to run "over the
            # same seeds as the full method"; nothing enforced it, so a 2-seed
            # ablation could be read against a 15-seed baseline.
            if status != "baseline" and single_module and how != "none" and baseline_seeds:
                if str(seeds) not in baseline_seeds:
                    rep.error(
                        "seed_counts_not_matching_the_baseline",
                        f"{seeds} seed(s) against a baseline of "
                        f"{'/'.join(sorted(baseline_seeds))}; run both sides over the same seeds",
                        label,
                    )

            for module in (m.strip() for m in varied.split("+")):
                # Only single-module rows count as covering a module. A combined
                # ablation measures the pair and settles neither half. The
                # baseline never counts: it is the reference, not a result.
                if not module or module == "none" or "+" in varied or status == "baseline":
                    continue
                if how in COVERING_HOW:
                    ablated_modules[module] += 1
                elif how == "swept":
                    swept_modules[module] += 1

        elif status == REFERENCE_STATUS:
            if varied and varied != "none":
                rep.error(
                    "reference_rows_asserting_a_module",
                    f"a reference row is not an ablation — it is what other rows are read "
                    f"against; `varied` must be none, got {varied!r}",
                    label,
                )

        elif status == VARIANCE_STATUS:
            if varied and varied != "none":
                rep.error(
                    "variance_rows_asserting_a_module",
                    f"variance rows compare one configuration to itself; "
                    f"`varied` must be none, got {varied!r}",
                    label,
                )

    for index, row in enumerate(rows, start=2):
        evidence = (row.get("evidence") or "").strip()
        status = row.get("status", "")
        label = f"line {index} ({row.get('commit', '?')})"

        if status == PLANNED_STATUS:
            # Pre-registered and not yet run. Its evidence path is a promise
            # about where the result will land, so it is a name, not a file.
            continue

        if not evidence:
            if status not in NO_EVIDENCE_EXPECTED:
                rep.error(
                    "missing_evidence",
                    f"no evidence path, and the status is not one of "
                    f"{', '.join(sorted(NO_EVIDENCE_EXPECTED))}",
                    label,
                )
            continue

        paths = [Path(part.strip()) for part in evidence.split(";") if part.strip()]
        for relative in paths:
            path = relative if relative.is_absolute() else root / relative
            if not path.is_file():
                rep.error("missing_evidence", f"{relative} is not on disk", label)
                continue
            try:
                value = load_json(path)
            except (OSError, json.JSONDecodeError) as error:
                rep.error("unreadable_evidence", f"{relative}: {error}", label)
                continue

            kind = evidence_kind(value)
            record = {"line": index, "path": str(relative), "status": status}
            if kind == "primary":
                seed = str(value["config"].get("seed", "unknown"))
                primary_seeds[seed] += 1
                record["seed"] = seed
                primary_rows.append(record)
                manifest_path = path.with_name(f"{path.stem}.meta.json")
                if not manifest_path.is_file():
                    rep.error("primary_without_manifest", f"{manifest_path.relative_to(root)} is missing", label)
                else:
                    try:
                        manifest = load_json(manifest_path)
                        missing = sorted(PRIMARY_MANIFEST_KEYS - set(manifest))
                        if missing:
                            rep.error(
                                "invalid_primary_manifests",
                                f"{manifest_path.relative_to(root)} missing {', '.join(missing)}",
                                label,
                            )
                        elif int(manifest["split_seed"]) != int(seed):
                            rep.error(
                                "invalid_primary_manifests",
                                f"manifest split_seed={manifest['split_seed']} contradicts config seed={seed}",
                                label,
                            )
                    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
                        rep.error(
                            "invalid_primary_manifests",
                            f"{manifest_path.relative_to(root)}: {error}",
                            label,
                        )
            else:
                derived_rows.append(record)
                aggregates_by_row.setdefault(index, []).append(value)
                for name in run_identifiers(str(relative)):
                    aggregates_by_name.setdefault(name, []).append(value)
                if status in CLAIM_STATUSES and not has_input_manifest(value):
                    rep.error("derived_without_primary_input_manifest", f"{relative} lists no primary inputs", label)

    # ── ablation coverage ────────────────────────────────────────────────────
    # The method is whatever `ablation-plan.tsv` says it is made of. Every part
    # declared removable owes the record one row showing what removing it cost.
    plan_rows, plan_problems = read_ablation_plan(root)
    declared_modules: list[str] = []

    # Interior points before the endpoint. Sweeping a module's setting while
    # never removing it measures the shape of a curve whose ends are unknown,
    # and it reads in a table exactly like an ablation. The endpoint is the
    # cheaper experiment and it is the one that settles whether the module is
    # needed at all, so it comes first.
    # Endpoints before interior points — but only where an endpoint exists. A
    # module the plan declares un-ablatable, with a reason, has no removal to
    # run first, and sweeping its setting is then the only evidence available
    # about it. Demanding a removal there refuses correct work, which an agent
    # predicted before running: chunk length cannot be set to 1 without also
    # destroying temporal ensembling, and the sweep was filed knowing this rule
    # would fire on it.
    unremovable = {
        (r.get("module") or "").strip()
        for r in plan_rows
        if (r.get("ablatable") or "").strip().lower() not in AFFIRMATIVE
    }
    for module, count in sorted(swept_modules.items()):
        if ablated_modules[module] or module in unremovable:
            continue
        rep.error(
            "modules_swept_but_never_removed",
            f"swept {count} time(s), never removed or replaced. If no isolated removal "
            f"exists, say so in {ABLATION_PLAN} with a reason rather than sweeping around it",
            f"{ABLATION_PLAN}:{module}",
        )
    # A plan with a header and no rows satisfies "every declared module has a
    # row" vacuously. "We never wrote down what the method is made of" and "the
    # method is made of nothing" must not reach the same verdict, and a file
    # that exists is not a declaration.
    if plan_rows is not None and not plan_problems and not any(
        (r.get("module") or "").strip() for r in plan_rows
    ):
        plan_problems.append(
            f"{ABLATION_PLAN} declares no modules; a method with no parts has nothing to ablate "
            f"and nothing to claim"
        )
    for problem in plan_problems:
        rep.error("ablation_plan", problem, ABLATION_PLAN)

    seen_modules: set[str] = set()
    for plan_row in plan_rows:
        module = (plan_row.get("module") or "").strip()
        if not module:
            continue
        where = f"{ABLATION_PLAN}:{module}"
        if module in seen_modules:
            rep.error(
                "modules_declared_twice",
                "declared more than once; one module, one row, one verdict",
                where,
            )
            continue
        seen_modules.add(module)
        declared_modules.append(module)
        # Where the module lives in the source. Not verifiable from here — the
        # gate reads a ledger, not a codebase — but it is what makes the plan
        # reviewable by someone who can open the file, which is the only defence
        # against a plan that declares one easy module and omits the rest.
        if not (plan_row.get("source") or "").strip():
            rep.error(
                "modules_without_a_source_location",
                "no `source`; name the file and function this module lives in",
                where,
            )
        if (plan_row.get("ablatable") or "").strip().lower() in AFFIRMATIVE:
            if not ablated_modules[module]:
                rep.error(
                    "modules_never_ablated",
                    f"declared ablatable, no claim row has varied={module}",
                    where,
                )
        else:
            verdict = (plan_row.get("ablatable") or "").strip() or "(empty)"
            reason = (plan_row.get("reason") or "").strip()
            if reason.lower().rstrip(".") in NON_REASONS:
                rep.error(
                    "modules_excused_without_reason",
                    f"ablatable={verdict!r} with reason {reason or '(empty)'!r}, which is not "
                    f"a reason; say why removal is impossible, or why this study has no "
                    f"metric it would move, rather than that it is inconvenient",
                    where,
                )
            elif len(reason) < MIN_REASON_CHARS:
                rep.error(
                    "modules_excused_without_reason",
                    f"excused in {len(reason)} characters; a module the paper cannot "
                    f"claim contributes is worth a sentence",
                    where,
                )

    # A constrained metric assumes the full method clears the constraint. If it
    # does not, every off-constraint verdict below it is meaningless — the
    # ablations did not leave a region the baseline was ever inside.
    if any((r.get("status") or "").strip() == "off-constraint" for r in rows) and not any(
        (r.get("status") or "").strip() == REFERENCE_STATUS for r in rows
    ):
        rep.warn(
            "no_reference_row_for_a_constrained_metric",
            "rows report leaving the metric's feasible region, and nothing records that the "
            f"full method was inside it. Add a {REFERENCE_STATUS} row carrying the baseline's "
            "own value for the constraint",
            "results.tsv",
        )

    # One grid, one question. Arms that inherited the baseline's hyperparameters
    # and arms that were re-tuned are answering different things, and a table
    # holding both answers neither — the reader cannot tell which column is
    # which, and neither can this.
    if len(tuning_policies) > 1:
        summary = "; ".join(
            f"{policy}: {len(where)} row(s)" for policy, where in sorted(tuning_policies.items())
        )
        rep.error(
            "grid_mixes_tuning_policies",
            f"the grid mixes hyperparameter policies — {summary}. Inheriting the baseline's "
            f"settings measures what a module contributes to this configuration; re-tuning "
            f"measures what it contributes to the best system without it. Pick one for the "
            f"whole grid and say which",
            "results.tsv",
        )

    # ── rows against the plan, the direction nobody checked ──────────────────
    # Coverage ran plan -> rows only. A row could therefore claim to ablate a
    # module the plan never declared, and the plan is the artifact a reader
    # opens to see what was omitted — so the list being reviewed and the list
    # being claimed were allowed to differ. Found by an audit, not by a test.
    declared_set = set(declared_modules)
    if declared_set or plan_rows:
        for module, count in sorted(ablated_modules.items()):
            if module not in declared_set:
                rep.error(
                    "rows_ablating_an_undeclared_module",
                    f"{count} row(s) report varied={module}, which {ABLATION_PLAN} does not "
                    f"declare; the plan a reader checks must list everything the record claims",
                    "results.tsv",
                )
        for module, count in sorted(swept_modules.items()):
            if module not in declared_set:
                rep.error(
                    "rows_ablating_an_undeclared_module",
                    f"{count} row(s) sweep {module}, which {ABLATION_PLAN} does not declare",
                    "results.tsv",
                )

    # ── the numbers, recomputed from the evidence ────────────────────────────
    # SKILL.md's central quantitative rule is that a difference smaller than the
    # seed spread is not a difference. Until now the gate did no arithmetic at
    # all: `spread` was a column name. An audit built a study whose own evidence
    # contradicted its ledger, and whose null result was filed as an effect, and
    # the gate passed both.
    for index, row in enumerate(rows, start=2):
        status = (row.get("status") or "").strip()
        if status not in CLAIM_STATUSES or status == "baseline":
            continue
        docs = aggregates_by_row.get(index) or []
        label = f"line {index} ({row.get('commit', '?')})"
        own = next((d for d in docs if aggregate_mean(d) is not None), None)
        if own is None:
            if docs:
                rep.warn(
                    "aggregate_not_recomputable",
                    "no `overall.mean` in this row's aggregate, so its number could not be "
                    "checked against its evidence",
                    label,
                )
            continue

        own_mean = aggregate_mean(own)
        own_spread = aggregate_spread(own)
        ledger_metric = parse_number(row.get("metric", ""))
        if ledger_metric is not None and abs(ledger_metric - own_mean) > ledger_tolerance(row.get("metric", "")):
            rep.error(
                "ledger_disagrees_with_aggregate",
                f"metric={ledger_metric} but the aggregate reports {own_mean}; one of the two "
                f"is wrong and nothing here can tell which",
                label,
            )
        ledger_spread = parse_number(row.get("spread", ""))
        if (own_spread is not None and ledger_spread is not None
                and abs(ledger_spread - own_spread) > ledger_tolerance(row.get("spread", ""))):
            rep.error(
                "ledger_disagrees_with_aggregate",
                f"spread={ledger_spread} but the aggregate's values span {own_spread:.6g}",
                label,
            )

        contrast = (row.get("contrast") or "").strip()
        others = aggregates_by_name.get(contrast) or []
        against = next((d for d in others if aggregate_mean(d) is not None), None)
        if against is None:
            if contrast and contrast != "-":
                rep.warn(
                    "contrast_not_recomputable",
                    f"the aggregate for contrast={contrast!r} carries no mean, so the delta "
                    f"could not be computed",
                    label,
                )
            continue

        delta = own_mean - aggregate_mean(against)
        # The reference is the wider of the two noise floors. A delta that
        # clears neither side's spread has not cleared the noise.
        reference = max(x for x in (own_spread, aggregate_spread(against), ledger_spread)
                        if x is not None) if any(
            x is not None for x in (own_spread, aggregate_spread(against), ledger_spread)) else None
        recomputed.append({
            "where": label, "varied": (row.get("varied") or "").strip(),
            "metric": own_mean, "contrast": contrast,
            "contrast_metric": aggregate_mean(against),
            "delta": round(delta, 9),
            "reference_spread": reference,
            "clears_spread": None if reference is None else abs(delta) > reference,
        })
        if reference is None:
            continue
        if status == "keep" and abs(delta) <= reference:
            rep.error(
                "effect_inside_spread",
                f"delta {delta:+.6g} against a spread of {reference:.6g}: this row claims an "
                f"effect its own evidence cannot separate from noise. That is `no-effect`",
                label,
            )
        elif status == "no-effect" and abs(delta) > reference:
            rep.warn(
                "no_effect_row_clears_the_spread",
                f"delta {delta:+.6g} clears the {reference:.6g} spread; recorded as no-effect, "
                f"which is conservative rather than wrong, but worth a second look",
                label,
            )

    # A record in which no module was ever ablated must not be handed the same
    # word as a completed grid.
    #
    # Nothing here can tell an honest zero from an evasive one. A benchmark paper
    # proposes no method, so every component is truthfully un-ablatable and its
    # plan is correct and complete — and it is byte-for-byte the shape of "mark
    # everything un-ablatable, run nothing, pass", which is the abuse the reason
    # checks exist to catch. Detecting intent is not available to a program that
    # reads a ledger. Refusing to call both of them ready is.
    discharged = sum(ablated_modules.get(module, 0) for module in declared_modules)
    if not rep.blocking and not discharged:
        rep.note(
            "no_ablation_evidence",
            "no module in the plan was discharged by a removal or replacement, so this "
            "record supports no claim about any part of the method. That is correct for "
            "work that proposes no method, and identical in shape to a plan that declined "
            "to ablate anything. A reader decides which by opening the plan.",
            ABLATION_PLAN,
        )

    if rep.blocking:
        gate = "BLOCKED"
    elif not discharged:
        gate = "NO_ABLATION_EVIDENCE"
    else:
        gate = "READY_FOR_CLAIM_SELECTION"

    return {
        "gate": gate,
        "results_rows": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "primary_evidence_rows": len(primary_rows),
        "derived_evidence_rows": len(derived_rows),
        "primary_seed_counts": dict(sorted(primary_seeds.items())),
        "declared_modules": declared_modules,
        "ablation_coverage": {
            module: ablated_modules.get(module, 0) for module in declared_modules
        },
        "recomputed": recomputed,
        "sweep_counts": {
            module: swept_modules[module] for module in declared_modules if swept_modules[module]
        },
        "variance_rows": status_counts.get(VARIANCE_STATUS, 0),
        "issues": rep.items,
        "error_count": rep.blocking,
        "warning_count": sum(1 for i in rep.items if i["severity"] == "warning"),
        "issue_count": len(rep.items),
        "note": (
            "READY_FOR_CLAIM_SELECTION still requires a claim-specific matrix; "
            "this inventory cannot prove that a particular manuscript claim is supported."
        ),
    }


def preflight(root: Path) -> str | None:
    """Why this root cannot be inspected, or None if it can.

    Separated from main() so the refusal is testable without driving argv, and
    so a wrong working directory produces an explanation rather than a
    traceback. Distinguishing "cannot run" from "ran and blocked" matters: the
    two exits mean opposite things about the evidence, and a caller that
    conflates them reads a mistyped path as a scientific verdict.
    """
    if not root.is_dir():
        return f"{root} is not a directory"
    if not (root / "results.tsv").is_file():
        return (
            f"no results.tsv at {root}; run this from the research repository root "
            f"or pass that root as an argument"
        )
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        # The working directory, not the script's own parent. This used to
        # default to `Path(__file__).resolve().parents[1]`, which is the skill
        # directory — it holds no results.tsv, so the invocation documented in
        # handoff.md raised FileNotFoundError instead of producing a verdict.
        default=Path.cwd(),
        help="research repository root (default: the current directory)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    root = args.root.resolve()
    problem = preflight(root)
    if problem:
        print(problem, file=sys.stderr)
        return 2

    report = inspect(root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{report['gate']}: {report['error_count']} error(s), {report['issue_count']} issue(s)")
        print(f"results rows: {report['results_rows']}")
        print(f"statuses: {report['status_counts']}")
        print(f"primary evidence rows: {report['primary_evidence_rows']}")
        print(f"derived evidence rows: {report['derived_evidence_rows']}")
        print(f"primary seed counts: {report['primary_seed_counts']}")
        print(f"variance rows: {report['variance_rows']}")
        print(f"ablation coverage: {report['ablation_coverage']}")
        if report["sweep_counts"]:
            print(f"sweeps (do not count as coverage): {report['sweep_counts']}")
        order = {"error": 0, "warning": 1, "advisory": 2}
        for item in sorted(report["issues"], key=lambda i: order[i["severity"]]):
            where = f" [{item['where']}]" if item["where"] else ""
            print(f"  {item['severity'].upper():9s} {item['code']}: {item['message']}{where}")
        print(report["note"])
    # NO_ABLATION_EVIDENCE exits 0: the record is correct, it simply contains no
    # evidence about any module. The verdict word carries that, not the status.
    return 1 if report["gate"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
