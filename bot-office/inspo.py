"""Inspo links: the right teammate "watches" a reference video or photo you like.

Paste any link in 📱 Content → ✨ Inspo:
  TikTok → Shane · Instagram / Facebook → Jacob · Canva / web pages / Pinterest → Asher · YouTube / other videos / photos → JP

How it is watched:
  1. the media is fetched: direct video/photo links, Google Drive links, social videos through yt-dlp (public posts),
     or the page's preview image/video (og:image / og:video) when the video itself can't be downloaded (e.g. Canva);
  2. JP measures it: length, aspect ratio, number of cuts and average shot length, sound, colour palette,
     and makes a contact sheet (12 frames);
  3. with an AI provider that can see images (Claude in ⚙️), the contact sheet is described: hook, style, shot list,
     pacing, text on screen, what to recreate and what not to copy.
The result feeds Asher's captions and the Prompt Pack. Inspiration only: never repost someone else's video, music or art.
"""
from __future__ import annotations

import base64
import html as htmlmod
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import content

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
MAX_BYTES = 200 * 1024 * 1024
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")
SOCIAL = ("tiktok.com", "instagram.com", "facebook.com", "fb.watch", "youtube.com", "youtu.be", "x.com", "twitter.com",
          "vimeo.com", "pinterest.", "pin.it", "threads.net")


def who(url: str) -> tuple[str, str]:
    """(bot id, platform label) of the teammate who watches this link."""
    h = (urlparse(url).hostname or "").lower()
    if "tiktok" in h:
        return "shane", "TikTok"
    if "instagram" in h:
        return "jacob", "Instagram"
    if "facebook" in h or "fb.watch" in h:
        return "jacob", "Facebook"
    if "canva" in h:
        return "asher", "Canva"
    if "pinterest" in h or "pin.it" in h:
        return "asher", "Pinterest"
    if "youtube" in h or "youtu.be" in h:
        return "jp", "YouTube"
    if "drive.google" in h:
        return "jp", "Google Drive"
    return "jp", h.replace("www.", "") or "link"


def parse_links(text: str) -> list[str]:
    out = []
    for m in re.finditer(r"https?://[^\s<>\"']+", text or ""):
        u = m.group(0).rstrip(").,;")
        if u not in out:
            out.append(u)
    return out[:10]


def _download(url: str, dest: Path, requests) -> Path | None:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=60, stream=True, allow_redirects=True)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    ext = (".mp4" if "video" in ctype else ".jpg" if "jpeg" in ctype else ".png" if "png" in ctype else ".webp" if "webp" in ctype
           else ".gif" if "gif" in ctype else Path(urlparse(r.url).path).suffix.lower())
    if not (ext in VIDEO_EXT or ext in IMAGE_EXT):
        return None
    out = dest.with_suffix(ext)
    size = 0
    with out.open("wb") as fh:
        for chunk in r.iter_content(1 << 16):
            size += len(chunk)
            if size > MAX_BYTES:
                break
            fh.write(chunk)
    return out


