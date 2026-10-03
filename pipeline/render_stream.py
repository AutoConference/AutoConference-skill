#!/usr/bin/env python3
"""render_stream -- one model turn, as a readable and complete transcript.

    claude -p ... --output-format stream-json --verbose | render_stream.py
    codex exec --json ...                              | render_stream.py --format codex
    gemini -p ... -o stream-json                        | render_stream.py --format gemini
    opencode run --format json ...                      | render_stream.py --format opencode

A CLI's plain output says what the agent concluded and little about how, so the
turn the runner uploads (consent §4A) would hold the answer and not the path to
it: which commands it ran, which files it read, what came back, what it thought
on the way. That path is the part of a turn the platform cannot see and the
reason the upload exists. Each CLI can print its turn as events; this turns
them into one transcript -- what it thought (where the CLI shows it), each tool
call with its whole input, everything the tool returned -- and then the final
answer as the LAST lines, so anything reading the end of the output (the
submission challenge takes the last number) sees what it always did.

Nothing is clipped (owner, 2026-10-01: the record must be complete; the runner
uploads a long turn in parts, turn_upload.py). An event this does not know is
printed as its JSON rather than skipped, and a line that is not JSON is printed
as it came. The one exception is a picture a tool returned: it is named by type,
size and SHA-256, not copied in as base64.
"""
import hashlib
import json
import os
import re
import sys
import time

# The tool input field that says what a call was about, shown on its [tool]
# line; the rest of the input follows on an [input] line.
KEY_FIELDS = ("command", "file_path", "path", "pattern", "url", "query", "prompt")

# The same events, one JSON line each, for its owner to watch live
# (pipeline/watch.py; owner, 2026-10-03: never leave them wondering what it is
# doing). The record above is unchanged; this is a copy, clipped, in a file
# agent-turn.sh names, and nothing here may fail a turn.
LIVE = os.environ.get("AC_LIVE_FILE") or ""
LIVE_LABEL = os.environ.get("AC_LIVE_LABEL") or ""
LIVE_MAX = 20000
_last_text = None


def live(kind: str, text: str) -> None:
    global _last_text
    if not LIVE:
        return
    if kind == "text":
        if text == _last_text:
            return  # the answer, printed again at the end
        _last_text = text
    if len(text) > LIVE_MAX:
        text = text[:LIVE_MAX] + f"\n[... {len(text) - LIVE_MAX} more characters in the log]"
    try:
        with open(LIVE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(time.time(), 3), "pid": os.getpid(), "label": LIVE_LABEL, "kind": kind, "text": text}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def emit(text: str) -> None:
    print(text, flush=True)
    if LIVE:
        m = re.match(r"\[([a-z_]+)\]( |$)", text)
        if m and m.group(1) in ("thinking", "tool", "input", "result", "error", "user", "session", "done", "todo"):
            live(m.group(1), text[m.end():])
        elif m or text.startswith("[block:"):
            live("other", text)
        else:
            live("text", text)


def as_text(v) -> str:
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def tool_lines(name, inp) -> None:
    """[tool] name: key field -- then the whole input, so nothing is lost."""
    if isinstance(inp, dict):
        key = next((k for k in KEY_FIELDS if k in inp), None)
        if key is not None:
            emit(f"[tool] {name}: {as_text(inp[key])}")
            rest = {k: v for k, v in inp.items() if k != key}
            if rest:
                emit(f"[input] {json.dumps(rest, ensure_ascii=False)}")
            return
    emit(f"[tool] {name}: {as_text(inp)}")


def picture(block: dict) -> str:
    src = block.get("source") or {}
    data = src.get("data") or ""
    digest = hashlib.sha256(data.encode("ascii", "replace")).hexdigest()[:16] if data else "-"
    return f"[image {src.get('media_type', '?')}, {len(data) * 3 // 4} bytes, sha256 {digest}]"


def result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for c in content:
            if not isinstance(c, dict):
                out.append(as_text(c))
            elif c.get("type") == "image":
                out.append(picture(c))
            elif "text" in c:
                out.append(c.get("text") or "")
            else:
                out.append(json.dumps(c, ensure_ascii=False))
        return "\n".join(out)
    return as_text(content)


def unknown(ev, tag: str = "event") -> None:
    emit(f"[{tag}] {json.dumps(ev, ensure_ascii=False)}")


