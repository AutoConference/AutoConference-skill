#!/usr/bin/env python3
"""paper_facts.py -- the countable facts about how a paper came to be, from
this kit's own records, for the post-submission survey and the two
statements (owner, 2026-10-03).

  python3 pipeline/paper_facts.py <workspace> [--own-paper]
  python3 pipeline/paper_facts.py <workspace> [--own-paper] --survey

Prints one JSON object. Nothing in it is a guess: a fact the records do not
hold is null, 0 or "unknown" -- survey.md says why that is the right answer.
With --survey it prints the survey's answers instead, in the platform's own
shape, built from the same records with no model call (owner, 2026-10-04:
the paper is not sent to review until the survey is answered, and a model
may be out of quota, or the machine off, before a duty turn comes);
submit-paper.sh sends them the moment the paper is in. The records read:

  state/runner.env                 the owner's settings (AC_MODE, AC_DIRECTION,
                                   AC_HUMAN_INVOLVEMENT, AC_HUMAN_NOTES, ...)
  <workspace>/DIRECTION, MODE,     what the loop recorded when it started the
    SEED                           paper (run-heartbeat.sh write_paper)
  state/ASK_HUMAN.md               the questions the agent put to its owner,
                                   and which were answered under them
  state/answers.md, answers.json   the answers that came from the website
  custom/                          the owner's standing instructions

Python 3.8; no dependencies. Imported by statements.py.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE = os.environ.get("AC_STATE") or os.path.join(ROOT, "state")
CUSTOM = os.path.join(os.path.dirname(os.path.abspath(STATE)), "custom")

# A line under a question that answers it (client.py ANSWERED_HERE).
ANSWERED_HERE = re.compile(r"^\W{0,4}answer(ed)?\W{0,4}:", re.I | re.M)
SECTION = re.compile(r"^## (\S+) — (.+?)\n(.*?)(?=^## |\Z)", re.M | re.S)


def read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def runner_env(key: str) -> str:
    """A setting as the loop reads it: the environment, else the last line
    of state/runner.env that names the key."""
    if os.environ.get(key):
        return os.environ[key]
    found = ""
    for line in read(os.path.join(STATE, "runner.env")).splitlines():
        k, sep, v = line.strip().partition("=")
        if sep and k.strip() == key:
            found = v.strip()
    return found


def own_paper_workspace(ws: str) -> bool:
    real = os.path.realpath(ws)
    own = os.path.realpath(os.path.join(STATE, "own-paper"))
    done = os.path.realpath(os.path.join(STATE, "own-paper-submitted"))
    return real == own or real.startswith(done + os.sep)


def cycle_of(ws: str, own: bool):
    """The conference a workspace is for: work/<cycle>, or
    state/own-paper-submitted/<cycle>; None for an owner's paper not yet in."""
    base = os.path.basename(os.path.realpath(ws).rstrip(os.sep))
    if own and base == "own-paper":
        return None
    return base if re.fullmatch(r"[a-z0-9-]+", base) else None


def created_at(ws: str) -> float:
    """When the workspace began: the oldest of its own files' times. A
    directory's mtime is its last change, not its birth."""
    times = []
    try:
        for n in os.listdir(ws):
            p = os.path.join(ws, n)
            try:
                times.append(os.stat(p).st_mtime)
            except OSError:
                pass
        times.append(os.stat(ws).st_mtime)
    except OSError:
        return 0.0
    return min(times) if times else 0.0


def concerns(cycle, own: bool, title: str, body: str) -> bool:
    """Whether a section of ASK_HUMAN.md is about this paper."""
    text = title + "\n" + body
    if cycle and (cycle in text):
        return True
    if own and re.search(r"your paper \(|own-paper|own paper", text, re.I):
        return True
    return False


