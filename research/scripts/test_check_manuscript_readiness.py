#!/usr/bin/env python3
"""Tests for the evidence gate.

    python3 scripts/test_check_manuscript_readiness.py

Standard library only, same as the gate itself. Every fixture is built in a
temporary directory, so the suite touches nothing in the workspace.

What this suite may claim: that the gate accepts and rejects what
`SKILL.md` and `references/manuscript-readiness.md` say it does. What it may
NOT claim: that an agent reading the skill produces better experiments. A row
that satisfies every check here can still be a hyperparameter tweak with
`varied` filled in optimistically. Only reading the ablation runs' diffs
answers that, and no test can.

The first case is the regression that motivated the columns: a sweep over
seeds, marked as a claim. It passed the old gate, because `seeds > 1` was the
only condition the old gate could check.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_manuscript_readiness import inspect, preflight  # noqa: E402


RESULTS_HEADER = [
    "commit", "hypothesis", "varied", "how", "contrast",
    "metric", "seeds", "spread", "status", "tuning", "notes", "evidence",
]
PLAN_HEADER = ["module", "source", "removal", "ablatable", "reason"]

# A full-method reference row every fixture can point `contrast` at.
BASELINE_ROW = {
    "commit": "aaa111", "hypothesis": "unmodified pipeline reference",
    "varied": "none", "how": "none", "contrast": "-", "metric": "0.187", "seeds": "5",
    "spread": "0.031", "status": "baseline", "tuning": "retuned", "notes": "control",
    "evidence": "runs/aggregate__full.json",
}
PLAN_TWO_MODULES = [
    {"module": "disagreement_opt", "source": "main_p2l.py:optimise_disagreement",
     "removal": "disabled", "ablatable": "yes", "reason": ""},
    {"module": "coreset_rule", "source": "main_p2l.py:select_coreset",
     "removal": "replaced by random", "ablatable": "yes", "reason": ""},
]
# A reason that says why removal is impossible, not merely that it was skipped.
FROZEN_REASON = "evaluation semantics are frozen; removing it removes the metric being reported"


def write_tsv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    lines = ["\t".join(header)]
    lines += ["\t".join(row.get(column, "") for column in header) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def real_aggregate(label: str, mean: float, spread: float, splits: int = 5) -> dict:
    """An aggregate carrying the fields the interface specifies, so the numeric
    checks have something to read. Values span exactly `spread` and average
    exactly `mean`, which makes every ledger cell in these fixtures true by
    construction — only a test that deliberately lies should trip the check."""
    half = spread / 2
    return {
        "label": label, "method": label, "metric": "val_ppl", "estimator": "mean over seeds",
        "primary_inputs": [f"runs/{label}-s{i}.json" for i in range(splits)],
        "per_split": {str(i + 1): {"mean": mean, "std": spread / 4, "n": 3,
                                   "values": [mean - half, mean, mean + half]}
                      for i in range(splits)},
        "overall": {"mean": mean, "std": spread / 4, "range": spread, "n_splits": splits},
    }


def build(root: Path, rows: list[dict[str, str]], plan: list[dict[str, str]] | None) -> None:
    """Materialise a workspace: the ledger, the plan, and every aggregate cited.

    Aggregates carry `source_runs` and no `config`, which is what makes the gate
    read them as derived evidence with a traceable input list — the shape a real
    claim row cites.
    """
    (root / "runs").mkdir(parents=True, exist_ok=True)
    write_tsv(root / "results.tsv", RESULTS_HEADER, rows)
    if plan is not None:
        write_tsv(root / "ablation-plan.tsv", PLAN_HEADER, plan)
    for row in rows:
        for part in row.get("evidence", "").split(";"):
            name = part.strip()
            if not name:
                continue
            stem = Path(name).stem
            (root / name).write_text(json.dumps({
                "label": stem, "method": stem, "metric": "p2l_bound",
                "estimator": "mean over split seeds",
                "source_runs": [f"runs/{stem}-s1__c0.json"],
                "per_split": {}, "overall": {},
            }), encoding="utf-8")


class GateCase(unittest.TestCase):
    def gate(self, rows, plan=PLAN_TWO_MODULES):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root, rows, plan)
            return inspect(root)

    def findings(self, report, code, severity=None):
        return [i for i in report["issues"]
                if i["code"] == code and (severity is None or i["severity"] == severity)]

    def _fired(self, report):
        return [f"{i['severity']}:{i['code']}" for i in report["issues"]]

    def assertBlockedBy(self, report, code):
        self.assertEqual(report["gate"], "BLOCKED")
        self.assertTrue(
            self.findings(report, code, "error"),
            f"expected {code} to block; fired: {self._fired(report)}",
        )

    def assertWarnsWith(self, report, code):
        """A warning is recorded and does not block. The two halves are the
        point: a check that only ever blocks cannot be added to a gate an
        unattended agent has to get through."""
        self.assertTrue(
            self.findings(report, code, "warning"),
            f"expected {code} to warn; fired: {self._fired(report)}",
        )

    def assertNoFinding(self, report, code):
        self.assertEqual(self.findings(report, code), [])

    def assertFindingMentions(self, report, code, needle):
        haystack = " ".join(i["message"] + " " + i["where"] for i in self.findings(report, code))
        self.assertIn(needle, haystack)


class TestSeedSweepIsNotAClaim(GateCase):
    def test_seed_sweep_marked_keep_is_rejected(self):
        """The regression the whole change exists for."""
        report = self.gate([BASELINE_ROW, {
            "commit": "bbb222", "hypothesis": "full method is stable across seeds",
            "varied": "none", "how": "none", "contrast": "-", "metric": "0.187", "seeds": "5",
            "spread": "0.031", "status": "keep", "tuning": "inherited", "notes": "looks fine",
            "evidence": "runs/aggregate__full.json",
        }])
        self.assertBlockedBy(report, "claim_rows_naming_no_module")

    def test_the_same_row_is_fine_as_a_variance_observation(self):
        report = self.gate([BASELINE_ROW, {
            "commit": "bbb222", "hypothesis": "trajectory seed moves the bound",
            "varied": "none", "how": "none", "contrast": "-", "metric": "0.187", "seeds": "5",
            "spread": "0.031", "status": "variance", "tuning": "inherited", "notes": "pipeline noise",
            "evidence": "runs/aggregate__full.json",
        }, *ablation_rows()])
        self.assertEqual(report["gate"], "READY_FOR_CLAIM_SELECTION")
        self.assertEqual(report["variance_rows"], 1)

    def test_variance_row_may_not_assert_a_module(self):
        report = self.gate([BASELINE_ROW, {
            "commit": "bbb222", "hypothesis": "noise", "varied": "coreset_rule", "how": "none",
            "contrast": "-", "metric": "0.187", "seeds": "5", "spread": "0.031",
            "status": "variance", "tuning": "inherited", "notes": "", "evidence": "runs/aggregate__full.json",
        }])
        self.assertBlockedBy(report, "variance_rows_asserting_a_module")


class TestContrastMustResolve(GateCase):
    def test_contrast_naming_nothing_is_rejected(self):
        rows = ablation_rows()
        rows[0]["contrast"] = "the previous version"
        report = self.gate([BASELINE_ROW, *rows])
        self.assertBlockedBy(report, "claim_rows_with_unresolved_contrast")

    def test_missing_contrast_is_rejected(self):
        rows = ablation_rows()
        rows[0]["contrast"] = ""
        report = self.gate([BASELINE_ROW, *rows])
        self.assertBlockedBy(report, "claim_rows_with_unresolved_contrast")

    def test_label_part_before_the_double_underscore_resolves(self):
        rows = ablation_rows()
        rows[0]["contrast"] = "aggregate"  # the label part of aggregate__full.json
        report = self.gate([BASELINE_ROW, *rows])
        self.assertEqual(report["gate"], "READY_FOR_CLAIM_SELECTION")


class TestAblationCoverage(GateCase):
    def test_declared_module_with_no_row_blocks(self):
        report = self.gate([BASELINE_ROW, ablation_rows()[0]])
        self.assertBlockedBy(report, "modules_never_ablated")
        self.assertEqual(report["ablation_coverage"]["coreset_rule"], 0)

    def test_full_grid_passes(self):
        report = self.gate([BASELINE_ROW, *ablation_rows()])
        self.assertEqual(report["gate"], "READY_FOR_CLAIM_SELECTION")
        self.assertEqual(
            report["ablation_coverage"], {"disagreement_opt": 1, "coreset_rule": 1}
        )

    def test_missing_plan_blocks(self):
        report = self.gate([BASELINE_ROW, *ablation_rows()], plan=None)
        self.assertBlockedBy(report, "ablation_plan")

    def test_unablatable_module_needs_a_reason(self):
        plan = PLAN_TWO_MODULES + [
            {"module": "bound_computation", "source": "bounds/p2l.py",
             "removal": "-", "ablatable": "no", "reason": ""}
        ]
        report = self.gate([BASELINE_ROW, *ablation_rows()], plan=plan)
        self.assertBlockedBy(report, "modules_excused_without_reason")

    def test_unablatable_module_with_a_reason_is_accepted(self):
        plan = PLAN_TWO_MODULES + [{
            "module": "bound_computation", "source": "bounds/p2l.py",
            "removal": "-", "ablatable": "no", "reason": FROZEN_REASON,
        }]
        report = self.gate([BASELINE_ROW, *ablation_rows()], plan=plan)
        self.assertEqual(report["gate"], "READY_FOR_CLAIM_SELECTION")

    def test_a_combined_ablation_does_not_cover_either_half(self):
        """`a+b` measures the pair. Counting it as coverage of `a` would let one
        run discharge two modules and hide which of them did the work."""
        report = self.gate([BASELINE_ROW, {
            "commit": "ccc333", "hypothesis": "both together matter",
            "varied": "disagreement_opt+coreset_rule", "how": "removed", "contrast": "aggregate__full",
            "metric": "0.260", "seeds": "5", "spread": "0.029", "status": "keep", "tuning": "inherited",
            "notes": "", "evidence": "runs/aggregate__no_both.json",
        }])
        self.assertBlockedBy(report, "modules_never_ablated")
        self.assertEqual(report["ablation_coverage"]["disagreement_opt"], 0)


class TestSweepIsNotAnAblation(GateCase):
    """A dose-response point and a removal both name the module. Only one of
    them is evidence that the module is load-bearing.

    Found by an A/B planning run: a plan filed six interior points against two
    modules, and — because it also contained their removal rows — was correct.
    Nothing in the ledger distinguished it from a plan that swept instead of
    removing, which is the version this suite has to reject.
    """

    def swept(self, module, **over):
        row = {
            "commit": "ddd444", "hypothesis": f"{module} setting matters",
            "varied": module, "how": "swept", "contrast": "aggregate__full",
            "metric": "0.185", "seeds": "5", "spread": "0.030", "status": "keep", "tuning": "inherited",
            "notes": "interior point", "evidence": f"runs/aggregate__{module}_mid.json",
        }
        row.update(over)
        return row

    def test_sweeping_a_module_does_not_discharge_it(self):
        rows = ablation_rows()
        rows[0] = self.swept("disagreement_opt")  # sweep INSTEAD of removing
        report = self.gate([BASELINE_ROW, *rows])
        self.assertBlockedBy(report, "modules_never_ablated")
        self.assertEqual(report["ablation_coverage"]["disagreement_opt"], 0)
        self.assertEqual(report["sweep_counts"]["disagreement_opt"], 1)

    def test_sweeping_before_removing_is_rejected_on_its_own_terms(self):
        rows = ablation_rows()
        rows[0] = self.swept("disagreement_opt")
        report = self.gate([BASELINE_ROW, *rows])
        self.assertBlockedBy(report, "modules_swept_but_never_removed")

    def test_a_sweep_is_fine_once_the_endpoint_exists(self):
        """What the observed plan actually did: removal first, interior after."""
        report = self.gate([
            BASELINE_ROW, *ablation_rows(), self.swept("disagreement_opt"),
        ])
        self.assertEqual(report["gate"], "READY_FOR_CLAIM_SELECTION")
        self.assertEqual(report["ablation_coverage"]["disagreement_opt"], 1)
        self.assertEqual(report["sweep_counts"]["disagreement_opt"], 1)

    def test_a_module_named_without_saying_how_is_rejected(self):
        rows = ablation_rows()
        rows[0]["how"] = "none"
        report = self.gate([BASELINE_ROW, *rows])
        self.assertBlockedBy(report, "claim_rows_naming_no_module")

    def test_an_unknown_how_is_rejected_rather_than_ignored(self):
        rows = ablation_rows()
        rows[0]["how"] = "ablated"  # plausible, not in the vocabulary
        report = self.gate([BASELINE_ROW, *rows])
        self.assertBlockedBy(report, "invalid_how_values")


class TestContrastMustBeTheFullMethod(GateCase):
    """A single-module row measured against another ablation.

    The arithmetic is the reason. Full method 0.187; removing disagreement_opt
    costs 0.008 (0.195); removing coreset_rule costs 0.053 (0.240). Contrast the
    first against the second and the recorded delta is 0.195 - 0.240 = -0.045:
    the table reports that removing disagreement_opt *improved* the bound by
    0.045, when removing it in fact made the bound worse. The sign flips, and
    both rows look identical in the ledger.
    """

    def chained(self, **over):
        row = {
            "commit": "eee555", "hypothesis": "disagreement_opt is dead weight",
            "varied": "disagreement_opt", "how": "removed",
            "contrast": "aggregate__no_coreset",  # another ablation, not the baseline
            "metric": "0.195", "seeds": "5", "spread": "0.030", "status": "keep", "tuning": "inherited",
            "notes": "", "evidence": "runs/aggregate__no_disag.json",
        }
        row.update(over)
        return row

    def test_a_removal_measured_against_another_removal_is_rejected(self):
        rows = ablation_rows()
        rows[0] = self.chained()
        report = self.gate([BASELINE_ROW, *rows])
        self.assertBlockedBy(report, "rows_not_measured_against_the_full_method")

    def test_the_message_names_the_baseline_it_should_have_used(self):
        rows = ablation_rows()
        rows[0] = self.chained()
        report = self.gate([BASELINE_ROW, *rows])
        self.assertFindingMentions(report, "rows_not_measured_against_the_full_method", "aggregate__full")

    def test_a_sweep_is_held_to_the_same_reference(self):
        """A dose-response point off a crippled reference draws a wrong curve
        for the same reason a removal does."""
        rows = ablation_rows()
        rows[0] = self.chained(how="swept", metric="0.19")
        report = self.gate([BASELINE_ROW, *rows])
        self.assertBlockedBy(report, "rows_not_measured_against_the_full_method")

    def test_an_interaction_may_reference_one_of_its_own_halves(self):
        """`A+B` against `B` alone is the right reference for what A adds on
        top of B, so the rule deliberately stops at single-module rows."""
        report = self.gate([BASELINE_ROW, *ablation_rows(), {
            "commit": "fff666", "hypothesis": "the two interact",
            "varied": "disagreement_opt+coreset_rule", "how": "removed",
            "contrast": "aggregate__no_coreset", "metric": "0.260",
            "seeds": "5", "spread": "0.029", "status": "keep", "tuning": "inherited", "notes": "",
            "evidence": "runs/aggregate__no_both.json",
        }])
        self.assertEqual(report["gate"], "READY_FOR_CLAIM_SELECTION")

    def test_no_baseline_at_all_says_so_rather_than_blaming_the_row(self):
        """Two ablations pointing at each other and no full-method run anywhere.

        Both contrasts resolve — those runs exist — so the failure is not that
        the reference is missing but that no reference is the full method. The
        message has to say that, or the author reads "contrast" and adds a run
        that is still not a baseline.
        """
        a, b = ablation_rows()
        a["contrast"] = "aggregate__no_coreset"  # b's evidence
        b["contrast"] = "aggregate__no_disag"    # a's evidence
        report = self.gate([a, b])               # no BASELINE_ROW anywhere
        self.assertBlockedBy(report, "rows_not_measured_against_the_full_method")
        self.assertNoFinding(report, "claim_rows_with_unresolved_contrast")
        self.assertFindingMentions(
            report, "rows_not_measured_against_the_full_method", "no row with status=baseline exists"
        )


class TestPreflight(unittest.TestCase):
    """"Cannot run" and "ran and blocked" are opposite statements about the
    evidence. Conflating them lets a mistyped path read as a scientific verdict,
    which is why this refuses with its own exit code rather than a traceback."""

    def test_a_root_without_results_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            problem = preflight(Path(tmp))
        self.assertIsNotNone(problem)
        self.assertIn("no results.tsv", problem)

    def test_a_path_that_is_not_a_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "results.tsv"
            target.write_text("", encoding="utf-8")
            self.assertIn("not a directory", preflight(target))

    def test_a_real_research_root_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root, [BASELINE_ROW, *ablation_rows()], PLAN_TWO_MODULES)
            self.assertIsNone(preflight(root))

    def test_the_skill_directory_is_not_a_research_root(self):
        """The old default. It holds no results.tsv, so running with no
        argument checked a tree that could not contain evidence."""
        self.assertIsNotNone(preflight(Path(__file__).resolve().parents[1]))


class TestTheDocumentedAggregateSchema(GateCase):
    def test_an_aggregate_using_primary_inputs_is_accepted(self):
        """`primary_inputs` is the field the interface contract specifies, and
        the one make_paper_data.py requires. The gate accepted four other names
        and not that one, so an aggregate written to the documented schema was
        rejected as having no input manifest. Every fixture here used
        `source_runs`, which is why 33 tests missed it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root, [BASELINE_ROW, *ablation_rows()], PLAN_TWO_MODULES)
            for path in (root / "runs").glob("*.json"):
                doc = json.loads(path.read_text(encoding="utf-8"))
                doc["primary_inputs"] = doc.pop("source_runs")
                path.write_text(json.dumps(doc), encoding="utf-8")
            report = inspect(root)
        self.assertEqual(report["gate"], "READY_FOR_CLAIM_SELECTION")
        self.assertNoFinding(report, "derived_without_primary_input_manifest")


