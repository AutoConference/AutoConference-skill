#!/usr/bin/env python3
"""Verify that every bibliography entry names a work that exists.

A fabricated citation is the failure mode most likely to survive every other
gate: it compiles, it renders, and it reads correctly. This resolves each entry
against the source that issued its identifier and compares the returned title
with the stored one.

    python3 scripts/check_citations.py paper/references.bib
    python3 scripts/check_citations.py paper/references.bib --json --strict

arXiv entries resolve through the arXiv API, DOI entries through Crossref.
An entry carrying neither identifier cannot be resolved automatically and is
reported as unverified: check it by hand rather than assuming it is fine.

Read-only. Never edits the bibliography. Needs network access; without it the
run reports what it could not reach instead of passing silently.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import shutil
import os
import time
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ARXIV_API = "https://export.arxiv.org/api/query"
CROSSREF_API = "https://api.crossref.org/works/"
ATOM = {"a": "http://www.w3.org/2005/Atom"}
TIMEOUT = 60
# Two titles for the same work differ in case, punctuation, and LaTeX escaping.
TITLE_MATCH = 0.82


ENTRY_START = re.compile(r"@(\w+)\s*\{\s*([^,\s}]+)\s*,")
ENTRY_MARK = re.compile(r"@(\w+)\s*\{")
NON_ENTRY = {"comment", "preamble", "string"}


def _brace_end(text: str, open_idx: int) -> int | None:
    r"""Index just past the brace group that opens at `open_idx`, or None if it
    never closes. Counting braces is what BibTeX itself does, so a title with
    nested braces, a field body containing a line that starts with `}`, and an
    entry whose closing brace is indented or shares a line with its last field
    all read correctly. The previous regex required the entry to end with a
    newline followed by `}` in column 0 and silently dropped every entry that
    did not -- an unverifiable citation the gate then never mentioned."""
    depth = 0
    i = open_idx
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _fields(body: str):
    """name -> raw value for each top-level `name = value` in an entry body."""
    i, n = 0, len(body)
    assign = re.compile(r"\s*(\w+)\s*=\s*")
    while i < n:
        m = assign.match(body, i)
        if not m:
            nxt = body.find(",", i)
            if nxt < 0:
                return
            i = nxt + 1
            continue
        name = m.group(1)
        i = m.end()
        if i < n and body[i] == "{":
            end = _brace_end(body, i)
            if end is None:
                return
            yield name, body[i + 1:end - 1]
            i = end
        elif i < n and body[i] == '"':
            j = i + 1
            while j < n and body[j] != '"':
                j += 2 if body[j] == "\\" else 1
            yield name, body[i + 1:j]
            i = min(j + 1, n)
        else:
            j = body.find(",", i)
            j = n if j < 0 else j
            yield name, body[i:j].strip()
            i = j
        while i < n and body[i] in " \t\r\n":
            i += 1
        if i < n and body[i] == ",":
            i += 1


def parse_bib(text: str) -> list[dict]:
    entries = []
    for match in ENTRY_START.finditer(text):
        kind, key = match.group(1), match.group(2)
        if kind.lower() in NON_ENTRY:
            continue
        brace = text.find("{", match.start())
        end = _brace_end(text, brace)
        body = text[match.end():(end - 1) if end else len(text)]
        fields = {name.lower(): " ".join(value.split()) for name, value in _fields(body)}
        entries.append({"key": key, "type": kind.lower(), "_closed": end is not None, **fields})
    return entries


def unreadable_entries(text: str, entries: list[dict]) -> int:
    """How many `@type{` markers the parser could not turn into an entry.

    An entry this file cannot read is an entry this gate cannot verify, so it
    is counted and reported rather than passed over in silence."""
    marks = sum(1 for m in ENTRY_MARK.finditer(text) if m.group(1).lower() not in NON_ENTRY)
    return max(0, marks - len(entries))


def normalize_title(raw: str) -> str:
    text = re.sub(r"\\[A-Za-z]+", " ", raw)
    text = re.sub(r"[^A-Za-z0-9 ]", " ", text)
    return " ".join(text.lower().split())


def similarity(a: str, b: str) -> float:
    """Token overlap, which survives subtitle and punctuation differences."""
    sa, sb = set(normalize_title(a).split()), set(normalize_title(b).split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(len(sa), len(sb))


_LAST_ARXIV_CALL = 0.0
ARXIV_INTERVAL = 3.0   # export.arxiv.org's terms: at most one request every 3 s; bursts get 406


def _curl(url: str) -> bytes | None:
    """GET via curl when it is installed. export.arxiv.org has answered every
    curl request in testing and a large fraction of otherwise identical
    urllib requests with 406; the transport, not the request, is the variable."""
    if not shutil.which("curl"):
        return None
    proc = subprocess.run(["curl", "-sS", "-L", "--max-time", str(TIMEOUT), "-w", "\n%{http_code}",
                           "-A", "paper-writing-check-citations/1.0 (curl)", url],
                          capture_output=True)
    body, _, code = proc.stdout.rpartition(b"\n")
    if proc.returncode != 0 or not code.strip().isdigit():
        return None
    status = int(code)
    if status == 200:
        return body
    raise urllib.error.HTTPError(url, status, "curl", hdrs=None, fp=None)


def _get(url: str) -> bytes:
    """GET with pacing and an identifying User-Agent.

    arXiv answers a burst of requests -- even two in quick succession -- with
    HTTP 406, which looks like a content-negotiation failure and is in fact
    rate limiting. Every call waits out the interval since the previous one,
    and a 406 is retried once after a full interval."""
    global _LAST_ARXIV_CALL
    # export.arxiv.org answers an unfamiliar User-Agent with 406 (every request,
    # not a rate limit: the same id from curl is 200). Identify as a browser-
    # compatible client and accept anything, the way curl does.
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; paper-writing-check-citations/1.0)",
        "Accept": "*/*"})
    for attempt in (1, 2, 3):
        wait = ARXIV_INTERVAL - (time.monotonic() - _LAST_ARXIV_CALL)
        if wait > 0:
            time.sleep(wait)
        try:
            data = _curl(url)
            if data is None:
                data = urllib.request.urlopen(request, timeout=TIMEOUT).read()
            _LAST_ARXIV_CALL = time.monotonic()
            return data
        except urllib.error.HTTPError as exc:
            _LAST_ARXIV_CALL = time.monotonic()
            # 429: throttled -- honor Retry-After (capped) and try again;
            # 406: the front end declined this request -- try again after the
            # interval. Anything else, or a third failure, is reported as is.
            if exc.code not in (406, 429) or attempt == 3:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                pause = min(60.0, float(retry_after)) if retry_after else ARXIV_INTERVAL * (3 if exc.code == 429 else 1)
            except ValueError:
                pause = ARXIV_INTERVAL * 3
            time.sleep(pause)
    raise AssertionError("unreachable")


CACHE_PATH = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "paper-writing" / "citations.json"


def load_cache() -> dict[str, str]:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(cache: dict[str, str]) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, indent=0, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


def fetch_arxiv(ids: list[str]) -> dict[str, str]:
    """Map arXiv id -> title, one paced request per id.

    export.arxiv.org answers some ids with HTTP 406 (observed for ids the
    API will not serve), and answers any comma-joined id_list containing one
    of them with 406 for the whole batch. One id per request keeps a single
    bad id from hiding every other entry: a 406 on an id means that id is
    not resolvable and is reported for that entry alone."""
    titles: dict[str, str] = {}
    for one in ids:
        url = f"{ARXIV_API}?id_list={urllib.parse.quote(one)}&max_results=1"
        try:
            root = ET.fromstring(_get(url))
        except urllib.error.HTTPError as exc:
            if exc.code in (406, 429):
                titles[one] = None          # -> unresolved for this entry, never "not found"
                continue
            raise
        for entry in root.findall("a:entry", ATOM):
            raw_id = entry.find("a:id", ATOM).text.rsplit("/", 1)[-1]
            title = entry.find("a:title", ATOM)
            if title is not None and title.text:
                titles[re.sub(r"v\d+$", "", raw_id)] = " ".join(title.text.split())
    return titles


def fetch_doi(doi: str) -> str | None:
    url = CROSSREF_API + urllib.parse.quote(doi)
    request = urllib.request.Request(url, headers={"User-Agent": "paper-writing-skill/1.0"})
    payload = json.loads(urllib.request.urlopen(request, timeout=TIMEOUT).read())
    titles = payload.get("message", {}).get("title") or []
    return titles[0] if titles else None


def check(entries: list[dict], offline: bool, no_cache: bool = False) -> list[dict]:
    results: list[dict] = []
    arxiv_ids = {}
    for entry in entries:
        eprint = entry.get("eprint", "")
        if eprint and "arxiv" in entry.get("archiveprefix", "arxiv").lower():
            arxiv_ids[entry["key"]] = re.sub(r"v\d+$", "", eprint)

    fetched: dict[str, str] = {}
    reachable = True
    # Titles already resolved by an earlier run (this paper's or another's)
    # are not fetched again: arXiv paces us at one request per 3 s, and a
    # bibliography is re-checked many times while it is being written.
    cache = {} if no_cache else load_cache()
    wanted = sorted(set(arxiv_ids.values()))
    fetched = {i: cache[f"arxiv:{i}"] for i in wanted if f"arxiv:{i}" in cache}
    missing = [i for i in wanted if i not in fetched]
    if missing and not offline:
        try:
            fetched.update(fetch_arxiv(missing))
            for i, t in fetched.items():
                if t is not None:
                    cache[f"arxiv:{i}"] = t
            if not no_cache:
                save_cache(cache)
        except (urllib.error.URLError, ET.ParseError, OSError) as exc:  # noqa: BLE001
            reachable = False
            fetched = {}
            results.append({"key": "-", "status": "unreachable", "severity": "warning",
                            "detail": f"arXiv API not reachable: {exc}"})

    for entry in entries:
        key, stored = entry["key"], entry.get("title", "")
        if not entry.get("_closed", True):
            results.append({"key": key, "status": "unreadable", "severity": "error",
                            "detail": "this entry's braces never close; BibTeX and this gate "
                                      "both stop reading the file here"})
            continue
        if not stored:
            results.append({"key": key, "status": "no_title", "severity": "error",
                            "detail": "entry has no title field"})
            continue

        if key in arxiv_ids:
            if offline or not reachable:
                results.append({"key": key, "status": "unchecked", "severity": "advisory",
                                "detail": "arXiv id present but not resolved"})
                continue
            if arxiv_ids[key] in fetched and fetched[arxiv_ids[key]] is None:
                results.append({"key": key, "status": "unchecked", "severity": "advisory",
                                "detail": f"arXiv declined the request for {arxiv_ids[key]} "
                                          "(406/429 after retries); re-run later"})
                continue
            found = fetched.get(arxiv_ids[key])
            if found is None:
                results.append({"key": key, "status": "not_found", "severity": "error",
                                "detail": f"arXiv id {arxiv_ids[key]} returned no record"})
            elif similarity(stored, found) < TITLE_MATCH:
                results.append({"key": key, "status": "title_mismatch", "severity": "error",
                                "detail": f"stored '{stored}' vs arXiv '{found}'"})
            else:
                results.append({"key": key, "status": "verified", "severity": "ok",
                                "detail": f"arXiv:{arxiv_ids[key]}"})
            continue

        doi = entry.get("doi")
        if doi:
            if offline:
                results.append({"key": key, "status": "unchecked", "severity": "advisory",
                                "detail": "DOI present but not resolved"})
                continue
            try:
                found = cache.get(f"doi:{doi}") if not no_cache else None
                if found is None:
                    found = fetch_doi(doi)
                    if found and not no_cache:
                        cache[f"doi:{doi}"] = found
                        save_cache(cache)
            except (urllib.error.URLError, OSError, json.JSONDecodeError):  # noqa: BLE001
                results.append({"key": key, "status": "not_found", "severity": "error",
                                "detail": f"DOI {doi} did not resolve"})
                continue
            if found is None:
                results.append({"key": key, "status": "not_found", "severity": "error",
                                "detail": f"DOI {doi} returned no title"})
            elif similarity(stored, found) < TITLE_MATCH:
                results.append({"key": key, "status": "title_mismatch", "severity": "error",
                                "detail": f"stored '{stored}' vs Crossref '{found}'"})
            else:
                results.append({"key": key, "status": "verified", "severity": "ok",
                                "detail": f"doi:{doi}"})
            continue

        results.append({"key": key, "status": "unverifiable", "severity": "warning",
                        "detail": "no arXiv id and no DOI; verify this entry by hand"})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bib", type=Path, nargs="?", default=Path("paper/references.bib"))
    parser.add_argument("--offline", action="store_true", help="parse only; resolve nothing")
    parser.add_argument("--no-cache", action="store_true",
                        help=f"ignore and do not write the resolved-title cache ({CACHE_PATH})")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true",
                        help="also fail on entries that could not be resolved")
    args = parser.parse_args()

    if not args.bib.exists():
        print(f"bibliography not found: {args.bib}", file=sys.stderr)
        return 2

    raw = args.bib.read_text(encoding="utf-8")
    entries = parse_bib(raw)
    results = check(entries, args.offline, args.no_cache)
    unreadable = unreadable_entries(raw, entries)
    if unreadable:
        results.append({"key": "-", "status": "unreadable", "severity": "error",
                        "detail": f"{unreadable} @entr{'y' if unreadable == 1 else 'ies'} in "
                                  f"{args.bib} could not be parsed (an unbalanced brace, or a key "
                                  "line without its comma); an entry this gate cannot read is an "
                                  "entry it cannot verify"})
    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1

    counts_unreadable = unreadable
    blocking = sum(1 for i in results if i["severity"] == "error")
    if counts_unreadable:
        counts["unreadable"] = counts_unreadable
    if args.strict:
        blocking += sum(1 for i in results if i["severity"] == "warning")
    # A network failure is not a pass. Entries that could not be resolved
    # because the API was unreachable stay unverified, and an unverified
    # bibliography is exactly what this gate exists to refuse. Deliberate
    # offline runs say so with --offline and are reported, not blocked.
    unresolved = sum(1 for i in results if i["status"] in ("unchecked", "unreachable"))
    if unresolved and not args.offline:
        blocking += 1
        results.append({"key": "-", "status": "unverified", "severity": "error",
                        "detail": f"{unresolved} entr{'y' if unresolved == 1 else 'ies'} could not be "
                                  "resolved against arXiv/Crossref; a bibliography this gate could not "
                                  "check does not pass it (pass --offline to report without blocking)"})
        counts["unverified"] = unresolved

    payload = {"verdict": "PASS" if blocking == 0 else "BLOCKED",
               "entries": len(entries), "counts": counts,
               "error_count": blocking, "results": results}

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        # An --offline run resolves nothing, so its headline must not read like a
        # verified bibliography: "PASS: 41 entries; 41 unchecked" is exactly the
        # line someone skims as "the citations are fine".
        verdict = payload["verdict"] + (" (offline: nothing was resolved)" if args.offline else "")
        print(f"{verdict}: {len(entries)} entries; "
              + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
        for item in results:
            if item["severity"] != "ok":
                print(f"  {item['severity'].upper():9s} {item['status']}: "
                      f"{item['key']} — {item['detail']}")
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