def questions_about(cycle, own: bool) -> dict:
    """How many questions the agent put to its owner about this paper, and
    how many were answered: under the question (an `Answer:` line), on the
    website (answers.json records the id), or in state/answers.md (the title
    repeated with "— answered")."""
    text = read(os.path.join(STATE, "ASK_HUMAN.md"))
    if not text:
        return {"asked": 0, "answered": 0, "website": 0}
    import hashlib
    try:
        recorded = json.load(open(os.path.join(STATE, "answers.json"), encoding="utf-8"))
    except (OSError, ValueError):
        recorded = {}
    answered_md = read(os.path.join(STATE, "answers.md"))
    asked = answered = web = 0
    for m in SECTION.finditer(text):
        at, title, body = m.group(1), m.group(2).strip(), m.group(3).strip()
        if not concerns(cycle, own, title, body):
            continue
        asked += 1
        qid = hashlib.sha256((at + "|" + title).encode("utf-8")).hexdigest()[:16]
        on_web = qid in recorded or (title and ("## " + title + " — answered") in answered_md)
        if on_web:
            web += 1
        if on_web or ANSWERED_HERE.search(body):
            answered += 1
    return {"asked": asked, "answered": answered, "website": web}


def standing_instructions() -> list:
    """The owner's instruction files in custom/, by name, never by path."""
    out = []
    try:
        names = sorted(os.listdir(CUSTOM))
    except OSError:
        return out
    for n in names:
        if n == "all.md":
            out.append("every research step")
        elif n == "website.md":
            out.append("written on the website")
        elif n == "review.md":
            out.append("reviewing")
        elif n == "chair.md":
            out.append("chair work")
        else:
            m = re.fullmatch(r"step-(\d+)\.md", n)
            if m:
                out.append("step " + m.group(1))
    return out


def facts(ws: str, own: bool = False) -> dict:
    own = own or own_paper_workspace(ws)
    cycle = cycle_of(ws, own)
    mode = read(os.path.join(ws, "MODE")).strip() or runner_env("AC_MODE")
    if own:
        mode = "owner_paper"
    if mode not in ("owner_paper", "owner_direction", "autonomous"):
        mode = "unknown"
    direction = read(os.path.join(ws, "DIRECTION")).strip() or runner_env("AC_DIRECTION")
    seed = read(os.path.join(ws, "SEED")).strip() or runner_env("AC_SEED_PAPER")
    q = questions_about(cycle, own)
    standing = standing_instructions()
    level = runner_env("AC_HUMAN_INVOLVEMENT")
    channels = []
    if q["asked"]:
        channels.append("question_file")
    if q["website"] or "written on the website" in standing:
        channels.append("website")
    if [s for s in standing if s != "written on the website"]:
        channels.append("instruction_files")
    return {
        "cycle": cycle,
        "own_paper": own,
        "workspace_created_at": int(created_at(ws)) or None,
        # How the paper came about (A14): the owner's paper, their direction,
        # or the agent's own topics.
        "mode": mode,
        "direction": direction[:500] or None,
        "seed_paper": bool(seed),
        "questions_asked": q["asked"],
        "questions_answered": q["answered"],
        "answered_on_website": q["website"],
        "standing_instructions": standing,
        "human_involvement": level if level in ("none", "light", "substantial", "full") else None,
        "human_notes": (runner_env("AC_HUMAN_NOTES")[:2000] or None),
        # Whether the owner confirms each submission on the website or has
        # auto-confirm on is the platform's setting, not this machine's.
        "confirm_mode": "unknown",
        "channels": channels,
        "allowed_dirs": bool(runner_env("AC_ALLOWED_DIRS")),
    }


# ── The survey, from the same records ───────────────────────────────────────

STAGES = ("idea", "direction", "related_work", "method", "experiments", "analysis",
          "writing", "figures", "revision", "submission")
# The pipeline's fifteen steps on the survey's ten stages (WORKFLOW.md's
# table): the stage a step's work belongs to, so an owner's instruction or
# answer at that step counts as guidance there. "direction" has no step; it
# is the owner's setting. 1 idea-discovery -> idea; 2 ablations, 3
# feasibility, 8 the method formally -> method; 4 calibration, 5 the
# experiments, 10 the clean re-run -> experiments; 6 intervals and claims, 14
# the number check -> analysis; 7 plots -> figures; 9 related work ->
# related_work; 11 the paper, 12 its shape -> writing; 13 the case against
# it, then fixes -> revision; 15 submit -> submission.
STEP_STAGE = {1: "idea", 2: "method", 3: "method", 4: "experiments", 5: "experiments", 6: "analysis",
              7: "figures", 8: "method", 9: "related_work", 10: "experiments", 11: "writing",
              12: "writing", 13: "revision", 14: "analysis", 15: "submission"}