def _og(url: str, requests) -> dict:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30, allow_redirects=True)
    r.raise_for_status()
    t = r.text
    def meta(prop):
        m = re.search(rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']+)', t, re.I) or \
            re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{prop}["\']', t, re.I)
        return htmlmod.unescape(m.group(1)) if m else ""
    return {"title": meta("og:title") or (re.search(r"<title>(.*?)</title>", t, re.S | re.I).group(1).strip() if "<title>" in t.lower() else ""),
            "description": meta("og:description"), "image": meta("og:image"), "video": meta("og:video:secure_url") or meta("og:video")}


def fetch(url: str, work: Path) -> dict:
    """Gets the media behind a link into work/. {kind: video|image|none, path, title, description, via, note}"""
    import requests
    work.mkdir(parents=True, exist_ok=True)
    res = {"kind": "none", "path": "", "title": "", "description": "", "via": "", "note": ""}
    host = (urlparse(url).hostname or "").lower()
    # 1. Google Drive
    if "drive.google" in host or "docs.google" in host:
        try:
            import kyb_docs
            got = kyb_docs.fetch(url, work / "drive")
            f = next((x for x in got["files"] if Path(x["name"]).suffix.lower() in VIDEO_EXT + IMAGE_EXT), None)
            if f:
                res.update(kind="video" if Path(f["name"]).suffix.lower() in VIDEO_EXT else "image", path=str(f["path"]),
                           title=f["name"], via="Google Drive")
                return res
        except Exception as exc:
            res["note"] = f"Drive: {exc}"
    # 2. direct media link
    if Path(urlparse(url).path).suffix.lower() in VIDEO_EXT + IMAGE_EXT:
        try:
            p = _download(url, work / "inspo", requests)
            if p:
                res.update(kind="video" if p.suffix in VIDEO_EXT else "image", path=str(p), title=Path(urlparse(url).path).name, via="direct link")
                return res
        except Exception as exc:
            res["note"] = f"Download: {type(exc).__name__}"
    # 3. social video through yt-dlp (public posts)
    if any(s in host for s in SOCIAL):
        try:
            import yt_dlp
            opts = {"outtmpl": str(work / "inspo.%(ext)s"), "format": "best[height<=720][ext=mp4]/best[height<=720]/best",
                    "quiet": True, "no_warnings": True, "noplaylist": True, "max_filesize": MAX_BYTES,
                    "logger": type("Quiet", (), {"debug": staticmethod(lambda m: None), "info": staticmethod(lambda m: None),
                                                 "warning": staticmethod(lambda m: None), "error": staticmethod(lambda m: None)})()}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            p = Path(ydl.prepare_filename(info))
            if p.exists():
                res.update(kind="video" if p.suffix.lower() in VIDEO_EXT else "image", path=str(p), title=info.get("title") or "",
                           description=(info.get("description") or "")[:500], via="yt-dlp")
                return res
        except ImportError:
            res["note"] = "Walang yt-dlp (i-restart ang start-mac.command para ma-install)"
        except Exception as exc:
            res["note"] = f"Hindi ma-download ang video ({type(exc).__name__}): baka private o kailangan ng login"
    # 4. the page's preview video / image (Canva, Pinterest, most sites)
    try:
        og = _og(url, requests)
        res.update(title=og["title"][:200], description=og["description"][:500])
        for key in ("video", "image"):
            if og[key]:
                p = _download(og[key], work / f"preview_{key}", requests)
                if p:
                    res.update(kind="video" if p.suffix in VIDEO_EXT else "image", path=str(p), via=f"page preview ({key})")
                    if "canva" in host:
                        res["note"] = ("Canva: preview image lang ang nakukuha sa share link. Para sa buong design, i-download ang MP4/PNG "
                                       "at i-upload, o hilingin kay Claude sa chat na i-export ito.")
                    return res
    except Exception as exc:
        res["note"] = (res["note"] + " · " if res["note"] else "") + f"Hindi mabuksan ang page ({type(exc).__name__})"
    return res


# ───────────────────────── JP: measure the video / photo ─────────────────────────

def _ff(*args, timeout=300) -> str:
    return subprocess.run([content.FFMPEG, "-hide_banner", *args], capture_output=True, text=True, timeout=timeout).stderr


def analyze_video(path: Path, out: Path) -> dict:
    info = {"seconds": None, "width": None, "height": None, "fps": None, "audio": False, "cuts": 0, "avg_shot": None}
    if not content.FFMPEG:
        return info
    head = _ff("-i", str(path))
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", head)
    if m:
        info["seconds"] = round(int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]), 1)
    v = re.search(r"Video:.*?(\d{2,5})x(\d{2,5}).*?(\d+(?:\.\d+)?) fps", head)
    if v:
        info.update(width=int(v[1]), height=int(v[2]), fps=float(v[3]))
    info["audio"] = "Audio:" in head
    sc = _ff("-i", str(path), "-vf", "select='gt(scene,0.32)',showinfo", "-an", "-f", "null", "-", timeout=600)
    cuts = [float(x) for x in re.findall(r"pts_time:([\d.]+)", sc)]
    info["cuts"] = len(cuts)
    if info["seconds"]:
        info["avg_shot"] = round(info["seconds"] / (len(cuts) + 1), 1)
        info["cut_times"] = [round(c, 1) for c in cuts[:30]]
    # contact sheet: 12 frames spread over the video
    n, frames = 12, []
    dur = info["seconds"] or 10
    for i in range(n):
        f = out / f"frame_{i:02d}.jpg"
        subprocess.run([content.FFMPEG, "-y", "-v", "error", "-ss", f"{dur * (i + 0.5) / n:.2f}", "-i", str(path), "-frames:v", "1",
                        "-vf", "scale=360:-2", str(f)], timeout=60)
        if f.exists():
            frames.append(f)
    info["sheet"] = _sheet(frames, out / "contact_sheet.jpg", [f"{dur * (i + 0.5) / n:.1f}s" for i in range(len(frames))])
    for f in frames:
        f.unlink(missing_ok=True)
    return info