class TestTheNumbersAreCheckedAgainstTheEvidence(GateCase):
    """SKILL.md's central quantitative rule — a difference smaller than the seed
    spread is not a difference — was doctrine the gate did no arithmetic to
    enforce. `spread` was a column name. An audit built a study whose evidence
    contradicted its own ledger and whose null result was filed as an effect,
    and the gate passed both."""

    def study(self, ablation_mean, status, spread=0.031, ledger_metric=None):
        base_mean = 0.187
        rows = [
            dict(BASELINE_ROW, metric=f"{base_mean}", spread=f"{spread}"),
            {"commit": "hhh888", "hypothesis": "removing it costs metric",
             "varied": "disagreement_opt", "how": "removed", "contrast": "aggregate__full",
             "metric": f"{ledger_metric if ledger_metric is not None else ablation_mean}",
             "seeds": "5", "spread": f"{spread}", "status": status,
             "tuning": "inherited", "notes": "",
             "evidence": "runs/aggregate__no_disag.json"},
            dict(ablation_rows()[1], metric="0.240", spread=f"{spread}", status="keep", tuning="inherited"),
        ]
        aggs = {"runs/aggregate__full.json": real_aggregate("full", base_mean, spread),
                "runs/aggregate__no_disag.json": real_aggregate("no_disag", ablation_mean, spread),
                "runs/aggregate__no_coreset.json": real_aggregate("no_coreset", 0.240, spread)}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root, rows, PLAN_TWO_MODULES)
            for path, doc in aggs.items():
                (root / path).write_text(json.dumps(doc), encoding="utf-8")
            return inspect(root)

    def test_a_delta_inside_the_spread_may_not_be_called_keep(self):
        """0.191 against 0.187 is 0.004, well inside a 0.031 spread."""
        report = self.study(0.191, "keep")
        self.assertBlockedBy(report, "effect_inside_spread")

    def test_the_same_row_as_no_effect_is_accepted(self):
        report = self.study(0.191, "no-effect")
        self.assertNoFinding(report, "effect_inside_spread")

    def test_a_delta_that_clears_the_spread_is_a_keep(self):
        report = self.study(0.243, "keep")
        self.assertEqual(report["gate"], "READY_FOR_CLAIM_SELECTION")

    def test_a_ledger_number_the_evidence_contradicts_blocks(self):
        report = self.study(0.243, "keep", ledger_metric=0.900)
        self.assertBlockedBy(report, "ledger_disagrees_with_aggregate")

    def test_rounding_to_the_cell_precision_is_accepted(self):
        """0.187 asserts [0.1865, 0.1875). The tolerance comes from the cell's
        own precision, so honest rounding passes where a fixed epsilon would
        have to be wrong for either two decimals or three."""
        report = self.study(0.24297, "keep", ledger_metric=0.243)
        self.assertNoFinding(report, "ledger_disagrees_with_aggregate")

    def test_the_arithmetic_it_used_is_reported(self):
        """A numeric check that hides its working cannot be argued with, and
        being arguable is this gate's purpose."""
        report = self.study(0.243, "keep")
        row = next(r for r in report["recomputed"] if r["varied"] == "disagreement_opt")
        self.assertAlmostEqual(row["delta"], 0.056, places=6)
        self.assertTrue(row["clears_spread"])


