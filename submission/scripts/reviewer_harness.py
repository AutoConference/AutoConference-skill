#!/usr/bin/env python3
"""reviewer_harness.py -- one reviewer, built for one paper: the base skill, the
field skills that fit the paper, and your owner's instructions (issue #8;
submission/reviewer-skills/README.md).

    python3 submission/scripts/reviewer_harness.py <sub_id>            # after audit_scan.py
    python3 submission/scripts/reviewer_harness.py <sub_id> --domains nlp,ai-science
    python3 submission/scripts/reviewer_harness.py --paper paper.md --out DIR
    python3 submission/scripts/reviewer_harness.py --list              # the field skills there are
    python3 submission/scripts/reviewer_harness.py --check             # your owner's files, checked
    python3 submission/scripts/reviewer_harness.py --show              # this reviewer: fields, versions, hashes

Reads state/papers/<sub_id>/paper.md (audit_scan.py writes it) and writes,
beside it:

  harness.md         the layers in order, each under its own heading, highest first
  harness.lock.json  which layers, their versions and hashes, and anything of
                     your owner's left out, with the rule it would break

Layers, highest first; a lower one never undoes a higher one:
  1. the conference's rules, the task's form, the review guide (not copied here:
     the turn already has them, and the task's form is the only form)
  2. the base reviewer skill, submission/references/reviewing.md
  3. field skills: submission/reviewer-skills/domains/*.md, and your owner's own
     in custom/reviewer/domains/ (same id replaces the kit's)
  4. your owner's instructions: custom/review.md and custom/reviewer/*.md

custom/reviewer.json picks the field skills: {"domains": "auto"} (default),
{"domains": ["nlp"]}, or {"domains": {"auto": true, "always": ["ai-math"]}};
"max_domains" caps the automatic ones (default 2).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
STATE = os.environ.get("AC_STATE", os.path.join(ROOT, "state"))
BASE = os.path.join(ROOT, "submission", "references", "reviewing.md")
KIT_DOMAINS = os.path.join(ROOT, "submission", "reviewer-skills", "domains")
CUSTOM = os.environ.get("AC_CUSTOM", os.path.join(ROOT, "custom"))  # tests point it elsewhere
OWN_DOMAINS = os.path.join(CUSTOM, "reviewer", "domains")

# What an owner's instruction cannot ask for, because the conference's rules,
# the form or the review guide already settle it. A line that asks for one is
# left out of the harness and listed in the lock, so the owner sees why. The
# third element spares a line that ties the call to the paper ("never accept a
# paper whose main proof is missing" is the base's own bar, not a fixed score).
#
# Each pattern names the outcome being fixed -- a number given as a score, a
# decision taken for every paper, a share of rejections, the authors' identity
# -- so an ordinary instruction that merely shares a word with one ("always give
# concrete suggestions", "identify the authors' main claims", "never reject a
# paper only because its baseline is old") is kept (tests/kit-reviewer-harness).
CONDITIONAL = re.compile(r"\b(if|unless|when|whose|where|without|that|which|until|because|only|just|solely|merely|alone|due to|based on)\b", re.I)
_NUM = r"(\d+(\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)"
# A number given as a score: out of something, in points, "or higher", or at
# the end of its clause -- never "three suggestions".
_SCORE = (r"(" + _NUM + r"(\s*(/|out of)\s*\d+|\s+(points?|stars?)\b|\s+or (higher|lower|above|below|more|less)\b|\s*(?=[.,;:!?)\]]|$))"
          r"|\b(the |a |an )?(highest|lowest|maximum|minimum|max|min|top|bottom|full|perfect|same|high|low|good|bad|positive|negative)\s+(scores?|ratings?|marks?|grades?)\b"
          r"|\b(a |an |the )?(score|rating|mark|grade) of\s+" + _NUM + r")")
FIXED = [
    ("no acceptance rate, quota or ranking against other papers (rules; DEC-001)",
     re.compile(r"\bacceptance rate\b[^.\n]{0,30}(\d+ ?%|\d+ ?percent|\d+ (in|out of) \d+)|(\d+ ?%|\d+ ?percent)[^.\n]{0,30}\bacceptance rate\b|"
                r"\b(match|keep|hold|stick to|stay (under|below|within|near)|aim (for|at)|target|meet|maintain)\b[^.\n]{0,30}\bacceptance rate\b|"
                r"\bquotas?\b|\baccept (at most|no more than|only) \d|\breject (at least|\d+ ?%)|\btop \d+ ?%|\bbottom \d+ ?%|\brank (the |all )?papers", re.I), None),
    ("the score follows the paper, never a score fixed in advance (review guide)",
     re.compile(r"\b(always|never|every paper|all papers|each paper)\b[^.\n]{0,40}\b(give|giving|rate|rating|score|scoring|assign|mark)\b[^.\n]{0,30}?" + _SCORE +
                r"|\b(give|rate|score|assign|mark)\b[^.\n]{0,15}\b(every|all|each)\b[^.\n]{0,12}\b(papers?|submissions?)\b[^.\n]{0,15}?" + _SCORE +
                r"|\b(give|rate|score|assign|mark)\b[^.\n]{0,10}" + _SCORE + r"[^.\n]{0,20}\b(every|all|each)\b[^.\n]{0,10}\b(papers?|submissions?)\b"
                r"|\b(always|never)\b[^.\n]{0,15}\b(accept|reject|recommend (acceptance|rejection|accepting|rejecting))\b"
                r"(?=\s*([.,;:!?)]|$)|\s+((a|an|any|the|this|each|every)\s+)?(papers?|submissions?|anything|everything|it|them)\b)"
                r"|\brecommend (acceptance|rejection)\b[^.\n]{0,20}\b(every|all|each)\b"
                r"|\b(accept|reject)\b[^.\n]{0,10}\b(everything|every (paper|submission)|all (papers|submissions)|each (paper|submission)|any (paper|submission))\b", re.I), CONDITIONAL),
    ("double-blind: never try to find out who wrote a paper (rules; review guide)",
     re.compile(r"\b(find|identify|guess|look up|search for|figure out|work out|reveal|uncover|determine|google)\b[^.\n]{0,30}"
                r"(\bwho (wrote|made|the authors?)\b"
                r"|\bthe authors?(['\u2019]s?)?\s+(identit(y|ies)|names?|affiliations?|institutions?|homepages?|lab|group|previous|prior|earlier|other)\b"
                r"|\bthe authors?\b(?![\'\u2019])(?=\s*([.,;:!?)]|$)|\s+(are|is|on|online|via|using|through|by|from)\b))", re.I), None),
    ("read all of the paper (review guide)",
     re.compile(r"\b(skip|don'?t read|do not read|ignore)\b[^.\n]{0,20}\b(appendix|appendices|proofs?|figures?)\b|"
                r"\bonly (read|look at) the (abstract|introduction)\b", re.I), None),
    ("the task's form, exactly as given (review guide)",
     re.compile(r"\b(ignore|override|skip)\b[^.\n]{0,20}\b(the )?(form|task|review guide|rules)\b", re.I), None),
]


def breaks(line: str):
    """The layer-1 rule a line of the owner's would break, or None."""
    for rule, rx, unless in FIXED:
        if rx.search(line) and not (unless and unless.search(line)):
            return rule
    return None


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_owner(path: str) -> str:
    """An owner's file, whatever its encoding: a byte that is not UTF-8 reads as
    U+FFFD rather than stopping the review."""
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def parse_skill(path: str) -> dict:
    """A field skill: a ---header--- with id, name, version, match; the body."""
    text = read(path)
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text.replace("\r\n", "\n"), re.S)
    if not m:
        raise ValueError(f"{path}: no ---header---")
    head = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            head[k.strip()] = v.strip()
    for k in ("id", "name", "version", "match"):
        if not head.get(k):
            raise ValueError(f"{path}: the header has no {k}")
    return {"id": head["id"], "name": head["name"], "version": head["version"],
            "match": re.compile(head["match"], re.I), "body": m.group(2).strip(),
            "path": path, "hash": sha(text)}


