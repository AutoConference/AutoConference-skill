#!/usr/bin/env python3
"""related-work gate -- step 9's references exist, are the papers they name, and differ.

    research/scripts/check_related_work.py work/<cycle>

Step 9 used to go on whenever the model's turn exited cleanly: a turn that wrote
no related work at all passed, and only step 12's citation count, a paper's
length later, could notice (a tester's report, 2026-10-05). This reads the list
step 9 writes beside its prose, refine-logs/RELATED_WORK.json:

    {"works": [{"title": "...", "arxiv_id": "2307.03172" | null, "doi": "10.…" | null,
                "relation": "builds_on" | "contradicts" | "neighbouring",
                "what_it_does": "...", "difference": "how it differs from this paper's claim"}]}

and fails the step for:

  * fewer works than quality.json's paper_shape.min_citations, or no
    refine-logs/RELATED_WORK.md for the writer to read;
  * a work listed twice, or with no title;
  * a work whose difference from this paper is missing, under 12 words, or the
    same words as another's (a stated difference is the point of the list);
  * a reference that does not exist: an arXiv id arXiv does not know, a DOI
    Crossref does not know, or a title alone that Semantic Scholar cannot find;
  * an identifier that names a different paper than the title says -- the
    commonest made-up citation is a real id under the wrong title.

Each work is looked up where its identifier lives (arXiv, then Crossref, then a
Semantic Scholar title search for a work with neither). A service that does not
answer is asked twice more; a work it still cannot check is "unchecked", never
passed as checked. Unchecked works beyond the minimum are reported and let
through; too few checked works because of them is its own outcome (exit 3), and
the pipeline then checks again without writing the list again.

The verdict goes to refine-logs/RELATED_WORK.check.json with the list's digest.

Exit 0 = the list holds, 1 = it does not (the step writes it again),
3 = the services did not answer for enough of it (checked again, unchanged).

AC_RELATED_WORK_FIXTURE=<file.json> answers the lookups from a file instead of
the network, for tests: {"arxiv:<id>" | "doi:<doi>" | "title:<title>":
{"title": "..."} | "missing" | "unavailable"}.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UA = "autoconference-kit related-work check (+https://autoconference.ai)"
ARXIV_ID = re.compile(r"^(?:arxiv:\s*|https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/)?"
                      r"(\d{4}\.\d{4,5}|[a-z][a-z\-]*(?:\.[a-z]{2})?/\d{7})(?:v\d+)?(?:\.pdf)?$", re.I)
DOI = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/\S+)$", re.I)
RELATIONS = ("builds_on", "contradicts", "neighbouring")
MIN_DIFF_WORDS = 12
# The same paper: most of the shorter title's words are in the other. A cited
# title is often the short form ("BERT"), so it is measured against the shorter.
SAME_BY_ID = 0.6
# A title alone has nothing else to stand on: most of both titles' words.
SAME_BY_TITLE = 0.8
STOP = set("a an the of for and in on to with via by from is are at as its into towards toward using".split())
ROUNDS = (0, 15, 45)   # seconds before each round of lookups


def norm_words(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"\\[a-zA-Z]+|[{}$]", " ", s)
    return [w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP]


def overlap(a: str, b: str) -> float:
    """Shared words over the shorter title's words."""
    wa, wb = set(norm_words(a)), set(norm_words(b))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def both_ways(a: str, b: str) -> float:
    wa, wb = set(norm_words(a)), set(norm_words(b))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


class Unavailable(Exception):
    """The service did not answer: nothing is known about the work."""