class TestOneGridOneTuningPolicy(GateCase):
    """Where each arm's hyperparameters came from.

    Keep the baseline's settings and the variant runs on hyperparameters tuned
    for a system that still had the module, so a loss is the module's
    contribution confounded with how badly those settings suit the smaller
    system. Re-tune and two things changed rather than one. Both are defensible
    and they answer different questions; a grid holding both answers neither.

    The gate cannot verify what was done — the same limit `how` has. It can
    refuse a grid that will not say, and one that says both."""

    def test_a_grid_mixing_inherited_and_retuned_arms_blocks(self):
        rows = ablation_rows()
        rows[0]["tuning"] = "retuned"
        rows[1]["tuning"] = "inherited"
        report = self.gate([BASELINE_ROW, *rows])
        self.assertBlockedBy(report, "grid_mixes_tuning_policies")

    def test_the_message_says_how_many_rows_took_each_policy(self):
        rows = ablation_rows()
        rows[0]["tuning"] = "retuned"
        report = self.gate([BASELINE_ROW, *rows])
        self.assertFindingMentions(report, "grid_mixes_tuning_policies", "inherited: 1 row(s)")

    def test_a_consistently_retuned_grid_is_accepted(self):
        """Re-tuning every arm is a legitimate design; it answers what each
        module contributes to the best system built without it."""
        rows = [dict(r, tuning="retuned") for r in ablation_rows()]
        report = self.gate([BASELINE_ROW, *rows])
        self.assertEqual(report["gate"], "READY_FOR_CLAIM_SELECTION")

    def test_the_baseline_does_not_constrain_the_grid(self):
        """The baseline's own settings came from a search; that says nothing
        about the policy the ablations follow."""
        rows = [dict(r, tuning="inherited") for r in ablation_rows()]
        report = self.gate([dict(BASELINE_ROW, tuning="retuned"), *rows])
        self.assertEqual(report["gate"], "READY_FOR_CLAIM_SELECTION")

    def test_an_unrecognised_policy_is_rejected_rather_than_ignored(self):
        rows = ablation_rows()
        rows[0]["tuning"] = "some"      # plausible, not in the vocabulary
        report = self.gate([BASELINE_ROW, *rows])
        self.assertBlockedBy(report, "invalid_tuning_value")


