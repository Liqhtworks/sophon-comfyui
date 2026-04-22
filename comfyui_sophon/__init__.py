"""ComfyUI-Sophon — Sophon HEVC encoding API nodes (V3 schema)."""

from .nodes import SophonExtension


async def comfy_entrypoint() -> SophonExtension:
    return SophonExtension()