def _sheet(frames: list[Path], out: Path, labels: list[str]) -> str:
    from PIL import Image, ImageDraw
    if not frames:
        return ""
    ims = [Image.open(f).convert("RGB") for f in frames]
    w = 240
    h = int(w * ims[0].height / ims[0].width)
    cols = 6 if h < w else 4
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * h), (12, 12, 20))
    d = ImageDraw.Draw(sheet)
    for i, im in enumerate(ims):
        x, y = (i % cols) * w, (i // cols) * h
        sheet.paste(im.resize((w, h)), (x, y))
        d.rectangle((x + 4, y + 4, x + 52, y + 20), fill=(0, 0, 0))
        d.text((x + 8, y + 6), labels[i], fill=(255, 255, 255))
    sheet.save(out, quality=82)
    return out.name


def analyze_image(path: Path, out: Path) -> dict:
    from PIL import Image
    im = Image.open(path).convert("RGB")
    info = {"width": im.width, "height": im.height}
    small = im.copy()
    small.thumbnail((720, 720))
    small.save(out / "contact_sheet.jpg", quality=85)
    info["sheet"] = "contact_sheet.jpg"
    q = im.resize((120, 120)).quantize(colors=5)
    pal, used = q.getpalette() or [], sorted(q.getcolors() or [], reverse=True)
    info["palette"] = ["#%02x%02x%02x" % tuple(pal[i * 3:i * 3 + 3]) for _, i in used[:5] if len(pal) >= i * 3 + 3]
    return info


def aspect(w, h) -> str:
    if not w or not h:
        return "?"
    r = w / h
    return "9:16 (vertical)" if r < 0.6 else "4:5" if r < 0.85 else "1:1" if r < 1.15 else "16:9 (horizontal)" if r > 1.6 else f"{w}x{h}"


# ───────────────────────── AI look at the frames ─────────────────────────

INSPO_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "hook": {"type": "string", "description": "what happens in the first 1-3 seconds and why it stops the scroll"},
        "style": {"type": "string", "description": "look: setting, light, colours, camera, faceless or on-camera"},
        "shots": {"type": "array", "items": {"type": "string"}, "description": "shot list in order"},
        "pacing": {"type": "string"},
        "on_screen_text": {"type": "string"},
        "recreate": {"type": "array", "items": {"type": "string"}, "description": "what to copy for our product (structure, not content)"},
        "avoid": {"type": "array", "items": {"type": "string"}, "description": "what not to copy (their music, faces, logos, exact wording)"},
    },
    "required": ["summary", "hook", "style", "shots", "pacing", "on_screen_text", "recreate", "avoid"],
    "additionalProperties": False,
}
INSPO_SYSTEM = ("You are a short-form video creative director for a Filipino affiliate creator. You get a contact sheet of a reference "
                "('inspo') video or photo with timestamps, plus measurements. Describe only what you can see. Explain the structure so we "
                "can make our OWN version for our product: never copy their footage, music, people, logos or exact words. Short, practical lines.")


def ai_describe(sheet: Path, facts: dict, title: str = "") -> dict | None:
    import ai
    if not ai.available():
        return None
    data = base64.standard_b64encode(sheet.read_bytes()).decode()
    user = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
            {"type": "text", "text": f"Title: {title}\nMeasurements: {json.dumps(facts)}\nBreak down this inspo."}]
    try:
        return ai._ask_json(INSPO_SYSTEM, user, INSPO_SCHEMA, 3000)
    except Exception:
        return None


