"""HTTP client for the Sophon Encoding API (api.liqhtworks.xyz).

Reference: https://registry.scalar.com/@liqhtworks/apis/sophon-encoding-api@latest
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
import uuid
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import requests

DEFAULT_BASE_URL = "https://api.liqhtworks.xyz"
TERMINAL_STATUSES = {"completed", "failed", "canceled"}

# Signed output URLs are served from Backblaze B2. Clients must only fetch
# job output from these hosts — a poisoned/redirected ``Location`` to any other
# host is refused (defends the local filesystem write that follows it).
_ALLOWED_OUTPUT_HOST_RE = re.compile(r"(^|\.)backblazeb2\.com$", re.IGNORECASE)

_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _assert_allowed_output_host(url: str) -> None:
    """Reject any output URL whose host isn't an allowlisted Backblaze B2 host."""
    host = (urlparse(url).hostname or "").strip()
    if not host or not _ALLOWED_OUTPUT_HOST_RE.search(host):
        raise SophonError(
            502,
            {"error": {"code": "untrusted_output_host",
                       "message": f"refusing to fetch job output from non-allowlisted host: {host!r}"}},
        )


def safe_output_filename(raw: str, default: str) -> str:
    """Reduce a server-supplied ``Content-Disposition`` filename to a safe
    basename. Strips directory components (defeats absolute paths and ``..``),
    drops null bytes/control chars, rejects dot- and Windows-reserved names, and
    allowlists the remaining characters. Falls back to ``default`` when nothing
    safe survives."""
    name = (raw or "").strip().strip('"').strip()
    # Basename only — kills path separators and absolute paths on every OS.
    name = name.replace("\\", "/").split("/")[-1]
    name = name.replace("\x00", "")
    name = "".join(ch for ch in name if ch >= " ")  # drop control chars
    if not name or name in (".", "..") or name.startswith("."):
        return default
    if name.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        return default
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name or default


class SophonError(RuntimeError):
    def __init__(self, status: int, body: dict[str, Any] | str):
        self.status = status
        self.body = body
        code = body.get("error", {}).get("code") if isinstance(body, dict) else "unknown"
        message = body.get("error", {}).get("message") if isinstance(body, dict) else str(body)
        super().__init__(f"Sophon {status} {code}: {message}")


