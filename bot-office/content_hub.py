"""Content Hub: the content team's real work.

  JP      Video editor   9:16 1080x1920 edit + a quick review of the edit (length, sound, size)
  Asher   Content manager SEO caption + hashtags, checks every affiliate link, final checks
  Shane   TikTok affiliate TikTok caption ("check the basket") + the TikTok Shop product for the yellow basket
  Jacob   Shopee affiliate Facebook and Instagram captions with the Shopee affiliate link
  Ashley  Scheduler      picks the posting slots (Asia/Manila)
  David   Autopost       at each slot: posts Facebook / Instagram Reels through the Meta Graph API, and
                         hands TikTok posts to Claude in Chrome (TikTok has no public API for product links)

Posts are kept in data/content_hub/posts.json so the schedule survives a restart.
"""
from __future__ import annotations

import html
import json
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import content
import veo

HERE = Path(__file__).resolve().parent
DIR = HERE / "data" / "content_hub"
POSTS = DIR / "posts.json"
PLATFORMS = {"tiktok": "TikTok", "facebook": "Facebook", "instagram": "Instagram"}
_lock = threading.Lock()


# ───────────────────────── storage ─────────────────────────

def load_posts() -> list[dict]:
    return json.loads(POSTS.read_text()) if POSTS.exists() else []


def save_posts(posts: list[dict]) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = POSTS.with_suffix(".tmp")
    tmp.write_text(json.dumps(posts, indent=1, ensure_ascii=False))
    tmp.replace(POSTS)


def update_post(pid: str, **kw) -> dict | None:
    with _lock:
        posts = load_posts()
        for p in posts:
            if p["id"] == pid:
                p.update(kw)
                save_posts(posts)
                return p
    return None


# ───────────────────────── JP: review the edit ─────────────────────────

