#!/usr/bin/env python3
"""watch -- what your agent is doing, live, in this terminal.

    pipeline/watch.py            its status, then each step as it happens
    pipeline/watch.py --steps    the same, every step shown in full
    pipeline/watch.py --status   one line: what it is doing now

./ac opens this ("Watch it work"), and so does setup once the agent is running
(owner, 2026-10-03: never leave an owner unsure what their agent is doing or
what it did). By default each step is one line -- what it read, ran, edited,
said. Press d to show every step in full: its thinking, each command's input
and what came back, every edit as a diff. t opens a conversation with it, q
leaves. Leaving changes nothing: the agent runs in the background either way.

It reads state/logs/live.jsonl, which the loop (run-heartbeat.sh) and every
model turn (render_stream.py) write as they go. The complete record of each
turn is the day's log, state/logs/heartbeat-*.log.
"""
import json
import os
import re
import select
import shutil
import sys
import time
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE = os.path.join(ROOT, "state")
LIVE = os.environ.get("AC_LIVE_FILE") or os.path.join(STATE, "logs", "live.jsonl")

COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR and text else text


def bold(t): return paint("1", t)
def dim(t): return paint("2", t)
def red(t): return paint("31", t)
def green(t): return paint("32", t)
def amber(t): return paint("33", t)
def cyan(t): return paint("36", t)


def width() -> int:
    return max(40, shutil.get_terminal_size((100, 24)).columns)


def clip(text: str, n: int) -> str:
    text = text.replace("\t", " ")
    return text if len(text) <= n else text[: max(0, n - 1)] + "…"


STEP_NAMES = {
    1: "ideas and a plan", 2: "baselines and ablations", 3: "does the plan fit this machine",
    4: "sizing the model budget", 5: "running the experiments", 6: "analysing the results", 7: "plots",
    8: "the method, formally", 9: "related work", 10: "re-running to check every number",
    11: "writing the paper", 12: "checking its shape", 13: "arguing against it, then fixing",
    14: "tracing every number", 15: "submitting",
}


def label_words(label: str) -> str:
    """What a turn is for, from the label the loop gave it."""
    m = re.match(r"paper step (\d+)/15", label or "")
    if m:
        n = int(m.group(1))
        return f"its paper, step {n} of 15 ({STEP_NAMES.get(n, '')})"
    return {
        "duties": "its tasks", "machine": "describing this machine", "own-paper": "preparing your paper",
        "reflect": "reading what its reviewers said", "research": "research", "loop": "",
    }.get(label or "", label or "")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False


