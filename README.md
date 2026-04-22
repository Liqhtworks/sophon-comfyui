# ComfyUI-Sophon

ComfyUI custom nodes for the [Sophon](https://sophon.liqhtworks.xyz) HEVC encoding API by Liqhtworks. Built against the V3 ComfyUI schema (`comfy_api.latest`) for forward compatibility with Comfy Cloud.

---

## Quick install (one command)

For **ComfyUI Desktop** on Windows, macOS, or Linux:

```bash
# Clone anywhere, then run the installer. It auto-detects your ComfyUI Desktop
# install, copies the repo into custom_nodes/, and registers it in the bundled venv.
git clone https://github.com/hamchowderr/ComfyUI-Sophon.git
python ComfyUI-Sophon/scripts/install.py
```

The installer will:
1. Find your ComfyUI Desktop base path from its `config.json`
2. Clone the repo into `<base-path>/custom_nodes/ComfyUI-Sophon` (or pull latest if it already exists)
3. `pip install -e` into ComfyUI's bundled Python venv so the V3 entry point registers

Then **fully close and relaunch ComfyUI Desktop**. Search `Sophon` in the node menu — you should see all five nodes.

If auto-detect fails (non-standard install location), pass the path explicitly:

```bash
python ComfyUI-Sophon/scripts/install.py --base-path "/path/to/your/ComfyUI"
```

### Manual install

If you don't use ComfyUI Desktop or prefer doing it by hand:

```bash
cd <your-ComfyUI>/custom_nodes
git clone https://github.com/hamchowderr/ComfyUI-Sophon
pip install -e ComfyUI-Sophon
```

---

## For Claude Code / Codex / Cursor agents

Paste this prompt into your coding agent to have it install the node for you:

> Install the ComfyUI-Sophon custom node into my local ComfyUI Desktop instance. Clone `https://github.com/hamchowderr/ComfyUI-Sophon` to a working directory, then run `python ComfyUI-Sophon/scripts/install.py`. If auto-detection fails, find my ComfyUI Desktop base path from `%APPDATA%\ComfyUI\config.json` on Windows (or equivalent on macOS/Linux) and pass it via `--base-path`. After install, confirm the five Sophon nodes load without errors and tell me to restart ComfyUI Desktop.

---

## Getting an API key

```bash
# Windows PowerShell (persists across sessions)
setx SOPHON_API_KEY "sk_..."
# macOS / Linux
export SOPHON_API_KEY=sk_...

# Optional: override the API base URL
export SOPHON_BASE_URL=https://api.liqhtworks.xyz
```

Or paste the key into any node's `api_key` field at the workflow level (saved into the workflow JSON). Never commit workflows that contain a real key.

---

## Nodes

| Node | Purpose |
|------|---------|
| `Sophon Upload` | Chunked upload of a local video → `upload_id` |
| `Sophon Encode` | Submit job for an `upload_id`, poll to completion → `job_id`, `status`, `output_url` |
| `Sophon Job Status` | Non-blocking status check for an existing `job_id` |
| `Sophon Download Output` | Resolve signed URL and optionally save to ComfyUI's output dir |
| `Sophon Encode Video (one-shot)` | Upload → encode → download in a single node |

The `Sophon Upload` and `Sophon Encode Video` nodes show a **dropdown of videos from ComfyUI's `input/` folder** — drop any `.mp4`, `.mov`, `.mkv`, `.webm`, `.avi`, `.m4v`, `.mpg`, `.mpeg`, `.ts`, or `.flv` file there and it appears in the dropdown on next open.

Progress bars are wired into the upload and poll loops via `comfy.utils.ProgressBar`.

---

## Profiles

8-bit (default, universal decoder compatibility):

- `sophon-espresso` — fastest, lowest compression
- `sophon-cortado` — balanced
- `sophon-americano` — slowest, highest compression

10-bit (HEVC Main10):

- `sophon-espresso-10bit`
- `sophon-cortado-10bit`
- `sophon-americano-10bit`

---

## Testing workflow (for the team)

1. Install via the Quick install section above.
2. Drop a short test video into `<ComfyUI>/input/`.
3. In ComfyUI, double-click the canvas → type `Sophon` → pick **`Sophon Encode Video (one-shot)`**.
4. Pick the video from the `video` dropdown, choose a profile (`sophon-espresso` is fastest for smoke tests), paste your API key, click **Queue**.
5. Result lands in `<ComfyUI>/output/`.

### Reporting issues

Anything that doesn't work — missing field, bad error, crash, unexpected output — **open an issue on GitHub** with:
- ComfyUI version (see the startup log line `ComfyUI version: …`)
- Operating system
- Exact node settings used
- Full error text from the ComfyUI console

Maintainer pushes a fix → re-run `python ComfyUI-Sophon/scripts/install.py` to pull the latest and re-register.

---

## Webhooks

The Sophon API uses pre-registered webhooks (`POST /v1/webhooks`) referenced by ID on job creation. This is unsuitable for spinning up a listener inside a ComfyUI workflow. If you maintain a public endpoint, register it once and pass its ID via the `webhook_ids` input — the node still polls so it can return a deterministic result, but your listener will also receive the terminal delivery.

Signature verification helper is exported at `comfyui_sophon.client.verify_webhook`.

---

## Comfy Cloud notes

- All nodes are pure server-side Python with no client↔server messaging, so they satisfy the Cloud/API compatibility requirement.
- Polling is the default and only reliable completion strategy on Cloud (ephemeral instances cannot accept inbound webhooks).
- `SOPHON_API_KEY` must be provisioned as a Cloud secret.

---

## Publish to Comfy Registry

```bash
comfy node publish
```

Ensure `pyproject.toml` `PublisherId` matches your Comfy Registry account.