@dataclass
class SophonClient:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 60.0
    allow_insecure: bool = False

    def __post_init__(self) -> None:
        self.base_url = (self.base_url or "").rstrip("/")
        scheme = urlparse(self.base_url).scheme.lower()
        if scheme != "https":
            if not self.allow_insecure:
                raise SophonError(
                    400,
                    {"error": {"code": "insecure_base_url",
                               "message": f"refusing to send the API key over a non-HTTPS base URL ({self.base_url!r}). "
                                          "Pass allow_insecure=True / set SOPHON_ALLOW_INSECURE=1 to override."}},
                )
            warnings.warn(
                f"SophonClient is using an insecure ({scheme or 'no-scheme'}) base URL — the API key is sent in cleartext.",
                stacklevel=2,
            )

    @classmethod
    def from_env(
        cls,
        override: str | None = None,
        base_url: str | None = None,
        allow_insecure: bool | None = None,
    ) -> "SophonClient":
        key = override or os.environ.get("SOPHON_API_KEY", "").strip()
        if not key:
            raise SophonError(401, {"error": {"code": "unauthorized", "message": "SOPHON_API_KEY not set and no override provided"}})
        if allow_insecure is None:
            allow_insecure = os.environ.get("SOPHON_ALLOW_INSECURE", "").strip().lower() in ("1", "true", "yes")
        return cls(
            api_key=key,
            base_url=base_url or os.environ.get("SOPHON_BASE_URL", DEFAULT_BASE_URL),
            allow_insecure=allow_insecure,
        )

    def _headers(self, *, idempotent: bool = False, json_body: bool = True) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self.api_key}"}
        if json_body:
            h["Content-Type"] = "application/json"
        if idempotent:
            h["Idempotency-Key"] = str(uuid.uuid4())
        return h

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.base_url}{path}"
        r = requests.request(method, url, timeout=self.timeout, **kwargs)
        if r.status_code >= 400:
            try:
                raise SophonError(r.status_code, r.json())
            except ValueError:
                raise SophonError(r.status_code, r.text)
        return r

    # ── Uploads (chunked) ───────────────────────────────────────────────

    def create_upload(self, file_name: str, file_size: int, mime_type: str) -> dict[str, Any]:
        r = self._request(
            "POST",
            "/v1/uploads",
            headers=self._headers(idempotent=True),
            json={"file_name": file_name, "file_size": file_size, "mime_type": mime_type},
        )
        return r.json()

    def upload_part(self, upload_id: str, part_number: int, chunk: bytes) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/octet-stream"}
        r = self._request(
            "PUT",
            f"/v1/uploads/{upload_id}/parts/{part_number}",
            headers=headers,
            data=chunk,
        )
        return r.json()

    def complete_upload(self, upload_id: str) -> dict[str, Any]:
        r = self._request(
            "POST",
            f"/v1/uploads/{upload_id}/complete",
            headers=self._headers(idempotent=True, json_body=False),
        )
        return r.json()

    def upload_file(self, path: str | Path, mime_type: str = "video/mp4", progress_cb=None) -> str:
        """Chunked upload helper. Returns upload_id for completed session."""
        p = Path(path)
        size = p.stat().st_size
        session = self.create_upload(p.name, size, mime_type)
        upload_id = session["id"]
        chunk_size = session["chunk_size"]
        total = session["total_chunks"]

        with p.open("rb") as f:
            for i in range(total):
                chunk = f.read(chunk_size)
                self.upload_part(upload_id, i, chunk)
                if progress_cb:
                    progress_cb(i + 1, total)

        self.complete_upload(upload_id)
        return upload_id

    # ── Jobs ────────────────────────────────────────────────────────────

    def create_job(
        self,
        upload_id: str,
        profile: str,
        container: str = "mp4",
        audio: bool = False,
        webhook_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = {
            "source": {"type": "upload", "upload_id": upload_id},
            "profile": profile,
            "output": {"container": container, "audio": audio},
            "webhook_ids": webhook_ids or [],
            "metadata": metadata or {},
        }
        r = self._request("POST", "/v1/jobs", headers=self._headers(idempotent=True), json=body)
        return r.json()

    def get_job(self, job_id: str) -> dict[str, Any]:
        r = self._request("GET", f"/v1/jobs/{job_id}", headers=self._headers(json_body=False))
        return r.json()

    def poll_job(
        self,
        job_id: str,
        interval: float = 2.0,
        timeout: float = 1800.0,
        progress_cb=None,
    ) -> dict[str, Any]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.get_job(job_id)
            if progress_cb:
                progress_cb(job)
            if job["status"] in TERMINAL_STATUSES:
                return job
            time.sleep(interval)
        raise SophonError(408, {"error": {"code": "timeout", "message": f"poll timeout after {timeout}s"}})

    def get_output_url(self, job_id: str) -> str:
        """Returns the signed download URL (the single 302 redirect target).

        The ``Location`` is validated against the Backblaze B2 host allowlist
        before being returned, so every consumer gets a host-checked URL.
        """
        url = f"{self.base_url}/v1/jobs/{job_id}/output"
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            allow_redirects=False,
            timeout=self.timeout,
        )
        if r.status_code == 302:
            location = r.headers.get("Location", "")
            _assert_allowed_output_host(location)
            return location
        try:
            raise SophonError(r.status_code, r.json())
        except ValueError:
            raise SophonError(r.status_code, r.text)

    def download_output(self, job_id: str, dest_dir: str | Path) -> str:
        """Fetch the signed output URL and save it under dest_dir. Returns the
        local path. The signed host is re-checked and the GET does not follow
        further redirects; the server-supplied filename is sanitized and the
        resolved write path is asserted to stay inside dest_dir."""
        signed = self.get_output_url(job_id)
        _assert_allowed_output_host(signed)  # defense in depth
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_root = dest_dir.resolve()
        # allow_redirects=False: do not become an open follower past the one
        # validated B2 hop. A redirect here is unexpected → treated as an error.
        with requests.get(signed, stream=True, timeout=self.timeout, allow_redirects=False) as r:
            if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
                raise SophonError(502, {"error": {"code": "unexpected_redirect",
                                                  "message": "output host issued an unexpected redirect"}})
            r.raise_for_status()
            cd = r.headers.get("Content-Disposition", "")
            raw = cd.split("filename=", 1)[1] if "filename=" in cd else ""
            fname = safe_output_filename(raw, f"{job_id}.mp4")
            out = dest_dir / fname
            if not out.resolve().is_relative_to(dest_root):
                raise SophonError(500, {"error": {"code": "unsafe_path",
                                                  "message": "refusing to write output outside the destination directory"}})
            with out.open("wb") as f:
                for block in r.iter_content(chunk_size=1 << 20):
                    f.write(block)
        return str(out)


def verify_webhook(
    secret: str,
    timestamp: str,
    raw_body: bytes,
    signature_header: str,
    *,
    max_age_seconds: float | None = 300.0,
    now: float | None = None,
) -> bool:
    """Verify the ``X-Turbo-Signature-256`` header (``sha256=<hex>``).

    Replay protection: the signed ``timestamp`` (unix epoch seconds) must be
    within ``max_age_seconds`` of now, so a captured-and-replayed delivery is
    rejected even though its signature is intact. Pass ``max_age_seconds=None``
    to skip the freshness check. Uses a constant-time compare throughout.
    """
    if not signature_header.startswith("sha256="):
        return False
    if max_age_seconds is not None:
        try:
            ts = float(timestamp)
        except (TypeError, ValueError):
            return False
        current = time.time() if now is None else now
        if abs(current - ts) > max_age_seconds:
            return False
    expected = signature_header.split("=", 1)[1]
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, mac)
