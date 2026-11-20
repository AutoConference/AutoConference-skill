"""Braindecode EEG preprocessing and explicit bounded sleep-classifier operations.

Amplitude is preserved unless exponential moving standardization is explicitly
requested. The optional sleep_fit/sleep_predict operations train a fixed upstream
sleep-staging baseline on supplied data, with disjoint development/test subjects.
API: https://braindecode.org/stable/generated/braindecode.preprocessing.exponential_moving_standardize.html
"""
from __future__ import annotations

import importlib.metadata
import inspect
import json
import math
from pathlib import Path

from .common import read_json, safe_input, safe_output


def probe() -> dict:
    try:
        from braindecode.preprocessing import exponential_moving_standardize, create_fixed_length_windows
        from braindecode.datasets import BaseConcatDataset
        from braindecode.models import SleepStagerChambon2018
        import mne
        return {"available": True, "reason": "Braindecode preprocessing, sleep staging and MNE are available on CPU.",
                "versions": {name: importlib.metadata.version(name) for name in ("braindecode", "mne", "numpy", "pandas", "scipy", "torch")}}
    except (ImportError, OSError, RuntimeError, importlib.metadata.PackageNotFoundError) as exc:
        return {"available": False, "reason": f"Braindecode preprocessing unavailable: {exc}", "versions": {}}


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if not low <= value <= high:
        raise ValueError(f"{name} must be in [{low}, {high}]")
    return float(value)


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