class TestReferenceRows(GateCase):
    """A run that is neither the method nor an ablation, recorded so the others
    have something to be read against. Both uses came from an advice audit."""

    def reference(self, **over):
        row = {"commit": "ref001", "hypothesis": "what the trivial behaviour scores",
               "varied": "none", "how": "none", "contrast": "-", "metric": "0.045",
               "seeds": "5", "spread": "0.004", "status": "reference", "tuning": "none",
               "notes": "popularity-only ranker, i.e. the chance level this metric rewards",
               "evidence": "runs/aggregate__chance.json"}
        row.update(over)
        return row

    def test_a_reference_row_is_accepted_and_claims_nothing(self):
        report = self.gate([BASELINE_ROW, *ablation_rows(), self.reference()])
        self.assertEqual(report["gate"], "READY_FOR_CLAIM_SELECTION")

    def test_a_reference_row_may_not_assert_a_module(self):
        report = self.gate([BASELINE_ROW, *ablation_rows(),
                            self.reference(varied="coreset_rule")])
        self.assertBlockedBy(report, "reference_rows_asserting_a_module")

    def test_leaving_a_constraint_with_no_reference_warns(self):
        """An off-constraint verdict says the variant left a region. Nothing
        said the full method was ever inside it."""
        rows = ablation_rows()
        rows[0] = dict(rows[0], status="off-constraint", metric="nan")
        report = self.gate([BASELINE_ROW, *rows])
        self.assertWarnsWith(report, "no_reference_row_for_a_constrained_metric")

    def test_with_the_reference_present_it_does_not_warn(self):
        rows = ablation_rows()
        rows[0] = dict(rows[0], status="off-constraint", metric="nan")
        report = self.gate([BASELINE_ROW, *rows,
                            self.reference(notes="baseline Jain index 0.97, inside the region")])
        self.assertNoFinding(report, "no_reference_row_for_a_constrained_metric")