# ── Claude Code: --output-format stream-json --verbose ─────────────────────
def claude(events) -> int:
    final = None
    for ev in events:
        kind = ev.get("type")
        if kind == "system":
            if ev.get("subtype") == "init":
                emit(f"[session] model={ev.get('model')} cwd={ev.get('cwd')}")
            else:
                unknown(ev, "system")
        elif kind == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                t = block.get("type")
                if t == "text":
                    if block.get("text", "").strip():
                        emit(block["text"])
                elif t == "thinking":
                    if block.get("thinking", "").strip():
                        emit(f"[thinking] {block['thinking']}")
                elif t == "redacted_thinking":
                    emit("[thinking] (withheld by the provider)")
                elif t == "tool_use":
                    tool_lines(block.get("name"), block.get("input"))
                else:
                    unknown(block, f"block:{t}")
        elif kind == "user":
            content = (ev.get("message") or {}).get("content")
            if isinstance(content, str):
                emit(f"[user] {content}")
                continue
            for block in content or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tag = "[error]" if block.get("is_error") else "[result]"
                    emit(f"{tag} {result_text(block.get('content'))}")
                elif isinstance(block, dict) and block.get("type") == "text":
                    emit(f"[user] {block.get('text', '')}")
                else:
                    unknown(block, "block")
        elif kind == "result":
            final = ev
        else:
            unknown(ev)
    if final is not None:
        cost = final.get("total_cost_usd")
        # Tokens as well as dollars (A36): a cost depends on the model's price
        # list, tokens do not, and the platform's cost estimates (A23) are
        # made per task type from these lines. Input counts cached reads too.
        u = final.get("usage") or {}
        tok = ""
        if u:
            tin = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            tok = f" tokens_in={tin} tokens_out={int(u.get('output_tokens') or 0)} cache_read={int(u.get('cache_read_input_tokens') or 0)}"
        emit(f"[done] turns={final.get('num_turns')} "
             f"duration_ms={final.get('duration_ms')}"
             + (f" cost_usd={cost}" if cost is not None else "") + tok)
        # The answer is printed after the summary line, so the last line is
        # always the answer -- usually a second time, as it was also the last
        # text block. Anything reading the tail relies on that.
        if final.get("result"):
            emit(final["result"])
        return 1 if final.get("is_error") else 0
    return 0


# ── Codex: codex exec --json ───────────────────────────────────────────────
def codex(events) -> int:
    answer = None
    for ev in events:
        kind = ev.get("type")
        item = ev.get("item") or {}
        t = item.get("type")
        if kind == "thread.started":
            emit(f"[session] thread={ev.get('thread_id')}")
        elif kind == "turn.started":
            continue  # nothing in it
        elif kind == "item.started":
            # The call, as it starts: a command killed half way still shows
            # what it was. Its output comes with item.completed.
            if t == "command_execution":
                tool_lines("shell", {"command": item.get("command")})
            elif t in ("mcp_tool_call", "web_search", "todo_list", "file_change", "reasoning", "agent_message"):
                continue
            else:
                unknown(ev)
        elif kind in ("item.completed", "item.updated"):
            if kind == "item.updated" and t != "todo_list":
                continue  # the finished item carries all of it
            if t == "agent_message":
                if (item.get("text") or "").strip():
                    emit(item["text"])
                    answer = item["text"]
            elif t == "reasoning":
                if (item.get("text") or "").strip():
                    emit(f"[thinking] {item['text']}")
            elif t == "command_execution":
                code = item.get("exit_code")
                tag = "[result]" if code in (0, None) else f"[error] exit {code}:"
                emit(f"{tag} {item.get('aggregated_output') or ''}")
            elif t == "file_change":
                tool_lines("apply_patch", {"path": ", ".join(c.get("path", "?") for c in item.get("changes") or []), "changes": item.get("changes"), "status": item.get("status")})
            elif t == "mcp_tool_call":
                tool_lines(f"{item.get('server')}.{item.get('tool')}", item.get("arguments"))
                res = item.get("result")
                if item.get("error"):
                    emit(f"[error] {as_text(item.get('error'))}")
                elif res is not None:
                    emit(f"[result] {result_text(res.get('content') if isinstance(res, dict) and 'content' in res else res)}")
            elif t == "web_search":
                tool_lines("web_search", {"query": item.get("query")})
            elif t == "todo_list":
                emit(f"[todo] {json.dumps(item.get('items'), ensure_ascii=False)}")
            elif t == "error":
                emit(f"[error] {item.get('message')}")
            else:
                unknown(ev)
        elif kind == "turn.completed":
            u = ev.get("usage") or {}
            emit(f"[done] tokens_in={int(u.get('input_tokens') or 0)} tokens_out={int(u.get('output_tokens') or 0)}"
                 f" cache_read={int(u.get('cached_input_tokens') or 0)} reasoning={int(u.get('reasoning_output_tokens') or 0)}")
        elif kind == "turn.failed":
            emit(f"[error] {((ev.get('error') or {}).get('message')) or json.dumps(ev, ensure_ascii=False)}")
        elif kind == "error":
            emit(f"[error] {ev.get('message') or json.dumps(ev, ensure_ascii=False)}")
        else:
            unknown(ev)
    if answer:
        emit(answer)
    return 0


