"""Sophon encoding nodes (V3 schema)."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from comfy_api.latest import ComfyExtension, io

from .client import SophonClient

PROFILES = [
    "sophon-auto",
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


def _resolve_output_dir(output_dir: str) -> str:
    """Resolve user-supplied output_dir. Relative paths anchor to ComfyUI's
    output directory (not process CWD, which is unpredictable)."""
    if not output_dir or not output_dir.strip():
        return _default_output_dir()
    p = Path(output_dir.strip())
    if p.is_absolute():
        return str(p)
    return str(Path(_default_output_dir()) / p)


def _preview_result(local_path: str) -> dict | None:
    """Build a preview descriptor for the ComfyUI /view endpoint if the file
    lives under ComfyUI's output directory; otherwise return None.

    We produce a plain dict (not SavedResult) so we can attach a ``format``
    hint — the frontend uses that to pick the <video> element and scale the
    player to fit the node width instead of rendering as a still image.
    """
    if not local_path:
        return None
    try:
        abs_path = Path(local_path).resolve()
        out_root = Path(_default_output_dir()).resolve()
        rel = abs_path.relative_to(out_root)
    except (ValueError, OSError):
        return None
    subfolder = str(rel.parent).replace("\\", "/")
    if subfolder == ".":
        subfolder = ""
    ext = abs_path.suffix.lower().lstrip(".") or "mp4"
    return {
        "filename": rel.name,
        "subfolder": subfolder,
        "type": io.FolderType.output.value,
        "format": f"video/{ext}",
        "fullpath": str(abs_path),
    }


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{int(n):,} B" if unit == "B" else f"{n:,.2f} {unit}"
        n /= 1024
    return f"{n:,.2f} PB"


def _format_stats(job: dict[str, Any]) -> str:
    """Render source/output size, savings, and bitrate from a JobResponse."""
    src = job.get("source") or {}
    out = job.get("output") or {}
    src_bytes = src.get("bytes")
    out_bytes = out.get("bytes")
    duration = src.get("duration_seconds")
    lines: list[str] = []
    if src_bytes is not None:
        lines.append(f"Source: {_fmt_bytes(src_bytes)}")
    if out_bytes is not None:
        lines.append(f"Output: {_fmt_bytes(out_bytes)}")
    if src_bytes and out_bytes:
        savings = (1.0 - float(out_bytes) / float(src_bytes)) * 100.0
        lines.append(f"Savings: {savings:.1f}%")
    if duration and duration > 0:
        if src_bytes is not None:
            lines.append(f"Source bitrate: {(src_bytes * 8) / duration / 1000:,.0f} kbps")
        if out_bytes is not None:
            lines.append(f"Output bitrate: {(out_bytes * 8) / duration / 1000:,.0f} kbps")
    eff = job.get("effective_profile_id")
    profile = job.get("profile")
    if eff and eff != profile:
        lines.append(f"Effective profile: {eff}")
    return "\n".join(lines)


def _build_preview_ui(local_path: str, job: dict[str, Any]) -> dict | None:
    """Compose a ui dict the sophon-preview.js extension knows how to render.

    All keys are namespaced (``sophon_video``, ``sophon_stats``) so no core
    UI renderer touches the payload — otherwise the legacy queue/history
    menu renders a duplicate floating preview at the top of the canvas.
    """
    payload: dict[str, Any] = {}
    sr = _preview_result(local_path)
    if sr is not None:
        payload["sophon_video"] = [sr]
    stats = _format_stats(job)
    if stats:
        payload["sophon_stats"] = [stats]
    return payload or None


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
                io.Combo.Input(
                    "video",
                    options=_list_input_videos(),
                    upload=io.UploadType.video,
                    image_folder=io.FolderType.input,
                    tooltip="Video from ComfyUI input/ folder, or click 'choose file to upload'.",
                ),
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
        stats = _format_stats(final)
        if stats:
            return io.NodeOutput(job_id, status, url, ui={"sophon_stats": [stats]})
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
        job = client.get_job(job_id)
        if download:
            local = client.download_output(job_id, _resolve_output_dir(output_dir))
        payload = _build_preview_ui(local, job)
        if payload is not None:
            return io.NodeOutput(url, local, ui=payload)
        return io.NodeOutput(url, local)


# ─── SophonEncodeVideo (one-shot convenience) ────────────────────────────

class SophonEncodeVideo(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SophonEncodeVideo",
            display_name="Sophon Encode Video",
            category="sophon",
            description="Upload → encode → download in a single node.",
            is_output_node=True,
            inputs=[
                io.Combo.Input(
                    "video",
                    options=_list_input_videos(),
                    upload=io.UploadType.video,
                    image_folder=io.FolderType.input,
                    tooltip="Video from ComfyUI input/ folder, or click 'choose file to upload'.",
                ),
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
            local = client.download_output(job_id, _resolve_output_dir(output_dir))
        if encode_bar is not None:
            encode_bar.update_absolute(100, 100)
        payload = _build_preview_ui(local, final)
        if payload is not None:
            return io.NodeOutput(job_id, url, local, ui=payload)
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