class TestDerivedTuning(GateCase):
    """`inherited` / `retuned` / `none` was short one value the day after it
    shipped: a grid that re-solves a fixed rule per arm — the privacy equation
    at fixed epsilon — has values that differ with no search behind them."""

    def test_a_consistently_derived_grid_is_accepted(self):
        rows = [dict(r, tuning="derived") for r in ablation_rows()]
        report = self.gate([BASELINE_ROW, *rows])
        self.assertEqual(report["gate"], "READY_FOR_CLAIM_SELECTION")

    def test_derived_still_may_not_be_mixed_with_another_policy(self):
        rows = ablation_rows()
        rows[0]["tuning"] = "derived"
        report = self.gate([BASELINE_ROW, *rows])
        self.assertBlockedBy(report, "grid_mixes_tuning_policies")


class TestTheGateDoesNotRefuseCorrectWork(GateCase):
    """Two false positives an advice audit found, both of the worst kind: the
    gate blocking work that was right. An unattended agent cannot argue back."""

    def test_a_module_with_no_isolated_removal_may_be_swept(self):
        """Endpoints before interior points assumes an endpoint exists. Chunk
        length cannot be set to 1 without also destroying temporal ensembling,
        so there is no removal to run first and the sweep is the only evidence
        available. An agent predicted this rule would fire on its correct plan,
        and filed the sweep anyway."""
        plan = [{"module": "chunk_length", "source": "policy.py:chunk", "removal": "-",
                 "ablatable": "no",
                 "reason": "K=1 necessarily also removes temporal ensembling, so no isolated "
                           "removal of this module exists"}]
        swept = dict(ablation_rows()[0], varied="chunk_length", how="swept",
                     evidence="runs/aggregate__k8.json")
        report = self.gate([BASELINE_ROW, swept], plan=plan)
        self.assertNoFinding(report, "modules_swept_but_never_removed")
        self.assertEqual(report["error_count"], 0)

    def test_a_removable_module_swept_without_an_endpoint_still_blocks(self):
        """The exemption is for modules the plan declares un-ablatable, not for
        anything anyone declines to remove."""
        rows = ablation_rows()
        rows[0]["how"] = "swept"
        report = self.gate([BASELINE_ROW, *rows])
        self.assertBlockedBy(report, "modules_swept_but_never_removed")

    def test_an_off_constraint_verdict_may_rest_on_one_run(self):
        """Removing gradient clipping makes epsilon unbounded by the definition
        of the mechanism, not by observation. Requiring repetitions there asks
        for evidence in support of a theorem."""
        rows = ablation_rows()
        rows[0] = dict(rows[0], status="off-constraint", seeds="1", metric="nan",
                       notes="epsilon is unbounded once clipping is gone; this follows from "
                             "the mechanism rather than from the runs")
        report = self.gate([BASELINE_ROW, *rows])
        self.assertNoFinding(report, "single_run_rows_marked_as_claims")

    def test_an_ordinary_claim_still_needs_more_than_one_run(self):
        rows = ablation_rows()
        rows[0]["seeds"] = "1"
        report = self.gate([BASELINE_ROW, *rows])
        self.assertBlockedBy(report, "single_run_rows_marked_as_claims")


