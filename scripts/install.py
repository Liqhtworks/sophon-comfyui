"""Install ComfyUI-Sophon into a local ComfyUI Desktop install.

Usage:
    python scripts/install.py
    python scripts/install.py --base-path "/path/to/ComfyUI"

Detects ComfyUI Desktop base path from its config.json on Windows/macOS/Linux,
clones or updates this repo into <base-path>/custom_nodes/ComfyUI-Sophon, then
installs it into ComfyUI's bundled Python venv so the V3 entry point registers.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_URL = "https://github.com/hamchowderr/ComfyUI-Sophon"
REPO_DIR_NAME = "ComfyUI-Sophon"


def _desktop_config_path() -> Path | None:
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "ComfyUI" / "config.json"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "ComfyUI" / "config.json"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        return Path(xdg) / "ComfyUI" / "config.json"
    return None


def detect_base_path() -> Path | None:
    cfg = _desktop_config_path()
    if cfg and cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            bp = data.get("basePath")
            if bp:
                return Path(bp)
        except Exception:
            pass
    return None


def detect_venv_python(base_path: Path) -> Path | None:
    candidates = [
        base_path / ".venv" / "Scripts" / "python.exe",  # Windows
        base_path / ".venv" / "bin" / "python",  # POSIX
        base_path / "venv" / "Scripts" / "python.exe",
        base_path / "venv" / "bin" / "python",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print(f"$ {' '.join(str(c) for c in cmd)}")
    subprocess.check_call(cmd, cwd=str(cwd) if cwd else None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-path", type=Path, help="ComfyUI base dir (auto-detected if omitted).")
    ap.add_argument("--branch", default="main", help="Branch to check out (default: main).")
    args = ap.parse_args()

    base = args.base_path or detect_base_path()
    if not base:
        print(
            "ERROR: Could not auto-detect ComfyUI Desktop base path.\n"
            "       Pass it explicitly: python scripts/install.py --base-path /path/to/ComfyUI",
            file=sys.stderr,
        )
        return 2
    if not base.is_dir():
        print(f"ERROR: base path does not exist: {base}", file=sys.stderr)
        return 2

    custom_nodes = base / "custom_nodes"
    custom_nodes.mkdir(exist_ok=True)
    target = custom_nodes / REPO_DIR_NAME

    print(f"ComfyUI base path: {base}")
    print(f"Target:            {target}")

    if target.exists():
        if (target / ".git").is_dir():
            print("Existing checkout found — pulling latest.")
            run(["git", "fetch", "--all"], cwd=target)
            run(["git", "checkout", args.branch], cwd=target)
            run(["git", "pull", "--ff-only"], cwd=target)
        else:
            print("Existing non-git folder found — removing and re-cloning.")
            shutil.rmtree(target)
            run(["git", "clone", "--branch", args.branch, REPO_URL, str(target)])
    else:
        run(["git", "clone", "--branch", args.branch, REPO_URL, str(target)])

    py = detect_venv_python(base)
    if py is None:
        print("WARN: Could not find ComfyUI's Python venv. Skipping pip install.", file=sys.stderr)
        print("      Install manually: pip install -e " + str(target), file=sys.stderr)
    else:
        print(f"Python venv:       {py}")
        run([str(py), "-m", "pip", "install", "-e", str(target)])

    print("\n✓ Installed ComfyUI-Sophon.")
    print("  1. Fully close and relaunch ComfyUI Desktop.")
    print("  2. Double-click the canvas, search 'Sophon', drop 'Sophon Encode Video (one-shot)'.")
    print("  3. Set SOPHON_API_KEY env var OR paste your key into the node's api_key field.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