def probe(path: Path) -> dict:
    import subprocess
    if not content.FFMPEG:
        return {}
    out = subprocess.run([content.FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=60).stderr
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", out)
    d = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", out)
    return {"width": int(m[1]) if m else None, "height": int(m[2]) if m else None, "audio": "Audio:" in out,
            "seconds": int(d[1]) * 3600 + int(d[2]) * 60 + float(d[3]) if d else None}


def review_edit(src: Path, media: dict, out_dir: Path) -> list[str]:
    """Notes on the edit; an empty list means it passed."""
    notes = []
    info = probe(src)
    if info.get("width") and info.get("height") and min(info["width"], info["height"]) < 720:
        notes.append(f"Low resolution source ({info['width']}x{info['height']}): it may look soft")
    if info and not info.get("audio"):
        notes.append("No sound: add music from the app's commercial library or a voiceover")
    secs = media.get("seconds") or info.get("seconds")
    if secs is not None and secs < 5:
        notes.append(f"Very short ({secs:.0f}s): 15-30s performs better")
    if "trimmed" in media.get("note", ""):
        notes.append(media["note"])
    return notes


# ───────────────────────── Asher: captions + link checks ─────────────────────────

PRICE = re.compile(r"(₱\s?|\b(php|p)\s?)\d[\d,.]*|\b\d[\d,.]*\s?(pesos?|php)\b", re.I)
PLATFORM_WORDS = re.compile(r"\b(tiktok|tik tok|shopee|lazada|facebook|instagram|fb|ig|threads)\b", re.I)


def clean(text: str) -> str:
    text = PRICE.sub("", text)
    text = re.sub(r"yellow basket", "basket", text, flags=re.I)
    text = PLATFORM_WORDS.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def seo_caption(name: str, notes: str, product: str) -> dict:
    rules = veo.load().get("caption_rules", "").strip()
    brief = "\n".join(x for x in [
        f"Product: {product}" if product else "",
        f"About the video: {notes}" if notes else "",
        "Write an SEO caption: put the main search keywords in the first line, 5-8 relevant hashtags (mix of broad and niche).",
        "No prices, no platform names, no claims the product page does not support.",
        f"Creator's caption rules: {rules}" if rules else "",
    ] if x)
    cap = content.write_caption(name, brief)
    cap["hook"], cap["caption"], cap["cta"] = clean(cap["hook"]), clean(cap["caption"]), clean(cap["cta"])
    cap["hashtags"] = [h for h in (clean(h) for h in cap["hashtags"]) if h][:8]
    return cap


def check_link(url: str, kind: str) -> tuple[str, list[str]]:
    """('ok' | 'warn' | 'bad' | 'none', notes). kind: tiktok | shopee."""
    url = (url or "").strip()
    if not url:
        return "none", []
    u = urlparse(url if "://" in url else "https://" + url)
    host = (u.hostname or "").lower()
    if kind == "shopee":
        if host in ("s.shopee.ph", "shope.ee", "shp.ee") or host.startswith("s.shopee."):
            return "ok", []
        if "shopee." in host:
            if re.search(r"(af_|utm_source=an_|smtt=|an_redir)", u.query):
                return "ok", []
            return "warn", ["Plain Shopee product link: it may not earn commission. Use Shopee Affiliate → Get link (s.shopee.ph/...)"]
        return "bad", [f"Not a Shopee link ({host})"]
    if kind == "tiktok":
        if host in ("vt.tiktok.com", "vm.tiktok.com") or (host.endswith("tiktok.com") and ("/product" in u.path or "/pdp/" in u.path or "/view/product" in u.path)):
            return "ok", []
        if host.endswith("tiktok.com"):
            return "warn", ["TikTok link but not a product page: copy it from the product's Share → Copy link"]
        return "bad", [f"Not a TikTok Shop product link ({host})"]
    return "bad", ["unknown link type"]


def product_name(url: str) -> str:
    try:
        import affiliate
        return affiliate.name_from_url(url) or ""
    except Exception:
        return ""


def full_caption(cap: dict) -> str:
    return content.caption_text(cap)


def platform_caption(cap: dict, platform: str, shopee: str, tiktok: str) -> tuple[str, str]:
    """(caption, first comment) for one platform."""
    base = f"{cap['hook']}\n\n{cap['caption']}"
    tags = " ".join("#" + h for h in cap["hashtags"])
    affiliate_tag = " #ad" if (shopee or tiktok) else ""
    if platform == "tiktok":
        cta = "Check the basket 🛒" if tiktok else cap["cta"]
        return f"{base}\n\n{cta}\n\n{tags}{affiliate_tag}", ""
    if platform == "facebook":
        shop = f"\n\n🛒 Shop here: {shopee}" if shopee else ""
        return f"{base}{shop}\n\n{cap['cta']}\n\n{tags}{affiliate_tag}", ""
    # Instagram captions can't hold clickable links: the link goes in the first comment
    cta = "🛒 Link in the comments" if shopee else cap["cta"]
    return f"{base}\n\n{cta}\n\n{tags}{affiliate_tag}", (f"🛒 Shop here: {shopee}" if shopee else "")


# ───────────────────────── Ashley: slots ─────────────────────────

def slot_times() -> list[tuple[int, int]]:
    out = []
    for part in re.split(r"[,\s]+", veo.load().get("post_slots", "")):
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", part.strip())
        if m and int(m[1]) < 24 and int(m[2]) < 60:
            out.append((int(m[1]), int(m[2])))
    return sorted(set(out)) or [(12, 0), (19, 0)]


def next_slots(n: int, taken: set[str], start: datetime | None = None) -> list[datetime]:
    t = start or datetime.now(content.MANILA) + timedelta(minutes=30)
    day, out = t.date(), []
    while len(out) < n:
        for hh, mm in slot_times():
            s = datetime(day.year, day.month, day.day, hh, mm, tzinfo=content.MANILA)
            if s >= t and s.isoformat() not in taken and len(out) < n:
                out.append(s)
                taken.add(s.isoformat())
        day += timedelta(days=1)
    return out


# ───────────────────────── David: Meta Graph API + Claude handoff ─────────────────────────

GRAPH = "https://graph.facebook.com"


def _meta() -> dict:
    s = veo.load()
    return {"page": s.get("meta_page_id", "").strip(), "token": s.get("meta_page_token", "").strip(),
            "ig": s.get("meta_ig_user_id", "").strip(), "ver": s.get("meta_graph_version", "v23.0").strip() or "v23.0"}


def meta_ready(platform: str) -> bool:
    if platform not in ("facebook", "instagram"):
        return False  # TikTok has no public posting API for product links: always handed to Claude
    m = _meta()
    return bool(m["token"] and (m["page"] if platform == "facebook" else m["ig"]))


def meta_test() -> dict:
    import requests
    m = _meta()
    if not (m["page"] and m["token"]):
        return {"ok": False, "message": "Add the Facebook Page ID and the Page access token first."}
    r = requests.get(f"{GRAPH}/{m['ver']}/{m['page']}", params={"fields": "name,instagram_business_account{id,username}",
                                                                "access_token": m["token"]}, timeout=20)
    j = r.json()
    if r.status_code != 200:
        return {"ok": False, "message": j.get("error", {}).get("message", f"HTTP {r.status_code}")}
    ig = j.get("instagram_business_account") or {}
    if ig.get("id") and not m["ig"]:
        veo.save({"meta_ig_user_id": ig["id"]})
    return {"ok": True, "page": j.get("name", ""), "instagram": ig.get("username", ""), "ig_id": ig.get("id", ""),
            "message": f"Connected: Page “{j.get('name', '')}”" + (f" + Instagram @{ig['username']}" if ig.get("username") else
                                                                  " (no Instagram Professional account linked to this Page)")}


def _check(r) -> dict:
    try:
        j = r.json()
    except ValueError:
        j = {}
    if r.status_code >= 400 or "error" in j:
        raise RuntimeError(j.get("error", {}).get("message") or f"HTTP {r.status_code}")
    return j


def post_facebook_reel(video: Path, caption: str) -> str:
    import requests
    m = _meta()
    base = f"{GRAPH}/{m['ver']}/{m['page']}/video_reels"
    start = _check(requests.post(base, data={"upload_phase": "start", "access_token": m["token"]}, timeout=60))
    data = video.read_bytes()
    _check(requests.post(start["upload_url"], data=data, timeout=600,
                         headers={"Authorization": f"OAuth {m['token']}", "offset": "0", "file_size": str(len(data))}))
    _check(requests.post(base, data={"upload_phase": "finish", "video_id": start["video_id"], "video_state": "PUBLISHED",
                                     "description": caption, "access_token": m["token"]}, timeout=120))
    return f"https://www.facebook.com/reel/{start['video_id']}"


def post_instagram_reel(video: Path, caption: str, comment: str = "") -> str:
    import requests
    m = _meta()
    g = f"{GRAPH}/{m['ver']}"
    c = _check(requests.post(f"{g}/{m['ig']}/media", data={"media_type": "REELS", "upload_type": "resumable", "caption": caption,
                                                            "share_to_feed": "true", "access_token": m["token"]}, timeout=60))
    data = video.read_bytes()
    _check(requests.post(c["uri"], data=data, timeout=600,
                         headers={"Authorization": f"OAuth {m['token']}", "offset": "0", "file_size": str(len(data))}))
    for _ in range(60):  # Instagram processes the video before it can be published
        st = _check(requests.get(f"{g}/{c['id']}", params={"fields": "status_code", "access_token": m["token"]}, timeout=30))
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") == "ERROR":
            raise RuntimeError("Instagram could not process the video")
        time.sleep(5)
    pub = _check(requests.post(f"{g}/{m['ig']}/media_publish", data={"creation_id": c["id"], "access_token": m["token"]}, timeout=60))
    if comment:
        try:
            _check(requests.post(f"{g}/{pub['id']}/comments", data={"message": comment, "access_token": m["token"]}, timeout=30))
        except Exception:
            pass  # the post is up; the comment is a bonus
    link = _check(requests.get(f"{g}/{pub['id']}", params={"fields": "permalink", "access_token": m["token"]}, timeout=30))
    return link.get("permalink", "")


UPLOAD_PAGES = {"tiktok": "https://www.tiktok.com/tiktokstudio/upload",
                "facebook": "https://business.facebook.com/latest/reels_composer",
                "instagram": "https://business.facebook.com/latest/reels_composer"}


def claude_prompt(p: dict) -> str:
    """Ready-made instructions for Claude in Chrome (the 'hand the job to your Claude' step)."""
    steps = [f"Please post this video on my {PLATFORMS[p['platform']]} account in this browser. I'm logged in.",
             f"1. Open {UPLOAD_PAGES[p['platform']]}",
             f"2. Upload the video file “{p['file_name']}” (it's in my Downloads after I click Download video). "
             "If you can't attach files, wait for me to drag it in, then continue.",
             "3. Paste this caption exactly:\n---\n" + p["caption"] + "\n---"]
    if p["platform"] == "tiktok" and p.get("tiktok_link"):
        steps.append(f"4. Click “Add link” → “Products” → add this TikTok Shop product (search it or paste the link): {p['tiktok_link']}. "
                     "This adds the yellow basket. Use the product's own name as the product title.")
    if p["platform"] == "instagram" and p.get("comment"):
        steps.append(f"4. After it's posted, add this as the first comment: {p['comment']}")
    steps.append("5. Turn on the “AI-generated content” label if the video uses AI visuals, then Post. "
                 "Tell me when it's done and give me the post link. Don't change anything else on my account.")
    return "\n".join(steps)


# ───────────────────────── page ─────────────────────────

def render_batch(bid: str, posts: list[dict], videos: list[dict]) -> str:
    e = html.escape
    rows = []
    for v in videos:
        ps = [p for p in posts if p["video"] == v["id"]]
        cards = []
        for p in ps:
            st = p["status"]
            badge = {"scheduled": ("📅 Scheduled", "#4da3ff"), "posted": ("✅ Posted", "#3ddc84"), "handoff": ("🤖 Hand to Claude now", "#ffb02e"),
                     "posting": ("⏳ Posting…", "#a77bff"), "failed": ("⚠️ Failed", "#e84a5f")}.get(st, (st, "#9c96c9"))
            when = datetime.fromisoformat(p["slot"]).strftime("%a %b %d, %I:%M %p").replace(" 0", " ")
            how = "auto-post (Meta API)" if p.get("auto") else "hand to Claude"
            link = f' · <a href="{e(p["post_url"])}" target="_blank">open post</a>' if p.get("post_url") else ""
            err = f'<p class="err">{e(p["error"])}</p>' if p.get("error") else ""
            extra = f'<p class="muted">First comment: {e(p["comment"])}</p>' if p.get("comment") else ""
            basket = (f'<p>🛒 Yellow basket product: <a href="{e(p["tiktok_link"])}" target="_blank">{e(p["tiktok_link"])}</a></p>'
                      if p["platform"] == "tiktok" and p.get("tiktok_link") else "")
            prompt = claude_prompt(p)
            cards.append(f"""<div class="post"><h3>{e(PLATFORMS[p['platform']])} <span class="badge" style="background:{badge[1]}">{badge[0]}</span></h3>
<p class="muted">{e(when)} (Manila) · {how}{link}</p>{err}{basket}
<pre>{e(p['caption'])}</pre>{extra}
<button onclick="copy(this, {e(json.dumps(p['caption']))})">📋 Copy caption</button>
<button onclick="copy(this, {e(json.dumps(prompt))})">🤖 Copy Claude prompt</button>
<a class="btn" href="{UPLOAD_PAGES[p['platform']]}" target="_blank">Open upload page</a>
<button onclick="act('{p['id']}','now')">🚀 Post now</button>
<button onclick="act('{p['id']}','done')">✔ Mark posted</button></div>""")
        review = "".join(f"<li>{e(x)}</li>" for x in v["review"]) or "<li>✅ Edit looks good</li>"
        links = "".join(f"<li>{'✅' if s == 'ok' else '⚠️' if s == 'warn' else '❌'} {e(k)}: {e(u)}{' — ' + e('; '.join(n)) if n else ''}</li>"
                        for k, u, s, n in v["links"] if s != "none") or "<li>No affiliate links on this video</li>"
        rows.append(f"""<section class="video"><div class="left"><video src="/outbox/{v['job']}/{e(v['media'])}" controls playsinline></video>
<a class="btn" href="/outbox/{v['job']}/{e(v['media'])}" download="{e(v['file_name'])}">⬇ Download video</a></div>
<div class="right"><h2>🎬 {e(v['name'])}</h2>
<h4>JP · review of the edit</h4><ul>{review}</ul><h4>Asher · link check</h4><ul>{links}</ul>{''.join(cards)}</div></section>""")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Content Hub batch</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{font:15px/1.5 system-ui,sans-serif;background:#0b2a3a;color:#eafaff;margin:0;padding:22px}}
h1{{margin:0 0 4px}} .muted{{color:#9cc7d6;font-size:13px}} .video{{display:flex;gap:20px;flex-wrap:wrap;background:#103a4f;border:1px solid #1f6a86;border-radius:16px;padding:16px;margin:16px 0}}
.left{{width:240px}} video{{width:240px;aspect-ratio:9/16;border-radius:12px;background:#000}} .right{{flex:1;min-width:280px}}
.post{{background:#0b2a3a;border-radius:12px;padding:10px 14px;margin:10px 0}} h3{{margin:4px 0}} h4{{margin:10px 0 2px;color:#ffd23d}}
pre{{white-space:pre-wrap;background:#06202c;border-radius:8px;padding:10px;font:inherit;font-size:14px}}
.badge{{color:#10202a;border-radius:99px;padding:2px 10px;font-size:12px;font-weight:800}} .err{{color:#ff8a8a}}
button,a.btn{{background:#ffd23d;color:#2a1a00;border:0;border-radius:8px;padding:7px 11px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block;margin:4px 4px 0 0;font-size:13px}}
a{{color:#7fe3ff}}</style></head><body><h1>📱 Content Hub · batch {e(bid)}</h1>
<p class="muted">JP edits · Asher writes the SEO captions and checks the links · Shane (TikTok + basket) · Jacob (Shopee link on Facebook / Instagram) ·
Ashley schedules · David posts. Facebook and Instagram post by themselves when the Meta connection is set in ⚙️; TikTok posts are handed to Claude in Chrome
(TikTok has no public API for product links). Reload to see the latest status.</p>
{''.join(rows)}
<script>function copy(b,t){{navigator.clipboard.writeText(t);b.textContent='Copied ✅'}}
async function act(id,a){{const r=await fetch('/api/content/post/'+id+'/'+a,{{method:'POST'}});const j=await r.json();alert(j.message||'OK');location.reload()}}</script>
</body></html>"""


def new_id() -> str:
    return uuid.uuid4().hex[:10]