STOPPED_AT = re.compile(r"stopped at pipeline step (\d+)/15")
WEB_ANSWER = re.compile(r"^## (.+?) — answered [^\n]*\n(.*?)(?=^## |\Z)", re.M | re.S)


def mtime(path: str) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def scrub(text: str) -> str:
    """A quotation from the records with what must not leave this machine
    taken out: links, addresses, paths, host names."""
    text = re.sub(r"https?://\S+", "[link]", text)
    text = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "[address]", text)
    text = re.sub(r"[A-Za-z]:\\[^\s]+", "[path]", text)
    text = re.sub(r"(?<![\w/])(?:~)?(?:/[A-Za-z0-9_.@-]+){2,}/?", "[path]", text)
    text = re.sub(r"\b(?:[a-z0-9-]+\.)+(?:edu|org|com|net|io|ai|gov|mil|uk|de|cn|jp|fr|ch|ca|au|in|kr|br|nl|se|it|es|ru|eu|info|dev|app|cloud|co|us|tw|hk|sg|nz|il|be|at|dk|fi|no|pl|cz|pt|gr|ie)\b",
                  "[host]", text, flags=re.I)
    return text


def answers_about(cycle, own: bool) -> list:
    """The owner's answers about this paper, as the records hold them: under
    the question (an `Answer:` line) or on the website (state/answers.md;
    answers.json alone when the text was not kept), each with the step the
    question stopped at, when it did."""
    web = {m.group(1).strip(): m.group(2).strip()
           for m in WEB_ANSWER.finditer(read(os.path.join(STATE, "answers.md")))}
    try:
        recorded = json.load(open(os.path.join(STATE, "answers.json"), encoding="utf-8"))
    except (OSError, ValueError):
        recorded = {}
    import hashlib
    out = []
    for m in SECTION.finditer(read(os.path.join(STATE, "ASK_HUMAN.md"))):
        at, title, body = m.group(1), m.group(2).strip(), m.group(3).strip()
        if not concerns(cycle, own, title, body):
            continue
        qid = hashlib.sha256((at + "|" + title).encode("utf-8")).hexdigest()[:16]
        here = ANSWERED_HERE.search(body)
        if here:
            text = re.sub(r"^\W+", "", body[here.end():].strip()).split("\n\n")[0]
        elif title in web:
            text = web[title]
        elif qid in recorded:
            text = ""
        else:
            continue
        st = STOPPED_AT.search(title)
        out.append({"title": title, "text": text, "step": int(st.group(1)) if st else None})
    return out


def custom_files() -> dict:
    """The owner's instruction files: which exist, and when each last changed."""
    out = {"all": False, "website": False, "steps": {}, "mtimes": {}}
    try:
        names = sorted(os.listdir(CUSTOM))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".md"):
            continue
        out["mtimes"][n] = mtime(os.path.join(CUSTOM, n))
        if n == "all.md":
            out["all"] = True
        elif n == "website.md":
            out["website"] = True
        else:
            m = re.fullmatch(r"step-(\d+)\.md", n)
            if m:
                out["steps"][int(m.group(1))] = out["mtimes"][n]
    return out


def overall_of(stages: dict, own: bool) -> int:
    """People's share, 0-4, from the stages: 4 an owner's own paper; 3 a
    person did the method, experiments, analysis, writing, figures or
    revision; 2 the direction was theirs and they guided a stage, or they
    guided three; 1 their direction alone, or one guided stage; 0 nothing."""
    if own:
        return 4
    if any(stages[s] == "did" for s in ("method", "experiments", "analysis", "writing", "figures", "revision")):
        return 3
    guided = sum(1 for s in STAGES if stages[s] in ("guided", "approved"))
    if (stages["direction"] == "did" and guided) or guided >= 3:
        return 2
    if stages["direction"] == "did" or guided:
        return 1
    return 0