def validate_eeg(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("EEG input must be an object")
    sfreq = _number(data.get("sfreq_hz"), "sfreq_hz", 1, 10000)
    unit = data.get("unit")
    if unit not in ("uV", "V"):
        raise ValueError("unit must explicitly be uV or V")
    records = data.get("records")
    if not isinstance(records, list) or not 1 <= len(records) <= 16:
        raise ValueError("records must contain 1 to 16 independently processed EEG chunks")
    checked, names, total = [], set(), 0
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("each record must be an object")
        name = record.get("id")
        if not isinstance(name, str) or not name.strip() or len(name) > 100 or name in names:
            raise ValueError("each record needs a unique non-empty id of at most 100 characters")
        names.add(name)
        split = record.get("split")
        if split not in ("train", "validation", "test"):
            raise ValueError("each record must declare split: train, validation or test")
        signals = record.get("signals")
        if not isinstance(signals, list) or not 1 <= len(signals) <= 32:
            raise ValueError("signals must contain 1 to 32 channels")
        if not isinstance(signals[0], list) or not 16 <= len(signals[0]) <= 8192:
            raise ValueError("a chunk must contain 16 to 8192 samples per channel")
        length = len(signals[0])
        total += length * len(signals)
        if total > 32768:
            raise ValueError("EEG input exceeds 32768 values; split a large recording into explicit chunks")
        rows = []
        for row in signals:
            if not isinstance(row, list) or len(row) != length:
                raise ValueError("all channels in one recording must have the same length")
            rows.append([_number(v, "signal", -1e8 if unit == "uV" else -100, 1e8 if unit == "uV" else 100) for v in row])
        checked.append({"id": name, "split": split, "signals": rows})
    return {"sfreq_hz": sfreq, "unit": unit, "records": checked}


def run(request: dict, workspace: Path) -> dict:
    tier = request.get("tier")
    if type(tier) is not int or tier not in (25, 75, 100):
        raise ValueError("Braindecode run tier must be 25, 75 or 100")
    inputs, params = request.get("inputs", {}), request.get("params", {})
    if isinstance(params, dict) and params.get("operation") in ("sleep_fit", "sleep_predict"):
        return run_sleep(request, workspace)
    if isinstance(params, dict) and params.get("operation", "preprocess") != "preprocess":
        raise ValueError("operation must be preprocess, sleep_fit or sleep_predict")
    if not isinstance(inputs, dict) or set(inputs) != {"eeg"}:
        raise ValueError("inputs must contain exactly eeg (JSON)")
    if not isinstance(params, dict) or set(params) - {"operation", "normalization", "factor_new", "eps", "window_samples", "stride_samples"}:
        raise ValueError("unsupported Braindecode parameters")
    normalization = params.get("normalization", "none")
    if normalization not in ("none", "exponential_moving"):
        raise ValueError("normalization must be none or exponential_moving")
    if normalization == "none" and {"factor_new", "eps"} & set(params):
        raise ValueError("factor_new and eps require explicit normalization=exponential_moving")
    data = validate_eeg(read_json(workspace, inputs["eeg"]))
    factor = _number(params.get("factor_new", 0.01), "factor_new", 0.00001, 1)
    eps = _number(params.get("eps", 0.0001), "eps", 1e-12, 1)
    window = _integer(params.get("window_samples", 32), "window_samples", 8, 8192)
    stride = _integer(params.get("stride_samples", window), "stride_samples", 1, window)
    if any(len(r["signals"][0]) < window for r in data["records"]):
        raise ValueError("window_samples exceeds an input recording's length")

    import numpy as np
    import mne
    from braindecode.datasets import BaseConcatDataset
    try:
        from braindecode.datasets import RawDataset
    except ImportError:  # Braindecode 1.x; the name changed in 2.0.
        from braindecode.datasets import BaseDataset as RawDataset
    from braindecode.preprocessing import exponential_moving_standardize, create_fixed_length_windows

    processed, windows_total, dropped_total, flat_total, window_values = [], 0, 0, 0, 0
    processed_values = []
    selected = data["records"][:1] if tier == 25 else data["records"]
    for record in selected:
        samples = np.asarray(record["signals"], dtype=np.float64)
        if tier == 25:
            samples = samples[:, :window]
        # Work in microvolts before the normalizer's epsilon is applied.
        samples_uv = samples * (1e6 if data["unit"] == "V" else 1)
        signal = (exponential_moving_standardize(samples_uv, factor_new=factor,
                                                init_block_size=None, eps=eps)
                  if normalization == "exponential_moving" else samples_uv)
        if not np.isfinite(signal).all():
            raise ValueError("Braindecode produced non-finite signals")
        processed_values.append(signal.reshape(-1))
        entry = {"id": record["id"], "split": record["split"],
                 "signals": signal.tolist()}
        if normalization == "exponential_moving":
            # Retain the explicit-standardization output for existing consumers.
            entry["standardized_signals"] = entry["signals"]
        if tier >= 75:
            count = 1 + (samples.shape[1] - window) // stride
            if windows_total + count > 1024 or window_values + count * samples.shape[0] * window > 32768:
                raise ValueError("window output exceeds the bounded workload; increase stride or split the input")
            # Braindecode slices the supplied numeric values without rescaling.
            # Serialized windows use output_unit below (uV or standardized), not V.
            raw = mne.io.RawArray(signal, mne.create_info(
                [f"EEG{i}" for i in range(samples.shape[0])], data["sfreq_hz"], ch_types="eeg"), verbose=False)
            dataset = BaseConcatDataset([RawDataset(raw, description={"record": record["id"]})])
            options = {"window_size_samples": window, "window_stride_samples": stride,
                       "preload": True, "n_jobs": 1, "verbose": "error"}
            if "on_last_window" in inspect.signature(create_fixed_length_windows).parameters:
                options["on_last_window"] = "drop"
            else:
                options["drop_last_window"] = True
            windows = create_fixed_length_windows(dataset, **options)
            entry["windows"] = [np.asarray(windows[i][0], dtype=float).tolist() for i in range(len(windows))]
            entry["starts"] = [int(windows[i][2][1]) for i in range(len(windows))]
            dropped = samples.shape[1] - (entry["starts"][-1] + window) if len(windows) else samples.shape[1]
            entry["trailing_samples_dropped"] = int(dropped)
            windows_total += len(windows)
            window_values += len(windows) * samples.shape[0] * window
            dropped_total += dropped
        if tier == 100:
            channel_stds = samples_uv.std(axis=1)
            flat = int((channel_stds < 1e-9).sum())
            flat_total += flat
            entry["quality"] = {"raw_channel_std_uv": channel_stds.tolist(),
                                "raw_channel_peak_to_peak_uv": np.ptp(samples_uv, axis=1).tolist(),
                                "flat_channels": flat,
                                "output_channel_mean": signal.mean(axis=1).tolist(),
                                "output_channel_std": signal.std(axis=1).tolist()}
        processed.append(entry)
    values = np.concatenate(processed_values)
    metrics = {"records_processed": len(processed), "values_processed": int(values.size),
               "records_supplied": len(data["records"]),
               "signal_mean": float(values.mean()), "signal_std": float(values.std())}
    if normalization == "exponential_moving":
        metrics.update(standardized_mean=float(values.mean()), standardized_std=float(values.std()))
    if tier >= 75:
        metrics.update(windows=windows_total, trailing_samples_dropped=dropped_total)
    if tier == 100:
        metrics.update(flat_channels=flat_total, splits_present=len({r["split"] for r in selected}),
                       independent_record_normalization=int(normalization == "exponential_moving"))
    relative = f"{request.get('_output_dir', 'runs/science-extensions/braindecode')}/preprocessed.json"
    safe_output(workspace, relative).write_text(json.dumps(
        {"normalization": normalization, "preview_only": tier == 25,
         "records_supplied": len(data["records"]),
         "sfreq_hz": data["sfreq_hz"],
         "output_unit": "standardized" if normalization == "exponential_moving" else "uV",
         "records": processed},
        separators=(",", ":"), allow_nan=False), encoding="utf-8")
    notes = ["25 previews one window of the first recording, not a replacement for the dataset; 75 creates all windows; 100 adds QC. Levels control scope, not normalization strength.",
             "Default normalization=none preserves amplitude in microvolts. Keep the study's original training-only preprocessing downstream.",
             "Records keep their supplied split. No cross-record train/test statistic is fitted.",
             "Preprocessing only: encoder compatibility, frozen linear probes and macro-F1 evaluation remain separate tasks."]
    if normalization == "exponential_moving":
        notes.append("Explicit exponential moving standardization removes absolute amplitude and restarts at every chunk, with no initialization block. Validate this method against the study's baseline; a higher tier does not establish suitability.")
    return {"metrics": metrics, "artifacts": [relative], "notes": notes}


SLEEP_ARCHITECTURE = "SleepStagerChambon2018-single-channel-100Hz-30s"


def sleep_model():
    """Fixed upstream sleep-staging baseline; random initialization, no downloads."""
    from braindecode.models import SleepStagerChambon2018
    return SleepStagerChambon2018(n_chans=1, sfreq=100, n_times=3000,
                                  n_outputs=5, n_conv_chs=8, drop_prob=.25,
                                  apply_batch_norm=False)


def load_sleep_data(workspace, relative, *, labelled):
    """Bounded numeric NPZ; labels are deliberately absent at prediction time."""
    import zipfile
    import numpy as np
    path = safe_input(workspace, relative)
    if path.stat().st_size > 160 * 1024 * 1024:
        raise ValueError("Sleep data archive exceeds 160 MiB")
    required = {"x", "subject", "sample_id", "sfreq_hz", "unit"} | ({"y"} if labelled else set())
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) != len(required) or {i.filename for i in entries} != {k + ".npy" for k in required}:
            raise ValueError("Sleep NPZ contains unexpected arrays or duplicate names")
        if sum(i.file_size for i in entries) > 160 * 1024 * 1024:
            raise ValueError("Expanded sleep archive exceeds 160 MiB")
    with np.load(path, allow_pickle=False) as archive:
        data = {k: archive[k] for k in required}
    x = data["x"]
    if x.dtype not in (np.dtype("float32"), np.dtype("float64")) or x.ndim != 2 or x.shape[1] != 3000 or not 5 <= len(x) <= 12000:
        raise ValueError("Sleep x must be 5..12000 single-channel 3000-sample float epochs")
    if not np.isfinite(x).all() or np.max(np.abs(x)) > 1e8:
        raise ValueError("Sleep x must contain finite microvolt values")
    if data["sfreq_hz"].shape != () or data["sfreq_hz"].dtype.kind not in "fi" or float(data["sfreq_hz"]) != 100:
        raise ValueError("Sleep classifier requires explicit 100 Hz sampling")
    if data["unit"].shape != () or data["unit"].dtype.kind != "U" or str(data["unit"]) != "uV":
        raise ValueError("Sleep classifier requires explicit uV input")
    for key in ("subject", "sample_id"):
        v = data[key]
        if v.shape != (len(x),) or v.dtype.kind != "U" or any(not s.strip() or len(s) > 100 for s in v):
            raise ValueError(f"Sleep {key} must be one nonempty string per epoch")
    if len(set(data["sample_id"])) != len(x):
        raise ValueError("Duplicate sleep sample_id")
    if labelled:
        y = data["y"]
        if y.shape != (len(x),) or y.dtype.kind not in "iu" or not np.isin(y, np.arange(5)).all():
            raise ValueError("Sleep y must be integer labels 0=W, 1=N1, 2=N2, 3=N3, 4=REM")
        data["y"] = y.astype("int64")
    return data