def fetch(url: str, accept: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, **(
        {"x-api-key": os.environ["S2_API_KEY"]} if "semanticscholar" in url and os.environ.get("S2_API_KEY") else {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return b""
        raise Unavailable(f"HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Unavailable(str(e)[:120])


class Lookup:
    """Where each kind of identifier is looked up. Returns the title found,
    None for "no such work", or raises Unavailable."""

    def __init__(self) -> None:
        f = os.environ.get("AC_RELATED_WORK_FIXTURE")
        self.fixture = json.load(open(f, encoding="utf-8")) if f else None

    def _fixed(self, key: str):
        v = self.fixture.get(key, "missing")
        if v == "unavailable":
            raise Unavailable("fixture")
        return None if v == "missing" else v.get("title")

    def arxiv(self, ids: list[str]) -> dict:
        """id -> title, None, or an Unavailable, for a batch."""
        if self.fixture is not None:
            out = {}
            for i in ids:
                try:
                    out[i] = self._fixed(f"arxiv:{i}")
                except Unavailable as e:
                    out[i] = e
            return out
        out: dict = {}
        for k in range(0, len(ids), 40):
            batch = ids[k:k + 40]
            url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
                {"id_list": ",".join(batch), "max_results": len(batch)})
            try:
                raw = fetch(url, "application/atom+xml")
                if not raw:
                    raise Unavailable("arXiv's API answered 404")
                root = ET.fromstring(raw)
            except Unavailable as e:
                out.update({i: e for i in batch})
                continue
            except ET.ParseError:
                out.update({i: Unavailable("arXiv answered with something that is not a feed") for i in batch})
                continue
            ns = {"a": "http://www.w3.org/2005/Atom"}
            found = {}
            for e in root.findall("a:entry", ns):
                eid = (e.findtext("a:id", default="", namespaces=ns) or "").rsplit("/abs/", 1)[-1]
                eid = re.sub(r"v\d+$", "", eid.strip())
                title = " ".join((e.findtext("a:title", default="", namespaces=ns) or "").split())
                if eid and title and title.lower() != "error":
                    found[eid.lower()] = title
            for i in batch:
                out[i] = found.get(i.lower())
            time.sleep(3)   # arXiv asks for one request every three seconds
        return out

    def doi(self, doi: str):
        if self.fixture is not None:
            return self._fixed(f"doi:{doi}")
        raw = fetch("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/"), "application/json")
        if not raw:
            return None
        try:
            titles = json.loads(raw.decode("utf-8", "replace")).get("message", {}).get("title") or []
        except ValueError:
            raise Unavailable("Crossref answered with something that is not JSON")
        return " ".join(str(titles[0]).split()) if titles else ""

    def title(self, title: str):
        if self.fixture is not None:
            return self._fixed(f"title:{title}")
        raw = fetch("https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(
            {"query": title, "limit": 5, "fields": "title"}), "application/json")
        try:
            data = json.loads(raw.decode("utf-8", "replace")).get("data") or [] if raw else []
        except ValueError:
            raise Unavailable("Semantic Scholar answered with something that is not JSON")
        best = max((p.get("title") or "" for p in data), key=lambda t: both_ways(title, t), default="")
        return best if best and both_ways(title, best) >= SAME_BY_TITLE else None


def key_of(w: dict) -> tuple[str, str]:
    """('arxiv' | 'doi' | 'title', the normalised identifier)."""
    a = str(w.get("arxiv_id") or "").strip()
    m = ARXIV_ID.match(a) if a else None
    if m:
        return "arxiv", m.group(1).lower()
    d = str(w.get("doi") or "").strip()
    m = DOI.match(d) if d else None
    if m:
        return "doi", m.group(1).lower().rstrip(".")
    return "title", " ".join(norm_words(w.get("title")))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workspace")
    ap.add_argument("--quality", default=os.path.join(KIT, "interfaces", "quality.example.json"))
    a = ap.parse_args()
    logs = os.path.join(a.workspace, "refine-logs")
    src = os.path.join(logs, "RELATED_WORK.json")
    try:
        need = int(json.load(open(a.quality, encoding="utf-8"))["paper_shape"]["min_citations"])
    except (OSError, ValueError, KeyError, TypeError):
        need = 8
    problems: list[str] = []
    rows: list[dict] = []

    def finish(outcome: str, code: int) -> None:
        digest = ""
        if os.path.exists(src):
            digest = hashlib.sha256(open(src, "rb").read()).hexdigest()
        os.makedirs(logs, exist_ok=True)
        with open(os.path.join(logs, "RELATED_WORK.check.json"), "w", encoding="utf-8") as f:
            json.dump({"outcome": outcome, "sha256": digest, "min_works": need,
                       "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                       "problems": problems, "works": rows}, f, indent=2, ensure_ascii=False)
        for p in problems:
            print(f"  FAIL  {p}")
        verified = sum(r.get("status") == "verified" for r in rows)
        print(f"related-work: {outcome.upper()} -- {verified} of {len(rows)} work(s) checked against "
              f"arXiv / Crossref / Semantic Scholar; {need} needed")
        sys.exit(code)

    md = os.path.join(logs, "RELATED_WORK.md")
    if not (os.path.exists(md) and os.path.getsize(md) > 0):
        problems.append("no refine-logs/RELATED_WORK.md: the writer reads the related work from it")
    try:
        doc = json.load(open(src, encoding="utf-8"))
    except FileNotFoundError:
        problems.append("no refine-logs/RELATED_WORK.json: step 9 lists its works there, for this check")
        finish("fail", 1)
    except (OSError, ValueError) as e:
        problems.append(f"refine-logs/RELATED_WORK.json is not JSON ({e})")
        finish("fail", 1)
    works = doc.get("works") if isinstance(doc, dict) else doc
    if not isinstance(works, list):
        problems.append('refine-logs/RELATED_WORK.json has no "works" list')
        finish("fail", 1)

    seen: dict[tuple, int] = {}
    diffs: dict[str, int] = {}
    for i, w in enumerate(works, 1):
        if not isinstance(w, dict):
            problems.append(f"work {i} is not an object")
            continue
        title = " ".join(str(w.get("title") or "").split())
        kind, ident = key_of(w)
        row = {"n": i, "title": title, "key": f"{kind}:{ident}" if kind != "title" else "title", "status": "pending"}
        rows.append(row)
        if not norm_words(title):
            row["status"] = "no_title"
            problems.append(f"work {i} has no title")
            continue
        if (kind, ident) in seen:
            row["status"] = "duplicate"
            problems.append(f"work {i} ({title[:60]}) is work {seen[(kind, ident)]} again")
            continue
        seen[(kind, ident)] = i
        # An identifier given but not shaped like one would otherwise fall
        # through to a title search, and the paper would cite it as written.
        bad_id = []
        if str(w.get("arxiv_id") or "").strip() and kind != "arxiv":
            bad_id.append(f"arXiv id {w['arxiv_id']!r}")
        if str(w.get("doi") or "").strip() and kind == "title":
            bad_id.append(f"DOI {w['doi']!r}")
        if bad_id:
            row["status"] = "bad_identifier"
            problems.append(f"work {i} ({title[:60]}): {' and '.join(bad_id)} {'is' if len(bad_id) == 1 else 'are'} "
                            f"not well formed (an arXiv id is like 2307.03172, a DOI like 10.1145/3442188.3445922; null when there is none)")
            continue
        diff = " ".join(str(w.get("difference") or "").split())
        nd = " ".join(norm_words(diff))
        if len(diff.split()) < MIN_DIFF_WORDS:
            row["status"] = "no_difference"
            problems.append(f"work {i} ({title[:60]}) states no difference from this paper's claim "
                            f"({len(diff.split())} words; at least {MIN_DIFF_WORDS})")
            continue
        if nd in diffs:
            row["status"] = "no_difference"
            problems.append(f"work {i} ({title[:60]}) states work {diffs[nd]}'s difference word for word")
            continue
        diffs[nd] = i
        if w.get("relation") not in RELATIONS:
            # Said, not failed: the grouping helps the writer; the difference is what matters.
            print(f"  note  work {i}: relation {w.get('relation')!r} is not one of {', '.join(RELATIONS)}")
        row["_kind"], row["_ident"] = kind, ident

    look = Lookup()
    todo = [r for r in rows if "_kind" in r]
    for wait in ROUNDS:
        pending = [r for r in todo if r["status"] in ("pending", "unchecked")]
        if not pending:
            break
        if wait and look.fixture is None:
            time.sleep(wait)
        ids = [r["_ident"] for r in pending if r["_kind"] == "arxiv"]
        got = look.arxiv(ids) if ids else {}
        for r in pending:
            try:
                if r["_kind"] == "arxiv":
                    found = got.get(r["_ident"])
                    if isinstance(found, Exception):
                        raise found
                    via = "arxiv"
                elif r["_kind"] == "doi":
                    found, via = look.doi(r["_ident"]), "crossref"
                else:
                    found, via = look.title(r["title"]), "semantic_scholar"
            except Unavailable as e:
                r["status"], r["why"] = "unchecked", str(e)
                continue
            if found is None:
                r["status"] = "not_found"
            elif r["_kind"] != "title" and found and overlap(r["title"], found) < SAME_BY_ID:
                r["status"], r["found_title"] = "other_paper", found
            else:
                r["status"], r["found_title"], r["via"] = "verified", found, via

    for r in todo:
        if r["status"] == "not_found":
            where = {"arxiv": "arXiv has no paper", "doi": "Crossref has no work",
                     "title": "Semantic Scholar finds no paper"}[r["_kind"]]
            problems.append(f"work {r['n']} ({r['title'][:60]}): {where} under {r['key'] if r['_kind'] != 'title' else 'that title'}")
        elif r["status"] == "other_paper":
            problems.append(f"work {r['n']}: {r['key']} is \"{r['found_title'][:80]}\", not \"{r['title'][:80]}\"")
        r.pop("_kind", None)
        r.pop("_ident", None)

    verified = sum(r["status"] == "verified" for r in rows)
    unchecked = [r for r in rows if r["status"] == "unchecked"]
    for r in unchecked:
        print(f"  note  work {r['n']} ({r['title'][:60]}) could not be checked now ({r.get('why', '')})")
    # Too few is said with everything else, so one rewrite fixes it all --
    # unless the works a service did not answer for would make up the number.
    if verified + len(unchecked) < need:
        problems.append(f"{verified} checked work(s); at least {need} needed (quality.json paper_shape.min_citations)")
    if problems:
        finish("fail", 1)
    if verified < need:
        problems.append(f"only {verified} work(s) could be checked; {len(unchecked)} more waited on a "
                        f"service that did not answer. The list is checked again, unchanged.")
        finish("unchecked", 3)
    finish("pass", 0)


if __name__ == "__main__":
    main()