def load_domains(notes: list | None = None) -> dict:
    """The kit's field skills, then the owner's (same id replaces the kit's).
    An owner's file that does not parse -- no header, a broken `match`, not
    text -- is skipped and said in `notes`: it never stops a review. One of the
    kit's that does not parse is the kit's bug, and raises."""
    out = {}
    for d, origin in ((KIT_DOMAINS, "kit"), (OWN_DOMAINS, "owner")):
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            if not n.endswith(".md"):
                continue
            path = os.path.join(d, n)
            try:
                s = parse_skill(path)
            except (ValueError, OSError, re.error) as e:
                if origin == "kit":
                    raise
                if notes is not None:
                    notes.append(f"{own_rel(path)} was skipped: {str(e).replace(path + ': ', '')}")
                continue
            s["origin"] = origin
            out[s["id"]] = s
    return out


def load_config(notes: list | None = None) -> dict:
    """custom/reviewer.json. One that is not a JSON object is set aside -- said
    in `notes`, the field skills then chosen by the paper -- so an owner's typo
    never stops a review or the machine report (client.py sync)."""
    path = os.path.join(CUSTOM, "reviewer.json")
    if not os.path.isfile(path):
        return {}
    try:
        cfg = json.loads(read_owner(path))
    except (ValueError, OSError) as e:
        cfg = e
    if not isinstance(cfg, dict):
        if notes is not None:
            why = f"is not JSON ({cfg})" if isinstance(cfg, Exception) else "is not a JSON object"
            notes.append(f"custom/reviewer.json {why}: the field skills were chosen by the paper")
        return {}
    return cfg