def loop_pid():
    try:
        with open(os.path.join(STATE, "heartbeat.pid")) as f:
            pid = int(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return pid if alive(pid) else None


def read_events(path: str, last: int = 400) -> list:
    """The file's last `last` events (and its previous file's, if this one is new)."""
    out = deque(maxlen=last)
    for p in (path + ".1", path):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(ev, dict):
                        out.append(ev)
        except OSError:
            continue
    return list(out)


def hhmm(t) -> str:
    try:
        return time.strftime("%H:%M", time.localtime(float(t)))
    except (TypeError, ValueError):
        return "     "


def when(t: float) -> str:
    """A time ahead, as its owner reads it: HH:MM, with the day when it is
    not within the next 20 hours."""
    lt = time.localtime(t)
    return hhmm(t) if t - time.time() <= 20 * 3600 else f"{time.strftime('%b', lt)} {lt.tm_mday} {hhmm(t)}"


def ago(seconds: float) -> str:
    m = int(seconds // 60)
    return "under a minute" if m < 1 else f"{m} min" if m < 90 else f"{m // 60} h {m % 60} min"


def open_questions() -> int:
    """Its questions to you that are not answered yet (client.py's own count)."""
    try:
        sys.path.insert(0, os.path.join(ROOT, "submission", "scripts"))
        import client  # noqa: E402

        return len(client.questions())
    except Exception:
        return 0


# KIT-015: the model is not there for now (state/model_blocked, by the loop).
WHY = {
    "limit": "usage limit reached",
    "credit": "no API credit left",
    "signin": "its CLI is signed out",
    "connection": "the connection dropped",
    "server": "the model server is not answering",
}
FIX = {
    "limit": "It goes on by itself then. Sooner: raise the limit, or pick another model (./ac, Model).",
    "credit": "Add API credit, or pick another model (./ac, Model).",
    "signin": "Sign its CLI in again on this machine: {signin}",
    "connection": "It tries again by itself.",
    "server": "Start the model server on this machine.",
}
SIGNIN = {"claude": "claude auth login", "codex": "codex login", "gemini": "gemini (then /auth)", "opencode": "opencode auth login"}


def backend() -> str:
    """The agent CLI it runs on (state/runner.env), or ""."""
    try:
        for line in open(os.path.join(STATE, "runner.env")):
            if line.startswith("AC_BACKEND="):
                return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return ""


def block_fix(why: str) -> str:
    """What its owner can do while its model is out, in a sentence."""
    return FIX.get(why, FIX["server"]).format(signin=SIGNIN.get(backend(), "its CLI's sign-in command"))


def model_block():
    """(back, why) while the model is not there, else None: when it should be
    back (the block's 4th field), not the loop's next try."""
    try:
        parts = open(os.path.join(STATE, "model_blocked")).read().split()
        retry, why = int(parts[0]), parts[1] if len(parts) > 1 else "server"
        back = int(parts[3]) if len(parts) > 3 else retry
    except (OSError, ValueError, IndexError):
        return None
    return (max(back, retry), why) if retry > time.time() else None


def papers_running() -> list:
    """(cycle, step) for each paper whose steps are running in the background."""
    out = []
    work = os.path.join(ROOT, "work")
    try:
        cycles = sorted(os.listdir(work))
    except OSError:
        return out
    for c in cycles:
        try:
            with open(os.path.join(work, c, "pipeline.pid")) as f:
                pid = int(f.read().split()[0])
        except (OSError, ValueError, IndexError):
            continue
        if not alive(pid):
            continue
        try:
            with open(os.path.join(work, c, "pipeline.next")) as f:
                step = int(f.read().strip() or 1)
        except (OSError, ValueError):
            step = 0
        out.append((c, step))
    return out


def now_line(events: list) -> str:
    """What it is doing right now, in a few words."""
    if loop_pid() is None:
        return amber("stopped") + dim(" · start it from ./ac")
    now = time.time()
    blocked = model_block()
    if blocked:
        until, why = blocked
        return amber(f"its model is out ({WHY.get(why, WHY['server'])}) until {when(until)}; tasks wait")
    turns = {}
    for ev in events:
        if ev.get("kind") == "start":
            turns[ev.get("pid")] = ev
        elif ev.get("kind") == "end":
            turns.pop(ev.get("pid"), None)
    working = [ev for pid, ev in turns.items() if isinstance(pid, int) and alive(pid)]
    parts = []
    for ev in working:
        what = label_words(ev.get("label", "")) or "a task"
        parts.append(f"working on {what} ({ev.get('text', 'its CLI')}, {ago(now - float(ev.get('t', now)))} so far)")
    if not any(str(ev.get("label", "")).startswith("paper step") for ev in working):
        for _cycle, step in papers_running():
            parts.append(f"writing its paper: step {step} of 15 ({STEP_NAMES.get(step, '')})" if step else "writing its paper")
    nap = None
    for ev in reversed(events):
        if ev.get("kind") == "nap":
            try:
                nap = float(ev.get("text"))
            except (TypeError, ValueError):
                nap = None
            break
        if ev.get("kind") == "status" and ev.get("label") == "loop" and not str(ev.get("text", "")).startswith("paper "):
            break  # the loop is awake: no nap pending
    if parts:
        tail = f"; it looks for new tasks at {hhmm(nap)}" if nap and nap > now else ""
        return green("; ".join(parts)) + dim(tail)
    if nap and nap > now:
        return f"waiting; it looks for work again at {hhmm(nap)} (in {ago(nap - now)})"
    for ev in reversed(events):
        if ev.get("kind") == "status":
            return status_words(ev.get("text", "")) or "running"
    return "running"


def status_words(text: str) -> str:
    """The loop's own line, as its owner would say it; "" to leave it out."""
    m = re.match(r"(\d+) unhandled task\(s\); waking (\S+)", text)
    if m:
        n = int(m.group(1))
        return f"{n} {'task' if n == 1 else 'tasks'} to do; {m.group(2)} is on it"
    if text == "inbox empty; sleeping":
        return "nothing to do right now"
    if text == "no cycle open; sleeping":
        return "no conference is open; nothing to do"
    if text.startswith("phase: "):
        return ""
    m = re.match(r"turn done \(exit (\d+)\)", text)
    if m:
        return "✓ done" if m.group(1) == "0" else f"✗ ended with an error (exit {m.group(1)}); the day's log in state/logs/ has it"
    m = re.match(r"paper (\S+): pipeline step (\d+)/15$", text)
    if m:
        n = int(m.group(2))
        return f"its paper: step {n} of 15, {STEP_NAMES.get(n, '')}"
    return text


def done_words(text: str) -> str:
    """A turn's [done] line, e.g. "6 model calls · 41 s · 41.2k tokens in, 2.1k out · $0.52"."""
    kv = dict(re.findall(r"(\w+)=(\S+)", text))

    def k(n):
        try:
            n = int(float(n))
        except ValueError:
            return n
        return f"{n / 1000:.1f}k" if n >= 1000 else str(n)

    parts = []
    if kv.get("turns"):
        parts.append(f"{kv['turns']} model calls")
    if kv.get("duration_ms"):
        try:
            parts.append(f"{int(float(kv['duration_ms']) / 1000)} s")
        except ValueError:
            pass
    tin, tout = kv.get("tokens_in") or kv.get("input_tokens"), kv.get("tokens_out") or kv.get("output_tokens")
    if tin and tout:
        parts.append(f"{k(tin)} tokens in, {k(tout)} out")
    if kv.get("cost_usd") and kv["cost_usd"] not in ("0", "0.0", "None"):
        parts.append(f"${kv['cost_usd']}")
    return " · ".join(parts) or text


class View:
    def __init__(self, steps: bool):
        self.steps = steps
        self.label = None

    def out(self, line: str = "") -> None:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    def block(self, lead: str, text: str, keep: int, style=dim) -> None:
        """A multi-line block under its step, at most `keep` lines."""
        lines = text.rstrip("\n").split("\n")
        for i, ln in enumerate(lines[:keep]):
            self.out(" " * 9 + (lead if i == 0 else " " * len(lead)) + style(ln))
        if len(lines) > keep:
            self.out(" " * 9 + " " * len(lead) + dim(f"… {len(lines) - keep} more lines in the day's log"))

    def diff(self, inp: dict) -> bool:
        """An edit, shown as one: lines out in red, lines in in green."""
        old, new = inp.get("old_string"), inp.get("new_string")
        if isinstance(old, str) and isinstance(new, str):
            for ln in old.split("\n")[:20]:
                self.out(" " * 11 + red("- " + ln))
            for ln in new.split("\n")[:20]:
                self.out(" " * 11 + green("+ " + ln))
            return True
        content = inp.get("content")
        if isinstance(content, str):
            lines = content.split("\n")
            for ln in lines[:20]:
                self.out(" " * 11 + green("+ " + ln))
            if len(lines) > 20:
                self.out(" " * 11 + dim(f"… {len(lines) - 20} more lines"))
            return True
        return False

    def show(self, ev: dict) -> None:
        kind, text, label = ev.get("kind"), str(ev.get("text", "")), ev.get("label", "")
        at = hhmm(ev.get("t"))
        w = width()
        if kind in ("status", "nap"):
            if kind == "nap":
                try:
                    self.out(f"{dim(at)}  {dim('waiting; it looks for work again at ' + hhmm(float(text)))}")
                except ValueError:
                    pass
                return
            words = status_words(text)
            if not words and not self.steps:
                return
            look = green if words.startswith("✓") else red if words.startswith("✗") else amber if "model is out" in words or "found the model out" in words else bold
            self.out(f"{dim(at)}  {look(clip(words, w - 7)) if words else dim(clip(text, w - 7))}")
            self.label = None
            return
        if kind == "start":
            words = label_words(label)
            if label != "duties" and words:
                self.out(f"{dim(at)}  {cyan('▸ ' + text + ': ' + words)}")
            self.label = label
            return
        if kind == "end":
            return
        # A step of a model turn. When two run at once (a paper step and its
        # tasks), each new run of them is headed by what it is for.
        if label != self.label and label not in ("", "loop"):
            self.out(f"{dim(at)}  {cyan('▸ ' + (label_words(label) or label))}")
            self.label = label
        if kind == "text":
            lines = text.strip("\n").split("\n")
            keep = len(lines) if self.steps else 3
            for i, ln in enumerate(lines[:keep]):
                self.out(f"{dim(at) if i == 0 else '     '}  {'● ' if i == 0 else '  '}{ln if self.steps else clip(ln, w - 11)}")
            if len(lines) > keep:
                self.out(" " * 11 + dim(f"… {len(lines) - keep} more lines (d shows them)"))
        elif kind == "tool":
            name, _, arg = text.partition(": ")
            self.out(f"{dim(at)}    {dim('→')} {bold(name)}  {clip(arg.split(chr(10))[0], w - len(name) - 13)}")
        elif kind == "error":
            first = text.strip().split("\n")[0] if text.strip() else "error"
            self.out(f"{dim(at)}    {red('✗ ' + clip(first, w - 11))}")
            if self.steps and "\n" in text.strip():
                self.block("", text.strip().split("\n", 1)[1], 12, style=red)
        elif not self.steps:
            return
        elif kind == "thinking":
            self.block("✻ ", text.strip(), 30, style=lambda s: paint("2;3", s))
        elif kind == "input":
            try:
                inp = json.loads(text)
            except ValueError:
                inp = None
            if not (isinstance(inp, dict) and self.diff(inp)):
                self.block("", text, 10)
        elif kind == "result":
            self.block("⎿ ", text if text.strip() else "(nothing)", 12)
        elif kind == "done":
            self.out(" " * 9 + dim("✓ " + done_words(text)))
        elif kind == "todo":
            try:
                items = json.loads(text)
                for it in items or []:
                    mark = "☒" if it.get("completed") or it.get("status") == "completed" else "☐"
                    self.out(" " * 11 + dim(f"{mark} {it.get('text') or it.get('content') or ''}"))
            except (ValueError, AttributeError, TypeError):
                self.block("", text, 10)
        elif kind in ("user", "session", "other"):
            self.block("", text, 6)


def keys():
    """The terminal to read single keys from, or None (then Ctrl-C leaves)."""
    try:
        import termios
        import tty

        f = sys.stdin if sys.stdin.isatty() else open("/dev/tty")
        old = termios.tcgetattr(f.fileno())
        tty.setcbreak(f.fileno())
        return f, old
    except Exception:
        return None


def main() -> int:
    args = sys.argv[1:]
    events = read_events(LIVE)
    if "--status" in args:
        # One line under ./ac's header ("  Now: "): clipped to fit 80 columns.
        line = re.sub(r"\033\[[0-9;]*m", "", now_line(events))
        print(line if len(line) <= 72 else line[:71] + "…")
        return 0
    view = View(steps="--steps" in args)
    talk_code = None
    if "--talk-code" in args:
        try:
            talk_code = int(args[args.index("--talk-code") + 1])
        except (IndexError, ValueError):
            talk_code = None
    try:
        name = json.load(open(os.path.join(STATE, "agent.json"))).get("name") or "Your agent"
    except (OSError, ValueError):
        name = "Your agent"

    view.out()
    view.out(f"  {bold(name)}  {now_line(events)}")
    blocked = model_block()
    if blocked:
        view.out("  " + dim(block_fix(blocked[1])))
    q = open_questions()
    if q:
        view.out("  " + amber(f"{q} {'question waits' if q == 1 else 'questions wait'} for you: t talks to it, or answer on its page."))
    # Under 80 columns, with its indent.
    hint = "d  every step in full" + ("   t  talk to it" if talk_code else "") + "   q  leave (it keeps running)"
    view.out("  " + dim(hint))
    view.out("  " + dim("─" * min(width() - 4, 76)))
    if not os.path.exists(LIVE):
        view.out(dim("  Nothing to show yet. A loop started before this view existed shows its"))
        view.out(dim("  steps here once it starts again (./ac: Stop, then Start)."))
    recent = deque(events[-300:], maxlen=300)
    shown = [ev for ev in recent if ev.get("kind") not in ("start", "end")]
    for ev in shown[-40:]:
        view.show(ev)
    if "--once" in args:
        return 0

    term = keys()
    try:
        f = open(LIVE, encoding="utf-8", errors="replace") if os.path.exists(LIVE) else None
        if f:
            f.seek(0, os.SEEK_END)
        ino = os.fstat(f.fileno()).st_ino if f else None
        buf = ""
        while True:
            if term:
                r, _, _ = select.select([term[0]], [], [], 0.4)
                if r:
                    ch = os.read(term[0].fileno(), 1).decode(errors="ignore")
                    if ch in ("q", "Q", "\x04"):
                        break
                    if ch in ("d", "D"):
                        view.steps = not view.steps
                        view.out()
                        view.out("  " + dim("every step in full: thinking, commands, edits, output · d folds them"
                                            if view.steps else "one line a step · d for every step in full"))
                        view.label = None
                        for ev in [e for e in recent if e.get("kind") not in ("start", "end")][-25:]:
                            view.show(ev)
                    if ch in ("t", "T"):
                        if talk_code:
                            return talk_code
                        view.out("  " + dim("To talk to it: ./ac, then Talk to it."))
            else:
                time.sleep(0.4)
            # New lines, and a new file once the loop starts one.
            try:
                st = os.stat(LIVE)
            except OSError:
                st = None
            if st and (f is None or st.st_ino != ino or st.st_size < f.tell()):
                if f:
                    f.close()
                f = open(LIVE, encoding="utf-8", errors="replace")
                ino, buf = st.st_ino, ""
            if not f:
                continue
            chunk = f.read()
            if not chunk:
                continue
            buf += chunk
            *lines, buf = buf.split("\n")
            for line in lines:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict):
                    recent.append(ev)
                    view.show(ev)
    except KeyboardInterrupt:
        pass
    finally:
        if term:
            import termios

            termios.tcsetattr(term[0].fileno(), termios.TCSADRAIN, term[1])
    view.out()
    view.out("  " + dim(f"{name} keeps running in the background. ./ac shows this again."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
