#!/usr/bin/env python3
"""render_stream -- a Claude Code turn, as a readable transcript.

    claude -p ... --output-format stream-json --verbose | render_stream.py

Plain `claude -p` prints only the final answer, so the turn the runner uploads
(consent §4A) would say what the agent concluded and nothing about how: which
commands it ran, which files it read, what came back. That path is the part of
a turn the platform cannot see and the reason the upload exists. This prints
it -- each tool call and a bounded slice of its result -- and then the final
answer as the LAST lines, so anything reading the end of the output (the
submission challenge takes the last number) sees what it always did.

Tolerant by design: a line that is not JSON is printed as it came, and an event
type it does not know is skipped rather than guessed at.
"""
import json
import sys

TOOL_INPUT = 2000      # characters of a tool call's input
TOOL_RESULT = 2000     # characters of what came back


def clip(s: str, n: int) -> str:
    s = s if isinstance(s, str) else json.dumps(s, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + f" … [{len(s) - n} more chars]"


def tool_input(name: str, inp: dict) -> str:
    for key in ("command", "file_path", "path", "pattern", "url", "query", "prompt"):
        if isinstance(inp, dict) and key in inp:
            return clip(str(inp[key]), TOOL_INPUT)
    return clip(json.dumps(inp, ensure_ascii=False), TOOL_INPUT)


def result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return json.dumps(content, ensure_ascii=False)


def main() -> int:
    final = None
    for raw in sys.stdin:
        line = raw.rstrip("\n")
        try:
            ev = json.loads(line)
        except ValueError:
            print(line, flush=True)
            continue
        kind = ev.get("type")
        if kind == "system" and ev.get("subtype") == "init":
            print(f"[session] model={ev.get('model')} cwd={ev.get('cwd')}", flush=True)
        elif kind == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                t = block.get("type")
                if t == "text" and block.get("text", "").strip():
                    print(block["text"], flush=True)
                elif t == "thinking" and block.get("thinking", "").strip():
                    print(f"[thinking] {clip(block['thinking'], TOOL_RESULT)}", flush=True)
                elif t == "tool_use":
                    print(f"[tool] {block.get('name')}: {tool_input(block.get('name'), block.get('input'))}",
                          flush=True)
        elif kind == "user":
            for block in (ev.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tag = "[error]" if block.get("is_error") else "[result]"
                    print(f"{tag} {clip(result_text(block.get('content')), TOOL_RESULT)}", flush=True)
        elif kind == "result":
            final = ev
    if final is not None:
        cost = final.get("total_cost_usd")
        print(f"[done] turns={final.get('num_turns')} "
              f"duration_ms={final.get('duration_ms')}"
              + (f" cost_usd={cost}" if cost is not None else ""), flush=True)
        # The answer is printed after the summary line, so the last line is
        # always the answer -- usually a second time, as it was also the last
        # text block. Anything reading the tail relies on that.
        if final.get("result"):
            print(final["result"], flush=True)
        return 1 if final.get("is_error") else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
