"""Sophon encoding nodes (V3 schema)."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from comfy_api.latest import ComfyExtension, io

from .client import SophonClient

PROFILES = [
    "sophon-espresso",
    "sophon-cortado",
    "sophon-americano",
    "sophon-espresso-10bit",
    "sophon-cortado-10bit",
    "sophon-americano-10bit",
]


def _default_output_dir() -> str:
    try:
        import folder_paths  # type: ignore

        return folder_paths.get_output_directory()
    except Exception:
        return str(Path.cwd() / "output")


VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".ts", ".flv")


def _input_dir() -> str:
    try:
        import folder_paths  # type: ignore

        return folder_paths.get_input_directory()
    except Exception:
        return str(Path.cwd() / "input")


def _list_input_videos() -> list[str]:
    root = Path(_input_dir())
    if not root.is_dir():
        return ["<no videos in input/>"]
    files = [
        str(p.relative_to(root)).replace("\\", "/")
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    ]
    return sorted(files) or ["<no videos in input/>"]


def _resolve_video_path(video: str) -> str:
    if not video or video.startswith("<no videos"):
        raise RuntimeError("No video selected. Drop a file into ComfyUI's input/ folder.")
    p = Path(video)
    if p.is_absolute() and p.exists():
        return str(p)
    candidate = Path(_input_dir()) / video
    if candidate.exists():
        return str(candidate)
    if p.exists():
        return str(p)
    raise FileNotFoundError(f"Video not found: {video}")


def _client(api_key: str) -> SophonClient:
    return SophonClient.from_env(override=api_key or None)


def _nonce() -> str:
    # Force ComfyUI to always re-run API-call nodes — results are not deterministic.
    return uuid.uuid4().hex


def _progress_bar(total: int):
    try:
        from comfy.utils import ProgressBar  # type: ignore

        return ProgressBar(total)
    except Exception:
        return None


# ─── SophonUpload ────────────────────────────────────────────────────────

class SophonUpload(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SophonUpload",
            display_name="Sophon Upload",
            category="sophon",
            description="Chunked upload of a local video file to the Sophon API. Returns upload_id.",
            inputs=[
                io.Combo.Input("video", options=_list_input_videos(), tooltip="Video from ComfyUI input/ folder."),
                io.String.Input("mime_type", multiline=False, default="video/mp4"),
                io.String.Input("api_key", multiline=False, default="", tooltip="Bearer API key. Leave empty to use $SOPHON_API_KEY."),
            ],
            outputs=[io.String.Output(display_name="upload_id")],
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs) -> Any:
        return _nonce()

    @classmethod
    def execute(cls, video: str, mime_type: str, api_key: str) -> io.NodeOutput:
        client = _client(api_key)
        path = _resolve_video_path(video)
        # Determine part count for progress bar
        size = Path(path).stat().st_size
        # We don't know chunk_size until create_upload — use a two-phase approach.
        pbar_holder = {"bar": None}

        def cb(done: int, total: int) -> None:
            if pbar_holder["bar"] is None:
                pbar_holder["bar"] = _progress_bar(total)
            bar = pbar_holder["bar"]
            if bar is not None:
                bar.update_absolute(done, total)

        upload_id = client.upload_file(path, mime_type=mime_type, progress_cb=cb)
        return io.NodeOutput(upload_id)


# ─── SophonEncode ────────────────────────────────────────────────────────

class SophonEncode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SophonEncode",
            display_name="Sophon Encode",
            category="sophon",
            description="Submit a transcoding job for an existing upload_id, then poll to completion.",
            inputs=[
                io.String.Input("upload_id", multiline=False),
                io.Combo.Input("profile", options=PROFILES, default="sophon-cortado"),
                io.Combo.Input("container", options=["mp4", "mkv"], default="mp4"),
                io.Boolean.Input("audio", default=False),
                io.String.Input("webhook_ids", multiline=False, default="", tooltip="Comma-separated webhook IDs (optional)."),
                io.Int.Input("poll_interval", default=2, min=1, max=60),
                io.Int.Input("timeout_seconds", default=1800, min=30, max=7200),
                io.String.Input("api_key", multiline=False, default=""),
            ],
            outputs=[
                io.String.Output(display_name="job_id"),
                io.String.Output(display_name="status"),
                io.String.Output(display_name="output_url"),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs) -> Any:
        return _nonce()

    @classmethod
    def execute(
        cls,
        upload_id: str,
        profile: str,
        container: str,
        audio: bool,
        webhook_ids: str,
        poll_interval: int,
        timeout_seconds: int,
        api_key: str,
    ) -> io.NodeOutput:
        client = _client(api_key)
        ids = [x.strip() for x in webhook_ids.split(",") if x.strip()]
        job = client.create_job(upload_id, profile, container=container, audio=audio, webhook_ids=ids)
        job_id = job["id"]
        bar = _progress_bar(100)

        def cb(j: dict[str, Any]) -> None:
            if bar is None:
                return
            pct = ((j.get("progress") or {}).get("percent") or 0.0)
            bar.update_absolute(int(pct), 100)

        final = client.poll_job(job_id, interval=float(poll_interval), timeout=float(timeout_seconds), progress_cb=cb)
        status = final["status"]
        url = client.get_output_url(job_id) if status == "completed" else ""
        return io.NodeOutput(job_id, status, url)


# ─── SophonJobStatus ─────────────────────────────────────────────────────

class SophonJobStatus(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SophonJobStatus",
            display_name="Sophon Job Status",
            category="sophon",
            description="One-shot status check for an existing job_id.",
            inputs=[
                io.String.Input("job_id", multiline=False),
                io.String.Input("api_key", multiline=False, default=""),
            ],
            outputs=[
                io.String.Output(display_name="status"),
                io.Float.Output(display_name="percent"),
                io.String.Output(display_name="stage"),
                io.Float.Output(display_name="fps"),
                io.Int.Output(display_name="eta_seconds"),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs) -> Any:
        return _nonce()

    @classmethod
    def execute(cls, job_id: str, api_key: str) -> io.NodeOutput:
        client = _client(api_key)
        job = client.get_job(job_id)
        progress = job.get("progress") or {}
        return io.NodeOutput(
            job.get("status", "unknown"),
            float(progress.get("percent") or 0.0),
            str(progress.get("stage") or ""),
            float(progress.get("fps") or 0.0),
            int(progress.get("eta_seconds") or 0),
        )


# ─── SophonDownloadOutput ────────────────────────────────────────────────

class SophonDownloadOutput(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SophonDownloadOutput",
            display_name="Sophon Download Output",
            category="sophon",
            description="Resolve the signed output URL and optionally download locally.",
            is_output_node=True,
            inputs=[
                io.String.Input("job_id", multiline=False),
                io.Boolean.Input("download", default=True, tooltip="If true, save to ComfyUI output dir."),
                io.String.Input("output_dir", multiline=False, default="", tooltip="Override output dir. Empty = ComfyUI default."),
                io.String.Input("api_key", multiline=False, default=""),
            ],
            outputs=[
                io.String.Output(display_name="output_url"),
                io.String.Output(display_name="local_path"),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs) -> Any:
        return _nonce()

    @classmethod
    def execute(cls, job_id: str, download: bool, output_dir: str, api_key: str) -> io.NodeOutput:
        client = _client(api_key)
        url = client.get_output_url(job_id)
        local = ""
        if download:
            dest = output_dir.strip() or _default_output_dir()
            local = client.download_output(job_id, dest)
        return io.NodeOutput(url, local)


# ─── SophonEncodeVideo (one-shot convenience) ────────────────────────────

class SophonEncodeVideo(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SophonEncodeVideo",
            display_name="Sophon Encode Video (one-shot)",
            category="sophon",
            description="Upload → encode → download in a single node.",
            is_output_node=True,
            inputs=[
                io.Combo.Input("video", options=_list_input_videos(), tooltip="Video from ComfyUI input/ folder."),
                io.Combo.Input("profile", options=PROFILES, default="sophon-cortado"),
                io.Combo.Input("container", options=["mp4", "mkv"], default="mp4"),
                io.Boolean.Input("audio", default=False),
                io.Boolean.Input("download", default=True),
                io.String.Input("output_dir", multiline=False, default=""),
                io.Int.Input("poll_interval", default=2, min=1, max=60),
                io.Int.Input("timeout_seconds", default=1800, min=30, max=7200),
                io.String.Input("api_key", multiline=False, default=""),
            ],
            outputs=[
                io.String.Output(display_name="job_id"),
                io.String.Output(display_name="output_url"),
                io.String.Output(display_name="local_path"),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs) -> Any:
        return _nonce()

    @classmethod
    def execute(
        cls,
        video: str,
        profile: str,
        container: str,
        audio: bool,
        download: bool,
        output_dir: str,
        poll_interval: int,
        timeout_seconds: int,
        api_key: str,
    ) -> io.NodeOutput:
        client = _client(api_key)
        path = _resolve_video_path(video)

        # Two-phase progress bar: 0-50% upload, 50-100% encode.
        upload_pbar = {"bar": None}

        def upload_cb(done: int, total: int) -> None:
            if upload_pbar["bar"] is None:
                upload_pbar["bar"] = _progress_bar(100)
            bar = upload_pbar["bar"]
            if bar is not None:
                bar.update_absolute(int(50 * done / max(total, 1)), 100)

        upload_id = client.upload_file(path, progress_cb=upload_cb)

        job = client.create_job(upload_id, profile, container=container, audio=audio)
        job_id = job["id"]
        encode_bar = upload_pbar["bar"] or _progress_bar(100)

        def encode_cb(j: dict[str, Any]) -> None:
            if encode_bar is None:
                return
            pct = ((j.get("progress") or {}).get("percent") or 0.0)
            encode_bar.update_absolute(int(50 + 50 * pct / 100.0), 100)

        final = client.poll_job(job_id, interval=float(poll_interval), timeout=float(timeout_seconds), progress_cb=encode_cb)
        if final["status"] != "completed":
            raise RuntimeError(f"Sophon job {job_id} ended with status {final['status']}: {final.get('error')}")
        url = client.get_output_url(job_id)
        local = ""
        if download:
            dest = output_dir.strip() or _default_output_dir()
            local = client.download_output(job_id, dest)
        if encode_bar is not None:
            encode_bar.update_absolute(100, 100)
        return io.NodeOutput(job_id, url, local)


class SophonExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [
            SophonUpload,
            SophonEncode,
            SophonJobStatus,
            SophonDownloadOutput,
            SophonEncodeVideo,
        ]
