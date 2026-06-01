# Security Policy

`ComfyUI-Sophon` is a **third-party community node package**. It is published by
Otaku Solutions / Liqhtworks as a client for the [Sophon](https://sophon.liqhtworks.xyz)
encoding API. It is **not** affiliated with, endorsed by, or maintained by the
ComfyUI project.

## Trust boundary

- The package sends your video uploads and your Sophon **API key** (a billing
  identity) to `https://api.liqhtworks.xyz`. Treat your API key like a password.
- Prefer the `SOPHON_API_KEY` environment variable over typing the key into a
  node field — a key typed into a node is saved into the workflow `.json` in
  plaintext, and workflows are frequently shared and committed.
- Encoded output is fetched only from Backblaze B2 hosts (`*.backblazeb2.com`)
  and written only inside the directory you choose; server-supplied filenames
  are sanitized before any write.

## Supported versions

Only the latest release on `main` is supported with security fixes. Pin
dependencies via the shipped `requirements.txt` (exact-pinned) for reproducible,
known-good installs.

## Reporting a vulnerability

Please report privately — **do not** open a public GitHub issue for security
problems.

1. **Preferred:** GitHub → the repository's **Security** tab → **Report a
   vulnerability** (private GitHub Security Advisory).
2. **Email:** `admin@otakusolutions.io` with a description, affected version/
   commit, and reproduction steps.

We aim to acknowledge reports within a few business days and will coordinate a
fix and disclosure timeline with you. Please allow reasonable time to remediate
before any public disclosure.
