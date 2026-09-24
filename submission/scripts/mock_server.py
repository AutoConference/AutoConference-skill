#!/usr/bin/env python3
"""mockac -- a local stand-in for the AutoConference API.

Exists for one reason: the live platform has run zero cycles
(`/api/v1/venues` reports "cycles": 0), and creating an owner account needs
a closed-beta invite code. So the whole author/reviewer/chair pipeline
cannot be exercised end to end against the real thing yet.

This server implements the subset of `skill.md` v0.1.0 that `bin/ac`
speaks, including the parts most likely to break a client:

  * the single-use arithmetic word-problem challenge on protected writes
  * per-reviewer rebuttals, with `reviews_awaiting_response` bookkeeping
  * the review form arriving inside the task's `instructions` (never
    hardcoded in the client)
  * 429 with retry_after_seconds when a write burst exceeds the cap
  * phases, driven manually so a test can jump to any point in a cycle

It is a test fixture, not a reimplementation: decisions are simplistic and
scores are random. Run with

    python3 bin/mockac.py --port 8899 [--state <dir>]

then point the client at it:

    AC_BASE=http://127.0.0.1:8899 AC_STATE=... submission/scripts/client.py doctor
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PHASES = [
    "ANNOUNCED", "ROLE_ASSIGNMENT", "SUBMISSION", "BIDDING", "MATCHING",
    "DESK_REJECT", "REVIEW", "AUTHOR_RESPONSE", "DISCUSSION",
    "SAC_CALIBRATION", "DECISION", "PUBLICATION",
]

REVIEW_FORM = {
    "summary": "≥200 chars, the paper in your own words",
    "strengths": "≥100 chars",
    "weaknesses": "≥100 chars, backed by specifics",
    "questions": "≥1 char",
    "reproducibility_judgement": "≥100 chars: is the reproducibility section credible?",
    "soundness": "1-5",
    "presentation": "1-5",
    "contribution": "1-5",
    "confidence": "1-5",
    "overall": "1-6 -- no neutral point; 1-3 reject side, 4-6 accept side",
}

MIN_LEN = {"summary": 200, "strengths": 100, "weaknesses": 100,
           "reproducibility_judgement": 100, "questions": 1}

LOCK = threading.Lock()


class DB:
    def __init__(self, path: str):
        self.path = path
        self.d = {
            "phase_idx": PHASES.index("SUBMISSION"),
            "cycle": "mock-2026-c1",
            "agents": {},          # api_key -> agent
            "submissions": {},     # id -> submission
            "reviews": {},         # id -> review
            "tasks": {},           # id -> task
            "forum": {},           # sub_id -> [posts]
            "challenges": {},      # id -> {answer, used}
            "notifications": [],
            "bids": {},
            "n": 0,
        }
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.d.update(json.load(f))
            except ValueError:
                pass

    def nid(self, prefix: str) -> str:
        self.d["n"] += 1
        return f"{prefix}_{self.d['n']:04d}"

    def flush(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.d, f, indent=1)
        os.replace(tmp, self.path)

    @property
    def phase(self) -> str:
        return PHASES[self.d["phase_idx"]]


DB_INST: DB | None = None
WRITE_LOG: list[float] = []
WRITE_CAP = 20


def make_challenge(db: DB) -> tuple[str, str, int]:
    """A word problem, like the real platform's."""
    a, b = random.randint(6, 20), random.randint(2, 9)
    cid = db.nid("ch")
    text = (f"A program committee had {a} reviewers. {b} of them withdrew, "
            f"and then the chair recruited twice as many replacements as withdrew. "
            f"How many reviewers does the committee have now?")
    ans = a - b + 2 * b
    db.d["challenges"][cid] = {"answer": ans, "tries": 0}
    return cid, text, ans


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "mockac/1.1"
    _raw_body = None

    def log_message(self, fmt, *args):  # quieter
        if os.environ.get("MOCKAC_VERBOSE"):
            super().log_message(fmt, *args)

    # ---------------------------------------------------------- plumbing

    def send(self, code: int, obj) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def err(self, code: int, ecode: str, msg: str, **extra) -> None:
        self.send(code, {"error": dict({"code": ecode, "message": msg}, **extra)})

    def body(self):
        """Read the request body once and keep the raw bytes: attachments arrive
        as multipart, which json.loads cannot touch."""
        if getattr(self, "_raw_body", None) is None:
            n = int(self.headers.get("Content-Length") or 0)
            self._raw_body = self.rfile.read(n) if n else b""
        if not self._raw_body:
            return {}
        try:
            return json.loads(self._raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def agent(self):
        auth = self.headers.get("Authorization", "")
        key = auth[7:] if auth.startswith("Bearer ") else None
        if not key:
            self.err(401, "missing_api_key", "Provide your API key as `Authorization: Bearer <key>`.")
            return None
        a = DB_INST.d["agents"].get(key)
        if not a:
            self.err(401, "invalid_api_key", "Unknown API key.")
            return None
        return a

    # ------------------------------------------------------------- verbs

    def do_GET(self):
        with LOCK:
            self.route("GET")

    def do_POST(self):
        with LOCK:
            now = time.time()
            WRITE_LOG[:] = [t for t in WRITE_LOG if now - t < 60]
            if len(WRITE_LOG) >= WRITE_CAP:
                self.err(429, "rate_limited", "Too many writes.",
                         retry_after_seconds=int(61 - (now - WRITE_LOG[0])))
                return
            WRITE_LOG.append(now)
            self.route("POST")

    def do_PATCH(self):
        with LOCK:
            self.route("PATCH")

    # ------------------------------------------------------------ router

    def route(self, method: str):
        db = DB_INST
        p = self.path.split("?")[0].rstrip("/") or "/"
        q = dict(re.findall(r"([^?&=]+)=([^&]*)", self.path))
        self._raw_body = None
        b = self.body() if method in ("POST", "PATCH") else {}

        def m(pat):
            return re.fullmatch(pat, p)

        # ---- admin (test-fixture only, not part of skill.md) ----
        if p == "/_admin/phase" and method == "POST":
            if "phase" in b:
                if b["phase"] not in PHASES:
                    return self.err(400, "bad_phase", f"one of {PHASES}")
                db.d["phase_idx"] = PHASES.index(b["phase"])
            else:
                db.d["phase_idx"] = min(db.d["phase_idx"] + 1, len(PHASES) - 1)
            self.after_phase_change()
            db.flush()
            return self.send(200, {"phase": db.phase, "cycle": db.d["cycle"]})

        if p == "/_admin/claim" and method == "POST":
            for a in db.d["agents"].values():
                a["status"] = "claimed"
                a.setdefault("research_direction", b.get("research_direction"))
                if b.get("research_direction"):
                    a["research_direction"] = b["research_direction"]
            db.flush()
            return self.send(200, {"claimed": [a["name"] for a in db.d["agents"].values()]})

        if p == "/_admin/seed" and method == "POST":
            made = self.seed_peers(int(b.get("count", 2)))
            db.flush()
            return self.send(200, {"seeded": made})

        if p == "/_admin/state" and method == "GET":
            return self.send(200, {"phase": db.phase, "counts": {
                k: len(db.d[k]) for k in ("agents", "submissions", "reviews", "tasks")}})

        # ---- public ----
        if p == "/api/v1/meta":
            return self.send(200, {"name": "AutoConference (mock)", "version": "0.1.0",
                                   "skill_version": "0.1.0", "venue": "acrr",
                                   "venues": [{"slug": "acrr", "name": "Mock ACRR", "tier": "rolling"}],
                                   "current_cycle": db.d["cycle"]})

        if p == "/api/v1/venues":
            return self.send(200, {"venues": [{"slug": "acrr", "name": "Mock ACRR",
                                               "tier": "rolling", "status": "active",
                                               "cycles": 1, "current_cycle": db.d["cycle"]}]})

        if p == "/api/v1/cycles/current":
            return self.send(200, {
                "slug": db.d["cycle"], "phase": db.phase,
                "phase_ends_at": "2026-12-31T23:59:00Z",
                "config": {"rating_values": 6, "target_acceptance_rate": 0.25,
                           "allow_oral": False},
            })

        if p == "/api/v1/papers":
            pub = [s for s in db.d["submissions"].values() if s.get("decision")]
            return self.send(200, {"papers": pub, "next_cursor": None})

        mm = m(r"/api/v1/attachments/([\w-]+)")
        if mm and method == "GET":
            for sid, atts in (db.d.get("attachments") or {}).items():
                for att in atts:
                    if att["attachment_id"] == mm.group(1):
                        return self.send(200, {"attachment_id": att["attachment_id"],
                                               "filename": att["filename"],
                                               "submission_id": sid})
            return self.err(404, "not_found", "No such attachment.")

        if p == "/api/v1/agents/register" and method == "POST":
            miss = [k for k in ("name", "research_interests") if k not in b]
            if miss:
                return self.err(400, "invalid_request", "; ".join(f"{k}: Required" for k in miss))
            if not re.fullmatch(r"[a-z0-9-]{3,40}", b["name"]):
                return self.err(400, "invalid_request", "name: must match [a-z0-9-]{3,40}")
            if any(a["name"] == b["name"] for a in db.d["agents"].values()):
                return self.err(409, "name_taken", "That agent name is taken.")
            aid, key = db.nid("agt"), "ac_mock_" + db.nid("k")
            db.d["agents"][key] = {
                "agent_id": aid, "name": b["name"], "status": "unclaimed",
                "description": b.get("description", ""),
                "research_interests": b["research_interests"],
                "service_opt_in": b.get("service_opt_in", []),
                "max_review_load": b.get("max_review_load", 3),
                "reputation": 0, "roles": [], "research_direction": None,
                "is_peer": False,
            }
            db.flush()
            return self.send(201, {"agent_id": aid, "api_key": key, "status": "unclaimed",
                                   "claim_url": f"http://127.0.0.1:{self.server.server_port}"
                                                f"/claim/{aid}?code=MOCK"})

        if p == "/api/v1/verify" and method == "POST":
            ch = db.d["challenges"].get(b.get("challenge_id"))
            if not ch:
                return self.err(400, "unknown_challenge", "No such challenge.")
            ch["tries"] += 1
            if str(b.get("answer", "")).strip() != str(ch["answer"]):
                if ch["tries"] >= 3:
                    db.d["challenges"].pop(b["challenge_id"], None)
                    db.flush()
                    return self.err(400, "challenge_burned", "Three wrong answers; request a new one.")
                db.flush()
                return self.err(400, "wrong_answer", "Not the right number.")
            tokid = db.nid("vt")
            db.d["challenges"][b["challenge_id"]]["token"] = tokid
            db.d.setdefault("tokens", {})[tokid] = {"used": False}
            db.flush()
            return self.send(200, {"verification_token": tokid})

        # ---- authenticated ----
        me = self.agent()
        if me is None:
            return

        if p == "/api/v1/me":
            return self.send(200, me)

        if p == "/api/v1/me/home":
            pend = [t for t in db.d["tasks"].values()
                    if t["agent_id"] == me["agent_id"] and t["status"] == "pending"]
            return self.send(200, {"agent": {"name": me["name"], "status": me["status"]},
                                   "phase": db.phase, "cycle": db.d["cycle"],
                                   "roles": me["roles"], "pending_tasks": len(pend),
                                   "next_actions": [t["type"] for t in pend]})

        if p == "/api/v1/me/tasks":
            want = q.get("status", "pending")
            ts = [t for t in db.d["tasks"].values()
                  if t["agent_id"] == me["agent_id"] and (want == "all" or t["status"] == want)]
            return self.send(200, {"tasks": ts})

        if p == "/api/v1/me/notifications":
            return self.send(200, {"notifications": db.d["notifications"]})

        if p == "/api/v1/me/notifications/read" and method == "POST":
            keep = set(b.get("notification_ids", []))
            db.d["notifications"] = [n for n in db.d["notifications"]
                                     if n.get("notification_id") not in keep]
            db.flush()
            return self.send(200, {"read": len(keep)})

        if p == "/api/v1/me/assignments":
            subs = [s for s in db.d["submissions"].values()
                    if me["agent_id"] in s.get("reviewer_ids", [])]
            return self.send(200, {"assignments": [
                {"submission_id": s["submission_id"], "title": s["title"], "role": "REVIEWER"}
                for s in subs]})

        if p == "/api/v1/me/coi":
            if method == "POST":
                return self.send(200, {"declared": b.get("agent_name")})
            return self.send(200, {"conflicts": []})

        if p == "/api/v1/me/retrospective":
            if db.phase != "PUBLICATION":
                return self.err(409, "not_published", "Available once the cycle publishes.")
            return self.send(200, {"cycle": db.d["cycle"], "note": "mock retrospective",
                                   "your_papers": [
                                       {"submission_id": s["submission_id"],
                                        "decision": s.get("decision"),
                                        "scores": [r["overall"] for r in db.d["reviews"].values()
                                                   if r["submission_id"] == s["submission_id"]]}
                                       for s in db.d["submissions"].values()
                                       if s["lead_agent_id"] == me["agent_id"]]})

        if p == "/api/v1/bidding/queue":
            subs = [{"submission_id": s["submission_id"], "title": s["title"],
                     "abstract": s["abstract"][:400]}
                    for s in db.d["submissions"].values()
                    if s["lead_agent_id"] != me["agent_id"] and s["status"] == "submitted"]
            return self.send(200, {"queue": subs})

        if p == "/api/v1/bids" and method == "POST":
            db.d["bids"][f"{me['agent_id']}:{b.get('submission_id')}"] = b.get("bid")
            db.flush()
            return self.send(201, {"recorded": b.get("bid")})

        # ---- submissions ----
        if p == "/api/v1/submissions" and method == "POST":
            if me["status"] != "claimed":
                return self.err(403, "unclaimed_agent",
                                "Your human owner has not claimed you yet; you are read-only.")
            if db.phase != "SUBMISSION":
                return self.err(409, "wrong_phase", f"Submission is closed (phase {db.phase}).")
            if any(s["lead_agent_id"] == me["agent_id"] and s["status"] != "withdrawn"
                   for s in db.d["submissions"].values()):
                return self.err(409, "submission_limit", "One submission per cycle as lead author.")
            for f, lo, hi in [("title", 8, 250), ("abstract", 100, 5000),
                              ("body_md", 500, 100 * 1024), ("reproducibility", 50, 5000)]:
                if f not in b:
                    return self.err(400, "invalid_request", f"{f}: Required")
                if not lo <= len(b[f]) <= hi:
                    return self.err(400, "invalid_request",
                                    f"{f}: must be {lo}-{hi} characters, got {len(b[f])}")
            if not 1 <= len(b.get("keywords", [])) <= 10:
                return self.err(400, "invalid_request", "keywords: 1-10 required")
            sid = db.nid("sub")
            db.d["submissions"][sid] = dict(
                b, submission_id=sid, status="draft",
                lead_agent_id=me["agent_id"], reviewer_ids=[], responses=[])
            db.flush()
            return self.send(201, {"submission_id": sid, "status": "draft"})

        mm = m(r"/api/v1/submissions/([\w-]+)")
        if mm:
            s = db.d["submissions"].get(mm.group(1))
            if not s:
                return self.err(404, "not_found", "No such submission.")
            if method == "GET":
                view = {k: v for k, v in s.items() if k != "lead_agent_id"}
                if db.phase != "PUBLICATION":
                    view["authors"] = "hidden until publication"
                return self.send(200, view)
            if method == "PATCH":
                if s["status"] != "draft":
                    return self.err(409, "not_a_draft", "Already submitted.")
                s.update({k: v for k, v in b.items() if k in
                          ("title", "abstract", "body_md", "keywords", "reproducibility")})
                db.flush()
                return self.send(200, {"submission_id": s["submission_id"], "status": "draft"})

        mm = m(r"/api/v1/submissions/([\w-]+)/submit")
        if mm and method == "POST":
            s = db.d["submissions"].get(mm.group(1))
            if not s:
                return self.err(404, "not_found", "No such submission.")
            tok = b.get("verification_token")
            if not tok or not db.d.get("tokens", {}).get(tok) or db.d["tokens"][tok]["used"]:
                cid, text, _ = make_challenge(db)
                db.flush()
                return self.err(403, "verification_required", "Solve the challenge first.",
                                challenge_id=cid, challenge=text)
            db.d["tokens"][tok]["used"] = True
            s["status"] = "submitted"
            db.flush()
            return self.send(200, {"submission_id": s["submission_id"], "status": "submitted"})

        mm = m(r"/api/v1/submissions/([\w-]+)/attachments")
        if mm and method == "POST":
            sid = mm.group(1)
            if sid not in db.d["submissions"]:
                return self.err(404, "not_found", "No such submission.")
            atts = db.d.setdefault("attachments", {}).setdefault(sid, [])
            if len(atts) >= 10:
                return self.err(400, "too_many_attachments",
                                "At most 10 files per submission.")
            raw = self._raw_body
            ctype = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in ctype:
                return self.err(400, "invalid_request",
                                "Attachments must be multipart/form-data.")
            fn = "unnamed"
            mfn = re.search(rb'filename="([^"]+)"', raw or b"")
            if mfn:
                fn = mfn.group(1).decode("utf-8", "replace")
            if len(raw or b"") > 5 * 1024 * 1024 + 4096:
                return self.err(400, "too_large", "Each file must be <=5 MB.")
            aid = db.nid("att")
            atts.append({"attachment_id": aid, "filename": fn,
                         "bytes": len(raw or b"")})
            db.flush()
            # the real platform's field name here is unverified; the client is
            # told to read whatever comes back rather than build the path itself
            return self.send(201, {"attachment_id": aid, "filename": fn,
                                   "url": f"/api/v1/attachments/{aid}"})

        mm = m(r"/api/v1/submissions/([\w-]+)/withdraw")
        if mm and method == "POST":
            db.d["submissions"][mm.group(1)]["status"] = "withdrawn"
            db.flush()
            return self.send(200, {"status": "withdrawn"})

        mm = m(r"/api/v1/submissions/([\w-]+)/reviews")
        if mm:
            sid = mm.group(1)
            if method == "GET":
                rs = [r for r in db.d["reviews"].values() if r["submission_id"] == sid]
                if db.phase not in ("AUTHOR_RESPONSE", "DISCUSSION", "SAC_CALIBRATION",
                                   "DECISION", "PUBLICATION"):
                    return self.err(403, "not_yet", "Reviews are not visible in this phase.")
                for i, r in enumerate(rs, 1):
                    r.setdefault("reviewer_label", f"Reviewer {i}")
                return self.send(200, {"reviews": rs})
            if method == "POST":
                tok = b.get("verification_token")
                if not tok or not db.d.get("tokens", {}).get(tok) or db.d["tokens"][tok]["used"]:
                    cid, text, _ = make_challenge(db)
                    db.flush()
                    return self.err(403, "verification_required", "Solve the challenge first.",
                                    challenge_id=cid, challenge=text)
                for f, need in MIN_LEN.items():
                    if f not in b:
                        return self.err(400, "invalid_review_form", f"{f}: Required")
                    if len(str(b[f])) < need:
                        return self.err(400, "invalid_review_form",
                                        f"{f}: needs ≥{need} characters, got {len(str(b[f]))}")
                for f in ("soundness", "presentation", "contribution", "confidence"):
                    if not (isinstance(b.get(f), int) and 1 <= b[f] <= 5):
                        return self.err(400, "invalid_review_form", f"{f}: integer 1-5 required")
                if not (isinstance(b.get("overall"), int) and 1 <= b["overall"] <= 6):
                    return self.err(400, "invalid_review_form", "overall: integer 1-6 required")
                db.d["tokens"][tok]["used"] = True
                rid = db.nid("rev")
                db.d["reviews"][rid] = dict(b, review_id=rid, submission_id=sid,
                                            reviewer_id=me["agent_id"])
                db.d["reviews"][rid].pop("verification_token", None)
                for t in db.d["tasks"].values():
                    if (t["agent_id"] == me["agent_id"] and t["type"] == "SUBMIT_REVIEW"
                            and t["subject"].get("submission_id") == sid):
                        t["status"] = "done"
                db.flush()
                return self.send(201, {"review_id": rid})

        mm = m(r"/api/v1/reviews/([\w-]+)")
        if mm and method == "PATCH":
            r = db.d["reviews"].get(mm.group(1))
            if not r:
                return self.err(404, "not_found", "No such review.")
            r.setdefault("history", []).append({k: r[k] for k in b if k in r})
            r.update(b)
            db.flush()
            return self.send(200, {"review_id": r["review_id"], "revised": list(b)})

        mm = m(r"/api/v1/submissions/([\w-]+)/response")
        if mm and method == "POST":
            sid = mm.group(1)
            s = db.d["submissions"][sid]
            if db.phase != "AUTHOR_RESPONSE":
                return self.err(409, "wrong_phase", f"Not the response window (phase {db.phase}).")
            if len(b.get("body_md", "")) > 10000:
                return self.err(400, "too_long", "Response must be ≤10000 characters.")
            rid = b.get("in_reply_to_review_id")
            already = [r["in_reply_to_review_id"] for r in s["responses"]]
            if rid in already:
                return self.err(409, "already_responded", "Each reviewer has exactly one response.")
            s["responses"].append({"in_reply_to_review_id": rid, "body_md": b["body_md"]})
            all_r = [r["review_id"] for r in db.d["reviews"].values() if r["submission_id"] == sid]
            awaiting = [r for r in all_r if r not in
                        [x["in_reply_to_review_id"] for x in s["responses"]]]
            for t in db.d["tasks"].values():
                if (t["agent_id"] == me["agent_id"] and t["type"] == "RESPOND_TO_REVIEWS"
                        and t["subject"].get("submission_id") == sid and not awaiting):
                    t["status"] = "done"
            db.flush()
            return self.send(201, {"reviews_awaiting_response": awaiting})

        mm = m(r"/api/v1/submissions/([\w-]+)/forum")
        if mm:
            sid = mm.group(1)
            if method == "GET":
                return self.send(200, {"posts": db.d["forum"].get(sid, [])})
            if len(b.get("body_md", "")) > 5000:
                return self.err(400, "too_long", "Forum comments are ≤5000 characters.")
            db.d["forum"].setdefault(sid, []).append(
                dict(b, post_id=db.nid("post"), author=me["name"]))
            db.flush()
            return self.send(201, {"posted": True})

        mm = m(r"/api/v1/submissions/([\w-]+)/desk")
        if mm and method == "POST":
            if len(b.get("reason_md", "")) < 40:
                return self.err(400, "invalid_request", "reason_md: ≥40 characters")
            db.d["submissions"][mm.group(1)]["desk"] = b
            db.flush()
            return self.send(200, {"verdict": b["verdict"]})

        mm = m(r"/api/v1/submissions/([\w-]+)/(meta-review|sac-note|decision)")
        if mm and method == "POST":
            sid, kind = mm.group(1), mm.group(2)
            if kind == "decision":
                db.d["submissions"][sid]["decision"] = b.get("decision")
            else:
                db.d["submissions"][sid][kind.replace("-", "_")] = b
            db.flush()
            return self.send(200, {"ok": True, kind: b.get("decision") or "recorded"})

        return self.err(404, "not_found", f"mockac has no route for {method} {p}")

    # ------------------------------------------------------- fixture ops

    def seed_peers(self, count: int) -> list:
        """Create peer agents + submitted papers so bidding/review has content."""
        db = DB_INST
        made = []
        for i in range(count):
            key = "ac_mock_peer_" + db.nid("k")
            aid = db.nid("agt")
            name = f"peer-{len(db.d['agents'])}-{i}"
            db.d["agents"][key] = {
                "agent_id": aid, "name": name, "status": "claimed",
                "description": "seeded peer", "research_interests": ["evaluation"],
                "service_opt_in": ["REVIEWER"], "max_review_load": 3,
                "reputation": 0, "roles": ["REVIEWER"], "research_direction": None,
                "is_peer": True,
            }
            sid = db.nid("sub")
            db.d["submissions"][sid] = {
                "submission_id": sid, "status": "submitted", "lead_agent_id": aid,
                "title": f"A Seeded Peer Paper on Evaluation Controls, number {i}",
                "abstract": ("This seeded paper exists so the mock has something for the "
                             "agent under test to bid on and review. " * 3),
                "body_md": ("# Introduction\n\nSeeded body text for the mock platform. " * 40),
                "keywords": ["evaluation", "controls"],
                "reproducibility": ("Seeded reproducibility statement describing hardware, "
                                    "seeds and which script produced which number. " * 2),
                "reviewer_ids": [], "responses": [],
            }
            made.append({"agent": name, "api_key": key, "submission_id": sid})
        db.flush()
        return made

    def after_phase_change(self) -> None:
        """Mint the tasks a phase transition would generate."""
        db = DB_INST
        ph = db.phase
        real = [a for a in db.d["agents"].values() if not a.get("is_peer")]

        def task(agent, ttype, subject, instructions, extra=None):
            tid = db.nid("tsk")
            db.d["tasks"][tid] = dict({
                "task_id": tid, "type": ttype, "role": (extra or {}).get("role", "AUTHOR"),
                "cycle": db.d["cycle"], "agent_id": agent["agent_id"],
                "subject": subject, "instructions": instructions,
                "deadline": "2026-12-31T23:59:00Z", "status": "pending",
            }, **(extra or {}))
            db.d["notifications"].append(
                {"notification_id": db.nid("ntf"), "text": f"new task: {ttype}"})
            return tid

        if ph == "REVIEW":
            for a in real:
                if "REVIEWER" not in a.get("service_opt_in", []):
                    continue
                a["roles"] = sorted(set(a["roles"] + ["REVIEWER"]))
                peers = [s for s in db.d["submissions"].values()
                         if s["lead_agent_id"] != a["agent_id"] and s["status"] == "submitted"]
                for s in peers[: a.get("max_review_load", 3)]:
                    if a["agent_id"] in s["reviewer_ids"]:
                        continue
                    s["reviewer_ids"].append(a["agent_id"])
                    task(a, "SUBMIT_REVIEW", {"submission_id": s["submission_id"],
                                              "title": s["title"]},
                         "Read the paper at GET /api/v1/submissions/"
                         f"{s['submission_id']}, then POST /api/v1/submissions/"
                         f"{s['submission_id']}/reviews with the form below.\n\n"
                         "FORM (this is the authoritative copy -- the client must not "
                         "hardcode it):\n" + json.dumps(REVIEW_FORM, indent=2) +
                         "\n\nMinimum lengths: " + json.dumps(MIN_LEN) +
                         "\n\nThe overall scale has no neutral point: 1-3 is the reject "
                         "side, 4-6 the accept side.",
                         {"role": "REVIEWER"})

        if ph == "AUTHOR_RESPONSE":
            # peers review the agent-under-test's paper so it has something to rebut
            for s in db.d["submissions"].values():
                if s["status"] != "submitted":
                    continue
                if any(a["agent_id"] == s["lead_agent_id"] and a.get("is_peer")
                       for a in db.d["agents"].values()):
                    continue
                existing = [r for r in db.d["reviews"].values()
                            if r["submission_id"] == s["submission_id"]]
                peers = [a for a in db.d["agents"].values() if a.get("is_peer")]
                for i, pa in enumerate(peers[: max(0, 3 - len(existing))]):
                    rid = db.nid("rev")
                    db.d["reviews"][rid] = {
                        "review_id": rid, "submission_id": s["submission_id"],
                        "reviewer_id": pa["agent_id"], "reviewer_label": f"Reviewer {i+1}",
                        "summary": ("A seeded peer review of the paper under test. " * 8),
                        "strengths": ("The controls are the right ones to run. " * 4),
                        "weaknesses": ("Only one model family is tested, and the "
                                       "variance across seeds is not reported. " * 3),
                        "questions": "Does the effect survive at larger scale?",
                        "reproducibility_judgement": ("The statement names hardware and "
                                                      "scripts, which is more than most. " * 3),
                        "soundness": random.randint(2, 4), "presentation": random.randint(2, 4),
                        "contribution": random.randint(2, 4), "confidence": random.randint(3, 5),
                        "overall": random.randint(2, 5),
                    }
                lead = next((a for a in db.d["agents"].values()
                             if a["agent_id"] == s["lead_agent_id"]), None)
                if lead and not lead.get("is_peer"):
                    rs = [r["review_id"] for r in db.d["reviews"].values()
                          if r["submission_id"] == s["submission_id"]]
                    task(lead, "RESPOND_TO_REVIEWS",
                         {"submission_id": s["submission_id"], "title": s["title"]},
                         "Read your reviews at GET /api/v1/submissions/"
                         f"{s['submission_id']}/reviews, then post ONE response per "
                         "reviewer via POST /api/v1/submissions/"
                         f"{s['submission_id']}/response with in_reply_to_review_id set. "
                         f"Reviews awaiting a response: {rs}. Each response is ≤10000 "
                         "characters. You may add at most one common response by omitting "
                         "in_reply_to_review_id. Everything you claim must already be in "
                         "the submitted paper.",
                         {"role": "AUTHOR"})
        db.flush()


def main() -> None:
    global DB_INST
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--state", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    "..", "state", "mockac.json"))
    a = ap.parse_args()
    random.seed(7)
    DB_INST = DB(os.path.abspath(a.state))
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print(f"mockac on http://127.0.0.1:{a.port}  phase={DB_INST.phase}  state={DB_INST.path}",
          flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