def key_moments(answers: list, custom: dict, f: dict, own: bool) -> str:
    """The moments the owner changed the course of the work, quoted from the
    records and scrubbed; "" when the records hold none."""
    lines = []
    if own:
        lines.append("The owner wrote the paper; the agent converted and submitted it.")
    for a in answers:
        where = f" (at step {a['step']}, {STEP_STAGE.get(a['step'], 'a step')})" if a["step"] else ""
        text = scrub(a["text"].replace("\n", " ").strip())[:300] or "(answered on the website)"
        lines.append(f"Owner's answer to \"{scrub(a['title'])[:120]}\"{where}: {text}")
    for n in sorted(custom["steps"]):
        lines.append(f"Standing instruction for step {n} ({STEP_STAGE.get(n, 'a step')}).")
    if custom["all"]:
        lines.append("Standing instructions for every research step.")
    if custom["website"]:
        lines.append("Instructions written on the website.")
    if f.get("human_notes"):
        lines.append("Owner's own note: " + scrub(f["human_notes"].replace("\n", " "))[:500])
    return "\n".join(lines)[:3000]


def survey(ws: str, own: bool = False) -> dict:
    """The survey's answers (src/lib/survey.ts, SurveySchema) from the
    records: never a guess. idea_origin: an owner's paper is owner_paper;
    a direction or seed paper the owner set is owner_direction; nothing set
    is agent (the records cannot tell a direction from a specific idea, so
    owner_idea is never claimed). stages: an owner's paper, people did every
    stage; otherwise none, except direction when the owner set it (did), and
    guided for a stage whose step had a standing instruction (custom/step-N.md,
    or all.md and website.md for every step) or an owner's answer at that
    step. interactions: the questions about this paper and their answers;
    owner_initiated, what the records show -- instruction files written or
    changed while the paper was made, a setting changed on this machine then
    -- a lower bound. owner_read_before_submitting is unknown here: the
    confirmation is the platform's. overall from the stages (overall_of)."""
    f = facts(ws, own)
    own = f["own_paper"]
    created = f["workspace_created_at"] or 0
    answers = answers_about(f["cycle"], own)
    custom = custom_files()
    if own:
        idea = "owner_paper"
        stages = {s: "did" for s in STAGES}
    else:
        idea = "owner_direction" if f["mode"] == "owner_direction" else "agent"
        stages = {s: "none" for s in STAGES}
        if f["mode"] == "owner_direction":
            stages["direction"] = "did"
        guided = set()
        if custom["all"] or custom["website"]:
            guided.update(STEP_STAGE.values())
        for n in custom["steps"]:
            if n in STEP_STAGE:
                guided.add(STEP_STAGE[n])
        for a in answers:
            if a["step"] in STEP_STAGE:
                guided.add(STEP_STAGE[a["step"]])
        for s in guided:
            if stages[s] == "none":
                stages[s] = "guided"
    initiated = sum(1 for t in custom["mtimes"].values() if created and t >= created)
    if created and mtime(os.path.join(STATE, "runner.env")) >= created:
        initiated += 1
    return {
        "idea_origin": idea,
        "stages": stages,
        "interactions": {
            "questions_asked": f["questions_asked"],
            "answers_received": f["questions_answered"],
            "owner_initiated": initiated,
            "channels": list(dict.fromkeys(f["channels"]))[:6],
        },
        "owner_read_before_submitting": "unknown",
        "overall": overall_of(stages, own),
        "key_moments": key_moments(answers, custom, f, own),
    }


def main(argv) -> int:
    own = "--own-paper" in argv
    want_survey = "--survey" in argv
    args = [a for a in argv if a not in ("--own-paper", "--survey")]
    if len(args) != 1:
        print("usage: paper_facts.py <workspace> [--own-paper] [--survey]", file=sys.stderr)
        return 2
    ws = args[0]
    if not os.path.isdir(ws):
        print(f"paper_facts: no such workspace: {ws}", file=sys.stderr)
        return 2
    print(json.dumps(survey(ws, own) if want_survey else facts(ws, own), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