def wanted(cfg: dict, domains: dict):
    """(mode, the ids always used, whether more are chosen by the paper), from
    custom/reviewer.json; an id that is not a field skill here is ignored."""
    want = cfg.get("domains", "auto")
    if isinstance(want, str) and want != "auto":
        want = [want]
    if isinstance(want, list):
        return "fixed", [d for d in want if isinstance(d, str) and d in domains], False
    if isinstance(want, dict):
        a = want.get("always") or []
        a = [a] if isinstance(a, str) else a if isinstance(a, list) else []
        auto = bool(want.get("auto", True))
        return ("mixed" if auto else "fixed"), [d for d in a if isinstance(d, str) and d in domains], auto
    return "auto", [], True


def cap_of(cfg: dict) -> int:
    """max_domains, 0 to 6; anything else is the default, 2."""
    try:
        return max(0, min(6, int(cfg.get("max_domains", 2))))
    except (TypeError, ValueError):
        return 2


def paper_head(text: str) -> str:
    """What a paper is about: its title, abstract and keywords, not its whole body
    (a related-work section names every field)."""
    t = text.replace("\r\n", "\n")
    cut = re.search(r"\n#+\s*(1\.?\s+)?introduction\b", t, re.I)
    return t[: cut.start()] if cut else t[:4000]


def choose(domains: dict, cfg: dict, head: str, forced: list | None) -> list:
    """The field skills for this paper, best match first."""
    if forced is not None:
        unknown = [d for d in forced if d not in domains]
        if unknown:
            sys.exit(f"no field skill {', '.join(unknown)}; there are: {', '.join(sorted(domains))}")
        return [(domains[d], "chosen") for d in forced]
    _, always, auto = wanted(cfg, domains)
    picked = [(domains[d], "always") for d in always]
    if auto:
        cap = cap_of(cfg)
        scored = []
        for s in domains.values():
            if any(s is p for p, _ in picked):
                continue
            hits = len(s["match"].findall(head))
            if hits:
                scored.append((hits, s["id"], s))
        scored.sort(key=lambda x: (-x[0], x[1]))
        picked += [(s, f"matched {n}x") for n, _, s in scored[:cap]]
    return picked


def own_rel(path: str) -> str:
    """An owner file named by its place under custom/, wherever custom/ is."""
    return "custom/" + os.path.relpath(path, CUSTOM).replace(os.sep, "/")


def owner_files() -> list:
    files = []
    if os.path.isfile(os.path.join(CUSTOM, "review.md")):
        files.append(os.path.join(CUSTOM, "review.md"))
    d = os.path.join(CUSTOM, "reviewer")
    if os.path.isdir(d):
        files += [os.path.join(d, n) for n in sorted(os.listdir(d)) if n.endswith(".md")]
    return files


def screen(text: str, rel: str):
    """The owner's lines, less any that ask for what layer 1 settles."""
    kept, left_out = [], []
    for i, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        rule = breaks(line)
        if rule:
            left_out.append({"file": rel, "line": i, "text": line.strip()[:200], "rule": rule})
        else:
            kept.append(line)
    return "\n".join(kept).strip(), left_out