def sleep_normalize(x, sigma):
    """Retain epoch amplitudes: epoch demeaning, one clean-training pooled scale."""
    import numpy as np
    a = x.astype(np.float64)
    return ((a - a.mean(axis=1, keepdims=True)) / sigma).astype(np.float32)


def sleep_logits(model, x, batch_size):
    import numpy as np
    import torch
    model.eval()
    with torch.inference_mode():
        result = np.concatenate([model(torch.from_numpy(x[i:i + batch_size, None, :])).numpy()
                                 for i in range(0, len(x), batch_size)])
    if result.shape != (len(x), 5) or not np.isfinite(result).all():
        raise ValueError("Non-finite or incorrectly shaped sleep logits")
    return result


def sleep_nll(logits, labels):
    import numpy as np
    from scipy.special import logsumexp
    z = logits.astype(np.float64)
    return float(np.mean(logsumexp(z, axis=1) - z[np.arange(len(labels)), labels]))


def run_sleep(request, workspace):
    """Fit on train/validation only, or predict from a saved fitted model.

    A caller-supplied seed schedule makes a matched architecture comparison
    possible without changing minibatch order, dropout seeds or epoch budget.
    Test labels, temperature fitting and research conclusions stay downstream.
    """
    import hashlib
    import numpy as np
    import torch
    tier, params, inputs = request["tier"], request["params"], request.get("inputs", {})
    operation = params["operation"]
    if not isinstance(inputs, dict):
        raise ValueError("Sleep inputs must be an object")
    allowed = {"operation", "batch_size", "threads"}
    if operation == "sleep_fit":
        allowed |= {"epochs", "learning_rate", "weight_decay"}
    if set(params) - allowed:
        raise ValueError("Unsupported sleep classifier parameters; preprocessing is fixed")
    threads = _integer(params.get("threads", 1), "threads", 1, 4)
    batch_size = _integer(params.get("batch_size", 128), "batch_size", 1, 128)
    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(True)
    folder = request.get("_output_dir", "runs/science-extensions/braindecode-sleep")
    artifacts = []

    def save(name, value):
        relative = f"{folder}/{name}.json"
        safe_output(workspace, relative).write_text(json.dumps(value, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        artifacts.append(relative)

    def predictions(data, logits):
        return {"sample_id": data["sample_id"].tolist(), "subject": data["subject"].tolist(),
                "logits": logits.tolist(), "class_order": ["W", "N1", "N2", "N3", "REM"]}

    notes = ["Core sleep staging with the upstream Chambon2018 baseline, not a claim of current SOTA.",
             "Single-channel 100 Hz, 30-second epochs. No neighbouring epochs or pretrained weights.",
             "Training-only pooled scale preserves relative epoch amplitude. Evaluate raw confidence and the original quality selector separately."]
    if operation == "sleep_predict":
        if set(inputs) != {"data", "model"}:
            raise ValueError("sleep_predict requires exactly data (unlabelled NPZ) and model (JSON)")
        data = load_sleep_data(workspace, inputs["data"], labelled=False)
        saved = read_json(workspace, inputs["model"])
        if saved.get("schema_version") != 1 or saved.get("architecture") != SLEEP_ARCHITECTURE:
            raise ValueError("Unsupported sleep model architecture")
        sigma = _number(saved.get("training_sigma_uv"), "training_sigma_uv", 1e-12, 1e8)
        seen = saved.get("development_subjects")
        if not isinstance(seen, list) or any(not isinstance(s, str) for s in seen):
            raise ValueError("Sleep model must declare development_subjects")
        if set(data["subject"]) & set(seen):
            raise ValueError("Prediction subjects overlap model training/validation subjects")
        model = sleep_model()
        state = model.state_dict()
        if not isinstance(saved.get("state"), dict) or set(saved["state"]) != set(state):
            raise ValueError("Sleep checkpoint has unexpected tensor keys")
        for key, tensor in state.items():
            value = np.asarray(saved["state"][key], dtype=np.float32)
            if value.shape != tuple(tensor.shape) or not np.isfinite(value).all():
                raise ValueError("Sleep checkpoint has invalid tensor shape or value")
            state[key] = torch.from_numpy(value)
        model.load_state_dict(state)
        count = min(batch_size, len(data["x"])) if tier == 25 else len(data["x"])
        x = sleep_normalize(data["x"][:count], sigma)
        z = sleep_logits(model, x, batch_size)
        subset = {k: data[k][:count] for k in ("sample_id", "subject")}
        save("predictions", {**predictions(subset, z), "preview_only": tier == 25})
        return {"metrics": {"epochs_predicted": count, "epochs_supplied": len(data["x"])},
                "artifacts": artifacts, "notes": notes + ["No labels are accepted for prediction. No test-based model selection or calibration occurs here."]}

    if set(inputs) != {"train", "validation", "schedule"}:
        raise ValueError("sleep_fit requires exactly train, validation (NPZ), and schedule (JSON)")
    train = load_sleep_data(workspace, inputs["train"], labelled=True)
    validation = load_sleep_data(workspace, inputs["validation"], labelled=True)
    if set(train["subject"]) & set(validation["subject"]) or set(train["sample_id"]) & set(validation["sample_id"]):
        raise ValueError("Training and validation subjects/sample IDs must be disjoint")
    if set(train["y"]) != set(range(5)):
        raise ValueError("Training must contain all five sleep stages")
    epochs = _integer(params.get("epochs", 20), "epochs", 1, 30)
    rate = _number(params.get("learning_rate", .001), "learning_rate", 1e-6, .1)
    decay = _number(params.get("weight_decay", .0001), "weight_decay", 0, .1)
    batches = math.ceil(len(train["x"]) / batch_size)
    if batches * epochs > 5000:
        raise ValueError("Sleep training exceeds 5000 optimizer steps")
    schedule = read_json(workspace, inputs["schedule"])
    if not isinstance(schedule, dict) or set(schedule) != {"schema_version", "n_train", "batch_size", "model_init", "minibatch", "dropout"}:
        raise ValueError("Invalid sleep training seed schedule")
    if schedule["schema_version"] != 1 or schedule["n_train"] != len(train["x"]) or schedule["batch_size"] != batch_size:
        raise ValueError("Seed schedule does not match the training data/batch size")
    _integer(schedule["model_init"], "model_init", 0, 2**64 - 1)
    if not isinstance(schedule["minibatch"], list) or len(schedule["minibatch"]) != epochs or not isinstance(schedule["dropout"], list) or len(schedule["dropout"]) != epochs:
        raise ValueError("Seed schedule must cover every training epoch")
    for seed, per_batch in zip(schedule["minibatch"], schedule["dropout"]):
        _integer(seed, "minibatch seed", 0, 2**64 - 1)
        if not isinstance(per_batch, list) or len(per_batch) != batches:
            raise ValueError("Seed schedule must cover every dropout batch")
        for seed in per_batch:
            _integer(seed, "dropout seed", 0, 2**64 - 1)
    a = train["x"].astype(np.float64)
    a -= a.mean(axis=1, keepdims=True)
    sigma = float(np.sqrt(np.square(a).sum(dtype=np.float64) / a.size))
    if not math.isfinite(sigma) or sigma <= 1e-12:
        raise ValueError("Training pooled scale is zero or invalid")
    x, vx = sleep_normalize(train["x"], sigma), sleep_normalize(validation["x"], sigma)
    torch.manual_seed(schedule["model_init"])
    model = sleep_model()
    h = hashlib.sha256()
    for key, tensor in model.state_dict().items():
        h.update(key.encode()); h.update(tensor.numpy().tobytes())
    parameter_count = sum(t.numel() for t in model.parameters())
    if tier == 25:
        save("preview", {"architecture": SLEEP_ARCHITECTURE, "preview_only": True, "trained": False,
                         "logits": sleep_logits(model, vx[:batch_size], batch_size).tolist()})
        return {"metrics": {"parameters": parameter_count, "training_epochs": 0,
                            "train_samples_checked": len(x), "validation_samples_checked": len(vx)},
                "artifacts": artifacts, "notes": notes + ["Tier 25 validates data and untrained forward shapes only; its logits do not measure learned accuracy."]}
    optimizer = torch.optim.AdamW(model.parameters(), lr=rate, weight_decay=decay,
                                   betas=(.9, .999), eps=1e-8, foreach=False, fused=False)
    best, curves, best_state = float("inf"), [], None
    for epoch in range(epochs):
        order = np.random.default_rng(schedule["minibatch"][epoch]).permutation(len(x))
        model.train(); total = 0.
        for batch, start in enumerate(range(0, len(x), batch_size)):
            ix = order[start:start + batch_size]
            torch.manual_seed(schedule["dropout"][epoch][batch])
            optimizer.zero_grad(set_to_none=True)
            z = model(torch.from_numpy(x[ix, None, :]))
            loss = torch.nn.functional.cross_entropy(z, torch.from_numpy(train["y"][ix]))
            if not torch.isfinite(loss):
                raise ValueError("Non-finite sleep training loss")
            loss.backward()
            if any(t.grad is not None and not torch.isfinite(t.grad).all() for t in model.parameters()):
                raise ValueError("Non-finite sleep training gradient")
            optimizer.step(); total += float(loss.detach()) * len(ix)
        logits = sleep_logits(model, vx, batch_size)
        score = sleep_nll(logits, validation["y"])
        curves.append({"epoch": epoch + 1, "train_loss": total / len(x), "validation_nll": score})
        if score < best - 1e-12:
            best, selected = score, epoch + 1
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    logits = sleep_logits(model, vx, batch_size)
    save("model", {"schema_version": 1, "architecture": SLEEP_ARCHITECTURE,
                   "training_sigma_uv": sigma, "development_subjects": sorted(set(train["subject"]) | set(validation["subject"])),
                   "state": {k: v.numpy().tolist() for k, v in model.state_dict().items()}})
    save("validation", {**predictions(validation, logits), "labels": validation["y"].tolist()})
    save("fit", {"architecture": SLEEP_ARCHITECTURE, "initial_sha256": h.hexdigest(), "parameters": parameter_count,
                 "training_sigma_uv": sigma, "selected_epoch": selected, "validation_nll": best, "curves": curves,
                 "train_subjects": sorted(set(train["subject"])), "validation_subjects": sorted(set(validation["subject"])),
                 "selection": "minimum validation NLL, earliest tie; no test input", "threads": threads})
    metrics = {"parameters": parameter_count, "training_epochs": epochs, "selected_epoch": selected,
               "train_samples": len(x), "validation_samples": len(vx), "validation_nll": best}
    if tier == 100:
        confusion = np.zeros((5, 5), dtype=int)
        np.add.at(confusion, (validation["y"], logits.argmax(1)), 1)
        save("validation_qc", {"class_order": ["W", "N1", "N2", "N3", "REM"], "confusion": confusion.tolist(),
                               "train_class_counts": np.bincount(train["y"], minlength=5).tolist(),
                               "validation_class_counts": np.bincount(validation["y"], minlength=5).tolist()})
        metrics["validation_accuracy"] = float(np.trace(confusion) / len(vx))
    return {"metrics": metrics, "artifacts": artifacts, "notes": notes + ["75 trains and selects on validation; 100 adds validation QC without changing the training method. Calibrate on validation logits only, then run sleep_predict on held-out subjects."]}