class TestRowsAreCheckedAgainstThePlan(GateCase):
    """Coverage ran plan -> rows only. A row could claim to ablate a module the
    plan never declared — and the plan is the artifact a reader opens to see
    what was omitted, so the list being reviewed and the list being claimed were
    allowed to differ."""

    def test_a_row_ablating_an_undeclared_module_blocks(self):
        rows = ablation_rows()
        rows[0]["varied"] = "a_module_nobody_declared"
        report = self.gate([BASELINE_ROW, *rows])
        self.assertBlockedBy(report, "rows_ablating_an_undeclared_module")

    def test_a_sweep_of_an_undeclared_module_blocks_too(self):
        rows = ablation_rows()
        extra = dict(rows[0], commit="zzz999", varied="undeclared", how="swept",
                     evidence="runs/aggregate__stray.json")
        report = self.gate([BASELINE_ROW, *rows, extra])
        self.assertBlockedBy(report, "rows_ablating_an_undeclared_module")


class TestAConstrainedMetricCanBeLeft(GateCase):
    """Goodput *at fixed fairness*. Accuracy *at fixed epsilon*.

    Removing a module can put the variant outside the region where the metric
    means what its name says — it did not score worse, it stopped being
    measurable on that axis. Two studies in the 33-idea validation had to record
    that as `crash` with `metric=nan`, which is the status for a run that did
    not finish, so the record could not distinguish a failure from a success
    that moved off the axis.
    """

    def off_constraint(self, **over):
        row = {
            "commit": "ggg777", "hypothesis": "clipping is what keeps epsilon meaningful",
            "varied": "disagreement_opt", "how": "removed", "contrast": "aggregate__full",
            "metric": "nan", "seeds": "5", "spread": "nan", "status": "off-constraint", "tuning": "inherited",
            "notes": "finished, but epsilon is no longer bounded, so accuracy is off-axis",
            "evidence": "runs/aggregate__no_disag.json",
        }
        row.update(over)
        return row

    def test_it_discharges_the_module(self):
        """A part whose absence leaves the feasible region is load-bearing, and
        more clearly so than a small delta would show."""
        rows = ablation_rows()
        rows[0] = self.off_constraint()
        report = self.gate([BASELINE_ROW, *rows])
        self.assertEqual(report["gate"], "READY_FOR_CLAIM_SELECTION")
        self.assertEqual(report["ablation_coverage"]["disagreement_opt"], 1)

    def test_it_owes_the_same_module_and_contrast_as_any_claim(self):
        report = self.gate([BASELINE_ROW, *ablation_rows(),
                            self.off_constraint(varied="none", how="none")])
        self.assertBlockedBy(report, "claim_rows_naming_no_module")

    def test_it_is_not_a_crash(self):
        """The run finished. Recording it as a crash loses that, which is what
        the studies in the validation were forced to do."""
        rows = ablation_rows()
        rows[0] = self.off_constraint()
        report = self.gate([BASELINE_ROW, *rows])
        self.assertEqual(report["status_counts"].get("crash", 0), 0)
        self.assertEqual(report["status_counts"]["off-constraint"], 1)


