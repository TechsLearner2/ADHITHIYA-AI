"""Generate an image with Gemini Imagen and save it to the Pictures folder."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from memory.config_manager import load_api_keys

_MODELS = ("imagen-3.0-generate-002", "imagen-3.0-generate-001", "imagegeneration")


def _api_key() -> str:
    try:
        return str(load_api_keys().get("gemini_api_key", "") or "")
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
        return "No Gemini API key is configured, so I can't generate images."

    if player:
        player.write_log(f"[Image] {prompt[:100]}")

    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)

        last_error = ""
        for model in _MODELS:
            try:
                resp = client.models.generate_images(
                    model=model,
                    prompt=prompt,
                    config=types.GenerateImagesConfig(number_of_images=1),
                )
                if resp.generated_images and resp.generated_images[0].image:
                    img = resp.generated_images[0].image
                    if getattr(img, "image_bytes", None):
                        path = _save_image(img.image_bytes, prompt)
                        return f"Image saved: {path}"
                    if getattr(img, "uri", None):
                        return f"Image generated: {img.uri}"
                last_error = "no image returned"
            except Exception as e:  # noqa: BLE001
                last_error = str(e)
        return f"Image generation failed: {last_error}"
    except Exception as e:  # noqa: BLE001
        return f"Image generation unavailable: {e}"