def template_breakdown(kind: str, facts: dict) -> dict:
    """No AI: a breakdown from the measurements alone."""
    if kind == "image":
        return {"summary": f"Photo inspo, {aspect(facts.get('width'), facts.get('height'))}. Kulay: {', '.join(facts.get('palette', []))}.",
                "hook": "Tingnan ang contact sheet: ano ang unang napapansin (produkto, mukha, kulay)?", "style": "Gamitin ang parehong kulay at framing.",
                "shots": [], "pacing": "-", "on_screen_text": "-",
                "recreate": ["Parehong framing at background vibe", "Parehong color palette"], "avoid": ["Ang mismong larawan, mukha o logo nila"]}
    s, cuts, avg = facts.get("seconds"), facts.get("cuts", 0), facts.get("avg_shot")
    pace = ("mabilis (fast cuts)" if avg and avg < 1.5 else "katamtaman" if avg and avg < 3.5 else "mabagal, cinematic")
    return {"summary": f"{s}s na video, {aspect(facts.get('width'), facts.get('height'))}, {cuts} cuts (≈{avg}s bawat shot), "
                       f"{'may tunog' if facts.get('audio') else 'walang tunog'}.",
            "hook": "Panoorin ang unang 2 frames sa contact sheet: iyon ang hook.", "style": "Tingnan ang contact sheet para sa setting at ilaw.",
            "shots": [f"Cut sa {t}s" for t in facts.get("cut_times", [])[:12]], "pacing": pace,
            "on_screen_text": "Tingnan ang frames (walang AI para basahin ang text).",
            "recreate": [f"Parehong haba (~{s}s) at bilang ng shots ({cuts + 1})", f"Pacing: {pace}", "Parehong uri ng hook sa unang 2 segundo"],
            "avoid": ["Ang footage, music, mukha at logo nila", "Eksaktong caption o script nila"]}


def summary_line(r: dict) -> str:
    b = r.get("breakdown") or {}
    return f"Inspo ({r['platform']}): {b.get('summary', '')} Hook: {b.get('hook', '')} Style: {b.get('style', '')} Pacing: {b.get('pacing', '')}"[:700]


def render(reports: list[dict], base: str) -> str:
    e = htmlmod.escape
    out = []
    for r in reports:
        b = r.get("breakdown") or {}
        img = f"<img class='sheet' src='{base}{r['id']}/{e(r['sheet'])}' alt=''>" if r.get("sheet") else ""
        lst = lambda xs: "".join(f"<li>{e(x)}</li>" for x in xs or [])
        dl = (f"<a class='btn' href='{base}{r['id']}/{e(Path(r['media']).name)}' download>⬇ Download inspo (para i-upload sa ChatGPT/Gemini/Seedance)</a>"
              if r.get("media") else "")
        out.append(f"""<div class="post"><h3>✨ {e(r['platform'])} · {e(r.get('title') or r['url'][:60])} <span class="muted">· pinanood ni {e(r['bot_name'])}</span></h3>
<p class="muted"><a href="{e(r['url'])}" target="_blank">{e(r['url'][:90])}</a> · {e(r.get('via') or 'hindi nakuha ang media')}{(' · ' + e(r['note'])) if r.get('note') else ''}</p>
{img}<p><b>{e(b.get('summary', ''))}</b></p>
<p>🎣 <b>Hook:</b> {e(b.get('hook', ''))}<br>🎨 <b>Style:</b> {e(b.get('style', ''))}<br>⏱ <b>Pacing:</b> {e(b.get('pacing', ''))}<br>🔤 <b>Text sa screen:</b> {e(b.get('on_screen_text', ''))}</p>
{('<h4>Shot list</h4><ol>' + lst(b.get('shots')) + '</ol>') if b.get('shots') else ''}
<h4>✅ Gayahin (structure)</h4><ul>{lst(b.get('recreate'))}</ul><h4>🚫 Huwag kopyahin</h4><ul>{lst(b.get('avoid'))}</ul>
<p class="muted">Breakdown by {e(r.get('by', 'measurements'))}. Inspirasyon lang: gumawa ng sariling version, huwag i-repost ang video, music o larawan nila.</p>{dl}</div>""")
    return ("<section class='video'><div class='right'><h2>✨ Inspo (pinanood ng team)</h2>" + "".join(out) +
            "<p class='muted'>Ginamit ito ni Asher sa captions at sa Prompt Pack (tingnan ang “Recreate a viral video's structure”).</p></div></section>")