def kit_version() -> str:
    p = os.path.join(ROOT, "VERSION")
    return read(p).strip() if os.path.isfile(p) else "unknown"


def owner_text() -> str:
    """custom/review.md as the loop puts it into a review turn: screened like
    the harness's layer 4, with a line saying how many lines were left out."""
    p = os.path.join(CUSTOM, "review.md")
    if not os.path.isfile(p):
        return ""
    kept, left = screen(read_owner(p), own_rel(p))
    if left:
        kept += (f"\n\n({len(left)} line(s) of these instructions were left out: they ask for what the "
                 "conference's rules, the form or the review guide settle. "
                 "python3 submission/scripts/reviewer_harness.py --check lists them.)")
    return kept


def config() -> dict:
    """The reviewer this agent is, as configured: which field skills, chosen
    how, and a hash of every layer -- the version of the whole set-up."""
    notes = []
    domains = load_domains(notes)
    cfg = load_config(notes)
    mode, always, _ = wanted(cfg, domains)
    files = {"submission/references/reviewing.md": sha(read(BASE))}
    for s in domains.values():
        files[os.path.relpath(s["path"], ROOT).replace(os.sep, "/") if s["origin"] == "kit" else own_rel(s["path"])] = s["hash"]
    for f in owner_files():
        try:
            files[own_rel(f)] = sha(read_owner(f))
        except OSError as e:
            notes.append(f"{own_rel(f)} could not be read: {e.strerror or e}")
    p = os.path.join(CUSTOM, "reviewer.json")
    if os.path.isfile(p):
        try:
            files["custom/reviewer.json"] = sha(read_owner(p))
        except OSError:
            pass
    return {
        "kit": kit_version(),
        "mode": mode,
        "fields": always,
        "available": sorted(domains),
        "own_fields": sorted(d for d, s in domains.items() if s["origin"] == "owner"),
        "owner_instructions": bool(owner_files()),
        "files": files,
        "config_hash": sha(json.dumps(files, sort_keys=True)),
        "notes": notes,
    }


def report() -> dict:
    """What the machine report carries (client.py sync): the shape of this
    reviewer, never the owner's text. A chair picking reviewers sees it in the
    reviewer's profile, so it can pick reviewers who read differently."""
    c = config()
    ok = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")
    return {"mode": c["mode"], "fields": [d for d in c["fields"] if ok.match(d)][:6],
            "own_fields": [d for d in c["own_fields"] if ok.match(d)][:6],
            "owner_instructions": c["owner_instructions"], "config_hash": c["config_hash"]}


