"""Google AI automation for Affiliate Studio: stills (Gemini image) -> clips (Veo) -> final edit.

Settings live in data/settings.json (never committed). Two backends:
  - "gemini": an API key from aistudio.google.com (billing must be on for Veo)
  - "vertex": Google Cloud / Vertex AI, either with an API key (express mode) or a
              project + location using `gcloud auth application-default login`
Model IDs are not hard-wired: "Test connection" lists what the key can use and you pick.

Every paid step is explicit: stills first (cheap) for you to check, then you press
"Animate" with a cost estimate and a per-job budget cap.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAKE = os.environ.get("BOT_OFFICE_FAKE_GOOGLE") == "1"  # test mode: no Google calls, no cost
SETTINGS = HERE / "data" / "settings.json"

DEFAULTS = {
    "backend": "gemini",            # gemini | vertex
    "api_key": "",
    "project": "",                  # vertex without api key
    "location": "us-central1",
    "image_model": "gemini-3.1-flash-lite-image",
    "video_model": "veo-3.1-generate-001",
    "clip_seconds": 6,
    "resolution": "720p",
    "price_per_second": 0.15,       # USD, for the estimate only: check your Google pricing page
    "budget_per_job": 30.0,         # USD cap per product (all 5 videos)
    "drive_folder": "",             # local Google Drive for desktop folder for case outputs (outputs.py)
}


def load() -> dict:
    s = dict(DEFAULTS)
    if SETTINGS.exists():
        s.update(json.loads(SETTINGS.read_text()))
    if not s["api_key"] and os.environ.get("GEMINI_API_KEY"):
        s["api_key"] = os.environ["GEMINI_API_KEY"]
    return s


def save(new: dict) -> dict:
    s = load()
    for k, v in new.items():
        if k not in DEFAULTS:
            continue
        if k == "api_key" and (not v or "•" in v):
            continue  # masked value sent back unchanged
        if isinstance(DEFAULTS[k], float):
            v = float(v)
        elif isinstance(DEFAULTS[k], int):
            v = int(v)
        s[k] = v
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s, indent=2))
    try:
        os.chmod(SETTINGS, 0o600)
    except OSError:
        pass
    return public(s)


def public(s: dict | None = None) -> dict:
    s = dict(s or load())
    k = s.get("api_key", "")
    s["api_key"] = (k[:4] + "•" * 8 + k[-4:]) if len(k) > 10 else ("•" * len(k))
    s["configured"] = configured(s)
    return s


def configured(s: dict | None = None) -> bool:
    if FAKE:
        return True
    s = s or load()
    return bool(s["api_key"] or (s["backend"] == "vertex" and s["project"]))


def client(s: dict | None = None):
    from google import genai
    s = s or load()
    if s["backend"] == "vertex":
        if s["api_key"]:
            return genai.Client(vertexai=True, api_key=s["api_key"])
        return genai.Client(vertexai=True, project=s["project"], location=s["location"])
    return genai.Client(api_key=s["api_key"])


def _scan(c) -> dict:
    images, videos, names = [], [], []
    for m in c.models.list():
        name = (m.name or "").split("/")[-1]
        acts = [a.lower() for a in (m.supported_actions or [])]
        low = name.lower()
        names.append(name)
        if any(k in low for k in ("veo", "video", "omni")) or any("video" in a or "longrunning" in a for a in acts):
            videos.append(name)
        elif "image" in low or "imagen" in low:
            images.append(name)
    return {"ok": True, "video_models": sorted(videos), "image_models": sorted(images), "all_models": sorted(names)}


def test_connection() -> dict:
    """Tries the key on the Gemini API and on Vertex AI (express) and reports what each can use.
    If only one backend has video models, that backend is selected automatically."""
    if FAKE:
        return {"ok": True, "backend": "gemini", "results": {"gemini": {"ok": True, "video_models": ["fake-veo"], "image_models": ["fake-image"],
                "all_models": ["fake-image", "fake-veo"]}}, "video_models": ["fake-veo"], "image_models": ["fake-image"]}
    s = load()
    results = {}
    for backend in ("gemini", "vertex"):
        if backend == "vertex" and not s["api_key"] and not s["project"]:
            continue
        try:
            results[backend] = _scan(client({**s, "backend": backend}))
        except Exception as exc:
            results[backend] = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    ok = {b: r for b, r in results.items() if r.get("ok")}
    if not ok:
        return {"ok": False, "error": "; ".join(f"{b}: {r['error']}" for b, r in results.items()), "results": results}
    with_video = [b for b, r in ok.items() if r["video_models"]]
    chosen = s["backend"] if s["backend"] in with_video else (with_video[0] if with_video else s["backend"] if s["backend"] in ok else next(iter(ok)))
    if chosen != s["backend"]:
        save({"backend": chosen})
    r = ok.get(chosen, next(iter(ok.values())))
    return {"ok": True, "backend": chosen, "results": results, "video_models": r["video_models"], "image_models": r["image_models"]}


def estimate(n_clips: int, s: dict | None = None) -> float:
    s = s or load()
    return round(n_clips * s["clip_seconds"] * s["price_per_second"], 2)


def make_still(prompt: str, refs: list[Path], out: Path, s: dict | None = None) -> Path:
    """One 9:16 photoreal frame from the scene prompt + reference photos (model first, then product)."""
    from PIL import Image
    if FAKE:
        out.parent.mkdir(parents=True, exist_ok=True)
        im = Image.open(refs[0]).convert("RGB"); im.thumbnail((540, 960)); im.save(out); time.sleep(0.2)
        return out
    from google.genai import types
    s = s or load()
    intro = ("Generate ONE photorealistic vertical 9:16 still image: the first frame of the scene below. "
             + ("Image 1 is the model reference: keep her face, hair and skin tone exactly. " if len(refs) > 1 else "")
             + "The last image is the product reference: keep the product's shape, color, cut and details exactly. "
             "No text, captions, logos or watermarks.\n\n")
    contents = [intro + prompt] + [Image.open(p) for p in refs]
    resp = client(s).models.generate_content(
        model=s["image_model"], contents=contents,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"], image_config=types.ImageConfig(aspect_ratio="9:16")))
    for part in resp.parts or []:
        if part.inline_data:
            img = part.as_image()
            out.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(out))
            return out
    raise RuntimeError("Walang image na ibinalik ang model (baka na-block ng safety filter). Subukan ulit o baguhin ang prompt.")


def make_clip(still: Path, motion_prompt: str, negative: str, out: Path, s: dict | None = None, timeout: int = 900) -> Path:
    """Image-to-video from an approved still (first frame keeps face and product consistent)."""
    s = s or load()
    if FAKE:
        import subprocess, content
        subprocess.run([content.FFMPEG, "-y", "-v", "error", "-loop", "1", "-t", str(s["clip_seconds"]), "-i", str(still),
                        "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,zoompan=z='zoom+0.002':d=1:s=720x1280:fps=24",
                        "-pix_fmt", "yuv420p", str(out)], check=True)
        return out
    from google.genai import types
    c = client(s)
    if "veo" not in s["video_model"].lower():
        return _clip_via_generate_content(c, still, motion_prompt, negative, out, s)
    op = c.models.generate_videos(
        model=s["video_model"],
        source=types.GenerateVideosSource(prompt=motion_prompt, image=types.Image.from_file(location=str(still))),
        config=types.GenerateVideosConfig(number_of_videos=1, aspect_ratio="9:16", duration_seconds=int(s["clip_seconds"]),
                                          resolution=s["resolution"], negative_prompt=negative, person_generation="allow_adult"))
    t0 = time.time()
    while not op.done:
        if time.time() - t0 > timeout:
            raise TimeoutError("Matagal ang Veo (lampas 15 minuto). Subukan ulit mamaya.")
        time.sleep(10)
        op = c.operations.get(op)
    if op.error:
        raise RuntimeError(f"Veo error: {op.error}")
    vids = (op.response.generated_videos if op.response else None) or []
    if not vids:
        reasons = getattr(op.response, "rai_media_filtered_reasons", None) if op.response else None
        raise RuntimeError(f"Walang video na ibinalik (safety filter?): {reasons or 'walang dahilan'}")
    video = vids[0].video
    if s["backend"] == "gemini":
        c.files.download(file=video)
    out.parent.mkdir(parents=True, exist_ok=True)
    video.save(str(out))
    return out


def _clip_via_generate_content(c, still: Path, prompt: str, negative: str, out: Path, s: dict) -> Path:
    """Experimental: Gemini models that return video from generate_content (VIDEO modality)."""
    from google.genai import types
    from PIL import Image
    text = (f"{prompt}\n\nOutput: one vertical 9:16 video, about {s['clip_seconds']} seconds, starting from the attached image as "
            f"the first frame. Avoid: {negative}")
    resp = c.models.generate_content(model=s["video_model"], contents=[text, Image.open(still)],
                                     config=types.GenerateContentConfig(response_modalities=["VIDEO"]))
    for part in resp.parts or []:
        if part.inline_data and (part.inline_data.mime_type or "").startswith("video"):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(part.inline_data.data)
            return out
    raise RuntimeError(f"Walang video na ibinalik ang {s['video_model']}. Piliin ang ibang video model sa Settings.")


def motion_prompt(scene_prompt: str) -> str:
    """For image-to-video the first frame already fixes look; describe movement + camera + continuity."""
    keep = []
    for block in scene_prompt.split("\n\n"):
        head = block.split("\n", 1)[0]
        if head.startswith(("Scene ", "Subject and Action", "Camera and Visual Style", "Technical Requirements")):
            keep.append(block)
    return ("Animate this first frame as a single continuous 9:16 shot. Keep the person, outfit, product and setting exactly "
            "as in the first frame.\n\n" + "\n\n".join(keep))