# ── Gemini CLI: -o stream-json ─────────────────────────────────────────────
def gemini(events) -> int:
    buf: list = []
    answer = None
    seen_prompt = False

    def flush():
        nonlocal answer
        text = "".join(buf)
        buf.clear()
        if text.strip():
            emit(text)
            answer = text

    for ev in events:
        kind = ev.get("type")
        if kind == "message":
            if ev.get("role") == "assistant":
                buf.append(ev.get("content") or "")
                continue
            flush()
            if not seen_prompt:
                seen_prompt = True  # the instruction itself: the record's prompt holds it
                continue
            emit(f"[user] {as_text(ev.get('content'))}")
            continue
        flush()
        if kind == "init":
            emit(f"[session] model={ev.get('model')} session={ev.get('session_id')}")
        elif kind == "tool_use":
            tool_lines(ev.get("tool_name"), ev.get("parameters"))
        elif kind == "tool_result":
            if ev.get("status") == "error":
                emit(f"[error] {(ev.get('error') or {}).get('message') or ''}")
            else:
                emit(f"[result] {as_text(ev.get('output') or '')}")
        elif kind == "error":
            emit(f"[error] {ev.get('message')}")
        elif kind == "result":
            s = ev.get("stats") or {}
            tok = "".join(f" {k}={s[k]}" for k in ("duration_ms", "input_tokens", "output_tokens", "total_tokens", "cached", "tool_calls") if k in s)
            emit(f"[done] status={ev.get('status')}{tok}")
            if ev.get("error"):
                emit(f"[error] {(ev.get('error') or {}).get('message')}")
        else:
            unknown(ev)
    flush()
    if answer:
        emit(answer)
    return 0


# ── opencode: run --format json ────────────────────────────────────────────
def opencode(events) -> int:
    answer = None
    tin = tout = cache = reasoning = 0
    cost = 0.0
    steps = 0
    for ev in events:
        kind = ev.get("type")
        part = ev.get("part") or {}
        if kind == "text":
            if (part.get("text") or "").strip():
                emit(part["text"])
                answer = part["text"]
        elif kind == "reasoning":
            if (part.get("text") or "").strip():
                emit(f"[thinking] {part['text']}")
        elif kind == "tool_use":
            state = part.get("state") or {}
            tool_lines(part.get("tool"), state.get("input"))
            if state.get("status") == "error":
                emit(f"[error] {as_text(state.get('error'))}")
            else:
                emit(f"[result] {as_text(state.get('output') or '')}")
        elif kind == "step_start":
            continue  # nothing in it
        elif kind == "step_finish":
            steps += 1
            t = part.get("tokens") or {}
            tin += int(t.get("input") or 0)
            tout += int(t.get("output") or 0)
            reasoning += int(t.get("reasoning") or 0)
            cache += int((t.get("cache") or {}).get("read") or 0)
            cost += float(part.get("cost") or 0)
        elif kind == "error":
            err = ev.get("error") or {}
            emit(f"[error] {((err.get('data') or {}).get('message')) or err.get('name') or json.dumps(ev, ensure_ascii=False)}")
        else:
            unknown(ev)
    if steps:
        emit(f"[done] turns={steps} cost_usd={round(cost, 6)} tokens_in={tin} tokens_out={tout} cache_read={cache} reasoning={reasoning}")
    if answer:
        emit(answer)
    return 0


def events(stream):
    """JSON events from the stream; any other line goes straight through."""
    for raw in stream:
        line = raw.rstrip("\n")
        try:
            ev = json.loads(line)
        except ValueError:
            emit(line)
            continue
        if isinstance(ev, dict):
            yield ev
        else:
            emit(line)


def passthrough(stream) -> int:
    for raw in stream:
        emit(raw.rstrip("\n"))
    return 0


def run(cmd, render) -> int:
    """Run the CLI as this process's child and render what it prints.

    agent-turn.sh execs this, so a signal meant for the turn -- a research
    step's timeout, the loop being stopped -- arrives here, and is passed on.
    Piped (`cli | render`), the timeout reached only the shell, and the CLI went
    on working after the step had been given up. The CLI's exit status is the
    turn's, as it was."""
    import io
    import signal
    import subprocess
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    except OSError as e:
        emit(f"[error] could not start {cmd[0]}: {e}")
        return 127
    live("start", cmd[0])

    def forward(sig, _frame):
        try:
            proc.send_signal(sig)
        except OSError:
            pass

    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, forward)
    stream = io.TextIOWrapper(proc.stdout, encoding="utf-8", errors="replace")
    if render is None:
        passthrough(stream)
    else:
        render(events(stream))
    rc = proc.wait()
    rc = 128 - rc if rc < 0 else rc
    live("end", str(rc))
    return rc


def main() -> int:
    """render_stream.py [--format F] [-- command ...]

    With a command, runs it and renders its output (see run); without one,
    renders standard input."""
    fmt = "claude"
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--format":
        fmt, args = args[1], args[2:]
    render = {"claude": claude, "codex": codex, "gemini": gemini, "opencode": opencode}.get(fmt)
    if args[:1] == ["--"] and len(args) > 1:
        return run(args[1:], render)
    if render is None:
        # Not a format this knows: pass it through whole.
        return passthrough(sys.stdin)
    return render(events(sys.stdin))


if __name__ == "__main__":
    sys.exit(main())
