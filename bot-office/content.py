"""The real work behind the content bots.

Video Editor   -> make_vertical(): 9:16 1080x1920 version (max 60s) + thumbnail, via ffmpeg
Caption Writer -> write_caption(): hook, caption, hashtags (Claude if available, else a template)
Scheduler      -> next_slot(): next free posting slot in the content calendar
Poster         -> package(): ready-to-post folder (video, thumbnail, caption.txt, post.json)

Posting to TikTok/Facebook/Instagram needs each platform's API and account
approval, so Poster prepares the package and marks it "ready to post".
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ai

MANILA = timezone(timedelta(hours=8))
POST_TIMES = [(12, 0), (19, 0)]  # 12:00 NN and 7:00 PM Manila time
MAX_SECONDS = 60
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


# ───────────────────────── Video Editor ─────────────────────────

def _duration(path: Path) -> float | None:
    if not FFPROBE:
        return None
    try:
        out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=60)
        return float(out.stdout.strip())
    except (ValueError, subprocess.SubprocessError):
        return None


VERTICAL = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"


def make_vertical(src: Path, out_dir: Path) -> dict:
    """Returns {media, thumb, kind, seconds, note}. Paths are inside out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()
    kind = "image" if ext in IMAGE_EXT else "video"
    if not FFMPEG:
        dst = out_dir / f"original{ext}"
        shutil.copy(src, dst)
        return {"media": dst.name, "thumb": None, "kind": kind, "seconds": None,
                "note": "ffmpeg is not installed, so the original file was kept as-is"}

    if kind == "image":
        dst = out_dir / "post.jpg"
        subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-vf", VERTICAL, "-frames:v", "1", "-q:v", "3", str(dst)],
                       check=True, timeout=120)
        return {"media": dst.name, "thumb": dst.name, "kind": kind, "seconds": None, "note": "resized to 1080x1920"}

    dur = _duration(src)
    dst, thumb = out_dir / "video.mp4", out_dir / "thumb.jpg"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-t", str(MAX_SECONDS), "-vf", VERTICAL,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dst)], check=True, timeout=900)
    at = min(1.0, (dur or 2) / 3)
    subprocess.run([FFMPEG, "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(dst), "-frames:v", "1", "-q:v", "3", str(thumb)],
                   check=True, timeout=120)
    seconds = min(dur, MAX_SECONDS) if dur else None
    note = "converted to 9:16 1080x1920" + (f", trimmed to {MAX_SECONDS}s" if dur and dur > MAX_SECONDS else "")
    return {"media": dst.name, "thumb": thumb.name, "kind": kind, "seconds": seconds, "note": note}


# ───────────────────────── Caption Writer ─────────────────────────

def _topic(name: str) -> str:
    stem = re.sub(r"[_\-.]+", " ", Path(name).stem)
    stem = re.sub(r"\b(v\d+|final|edit|copy|img|vid|\d{3,})\b", "", stem, flags=re.I)
    return re.sub(r"\s+", " ", stem).strip() or "bagong post"


def write_caption(name: str, notes: str = "") -> dict:
    topic = _topic(name)
    brief = f"File name: {name}\nTopic (from file name): {topic}\n" + (f"Creator notes: {notes}\n" if notes else "")
    res = ai.write_caption(brief)
    if res:
        res["hashtags"] = [h.lstrip("#").replace(" ", "") for h in res["hashtags"] if h.strip()]
        res["by"] = "Claude"
        return res
    words = [w.lower() for w in topic.split() if len(w) > 2][:3]
    return {
        "hook": f"Wait lang, panoorin mo 'to 👀 — {topic}",
        "caption": f"{topic.capitalize()}! Sana magustuhan niyo 🫶",
        "hashtags": ["fyp", "foryou", "pinoy", *words],
        "cta": "Follow for more! 💛",
        "by": "template",
    }


def caption_text(c: dict) -> str:
    return f"{c['hook']}\n\n{c['caption']}\n\n{c['cta']}\n\n" + " ".join("#" + h for h in c["hashtags"])


# ───────────────────────── Scheduler ─────────────────────────
_cal_lock = threading.Lock()


def next_slot(calendar_file: Path, job_id: str, name: str) -> datetime:
    """Book the next free slot at least 1 hour from now and save it to the calendar."""
    with _cal_lock:
        cal = json.loads(calendar_file.read_text()) if calendar_file.exists() else []
        taken = {e["slot"] for e in cal}
        t = datetime.now(MANILA) + timedelta(hours=1)
        day = t.date()
        while True:
            for hh, mm in POST_TIMES:
                slot = datetime(day.year, day.month, day.day, hh, mm, tzinfo=MANILA)
                if slot >= t and slot.isoformat() not in taken:
                    cal.append({"slot": slot.isoformat(), "job": job_id, "name": name})
                    cal.sort(key=lambda e: e["slot"])
                    calendar_file.write_text(json.dumps(cal, indent=2))
                    return slot
            day += timedelta(days=1)


def fmt_slot(slot: datetime) -> str:
    return slot.strftime("%a %b %d, %I:%M %p").replace(" 0", " ")


# ───────────────────────── Poster ─────────────────────────

def package(out_dir: Path, name: str, media: dict, cap: dict, slot: datetime) -> None:
    (out_dir / "caption.txt").write_text(caption_text(cap), encoding="utf-8")
    (out_dir / "post.json").write_text(json.dumps({
        "source_file": name, "media": media["media"], "thumbnail": media["thumb"], "kind": media["kind"],
        "scheduled_for": slot.isoformat(), "caption": cap, "status": "ready_to_post",
        "platforms": ["tiktok", "instagram_reels", "facebook_reels", "youtube_shorts"],
    }, indent=2, ensure_ascii=False), encoding="utf-8")


def render_page(job_id: str, name: str, media: dict, cap: dict, slot: datetime) -> str:
    e = html.escape
    base = f"/outbox/{job_id}/"
    if media["kind"] == "video" and media["media"].endswith(".mp4"):
        player = f'<video src="{base}{e(media["media"])}" poster="{base}{e(media["thumb"] or "")}" controls playsinline></video>'
    else:
        player = f'<img src="{base}{e(media["media"])}" alt="">'
    full = caption_text(cap)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Ready to post — {e(name)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{font:15px/1.5 system-ui,sans-serif;background:#0d0b1a;color:#e9e6ff;margin:0;padding:24px}}
.wrap{{max-width:900px;margin:0 auto;display:flex;gap:24px;flex-wrap:wrap}}
video,img{{width:300px;aspect-ratio:9/16;object-fit:cover;border-radius:16px;background:#000;border:1px solid #3a3270}}
.card{{flex:1;min-width:280px;background:#17132e;border:1px solid #3a3270;border-radius:14px;padding:18px 20px}}
h1{{font-size:20px;margin:0 0 4px}} .muted{{color:#8d87b8;font-size:13px}} .hook{{font-size:18px;font-weight:800;color:#ffd23d;margin:14px 0 6px}}
.tags{{color:#2ee6c9}} pre{{white-space:pre-wrap;background:#0d0b1a;border-radius:10px;padding:12px;font:inherit}}
button,a.btn{{background:#ff6fae;color:#1a0d18;border:0;border-radius:8px;padding:9px 14px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block;margin:4px 6px 0 0}}
.pill{{display:inline-block;background:#3ddc8433;color:#3ddc84;border-radius:99px;padding:3px 10px;font-weight:700;font-size:12px}}</style></head>
<body><div class="wrap">{player}<div class="card">
<h1>🎬 {e(name)}</h1><div class="muted">{e(media["note"])} · caption by {e(cap.get("by", "?"))}</div>
<p><span class="pill">READY TO POST</span> 📅 <b>{e(fmt_slot(slot))}</b> (Manila)</p>
<div class="hook">{e(cap["hook"])}</div><p>{e(cap["caption"])}</p><p>{e(cap["cta"])}</p>
<p class="tags">{e(" ".join("#" + h for h in cap["hashtags"]))}</p>
<pre id="cap">{e(full)}</pre>
<button onclick="navigator.clipboard.writeText(document.getElementById('cap').innerText);this.textContent='Copied ✅'">📋 Copy caption</button>
<a class="btn" href="{base}{e(media["media"])}" download>⬇ Download {e(media["kind"])}</a>
<p class="muted">Not auto-posted: no TikTok/Meta/YouTube account is connected yet. Upload it at the scheduled time.</p>
</div></div></body></html>"""
