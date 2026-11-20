"""Workspace-bound I/O shared by science extensions (standard library only)."""
from __future__ import annotations

import json
from pathlib import Path


def safe_input(workspace: Path, relative: str) -> Path:
    root = Path(workspace).resolve(strict=True)
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or "\\" in relative:
        raise ValueError("Input must be a nonempty workspace-relative POSIX path")
    parts = Path(relative).parts
    if not parts or ".." in parts or ":" in relative:
        raise ValueError("Input path may not leave the workspace")
    path = root.joinpath(relative)
    cursor = root
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("Symbolic links are not extension inputs")
    resolved = path.resolve(strict=True)
    resolved.relative_to(root)
    return resolved


def safe_output(workspace: Path, relative: str) -> Path:
    root = Path(workspace).resolve(strict=True)
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or "\\" in relative:
        raise ValueError("Output must be a workspace-relative POSIX path")
    if not Path(relative).parts or ".." in Path(relative).parts or ":" in relative:
        raise ValueError("Output path may not leave the workspace")
    cursor = root
    for part in Path(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("Symbolic links are not extension outputs")
    path = cursor.resolve()
    path.relative_to(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def read_json(workspace: Path, relative: str):
    path = safe_input(workspace, relative)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("JSON input exceeds the 16 MiB per-file limit")
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=lambda s: (_ for _ in ()).throw(ValueError(f"Non-finite JSON: {s}")))