class TestPreRegistration(GateCase):
    """A row written before its run.

    `SKILL.md` says twice to write the hypothesis into `results.tsv` before
    running, and the status vocabulary had no value for a row in that state. Six
    agents in a 33-idea validation each invented `planned` independently, as did
    an unrelated agent before them — the doctrine's first rule could not be
    recorded in the doctrine's own schema.
    """

    def planned(self, **over):
        row = {
            "commit": "pending", "hypothesis": "removing it will loosen the bound",
            "varied": "disagreement_opt", "how": "removed", "contrast": "aggregate__full",
            "metric": "pending", "seeds": "5", "spread": "pending", "status": "planned", "tuning": "inherited",
            "notes": "pre-registered", "evidence": "runs/aggregate__no_disag.json",
        }
        row.update(over)
        return row

    def test_a_planned_row_citing_a_file_that_does_not_exist_yet_is_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root, [BASELINE_ROW, *ablation_rows()], PLAN_TWO_MODULES)
            # the promised aggregate is deliberately absent from disk
            row = self.planned(evidence="runs/aggregate__not_run_yet.json")
            write_tsv(root / "results.tsv", RESULTS_HEADER,
                      [BASELINE_ROW, *ablation_rows(), row])
            report = inspect(root)
        self.assertNoFinding(report, "missing_evidence")
        self.assertEqual(report["gate"], "READY_FOR_CLAIM_SELECTION")

    def test_a_planned_row_still_has_to_say_what_it_will_do(self):
        report = self.gate([BASELINE_ROW, *ablation_rows(), self.planned(how="none")])
        self.assertBlockedBy(report, "claim_rows_naming_no_module")

    def test_a_planned_row_still_has_to_name_a_real_contrast(self):
        report = self.gate([BASELINE_ROW, *ablation_rows(),
                            self.planned(contrast="whatever we had before")])
        self.assertBlockedBy(report, "claim_rows_with_unresolved_contrast")

    def test_planning_an_ablation_does_not_discharge_the_module(self):
        """What is planned is not what is done."""
        report = self.gate([BASELINE_ROW, ablation_rows()[0],
                            self.planned(varied="coreset_rule", how="removed")])
        self.assertBlockedBy(report, "modules_never_ablated")
        self.assertEqual(report["ablation_coverage"]["coreset_rule"], 0)


class TestAggregatesAreAddressableByMethod(GateCase):
    """`aggregate__<method>.json`. The half before the separator is the literal
    word "aggregate" — identical for every aggregate and identifying nothing —
    so the method name after it has to resolve, and six validation ideas were
    blocked because it did not."""

    def test_the_method_name_after_the_separator_resolves(self):
        rows = ablation_rows()
        rows[0]["contrast"] = "full"  # aggregate__full.json, the baseline's evidence
        report = self.gate([BASELINE_ROW, *rows])
        self.assertEqual(report["gate"], "READY_FOR_CLAIM_SELECTION")

    def test_a_run_label_does_not_leak_its_commit_as_an_identifier(self):
        """`<label>__<commit>.json` is not an aggregate, so the half after the
        separator is a commit hash and must not become a contrast target."""
        from check_manuscript_readiness import run_identifiers
        self.assertEqual(
            run_identifiers("runs/control-split1-traj0__demo000.json"),
            {"control-split1-traj0__demo000", "control-split1-traj0"},
        )
        self.assertIn("random", run_identifiers("runs/aggregate__random.json"))


class TestThePlanIsADeclaration(GateCase):
    """Ways to reach a passing verdict with no ablation run, found by an
    adversarial sweep over the gate. The plan is self-declared, so these are the
    escapes that were available through the file itself."""

    def test_a_plan_with_only_a_header_is_not_a_declaration(self):
        """Zero declared modules satisfies "every module has a row" vacuously.
        "We never wrote down what the method is made of" and "the method is made
        of nothing" must not reach the same verdict."""
        report = self.gate([BASELINE_ROW, *ablation_rows()], plan=[])
        self.assertBlockedBy(report, "ablation_plan")

    def test_excusing_every_module_with_n_a_is_rejected(self):
        """The whole escape: mark each module un-ablatable, write "n/a", run
        nothing, pass."""
        plan = [dict(row, ablatable="no", reason="n/a") for row in PLAN_TWO_MODULES]
        report = self.gate([BASELINE_ROW], plan=plan)
        self.assertBlockedBy(report, "modules_excused_without_reason")

    def test_a_reason_too_short_to_be_a_reason_is_rejected(self):
        plan = [dict(row, ablatable="no", reason="hard to do") for row in PLAN_TWO_MODULES]
        report = self.gate([BASELINE_ROW], plan=plan)
        self.assertBlockedBy(report, "modules_excused_without_reason")

    def test_a_real_reason_is_accepted_but_does_not_reach_the_good_word(self):
        """This case used to assert READY_FOR_CLAIM_SELECTION, and that
        assertion was the defect written down.

        Every module honestly un-ablatable is the benchmark-paper shape found in
        the 33-idea validation: a correct, complete plan for work that proposes
        no method. It is also byte-for-byte the shape of "mark everything
        un-ablatable, run nothing, pass". No program reading a ledger can tell
        those apart, so the gate stops trying and stops calling both of them
        ready."""
        plan = [dict(row, ablatable="no", reason=FROZEN_REASON) for row in PLAN_TWO_MODULES]
        report = self.gate([BASELINE_ROW], plan=plan)
        self.assertEqual(report["gate"], "NO_ABLATION_EVIDENCE")
        self.assertNoFinding(report, "modules_excused_without_reason")
        self.assertTrue(self.findings(report, "no_ablation_evidence", "advisory"))

    def test_no_ablation_evidence_is_not_a_failure(self):
        """The record is correct; it simply contains no evidence about a module.
        Exit status stays 0 and the verdict word carries the information."""
        plan = [dict(row, ablatable="no", reason=FROZEN_REASON) for row in PLAN_TWO_MODULES]
        report = self.gate([BASELINE_ROW], plan=plan)
        self.assertEqual(report["error_count"], 0)

    def test_one_discharged_module_is_enough_to_reach_the_good_word(self):
        plan = [PLAN_TWO_MODULES[0],
                dict(PLAN_TWO_MODULES[1], ablatable="no", reason=FROZEN_REASON)]
        report = self.gate([BASELINE_ROW, ablation_rows()[0]], plan=plan)
        self.assertEqual(report["gate"], "READY_FOR_CLAIM_SELECTION")

    def test_a_fully_pre_registered_grid_has_not_discharged_anything_yet(self):
        """Planning the whole grid is not running it. The modules are declared
        ablatable and nothing has been ablated, so this blocks — which is the
        honest answer in full mode, and the reason a plan-only mode is the next
        thing this gate needs."""
        planned = [dict(r, status="planned", tuning="inherited", metric="pending", spread="pending")
                   for r in ablation_rows()]
        report = self.gate([BASELINE_ROW, *planned])
        self.assertBlockedBy(report, "modules_never_ablated")

    def test_a_module_declared_twice_is_rejected(self):
        plan = PLAN_TWO_MODULES + [dict(PLAN_TWO_MODULES[0], ablatable="no", reason=FROZEN_REASON)]
        report = self.gate([BASELINE_ROW, *ablation_rows()], plan=plan)
        self.assertBlockedBy(report, "modules_declared_twice")

    def test_a_module_must_say_where_in_the_source_it_lives(self):
        """Unverifiable from here, and that is the point: it is what lets a
        reader open the file and see that the plan omitted four stages."""
        plan = [dict(row, source="") for row in PLAN_TWO_MODULES]
        report = self.gate([BASELINE_ROW, *ablation_rows()], plan=plan)
        self.assertBlockedBy(report, "modules_without_a_source_location")


