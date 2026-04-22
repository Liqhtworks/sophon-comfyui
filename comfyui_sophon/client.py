"""HTTP client for the Sophon Encoding API (api.liqhtworks.xyz).

Reference: https://registry.scalar.com/@liqhtworks/apis/sophon-encoding-api@latest
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import requests

DEFAULT_BASE_URL = "https://api.liqhtworks.xyz"
TERMINAL_STATUSES = {"completed", "failed", "canceled"}


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

    @classmethod
    def from_env(cls, override: str | None = None, base_url: str | None = None) -> "SophonClient":
        key = override or os.environ.get("SOPHON_API_KEY", "").strip()
        if not key:
            raise SophonError(401, {"error": {"code": "unauthorized", "message": "SOPHON_API_KEY not set and no override provided"}})
        return cls(api_key=key, base_url=base_url or os.environ.get("SOPHON_BASE_URL", DEFAULT_BASE_URL))

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
        """Returns the signed download URL (following the 302 redirect)."""
        url = f"{self.base_url}/v1/jobs/{job_id}/output"
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            allow_redirects=False,
            timeout=self.timeout,
        )
        if r.status_code == 302:
            return r.headers["Location"]
        try:
            raise SophonError(r.status_code, r.json())
        except ValueError:
            raise SophonError(r.status_code, r.text)

    def download_output(self, job_id: str, dest_dir: str | Path) -> str:
        """Follow the signed URL and save to dest_dir. Returns local path."""
        signed = self.get_output_url(job_id)
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Filename from Content-Disposition, fallback to job_id
        with requests.get(signed, stream=True, timeout=self.timeout) as r:
            r.raise_for_status()
            cd = r.headers.get("Content-Disposition", "")
            fname = f"{job_id}.mp4"
            if "filename=" in cd:
                fname = cd.split("filename=", 1)[1].strip().strip('"')
            out = dest_dir / fname
            with out.open("wb") as f:
                for block in r.iter_content(chunk_size=1 << 20):
                    f.write(block)
        return str(out)


def verify_webhook(secret: str, timestamp: str, raw_body: bytes, signature_header: str) -> bool:
    """Verify X-Turbo-Signature-256 header (sha256=<hex>)."""
    if not signature_header.startswith("sha256="):
        return False
    expected = signature_header.split("=", 1)[1]
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, mac)
