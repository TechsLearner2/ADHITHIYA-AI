"""Generate an image with the LLM provider and save it to the Pictures folder."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from memory.config_manager import load_api_keys



def _api_key() -> str:
    try:
        from core.llm import get_api_key
        return str(get_api_key() or "")
    except Exception:
        return ""


def _save_image(image_bytes: bytes, prompt: str) -> str:
    out_dir = Path.home() / "Pictures" / "ADHITHIYA"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"adhithiya_{datetime.now():%Y%m%d_%H%M%S}.png"
    path.write_bytes(image_bytes)
    return str(path)


def image_generate(parameters: dict, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    prompt = str(params.get("prompt", "")).strip()
    if not prompt:
        return "Tell me what to draw (prompt)."

    api_key = _api_key()
    if not api_key:
        return "No API key is configured, so I can't generate images."

    if player:
        player.write_log(f"[Image] {prompt[:100]}")

    try:
        from core.llm import generate_image
        image_bytes = generate_image(prompt)
        path = _save_image(image_bytes, prompt)
        return f"Image saved: {path}"
    except Exception as e:  # noqa: BLE001
        return f"Image generation failed: {e}"
