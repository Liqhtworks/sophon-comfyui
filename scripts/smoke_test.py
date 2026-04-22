"""End-to-end smoke test for the Sophon client.

Usage:
    export SOPHON_API_KEY=xt_live_...
    python scripts/smoke_test.py path/to/small.mp4 [profile]

Reads key from env only. Never hardcode credentials.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_pkg = Path(__file__).resolve().parent.parent / "comfyui_sophon"
import importlib.util
_spec = importlib.util.spec_from_file_location("sophon_client", _pkg / "client.py")
_mod = importlib.util.module_from_spec(_spec)
sys.modules["sophon_client"] = _mod
_spec.loader.exec_module(_mod)
SophonClient = _mod.SophonClient
SophonError = _mod.SophonError


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: smoke_test.py <video_path> [profile]")
        return 2
    video = Path(sys.argv[1])
    profile = sys.argv[2] if len(sys.argv) > 2 else "sophon-cortado"
    if not video.exists():
        print(f"file not found: {video}")
        return 2

    if not os.environ.get("SOPHON_API_KEY"):
        print("SOPHON_API_KEY not set")
        return 2

    c = SophonClient.from_env()
    print(f"[1/4] uploading {video.name} ({video.stat().st_size} bytes)…")
    t0 = time.time()
    upload_id = c.upload_file(video, progress_cb=lambda i, n: print(f"      part {i}/{n}"))
    print(f"      upload_id={upload_id}  ({time.time()-t0:.1f}s)")

    print(f"[2/4] creating job (profile={profile})…")
    job = c.create_job(upload_id, profile)
    job_id = job["id"]
    print(f"      job_id={job_id}  status={job['status']}")

    print("[3/4] polling…")
    def _show(j):
        p = j.get("progress") or {}
        print(f"      status={j['status']} stage={p.get('stage')} pct={p.get('percent')} fps={p.get('fps')}")
    final = c.poll_job(job_id, interval=3.0, timeout=1800.0, progress_cb=_show)
    if final["status"] != "completed":
        print(f"FAILED: terminal status={final['status']} error={final.get('error')}")
        return 1

    print("[4/4] resolving signed output URL…")
    url = c.get_output_url(job_id)
    print(f"      {url[:80]}…")
    out_bytes = final.get("output", {}).get("bytes")
    src_bytes = final.get("source", {}).get("bytes")
    print(f"source={src_bytes}B  output={out_bytes}B  done in {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SophonError as e:
        print(f"SophonError: {e}")
        sys.exit(1)