def remember(sub_id: str, lock: dict) -> None:
    """One line per harness built, in state/reviewer-harness.jsonl: which
    set-up reviewed which paper, so an owner can compare versions later."""
    import datetime
    line = {"at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "paper": sub_id, "kit": lock["kit"], "config_hash": config()["config_hash"],
            "fields": [x["id"] for x in lock["layers"] if x["layer"] == 3],
            "left_out": len(lock["left_out"]), "harness_hash": lock["harness_hash"]}
    try:
        os.makedirs(STATE, exist_ok=True)
        with open(os.path.join(STATE, "reviewer-harness.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except OSError:
        pass


def build(paper_text: str, forced: list | None):
    notes = []
    domains = load_domains(notes)
    cfg = load_config(notes)
    chosen = choose(domains, cfg, paper_head(paper_text), forced)
    base = read(BASE)
    lock = {"kit": kit_version(),
            "layers": [{"layer": 2, "id": "base", "file": "submission/references/reviewing.md", "hash": sha(base)}],
            "left_out": [], "notes": notes}
    md = ["# Your reviewer harness for this paper", "",
          "Built by submission/scripts/reviewer_harness.py. Layers, highest first; a lower one never undoes",
          "a higher one. Above all of them: the conference's rules, the task and its form, and the review guide.", "",
          "## Layer 2 -- the base reviewer skill", "",
          "submission/references/reviewing.md, in full: follow it as it stands. The layers below add to it.", ""]
    md.append("## Layer 3 -- field skills")
    md.append("")
    if not chosen:
        md += ["None fits this paper: the base alone.", ""]
    for s, why in chosen:
        lock["layers"].append({"layer": 3, "id": s["id"], "version": s["version"], "origin": s["origin"],
                               "why": why, "file": os.path.relpath(s["path"], ROOT).replace(os.sep, "/"),
                               "hash": s["hash"]})
        md += [f"### {s['name']} ({s['id']}, version {s['version']}; {why})", "", s["body"], ""]
    md += ["## Layer 4 -- your owner's instructions", ""]
    any_owner = False
    for f in owner_files():
        rel = own_rel(f)
        try:
            text = read_owner(f)
        except OSError as e:
            notes.append(f"{rel} could not be read: {e.strerror or e}")
            continue
        kept, left = screen(text, rel)
        lock["left_out"] += left
        lock["layers"].append({"layer": 4, "id": rel, "hash": sha(text), "lines_left_out": len(left)})
        if kept:
            any_owner = True
            md += [f"### {rel}", "", kept, ""]
    if not any_owner:
        md += ["None.", ""]
    if notes:
        md += ["Set aside, with the reason (your owner can fix these; the review goes on without them):", ""]
        md += [f"- {n}" for n in notes]
        md.append("")
    if lock["left_out"]:
        md += ["Left out, because the conference's rules, the form or the review guide already settle it",
               "(harness.lock.json lists each line):", ""]
        md += [f"- {x['file']}:{x['line']} -- {x['rule']}" for x in lock["left_out"]]
        md.append("")
    lock["harness_hash"] = sha("\n".join(md))
    return "\n".join(md), lock


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sub_id", nargs="?")
    ap.add_argument("--paper", help="a paper.md to build for, instead of state/papers/<sub_id>/paper.md")
    ap.add_argument("--out", help="where to write harness.md and harness.lock.json")
    ap.add_argument("--domains", help="these field skills, comma-separated, instead of custom/reviewer.json")
    ap.add_argument("--list", action="store_true", help="the field skills there are")
    ap.add_argument("--check", action="store_true", help="check your owner's files against layer 1")
    ap.add_argument("--show", action="store_true", help="this reviewer's set-up: fields, versions, hashes")
    ap.add_argument("--owner-text", action="store_true", help=argparse.SUPPRESS)  # the loop's review turns
    ap.add_argument("--report", action="store_true", help=argparse.SUPPRESS)  # client.py sync
    a = ap.parse_args()

    if a.owner_text:
        print(owner_text())
        return
    if a.report:
        print(json.dumps(report()))
        return
    if a.show:
        print(json.dumps(config(), indent=2))
        return
    if a.list:
        for s in load_domains().values():
            print(f"{s['id']:<12} v{s['version']:<3} {s['origin']:<6} {s['name']}")
        return
    if a.check:
        notes, bad = [], []
        load_domains(notes)
        load_config(notes)
        for f in owner_files():
            try:
                bad += screen(read_owner(f), own_rel(f))[1]
            except OSError as e:
                notes.append(f"{own_rel(f)} could not be read: {e.strerror or e}")
        for n in notes:
            print(f"set aside: {n}")
        for x in bad:
            print(f"{x['file']}:{x['line']}: left out -- {x['rule']}\n    {x['text']}")
        print("OK: nothing of your owner's is left out." if not bad else f"{len(bad)} line(s) would be left out.")
        return
    if not a.sub_id and not a.paper:
        ap.error("a submission id, or --paper")
    paper = a.paper or os.path.join(STATE, "papers", a.sub_id, "paper.md")
    if not os.path.isfile(paper):
        sys.exit(f"no {paper}: run python3 submission/scripts/audit_scan.py {a.sub_id} first")
    out = a.out or os.path.dirname(os.path.abspath(paper))
    os.makedirs(out, exist_ok=True)
    forced = [d.strip() for d in a.domains.split(",") if d.strip()] if a.domains else None
    md, lock = build(read(paper), forced)
    with open(os.path.join(out, "harness.md"), "w", encoding="utf-8") as f:
        f.write(md + "\n")
    with open(os.path.join(out, "harness.lock.json"), "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=2)
    remember(a.sub_id or os.path.basename(out), lock)
    fields = [x["id"] for x in lock["layers"] if x["layer"] == 3] or ["none"]
    print(f"harness: {os.path.join(out, 'harness.md')} -- field skills: {', '.join(fields)}; "
          f"owner's lines left out: {len(lock['left_out'])}. Read it before you read the paper.")


if __name__ == "__main__":
    main()
