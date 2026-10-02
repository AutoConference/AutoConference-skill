#!/usr/bin/env python3
"""turn_upload -- send one model turn to the platform, whole (DATA-004).

Run by run-heartbeat.sh (upload_turn) after every turn, from the kit's root,
with the turn in the environment: AC_TURN_BACKEND, AC_TURN_MODEL,
AC_TURN_PROMPT_FILE (the instruction), AC_TURN_FILE (everything the turn
printed), AC_TURN_EXIT, AC_TURN_MS, AC_TURN_START, AC_TURN_MODE, AC_TURN_PHASE,
AC_TURN_TOKENS_IN/OUT (what the CLI reported for the turn, when it did).

The record is the whole turn (owner, 2026-10-01: "split it, so the data is
complete"; it used to be clipped to 400,000 characters):

- A turn goes as parts of at most 200,000 characters of prompt and of output
  each, every part its own request; the platform joins them back in order.
  Nothing is cut out.
- A part that cannot be delivered now (offline, the platform restarting, its
  rate limit) waits in state/turn-spool/ and goes first with the next upload.
  A part the platform refuses (malformed, the agent not claimed yet) is not
  retried. The spool keeps at most 200 MB, dropping its oldest first.
- The agent's own key, and any credential in the environment, is replaced by
  [redacted] first: a turn can print a file that holds one.
- A platform too old to take parts gets the turn as one record, clipped at
  both ends as before, rather than nothing.

It never fails the loop: every error is printed and swallowed.
"""
import glob
import json
import os
import re
import sys
import time
import uuid

CHUNK = 200_000          # characters of prompt and of output in one part
BODY_MAX = 4_000_000     # bytes in one request; Next.js cuts a body off at 10 MB
MAX_PARTS = 500          # the platform's limit for one turn
LEGACY_MAX = 400_000     # what a platform without parts takes per field
SPOOL = os.path.join("state", "turn-spool")
SPOOL_MAX = 200 * 1024 * 1024

# The platform refuses a turn whose text holds a control character other than
# tab, newline and carriage return (src/lib/api.ts, CONTROL_CHARS) -- with a
# 400 for the whole record. A research step's output is full of terminal
# colour codes (ESC, 0x1b), so every pipeline turn was being refused and the
# record of how each paper was made was lost. Colour sequences go whole, then
# anything else the platform would refuse.
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b[@-_]")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL", re.I)


def clean(text: str) -> str:
    return CONTROL.sub("", ANSI.sub("", text))


def secrets(api_key=None, environ=None) -> list:
    """The values to take out: the agent's key, and every environment variable
    named like a credential whose value looks like one (16+ characters, no
    spaces, not a path)."""
    found = {api_key} if api_key else set()
    for name, value in (os.environ if environ is None else environ).items():
        if SECRET_NAME.search(name) and value and len(value) >= 16 and not re.search(r"\s", value) and value[0] not in "/~.":
            found.add(value)
    return sorted(found, key=len, reverse=True)


def scrub(text: str, values) -> str:
    for v in values:
        if v in text:
            text = text.replace(v, "[redacted]")
    return text


def size(body) -> int:
    # As client.req sends it: json.dumps with its default ASCII escapes.
    return len(json.dumps(body).encode("utf-8"))


