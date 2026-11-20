#!/usr/bin/env python3
"""Opt-in, local science extensions. No model APIs, installs or downloads.

Owner configuration: custom/science-extensions.json. Per-paper selection:
refine-logs/EXTENSION_PLAN.json. Execution and replay records live under runs/.
The four levels describe responsibility for one bounded subtask, not quality.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import signal
import shutil
import shlex
import subprocess
import sys
import time
import uuid

from adapters.common import read_json, safe_input, safe_output

HERE = Path(__file__).resolve().parent
KIT = HERE.parent.parent
CONFIG = Path(os.environ.get("AC_SCIENCE_CONFIG", str(KIT / "custom" / "science-extensions.json")))
PLAN = "refine-logs/EXTENSION_PLAN.json"
RECORDS = "runs/extension-runs"
TIERS = (0, 25, 75, 100)
DOMAINS = {"math": "数学与优化", "ml": "机器学习", "llm": "语言模型", "agent": "Agent 系统",
           "vision": "视觉与具身", "bio": "生物医学", "physics": "物理与科学计算", "chem": "化学与材料"}


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(dump(value) + "\n", encoding="utf-8")
    temporary.replace(path)


def load(path):
    path = Path(path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("JSON exceeds 16 MiB")
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=lambda s: (_ for _ in ()).throw(ValueError(f"Non-finite JSON: {s}")))


def catalog():
    result = {}
    for path in sorted((HERE / "catalog-parts").glob("*.json")):
        fragment = load(path)
        for item in fragment if isinstance(fragment, list) else fragment["extensions"]:
            key = item["id"]
            if key in result or not key.replace("_", "").isalnum() or item["domain"] not in DOMAINS:
                raise ValueError(f"Invalid or duplicate extension: {key}")
            if not (HERE / "adapters" / (key + ".py")).is_file():
                raise ValueError(f"Missing adapter: {key}")
            if set(item["tiers"]) != {"25", "75", "100"}:
                raise ValueError(f"Three enabled tiers required: {key}")
            result[key] = item
    return result


def settings(path=CONFIG):
    known = catalog()
    if not Path(path).exists():
        return {"schema_version": 1, "timeout_seconds": 180, "extensions": {k: 0 for k in known}}
    value = load(path)
    if not isinstance(value, dict) or set(value) - {"schema_version", "timeout_seconds", "python", "extensions", "enabled"}:
        raise ValueError("Unknown configuration fields")
    if value.get("schema_version") != 1 or isinstance(value.get("schema_version"), bool):
        raise ValueError("Configuration schema_version must be 1")
    # KIT-083: its owner's switch. Off, no new plan is offered a tool; the
    # levels stay, and a paper already planned with one keeps that plan.
    if type(value.get("enabled", True)) is not bool:
        raise ValueError("enabled must be true or false")
    levels = value.get("extensions")
    if not isinstance(levels, dict) or set(levels) - set(known):
        raise ValueError("Configuration names an unknown extension")
    if any(type(v) is not int or v not in TIERS for v in levels.values()):
        raise ValueError("Extension levels must be 0, 25, 75 or 100")
    seconds = value.get("timeout_seconds", 180)
    if type(seconds) is not int or not 1 <= seconds <= 3600:
        raise ValueError("timeout_seconds must be an integer from 1 to 3600")
    python = value.get("python", sys.executable)
    if not isinstance(python, str) or not python.strip() or "\n" in python:
        raise ValueError("python must name one executable, without shell arguments")
    return {**value, "timeout_seconds": seconds, "extensions": {k: levels.get(k, 0) for k in known}}


def normalized_request(request, config):
    if not isinstance(request, dict) or set(request) - {"id", "tier", "purpose", "inputs", "params"}:
        raise ValueError("Request fields: id, tier, purpose, inputs, params")
    key = request.get("id")
    if key not in catalog():
        raise ValueError(f"Unknown extension: {key}")
    tier = request.get("tier")
    if type(tier) is not int or tier not in TIERS:
        raise ValueError("Request tier must be 0, 25, 75 or 100")
    maximum = config["extensions"][key]
    if tier > maximum:
        raise ValueError(f"{key}: requested {tier}, owner's maximum is {maximum}")
    purpose = request.get("purpose", "")
    if tier and (not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 2000):
        raise ValueError("Enabled requests need a bounded subtask in purpose (1–2000 characters)")
    inputs, params = request.get("inputs", {}), request.get("params", {})
    if not isinstance(inputs, dict) or len(inputs) > 12 or any(not isinstance(k, str) or not isinstance(v, str) for k, v in inputs.items()):
        raise ValueError("inputs must map at most 12 names to workspace-relative paths")
    for relative in inputs.values():
        if not relative or not Path(relative).parts or relative.startswith("/") or Path(relative).is_absolute() or ".." in Path(relative).parts or "\\" in relative or ":" in relative:
            raise ValueError("Input must be a workspace-relative POSIX path")
    if not isinstance(params, dict) or len(dump(params)) > 32000:
        raise ValueError("params must be a bounded JSON object")
    return {"id": key, "tier": tier, "purpose": purpose, "inputs": inputs, "params": params}


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def input_hashes(workspace, request):
    result = {}
    for relative in request["inputs"].values():
        path = safe_input(workspace, relative)
        files = sorted(path.rglob("*")) if path.is_dir() else [path]
        if len(files) > 10000:
            raise ValueError("Input directory contains more than 10000 entries")
        for file in files:
            rel = file.relative_to(workspace).as_posix()
            file = safe_input(workspace, rel)
            if file.is_file():
                result[rel] = digest_file(file)
    return result


def adapter_hash(key):
    paths = [HERE / "adapters" / (key + ".py"), HERE / "adapters" / "common.py", Path(__file__)]
    return hashlib.sha256("".join(digest_file(p) for p in paths).encode()).hexdigest()


def snapshot_inputs(workspace, hashes):
    """Keep small text inputs in the existing publishable research-record tree.

    Content-addressing shares repeated inputs between tiers/runs. Model weights
    and large datasets stay local; their hashes and explicit omissions remain.
    """
    snapshots = []
    remaining = 8 * 1024 * 1024
    binary_suffixes = {".pt", ".pth", ".bin", ".safetensors", ".png", ".jpg", ".jpeg", ".npy", ".npz", ".pkl", ".pickle"}
    for relative, sha in hashes.items():
        source = safe_input(workspace, relative)
        item = {"input": relative, "sha256": sha}
        if source.suffix.lower() in binary_suffixes:
            item["omitted_reason"] = "Binary/model input: supply the original file with this hash"
        elif source.stat().st_size > min(2 * 1024 * 1024, remaining):
            item["omitted_reason"] = "Above the small-input snapshot limit: supply the original file with this hash"
        else:
            data = source.read_bytes()
            try:
                data.decode("utf-8-sig")
                if b"\0" in data:
                    raise UnicodeError()
            except UnicodeError:
                item["omitted_reason"] = "Non-text input: supply the original file with this hash"
            else:
                target = f"runs/extension-inputs/{sha}{source.suffix.lower()}"
                safe_output(workspace, target).write_bytes(data)
                remaining -= len(data)
                item["snapshot"] = target
        snapshots.append(item)
    return snapshots


def call_worker(config, mode, key, workspace, payload_path, output_path):
    command = [config.get("python", sys.executable), str(Path(__file__).resolve()), "_worker", mode, key,
               "--workspace", str(workspace), "--payload", str(payload_path), "--output", str(output_path)]
    env = {**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "HF_HUB_OFFLINE": "1",
           "TRANSFORMERS_OFFLINE": "1", "WANDB_MODE": "disabled", "PYTHONHASHSEED": "0"}
    output_path.unlink(missing_ok=True)  # a failed probe must not reuse an earlier success
    log_path = output_path.with_suffix(".log")
    with log_path.open("wb") as log:
        try:
            process = subprocess.Popen(command, cwd=workspace, stdout=log, stderr=subprocess.STDOUT, env=env,
                                       start_new_session=(os.name != "nt"))
        except OSError as error:
            return {"status": "unavailable", "reason": f"Could not start the configured Python: {error}"}
        try:
            code = process.wait(timeout=config["timeout_seconds"])
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            return {"status": "timeout", "reason": f"Exceeded {config['timeout_seconds']} seconds"}
    if code == 0 and output_path.exists():
        return load(output_path)
    # Keep diagnostics bounded. Research-record publishing applies its usual anonymisation.
    with log_path.open("rb") as log:
        log.seek(max(0, log_path.stat().st_size - 2000))
        tail = log.read().decode("utf-8", errors="replace")
    return {"status": "error", "reason": f"Adapter exited {code} without a result: {tail}"}


def worker(args):
    try:
        module = importlib.import_module("adapters." + args.id)
        probe = module.probe()
        if args.mode == "probe":
            value = {"status": "available" if probe["available"] else "unavailable", **probe}
        elif not probe["available"]:
            value = {"status": "unavailable", **probe}
        else:
            result = module.run(load(args.payload), Path(args.workspace).resolve())
            metrics = result.get("metrics")
            if not isinstance(metrics, dict) or not metrics or any(type(v) not in (int, float) or not math.isfinite(v) for v in metrics.values()):
                raise ValueError("Adapter must return nonempty finite numeric metrics")
            if not isinstance(result.get("artifacts", []), list):
                raise ValueError("Adapter artifacts must be a list")
            for path in result.get("artifacts", []):
                safe_input(Path(args.workspace), path)
            value = {"status": "completed", "versions": probe.get("versions", {}), "result": result}
        write_json(args.output, value)
    except Exception as error:
        write_json(args.output, {"status": "error", "reason": f"{type(error).__name__}: {error}"[:3000]})
    return 0


def execute(request, config, workspace, *, replay_of=None):
    workspace = Path(workspace).resolve(strict=True)
    request = normalized_request(request, config)
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    folder = f"{RECORDS}/{run_id}"
    record_path = safe_output(workspace, folder + "/record.json")
    record = {"schema_version": 1, "run_id": run_id, "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "request": request, "owner_maximum": config["extensions"][request["id"]], "replay_of": replay_of,
              "adapter_sha256": adapter_hash(request["id"])}
    tool = catalog()[request["id"]]
    record["tool"] = {k: tool[k] for k in ("name", "domain", "project_url", "license", "task")}
    started = time.monotonic()
    try:
        if request["tier"] == 0:
            record.update(status="disabled", reason="Tier 0: extension not invoked")
        else:
            hashes = input_hashes(workspace, request)
            record["input_sha256"] = hashes
            record["input_snapshots"] = snapshot_inputs(workspace, hashes)
            sources = [Path(__file__), HERE / "adapters" / "common.py", HERE / "adapters" / (request["id"] + ".py")]
            record["source_sha256"] = {}
            for source in sources:
                relative = folder + "/source/" + source.name
                shutil.copyfile(source, safe_output(workspace, relative))
                record["source_sha256"][relative] = digest_file(source)
            payload = safe_output(workspace, folder + "/request.json")
            write_json(payload, {**request, "_output_dir": folder + "/artifacts"})
            output = safe_output(workspace, folder + "/result.json")
            record.update(call_worker(config, "run", request["id"], workspace, payload, output))
            if input_hashes(workspace, request) != hashes:
                record.update(status="error", reason="Adapter changed its input files")
            if record["status"] == "completed":
                record["artifact_sha256"] = {p: digest_file(safe_input(workspace, p)) for p in record["result"].get("artifacts", [])}
    except Exception as error:
        record.update(status="error", reason=f"{type(error).__name__}: {error}"[:3000])
    record["duration_seconds"] = round(time.monotonic() - started, 4)
    write_json(record_path, record)
    return record


def records(workspace):
    root = safe_output(Path(workspace), RECORDS + "/placeholder").parent
    result = [load(safe_input(Path(workspace), p.relative_to(workspace).as_posix())) for p in root.glob("*/record.json")]
    return sorted(result, key=lambda r: (r.get("started_at", ""), r.get("run_id", "")))


def same_result(left, right):
    """Compare all structured outputs, not just their numeric summaries."""
    if type(left) in (int, float) and type(right) in (int, float):
        return math.isclose(left, right, rel_tol=1e-5, abs_tol=1e-7)
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same_result(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same_result(a, b) for a, b in zip(left, right))
    return left == right


def artifacts_intact(record, workspace):
    intact = all(digest_file(safe_input(workspace, path)) == sha for field in ("artifact_sha256", "source_sha256")
                 for path, sha in record.get(field, {}).items())
    return intact and all(digest_file(safe_input(workspace, item["snapshot"])) == item["sha256"]
                          for item in record.get("input_snapshots", []) if "snapshot" in item)


def plan(workspace, config):
    path = Path(workspace) / PLAN
    if config.get("enabled", True) is False and not path.exists():
        return {"schema_version": 1, "requests": [], "reason": "Research tools are off (its owner's switch)"}
    if not any(config["extensions"].values()) and not path.exists():
        return {"schema_version": 1, "requests": [], "reason": "No extensions enabled"}
    if not path.exists():
        raise ValueError(f"Enabled extensions require {PLAN}; write requests or an empty list with a reason")
    value = read_json(workspace, PLAN)
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("requests"), list):
        raise ValueError("Extension plan requires schema_version 1 and requests list")
    if len(value["requests"]) > len(catalog()):
        raise ValueError("At most one request per extension per plan")
    requests = [normalized_request(r, config) for r in value["requests"]]
    if len({r["id"] for r in requests}) != len(requests):
        raise ValueError("Duplicate extension requests")
    if not requests and (not isinstance(value.get("reason"), str) or not value["reason"].strip()):
        raise ValueError("An empty plan must explain why no extension fits")
    return {**value, "requests": requests}


def matching_record(request, workspace, config):
    current_hash = input_hashes(workspace, request) if request["tier"] else {}
    candidate = next((r for r in reversed(records(workspace)) if r.get("request") == request
                 and r["status"] in ("completed", "disabled") and not r.get("replay_of")
                 and r.get("input_sha256", {}) == current_hash
                 and r.get("adapter_sha256") == adapter_hash(request["id"])
                 and artifacts_intact(r, workspace)), None)
    if candidate is None or not request["tier"]:
        return candidate
    path = safe_output(workspace, f"refine-logs/EXTENSION_CACHE_{request['id']}.json")
    current = call_worker(config, "probe", request["id"], workspace, path, path)
    return candidate if current.get("status") == "available" and current.get("versions") == candidate.get("versions") else None


def verify_record(original, workspace, config):
    request = original["request"]
    if original["status"] == "disabled":
        return {"status": "disabled", "run_id": original["run_id"]}
    if original["status"] != "completed":
        raise ValueError("Only a completed run can be replayed")
    if input_hashes(workspace, request) != original["input_sha256"] or adapter_hash(request["id"]) != original["adapter_sha256"]:
        raise ValueError("Inputs or adapter changed since the original run")
    if not artifacts_intact(original, workspace):
        raise ValueError("A recorded artifact or source changed")
    replay = execute(request, config, workspace, replay_of=original["run_id"])
    if replay["status"] != "completed":
        return {"status": "failed", "run_id": original["run_id"], "replay_id": replay["run_id"], "reason": replay.get("reason", replay["status"])}
    old, new = original["result"]["metrics"], replay["result"]["metrics"]
    changed = [k for k in old if k not in new or not math.isclose(old[k], new[k], rel_tol=1e-5, abs_tol=1e-7)]
    data_match = same_result(original["result"].get("data"), replay["result"].get("data"))
    old_artifacts = original["result"].get("artifacts", [])
    new_artifacts = replay["result"].get("artifacts", [])
    artifacts_match = len(old_artifacts) == len(new_artifacts)
    if artifacts_match:
        for before, after in zip(old_artifacts, new_artifacts):
            a, b = safe_input(workspace, before), safe_input(workspace, after)
            if a.suffix == b.suffix == ".json":
                artifacts_match = artifacts_match and same_result(load(a), load(b))
            else:
                artifacts_match = artifacts_match and digest_file(a) == digest_file(b)
    passed = not changed and old.keys() == new.keys() and data_match and artifacts_match and original.get("versions") == replay.get("versions")
    return {"status": "passed" if passed else "failed", "run_id": original["run_id"], "replay_id": replay["run_id"],
            "changed_metrics": changed, "data_match": data_match, "artifacts_match": artifacts_match,
            "versions_match": original.get("versions") == replay.get("versions"),
            "scope": "Same-input, same-version numeric repeatability; not a scientific quality assessment"}


def context(config, config_path=CONFIG):
    if config.get("enabled", True) is False:
        return ""
    enabled = [(catalog()[k], tier) for k, tier in config["extensions"].items() if tier]
    if not enabled:
        return ""
    lines = ["\n=== Optional scientific extensions (owner-configured) ===",
             "Select by the experiment's bounded subtask, not merely its subject label.",
             "Each configured level is the maximum allowed responsibility; choose 0/25/75/100 at or below it.",
             "25 assists/checks, 75 handles the main relevant module, 100 handles that entire bounded subtask.",
             "Levels are not probabilities or quality scores. They do not replace baselines, held-out evaluation or review."]
    for item, tier in enabled:
        lines.append(f"{item['id']} ({item['name']}, {item['domain']}), maximum {tier}: {item['task']}")
        for number in (25, 75, 100):
            if number <= tier:
                text = item["tiers"][str(number)]
                lines.append(f"  {number}: {text['en'] if isinstance(text, dict) else text}")
        lines.append(f"  Input: {item['input_description']}; source: {item['project_url']}")
    lines.extend([f"Step 2: write {PLAN}: schema_version=1, requests=[{{id,tier,purpose,inputs,params}}].",
                  "First read the dependency availability below and match the actual subtask, not just a broad domain label.",
                  "Select no tool when the task, local resources, inputs or budget do not fit. Missing packages are a reason to skip, not to install automatically.",
                  "Before finalizing an enabled selection, run the selected preflight. A dependency-only check is not proof of suitability.",
                  "DEPENDENCY AVAILABILITY: " + dump(availability(config)),
                  "inputs map names to files/directories inside this paper workspace. Use the adapter's examples for its exact JSON schema.",
                  "If none fits, write requests=[] and a concrete reason. Never change owner configuration to make a request pass.",
                  "Step 3 checks the selected dependencies; step 5 prepares the inputs and runs the requests. Missing resources stop selected work explicitly.",
                  f"Run: python3 {shlex.quote(str(HERE / 'science_extensions.py'))} --config {shlex.quote(str(config_path))} run-plan --workspace .",
                  "Read result.json and record.json under runs/extension-runs. Keep scientific inputs separate from generated artifacts.",
                  "Include any numbers used in the paper in the existing experiment/aggregation replay manifest; extension records alone are not that evidence chain.",
                  "Step 10 replays selected extensions as well as the existing paper reproducibility gate.",
                  "All calls run locally; no package installs, model downloads or API services are started by this extension runner.",
                  "=== End scientific extensions ===\n"])
    return "\n".join(lines)


def availability(config):
    """Cheap dependency discovery in the configured environment, no imports/downloads.

    The selected adapter's real preflight still checks versions and inputs.
    """
    modules = {key: list(item.get('packages', {}).values()) for key, item in catalog().items()}
    code = ('import importlib.util,json,sys; data=json.loads(sys.argv[1]); '
            'print(json.dumps({k:[m for m in v if importlib.util.find_spec(m) is None] for k,v in data.items()}))')
    try:
        proc = subprocess.run([config.get('python',sys.executable),'-c',code,json.dumps(modules)],
                              capture_output=True,text=True,timeout=20,check=True)
        missing = json.loads(proc.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {key:{'status':'unavailable','reason':'Configured Python or package discovery failed'} for key in modules}
    return {key:{'status':'disabled' if not config['extensions'][key] else 'missing_dependencies' if names else 'dependencies_found',
                 'missing':names, 'maximum_tier':config['extensions'][key]} for key,names in missing.items()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("init")
    sub.add_parser("context")
    sub.add_parser("availability")
    setting = sub.add_parser("set")
    setting.add_argument("id")
    setting.add_argument("tier", type=int, choices=TIERS)
    for name in ("status", "preflight", "run-plan", "check-plan", "replay-plan", "report"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--workspace", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--workspace", type=Path, required=True)
    run.add_argument("--request", required=True)
    replay = sub.add_parser("replay")
    replay.add_argument("--workspace", type=Path, required=True)
    replay.add_argument("--record", required=True)
    worker_parser = sub.add_parser("_worker")
    worker_parser.add_argument("mode", choices=["probe", "run"])
    worker_parser.add_argument("id")
    worker_parser.add_argument("--workspace", required=True)
    worker_parser.add_argument("--payload", required=True)
    worker_parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.command == "_worker":
        if args.id not in catalog():
            raise ValueError("Unknown worker adapter")
        return worker(args)
    config = settings(args.config)
    if args.command == "availability":
        print(dump(availability(config)))
    elif args.command == "list":
        print(dump({"domains": DOMAINS, "extensions": list(catalog().values())}))
    elif args.command == "init":
        if args.config.exists():
            raise ValueError("Configuration already exists; use set")
        write_json(args.config, config)
        print(str(args.config))
    elif args.command == "set":
        if args.id not in catalog():
            raise ValueError("Unknown extension")
        config["extensions"][args.id] = args.tier
        write_json(args.config, config)
        print(f"{args.id}: {args.tier}")
    elif args.command == "context":
        print(context(config, args.config), end="")
    else:
        workspace = args.workspace.resolve(strict=True)
        if args.command == "run":
            result = execute(read_json(workspace, args.request), config, workspace)
            print(dump(result))
            return 0 if result["status"] in ("completed", "disabled") else 3
        if args.command == "replay":
            result = verify_record(read_json(workspace, args.record), workspace, config)
            write_json(safe_output(workspace, "refine-logs/EXTENSION_REPLAY.json"), result)
            print(dump(result))
            return 0 if result["status"] in ("passed", "disabled") else 3
        if args.command == "report":
            from report import build_report
            path = build_report(workspace, catalog(), config, records(workspace), DOMAINS)
            print(path)
            return 0
        if args.command in ("status", "preflight"):
            requests = plan(workspace, config)["requests"] if args.command == "preflight" else []
            keys = [r["id"] for r in requests if r["tier"]] if args.command == "preflight" else list(catalog())
            result = []
            for key in keys:
                path = safe_output(workspace, f"refine-logs/extension-status/{key}.json")
                status = call_worker(config, "probe", key, workspace, path, path)
                result.append({"id": key, "configured_level": config["extensions"][key], **status})
            write_json(safe_output(workspace, "refine-logs/EXTENSION_PREFLIGHT.json"), result)
            print(dump(result))
            return 3 if args.command == "preflight" and any(r["status"] != "available" for r in result) else 0
        selection = plan(workspace, config)
        results = []
        for request in selection["requests"]:
            try:
                original = matching_record(request, workspace, config)
            except (OSError, ValueError):
                original = None
            if args.command == "run-plan":
                results.append(original or execute(request, config, workspace))
            elif not original:
                results.append({"status": "failed", "id": request["id"], "reason": "No successful run for these inputs and configuration"})
            elif args.command == "replay-plan":
                results.append(verify_record(original, workspace, config))
            else:
                results.append({"status": original["status"], "id": request["id"], "run_id": original["run_id"]})
        out = "EXTENSION_REPLAY.json" if args.command == "replay-plan" else "EXTENSION_EXECUTION.json"
        write_json(safe_output(workspace, "refine-logs/" + out), {"results": results, "reason": selection.get("reason", "")})
        print(dump(results))
        return 3 if any(r["status"] not in ("completed", "disabled", "passed") for r in results) else 0
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(f"science-extensions: {error}", file=sys.stderr)
        sys.exit(2)
