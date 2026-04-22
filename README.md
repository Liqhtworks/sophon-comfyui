# ComfyUI-Sophon

ComfyUI custom nodes for the [Sophon](https://sophon.liqhtworks.xyz) HEVC encoding API by Liqhtworks. Built against the V3 ComfyUI schema (`comfy_api.latest`) for future-proofing and Comfy Cloud submission.

## Install

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/hamchowderr/ComfyUI-Sophon
pip install -r ComfyUI-Sophon/requirements.txt
```

Set your API key (never commit it):

```bash
export SOPHON_API_KEY=sk_...
# optional override
export SOPHON_BASE_URL=https://api.liqhtworks.xyz
```

Or paste the key into any node's `api_key` field at the workflow level.

## Nodes

| Node | Purpose |
|------|---------|
| `SophonUpload` | Chunked upload of a local video → `upload_id` |
| `SophonEncode` | Submit job for an `upload_id`, poll to completion → `job_id`, `status`, `output_url` |
| `SophonJobStatus` | Non-blocking status check for an existing `job_id` |
| `SophonDownloadOutput` | Resolve signed URL and optionally save to ComfyUI's output dir |
| `SophonEncodeVideo` | One-shot: upload → encode → download in a single node |

## Profiles

8-bit (default, universal decoder compatibility):

- `sophon-espresso` — fastest, lowest compression
- `sophon-cortado` — balanced
- `sophon-americano` — slowest, highest compression

10-bit (HEVC Main10):

- `sophon-espresso-10bit`
- `sophon-cortado-10bit`
- `sophon-americano-10bit`

## Webhooks

The Sophon API uses pre-registered webhooks (`POST /v1/webhooks`) referenced by ID on job creation. This is unsuitable for spinning up a listener inside a ComfyUI workflow. If you maintain a public endpoint, register it once and pass its ID via the `webhook_ids` input — the node still polls so it can return a deterministic result, but your listener will also receive the terminal delivery.

Signature verification helper is exported at `comfyui_sophon.client.verify_webhook`.

## Comfy Cloud notes

- All nodes are pure server-side Python with no client↔server messaging, so they satisfy the Cloud/API compatibility requirement.
- Polling is the default and only reliable completion strategy on Cloud (ephemeral instances cannot accept inbound webhooks).
- `SOPHON_API_KEY` must be provisioned as a Cloud secret.

## Publish to Comfy Registry

```bash
comfy node publish
```

Ensure `pyproject.toml` `PublisherId` matches your Comfy Registry account.