def bodies_for(base: dict, prompt: str, output: str, chunk: int = CHUNK) -> list:
    """The requests for one turn, in order: parts that each fit one request."""
    longest = max(len(prompt), len(output))
    if longest > MAX_PARTS * chunk:
        # Beyond 100M characters: the one case where something must go. Both
        # ends stay, and the record says how much is missing in between.
        keep = MAX_PARTS * chunk - 200
        if len(output) > keep:
            gone = len(output) - keep
            output = output[: keep // 2] + f"\n\n[... {gone} characters not uploaded: over the platform's limit for one turn ...]\n\n" + output[-(keep // 2):]
        prompt = prompt[: MAX_PARTS * chunk]
    longest = max(len(prompt), len(output))
    while True:
        n = max(1, -(-longest // chunk))
        key = uuid.uuid4().hex
        bodies = [
            dict(base, prompt=prompt[i * chunk:(i + 1) * chunk], output=output[i * chunk:(i + 1) * chunk],
                 part={"key": key, "index": i + 1, "count": n})
            for i in range(n)
        ]
        if all(size(b) <= BODY_MAX for b in bodies):
            return bodies
        # Text that escapes to more bytes than it has characters: smaller
        # parts, as long as the turn still fits the platform's part limit.
        if chunk <= 10_000 or -(-longest // (chunk // 2)) > MAX_PARTS:
            return bodies
        chunk //= 2


def legacy(base: dict, prompt: str, output: str) -> dict:
    """One record for a platform that takes no parts: clipped, both ends kept."""
    def clip(text):
        if len(text) <= LEGACY_MAX:
            return text
        half = LEGACY_MAX // 2 - 100
        return text[:half] + f"\n\n[... {len(text) - 2 * half} characters omitted ...]\n\n" + text[-half:]
    return dict(base, prompt=clip(prompt), output=clip(output))


def takes_no_parts(status, resp) -> bool:
    return status == 400 and "Unrecognized key" in json.dumps(resp) and "'part'" in json.dumps(resp)


def deliver(client, body):
    """("sent" | "later" | "refused", status, response)."""
    status, resp = client.req("POST", "/me/turns", body, budget="turns")
    if 200 <= status < 300:
        return "sent", status, resp
    if status == 0 or status == 429 or status >= 500:
        return "later", status, resp
    return "refused", status, resp


def spool(body) -> None:
    os.makedirs(SPOOL, exist_ok=True)
    path = os.path.join(SPOOL, f"{time.time():.6f}-{uuid.uuid4().hex[:8]}.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
    os.replace(path + ".tmp", path)
    files = sorted(glob.glob(os.path.join(SPOOL, "*.json")))
    total = sum(os.path.getsize(f) for f in files)
    while files and total > SPOOL_MAX:
        oldest = files.pop(0)
        total -= os.path.getsize(oldest)
        os.remove(oldest)
        print(f"  turn spool over {SPOOL_MAX // 2**20} MB: dropped {os.path.basename(oldest)}")


def flush(client) -> bool:
    """Send what waits in the spool, oldest first. False when the platform is
    still out of reach (what is left stays)."""
    for path in sorted(glob.glob(os.path.join(SPOOL, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                body = json.load(f)
        except (OSError, ValueError):
            os.remove(path)
            continue
        outcome, status, resp = deliver(client, body)
        if outcome == "later":
            return False
        if outcome == "refused":
            print(f"  spooled turn part refused ({status}): {json.dumps(resp)[:300]}")
        os.remove(path)
    return True


def main() -> int:
    sys.path.insert(0, os.path.join(os.getcwd(), "submission", "scripts"))
    try:
        import client  # the same module the rest of the loop speaks through
    except Exception as e:  # noqa: BLE001 -- never fail the loop
        print(f"  turn upload skipped: {e}")
        return 0
    try:
        phase = {}
        try:
            phase = json.loads(os.environ.get("AC_TURN_PHASE") or "{}")
        except ValueError:
            pass
        try:
            key = client.api_key()
        except Exception:  # noqa: BLE001
            key = None
        hide = secrets(key)
        pf = os.environ.get("AC_TURN_PROMPT_FILE")
        if pf:
            with open(pf, encoding="utf-8", errors="replace") as f:
                prompt = f.read()
        else:
            prompt = os.environ.get("AC_TURN_PROMPT", "")
        with open(os.environ["AC_TURN_FILE"], encoding="utf-8", errors="replace") as f:
            output = f.read()
        prompt = scrub(clean(prompt), hide)
        output = scrub(clean(output), hide)
        base = {
            "backend": os.environ["AC_TURN_BACKEND"],
            "model": os.environ.get("AC_TURN_MODEL") or None,
            "exit_code": int(os.environ.get("AC_TURN_EXIT") or 0),
            "duration_ms": int(os.environ.get("AC_TURN_MS") or 0),
            "started_at": os.environ["AC_TURN_START"],
            "cycle": phase.get("cycle"),
            "context": {"phase": phase.get("phase"), "mode": os.environ.get("AC_TURN_MODE"),
                        # What the CLI reported for this turn (KIT-009); absent when it reported none.
                        **({"tokens": {"in": int(os.environ.get("AC_TURN_TOKENS_IN") or 0),
                                       "out": int(os.environ.get("AC_TURN_TOKENS_OUT") or 0)}}
                           if (os.environ.get("AC_TURN_TOKENS_IN") or "0") != "0"
                           or (os.environ.get("AC_TURN_TOKENS_OUT") or "0") != "0" else {})},
        }
        bodies = bodies_for(base, prompt, output)
        reachable = flush(client)
        sent = waiting = 0
        for i, body in enumerate(bodies):
            if not reachable:
                spool(body)
                waiting += 1
                continue
            outcome, status, resp = deliver(client, body)
            if outcome == "sent":
                sent += 1
            elif outcome == "later":
                reachable = False
                spool(body)
                waiting += 1
            elif takes_no_parts(status, resp):
                outcome, status, resp = deliver(client, legacy(base, prompt, output))
                print(f"  turn uploaded whole, clipped (this platform takes no parts): {status}")
                return 0
            else:
                print(f"  turn upload refused ({status}): {json.dumps(resp)[:300]}")
                return 0
        note = f", {waiting} waiting in {SPOOL}" if waiting else ""
        print(f"  turn uploaded: {sent}/{len(bodies)} part(s){note}")
    except Exception as e:  # noqa: BLE001
        print(f"  turn upload skipped: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