class TestTheBaselineIsOnlyAReference(GateCase):
    def test_a_baseline_row_may_not_also_ablate(self):
        """One row cannot be both the full method and a module removed from it,
        and if it were, it would discharge that module against itself."""
        report = self.gate([
            dict(BASELINE_ROW, varied="coreset_rule", how="removed"),
            *ablation_rows(),
        ])
        self.assertBlockedBy(report, "baseline_rows_that_also_ablate")

    def test_an_ablation_run_on_fewer_seeds_than_the_baseline_is_rejected(self):
        """2 seeds against a 15-seed baseline: the delta and the spread are not
        commensurable, and the skill asks for the same seeds on both sides."""
        rows = [dict(r, seeds="2") for r in ablation_rows()]
        report = self.gate([dict(BASELINE_ROW, seeds="15"), *rows])
        self.assertBlockedBy(report, "seed_counts_not_matching_the_baseline")

    def test_matching_seed_counts_pass(self):
        rows = [dict(r, seeds="15") for r in ablation_rows()]
        report = self.gate([dict(BASELINE_ROW, seeds="15"), *rows])
        self.assertEqual(report["gate"], "READY_FOR_CLAIM_SELECTION")


class TestSeedCountStillApplies(GateCase):
    def test_single_seed_claim_citing_an_aggregate_is_caught(self):
        """The hole the row-level move closed.

        The seed check used to sit inside the `primary` branch of the evidence
        loop, but a claim row cites an aggregate, which is derived — so this row
        reached no seed check at all. The documented bar and the enforced bar
        were different bars.
        """
        rows = ablation_rows()
        rows[0]["seeds"] = "1"
        rows[0]["spread"] = "0"
        report = self.gate([BASELINE_ROW, *rows])
        self.assertBlockedBy(report, "single_run_rows_marked_as_claims")

    def test_baseline_is_exempt_from_varied_and_contrast_but_not_from_seeds(self):
        thin = dict(BASELINE_ROW, seeds="1", spread="0")
        report = self.gate([thin, *ablation_rows()])
        self.assertBlockedBy(report, "single_run_rows_marked_as_claims")
        self.assertNoFinding(report, "claim_rows_naming_no_module")
        self.assertNoFinding(report, "claim_rows_with_unresolved_contrast")


def ablation_rows() -> list[dict[str, str]]:
    """One leave-one-out row per module in PLAN_TWO_MODULES."""
    return [
        {
            "commit": "bbb222", "hypothesis": "removing disagreement optimisation loosens the bound",
            "varied": "disagreement_opt", "how": "removed", "contrast": "aggregate__full", "metric": "0.243",
            "seeds": "5", "spread": "0.028", "status": "keep", "tuning": "inherited",
            "notes": "costs 0.056, clears the spread", "evidence": "runs/aggregate__no_disag.json",
        },
        {
            "commit": "ccc333", "hypothesis": "the coreset rule carries the effect",
            "varied": "coreset_rule", "how": "replaced", "contrast": "aggregate__full", "metric": "0.191",
            "seeds": "5", "spread": "0.030", "status": "no-effect", "tuning": "inherited",
            "notes": "delta 0.004 sits inside the 0.031 spread",
            "evidence": "runs/aggregate__no_coreset.json",
        },
    ]


if __name__ == "__main__":
    unittest.main(verbosity=2)
