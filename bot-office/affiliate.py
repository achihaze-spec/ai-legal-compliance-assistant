"""Affiliate Studio: product link -> 5 faceless short-form affiliate videos.

Pipeline (each step is one bot in the office):
  Caption Writer  plan_videos()     5 scripts in 5 different styles (Claude if available, else templates)
  Reg Checker     policy_check()    platform rules: no price, no platform names, "check the basket",
                                    #ad, no banned claims / fake urgency, first-person only if owned
  Video Editor    render_video()    draft = storyboard video (seller photos + "shot needed" cards);
                                    final = your own / AI clips + optional voiceover
  Scheduler       content.next_slot() spreads the 5 posts over different slots

Why drafts and not finished videos from photos alone: TikTok Shop and Shopee penalise
unoriginal content (seller-photo slideshows, reposts, near-duplicate videos). Each video
needs original footage before posting; the draft shows exactly which shots to record.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import ai
import content

W, H, FPS = 1080, 1920, 30

# ───────────────────────── product from link ─────────────────────────
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def fetch_product(url: str) -> dict:
    """Best effort: read og: tags / JSON-LD from the product page. Shops often block bots,
    so a failure is normal and the user's photos + notes are used instead."""
    info = {"url": url, "name": "", "description": "", "images": [], "ok": False, "note": ""}
    try:
        import requests
        from bs4 import BeautifulSoup
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-PH,en;q=0.9"}, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        meta = lambda p: (soup.find("meta", property=p) or soup.find("meta", attrs={"name": p}) or {}).get("content", "")
        info["name"] = meta("og:title") or (soup.title.string.strip() if soup.title and soup.title.string else "")
        info["description"] = meta("og:description") or meta("description")
        info["images"] = [m.get("content") for m in soup.find_all("meta", property="og:image") if m.get("content")]
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
            except json.JSONDecodeError:
                continue
            for d in data if isinstance(data, list) else [data]:
                if isinstance(d, dict) and d.get("@type") == "Product":
                    info["name"] = d.get("name") or info["name"]
                    info["description"] = d.get("description") or info["description"]
                    imgs = d.get("image") or []
                    info["images"] += [imgs] if isinstance(imgs, str) else list(imgs)
        info["name"] = re.sub(r"\s*[|\-–]\s*(Shopee|TikTok|Lazada).*$", "", info["name"], flags=re.I).strip()
        generic = info["name"].lower() in ("", "shopee", "tiktok", "tiktok shop", "shopee philippines")
        info["ok"] = r.status_code == 200 and not generic
        if not info["ok"]:
            info["note"] = f"Hindi mabasa ang page (HTTP {r.status_code}); gagamitin ang photos at notes mo."
    except Exception as exc:
        info["note"] = f"Hindi ma-open ang link ({type(exc).__name__}); gagamitin ang photos at notes mo."
    if not info["ok"] and not info["name"]:
        info["name"] = name_from_url(url)
        if info["name"]:
            info["note"] += f" Nakuha ang pangalan mula sa link: “{info['name']}”."
    info["images"] = list(dict.fromkeys(i for i in info["images"] if i.startswith("http")))[:6]
    return info


def name_from_url(url: str) -> str:
    """Shopee: /Product-Name-Words-i.<shop>.<item>; TikTok Shop: /pdp/product-name-words/<id>."""
    from urllib.parse import unquote, urlparse
    path = unquote(urlparse(url).path)
    m = re.search(r"/([^/]+?)-i\.\d+\.\d+", path) or re.search(r"/pdp/([^/]+)/\d+", path)
    if not m:
        return ""
    name = re.sub(r"[-_]+", " ", m[1])
    return re.sub(r"\s+", " ", name.replace(" – ", " - ")).strip()


def download_images(urls: list[str], out: Path) -> list[Path]:
    import requests
    saved = []
    for i, u in enumerate(urls):
        try:
            r = requests.get(u, headers={"User-Agent": UA}, timeout=15)
            if r.ok and r.headers.get("content-type", "").startswith("image"):
                p = out / f"seller_{i}.jpg"
                p.write_bytes(r.content)
                saved.append(p)
        except Exception:
            continue
    return saved


CATEGORIES = {
    "beauty": r"serum|cream|lotion|lip|tint|makeup|skincare|sunscreen|toner|shampoo|perfume|cosmetic|facial|blush",
    "food": r"coffee|\btea\b|snack|chips|chocolate|juice|noodle|sauce|food|cookie|candy|protein|cereal",
    "gadgets": r"phone|charger|cable|earbuds|headphone|speaker|usb|power ?bank|bluetooth|keyboard|mouse|watch|led|camera",
    "fashion": r"dress|shirt|pants|shorts|skort|skirt|palda|blouse|bag|shoes|sandals|jacket|hoodie|wallet|\bcap\b|ootd|leggings|jeans",
    "home": r"organizer|storage|kitchen|lamp|pillow|bedsheet|towel|mop|cleaner|container|rack|\bfan\b|cookware|\bpan\b|tumbler|bottle|\bmug\b|flask",
    "pet": r"\bpet|dog|cat|leash|litter|kibble",
}
CAT_TAGS = {"beauty": ["beautyfinds", "skincareph"], "food": ["foodfinds", "pinoyfoodie"],
            "gadgets": ["gadgetfinds", "techfinds"], "fashion": ["fashionfinds", "ootdph"],
            "home": ["homefinds", "homeessentials"], "pet": ["petfinds", "furparent"], "other": ["musthave", "finds"]}


def categorize(name: str, extra: str = "") -> str:
    """The product name decides first; the description only breaks ties."""
    for text in (name, extra):
        t = text.lower()
        hit = next((c for c, pat in CATEGORIES.items() if re.search(pat, t)), None)
        if hit:
            return hit
    return "other"


def parse_notes(notes: str) -> dict:
    """Free-form notes. Lines like 'name: ...', 'problem: ...', 'warning: ...'; other lines = features."""
    out = {"features": [], "problem": "", "warning": "", "name": ""}
    for line in (notes or "").splitlines():
        line = line.strip(" -•*\t")
        if not line:
            continue
        m = re.match(r"(name|pangalan|problem|problema|warning|babala)\s*:\s*(.+)", line, re.I)
        if m:
            key = {"pangalan": "name", "problema": "problem", "babala": "warning"}.get(m[1].lower(), m[1].lower())
            out[key] = m[2].strip()
        else:
            out["features"] += [f.strip() for f in re.split(r"[;,]\s*", re.sub(r"^(features?|benefits?)\s*:\s*", "", line, flags=re.I)) if f.strip()]
    return out


# ───────────────────────── Caption Writer: 5 scripts ─────────────────────────
STYLES = ["Hands-only unboxing", "POV problem → solution", "Aesthetic b-roll + VO", "\"Totoo ba?\" label check", "3 reasons listicle"]


def _short(name: str) -> str:
    """2-3 words for spoken lines: drop brackets, sizes and 'for women'-type tails."""
    t = re.sub(r"[\[\(].*?[\]\)]", "", name)
    t = re.split(r"\s[-–|]\s|,|\bfor\b|\bwith\b", t, flags=re.I)[0]
    words = [w for w in t.split() if not re.fullmatch(r"\d+(ml|l|g|kg|oz|pcs|cm)?", w, re.I)]
    return " ".join(words[:3]) if words else "product na 'to"


def template_videos(p: dict, owns: bool) -> list[dict]:
    n = _short(p["name"])
    f = (p["features"] + ["[feature 1 mula sa label]", "[feature 2 mula sa label]", "[feature 3 mula sa label]"])[:3]
    lc = lambda t: t if t[:2].isupper() or t.startswith("[") else t[:1].lower() + t[1:]  # mid-sentence; keep acronyms
    F = [x[:1].upper() + x[1:] for x in f]
    prob = p["problem"] or "[problemang sinosolusyunan nito]"
    fashion = p["category"] == "fashion"
    found = ("sinuot ko" if fashion else "ginamit ko") if owns else "nakita ko"
    many_colors = any(re.search(r"kulay|color|variant", x, re.I) for x in p["features"])
    cta = "Check the basket para makita mo!"
    R = lambda s, e, footage, visual, vo, text: {"start": s, "end": e, "footage": footage, "visual": visual, "vo": vo, "text": text}
    vids = [
        {"style": STYLES[0], "title": "Unboxing",
         "hooks": [f"Unboxing tayo ng {n}", "Sulit ba 'to? Tingnan natin",
                   "Ilang kulay meron 'to? Tingnan natin" if many_colors else "Ito yung matagal kong tinitingnan"],
         "rows": [R(0, 3, "own", f"Close-up: kamay na binubuksan ang package ng {n}", f"Unboxing tayo ng {n}!", "Unboxing time"),
                  R(3, 10, "own", "Inilalabas ang produkto, ipinapakita lahat ng side", f"Ito na siya. Tingnan niyo yung itsura sa personal.", n),
                  R(10, 18, "own", "Kamay na ginagamit ang produkto, close-up", f"Ang bet ko dito: {lc(f[0])}. Tapos {lc(f[1])}.", f[0]),
                  R(18, 22, "seller", "Product photo, slow zoom sa detail", f"May {lc(f[2])} pa.", F[2]),
                  R(22, 25, "seller", "Hero shot ng produkto + arrow pababa", cta, "Check the basket")]},
        {"style": STYLES[1], "title": "POV",
         "hooks": [f"POV: ayaw mo na ng {prob}", f"Ito yung kailangan mo kung {prob}", f"Stop scrolling kung {prob} ka"],
         "rows": [R(0, 3, "own", f"POV, kamay lang: eksena ng {prob}", f"POV: {prob}.", "POV"),
                  R(3, 8, "own", "Kamay na kumukuha ng produkto sa mesa", f"Kaya {found} 'tong {n}.", n),
                  R(8, 15, "own", "Demo: kamay na ginagamit ang produkto", f"{F[0]}, tapos {lc(f[1])}.", F[0]),
                  R(15, 19, "seller", "Product photo, detail", f"May {lc(f[2])} pa.", F[2]),
                  R(19, 22, "seller", "Hero shot + arrow", cta, "Check the basket")]},
        {"style": STYLES[2], "title": "Aesthetic",
         "hooks": ["Small upgrade, big difference", "Aesthetic na, useful pa", "Ito yung bet ko ngayon"],
         "rows": [R(0, 3, "own", "Aesthetic shot: produkto sa mesa, natural light, mabagal na push-in", "Small upgrade, pero ang laking difference.", "small upgrade, big difference"),
                  R(3, 8, "seller", "Product photo, detail", f"Ito yung {n}.", n),
                  R(8, 14, "own", "Kamay na ginagamit ito, slow motion", f"{F[0]}.", F[0]),
                  R(14, 20, "own", "Lifestyle shot: produkto sa daily routine", f"Tapos {lc(f[1])}. " + ("Bagay sa kahit anong top." if fashion else "Ang ganda lang sa daily routine."), F[1]),
                  R(20, 25, "seller", "Hero shot + arrow", cta, "Check the basket")]},
        {"style": STYLES[3], "title": "Label check",
         "hooks": (["Totoo ba 'to? Check natin ang details", "Close-up check bago ka bumili", "Bago ka bumili, panoorin mo muna"] if fashion else
                   ["Totoo ba 'to? Check natin ang label", "Binasa ko ang label para sa'yo", "Bago ka bumili, panoorin mo muna"]),
         "rows": [R(0, 4, "own", "Kamay na hawak ang produkto, text na 'Totoo ba?'", f"Totoo ba yung sinasabi nila sa {n}? Check natin.", "Totoo ba?"),
                  R(4, 10, "seller", "Hero photo ng produkto", "Ito yung itsura niya.", n),
                  R(10, 18, "own", "Mabagal na close-up pan sa waistband, hiwa at loob" if fashion else "Mabagal na pan sa label / specs",
                    (f"Tingnan niyo: {lc(f[0])}. {F[1]}." if fashion else f"Sa label: {lc(f[0])}. {F[1]}."), "Detail check" if fashion else "Label check"),
                  R(18, 24, "own", "Close-up ng detail ng produkto", f"{F[2]}.", F[2]),
                  R(24, 30, "seller", "Hero shot + arrow", ("Para sa'kin, sulit. Check the basket!" if owns else "Kung bet mo rin, check the basket!"), "Check the basket")]},
        {"style": STYLES[4], "title": "3 reasons",
         "hooks": [f"3 reasons kung bakit bet ko 'tong {n}", f"3 bagay tungkol sa {n}", "Bago mo i-skip: 3 reasons lang"],
         "rows": [R(0, 3, "own", "Produkto sa gitna ng frame, kamay na nagbibilang ng 3", "3 reasons kung bakit bet ko 'to.", "3 reasons"),
                  R(3, 9, "own", f"Visual para sa: {f[0]}", f"Una, {lc(f[0])}.", f"1. {F[0]}"),
                  R(9, 15, "own", f"Visual para sa: {f[1]}", f"Pangalawa, {lc(f[1])}.", f"2. {F[1]}"),
                  R(15, 20, "seller", "Product photo, detail", f"Pangatlo, {lc(f[2])}.", f"3. {F[2]}"),
                  R(20, 24, "seller", "Hero shot + arrow", cta, "Check the basket")]},
    ]
    tags = ["ad"] + CAT_TAGS[p["category"]] + ["finds"]
    for v in vids:
        v["hook"] = v["hooks"][0]
        v["caption"] = f"{v['hooks'][0]}. {F[0]} at {lc(f[1])}." + (f" Paalala: {p['warning']}." if p["warning"] else "") + " Check the basket!"
        v["hashtags"] = list(dict.fromkeys(tags))[:5]
        v["pinned_comment"] = "Check the basket para sa details at variants!"
    return vids


SHOWCASE_STYLES = ["Lookbook walk-in", "3 ways to style", "Walk / runway", "Detail check", "Galaw test"]
LOOKBOOK_SETTING = ("a bright minimalist neutral studio with white arched walls, a cream boucle sofa, dried pampas grass "
                    "in white ceramic vases, light wood floor, soft diffused daylight")


def fashion_showcase_videos(p: dict, model: dict) -> list[dict]:
    """OOTD showcase: no voiceover, the model wears and displays the item; short on-screen text only."""
    n, m = _short(p["name"]), model["name"]
    f = (p["features"] + ["[detail 1]", "[detail 2]", "[detail 3]"])[:3]
    F = [x[:1].upper() + x[1:] for x in f]
    R = lambda s, e, footage, visual, text, en="", outfit=None: dict(start=s, end=e, footage=footage, visual=visual, vo="", text=text,
                                                                    visual_en=en, **({"outfit": outfit} if outfit else {}))
    end = lambda s, e: R(s, e, "own", f"{m} final pose, nakaharap sa camera, kita ang buong outfit", "Check the basket",
                         "She settles into a relaxed final pose facing the camera, one hand lightly on her hip, soft smile; the full outfit is visible")
    vids = [
        {"style": SHOWCASE_STYLES[0], "title": "Lookbook", "hooks": ["OOTD check", f"Today's fit: {n}", "Simple pero ang ganda"],
         "rows": [R(0, 4, "own", f"{m} pumapasok sa frame mula sa kaliwa, humihinto sa gitna at ngumingiti sa camera", "OOTD check",
                    "She walks into frame from the left, stops at center and smiles at the camera"),
                  R(4, 10, "own", f"{m} hinahawakan ang top at inaayos ang waistband ng {n}, nakatingin pababa saka sa camera", "",
                    "She lightly touches the hem of her top and smooths the waistband of the skort, glances down, then back at the camera"),
                  R(10, 16, "own", f"{m} hand on hip, half-turn para makita ang gilid at hiwa ng {n}, inaayos ang buhok", "",
                    "Hand on hip, she does a slow half-turn to show the side and the asymmetric hem, then tucks her hair behind one ear"),
                  R(16, 20, "seller", "Seller photo: detail ng produkto, slow zoom", ""),
                  end(20, 24)]},
        {"style": SHOWCASE_STYLES[1], "title": "3 ways", "hooks": [f"3 ways to style this {n.split()[-1].lower()}", "Isang skort, 3 outfits", "Saan mo susuotin?"],
         "rows": [R(0, 3, "own", f"{m} suot ang {n} at black crop top, nakatayo sa gitna", "3 ways to style",
                    "She stands at center and gives a small wave and smile to the camera", "a fitted black crop top"),
                  R(3, 9, "own", f"Look 1: {m} suot ang {n} at fitted black crop top, umiikot", "Look 1: casual",
                    "She turns slowly in a full circle to show the casual look", "a fitted black crop top"),
                  R(9, 15, "own", f"Look 2: {m} suot ang {n} at white button-down blouse, naglalakad", "Look 2: office",
                    "She walks a few steps toward the camera and stops in a confident pose", "a white button-down blouse tucked in"),
                  R(15, 21, "own", f"Look 3: {m} suot ang {n} at oversized cream knit sweater", "Look 3: weekend",
                    "She adjusts the sweater sleeves and does a relaxed half-turn", "an oversized cream knit sweater, front tucked in"),
                  end(21, 24)]},
        {"style": SHOWCASE_STYLES[2], "title": "Walk", "hooks": ["Lakad-lakad lang", "Walk check", "Kita ang hiwa pag naglalakad"],
         "rows": [R(0, 3, "own", f"{m} naglalakad papunta sa camera, full body", "Walk check",
                    "Full body: she walks toward the camera with an easy, natural stride"),
                  R(3, 9, "own", f"{m} lumiliko at naglalakad palayo, kita ang likod ng {n}", n,
                    "She turns and walks away from the camera, showing the back of the skort"),
                  R(9, 15, "own", f"{m} humihinto at umiikot, gumagalaw ang laylayan", F[2],
                    "She stops and spins once slowly; the hem moves naturally"),
                  R(15, 20, "own", f"Side view: {m} naglalakad, kita ang hugis ng {n}", F[0],
                    "Side view tracking shot as she walks across the room, showing the silhouette of the skort"),
                  end(20, 24)]},
        {"style": SHOWCASE_STYLES[3], "title": "Detail", "hooks": ["Close-up check", "Tingnan natin ang details", "Zoom in tayo"],
         "rows": [R(0, 3, "own", f"{m} suot ang {n}, camera dahan-dahang lumalapit", "Close-up check",
                    "She stands still and smiles while the camera slowly pushes in from full body to waist level"),
                  R(3, 8, "own", f"Close-up: waistband ng {n} habang inaayos ni {m}", F[0],
                    "Close-up at waist level: her hands smooth the high waistband of the skort"),
                  R(8, 13, "seller", "Seller photo: detail na makikita ang loob / inner part", F[1]),
                  R(13, 18, "own", f"Close-up: laylayan at hiwa ng {n} habang gumagalaw si {m}", F[2],
                    "Close-up on the asymmetric hem as she shifts her weight from one leg to the other"),
                  end(18, 22)]},
        {"style": SHOWCASE_STYLES[4], "title": "Galaw", "hooks": ["Upo, tayo, lakad", "Galaw test", "Paano siya pag gumagalaw?"],
         "rows": [R(0, 3, "own", f"{m} suot ang {n}, nakatayo sa gitna", "Galaw test",
                    "She stands at center, full body, and smiles at the camera"),
                  R(3, 8, "own", f"{m} umuupo sa sofa, kita ang fit ng {n}", "Upo",
                    "She sits down on the cream sofa naturally and crosses her legs"),
                  R(8, 13, "own", f"{m} tumatayo at inaayos ang {n}", "Tayo",
                    "She stands up from the sofa and smooths the front of the skort"),
                  R(13, 18, "own", f"{m} naglalakad sa kuwarto", "Lakad", "She walks across the room with a relaxed stride"),
                  R(18, 21, "seller", "Seller photo: buong produkto", F[1]),
                  end(21, 24)]},
    ]
    tags = ["ad"] + CAT_TAGS[p["category"]] + ["ootd"]
    for v in vids:
        for r in v["rows"][1:-1]:
            r["text"] = ""  # lookbook look: only the hook and the CTA on screen
        v["hook"] = v["hooks"][0]
        v["caption"] = f"{v['hooks'][0]}. {F[0]}, {f[1][:1].lower() + f[1][1:]}. Check the basket!"
        v["hashtags"] = list(dict.fromkeys(tags))[:5]
        v["pinned_comment"] = "Check the basket para sa sizes at kulay!"
        v["no_vo"] = True
    return vids


BEAUTY_STYLES = ["Swipe, set, go", "Multi-use: labi at pisngi", "Shade check", "Mabilis na GRWM", "Product reveal"]
BEAUTY_SETTING = ("a bright, minimal bedroom vanity with a round mirror, a white desk, a small vase of fresh flowers "
                  "and soft window daylight")


def beauty_showcase_videos(p: dict, model: dict) -> list[dict]:
    """Beauty + AI model, no voiceover. Shows application only; never fabricates proof (no transfer tests,
    no before/after). On-screen text comes only from the label/listing features."""
    n, m = _short(p["name"]), model["name"]
    f = (p["features"] + ["[feature 1 mula sa label]", "[feature 2]", "[feature 3]"])[:3]
    F = [x[:1].upper() + x[1:] for x in f]
    R = lambda s, e, footage, visual, text, en="": dict(start=s, end=e, footage=footage, visual=visual, vo="", text=text, visual_en=en)
    end = lambda s, e: R(s, e, "own", f"{m} nakangiti sa camera, hawak ang tube sa tabi ng mukha", "Check the basket",
                         "She smiles at the camera holding the tube next to her face, label facing the camera")
    vids = [
        {"style": BEAUTY_STYLES[0], "title": "Swipe set go", "hooks": ["Swipe, set, go", "Isang swipe lang", "Lip check"],
         "rows": [R(0, 3, "own", f"{m} kinukuha ang {n} mula sa vanity at ipinapakita sa camera", "Swipe, set, go",
                    "She picks up the tint tube from the vanity and shows it to the camera, label facing forward"),
                  R(3, 8, "own", f"Close-up: binubuksan ang tube, kita ang applicator", F[0],
                    "Close-up of her hands opening the tube; the doe-foot applicator comes out cleanly"),
                  R(8, 14, "own", f"Close-up: {m} sine-swipe ang tint sa labi", F[1],
                    "Close-up on her lips as she swipes the tint on evenly with the applicator, slow and neat"),
                  R(14, 18, "own", f"{m} pinagdidikit ang labi at tumitingin sa salamin", "",
                    "She presses her lips together softly and checks them in the mirror"),
                  end(18, 22)]},
        {"style": BEAUTY_STYLES[1], "title": "Multi-use", "hooks": ["Labi at pisngi, isang tint", "Multi-use check", "Blush din pala 'to?"],
         "rows": [R(0, 3, "own", f"{m} hawak ang {n}, nakangiti", "Multi-use", "She holds up the tint and smiles at the camera"),
                  R(3, 9, "own", f"Close-up: {m} naglalagay ng kaunting tint sa pisngi at bina-blend gamit ang daliri", "Sa pisngi",
                    "Close-up: she dabs a small amount of tint on her cheek and blends it softly with her fingertips"),
                  R(9, 15, "own", f"Close-up: {m} naglalagay ng tint sa labi", "Sa labi",
                    "Close-up: she applies the same tint to her lips with the applicator"),
                  R(15, 19, "seller", "Product photo (walang text)", F[2]),
                  end(19, 23)]},
        {"style": BEAUTY_STYLES[2], "title": "Shade check", "hooks": ["Shade check", "Ito yung kulay sa personal", "Swatch muna"],
         "rows": [R(0, 3, "own", f"Kamay ni {m} hawak ang tube sa harap ng camera", "Shade check",
                    "Her hand holds the tube up to the camera in soft daylight"),
                  R(3, 8, "own", "Close-up: isang swatch sa likod ng kamay", "",
                    "Close-up: she draws one smooth swatch of the tint on the back of her hand; the color matches the tube exactly"),
                  R(8, 13, "own", "Close-up: dahan-dahang pinapaikot ang kamay sa ilaw para makita ang finish", F[0],
                    "Close-up: she slowly tilts her hand in the daylight to show the soft matte finish of the swatch"),
                  R(13, 18, "own", f"{m} naglalagay sa labi, medium close-up", "",
                    "Medium close-up: she applies the tint to her lips and smiles"),
                  end(18, 22)]},
        {"style": BEAUTY_STYLES[3], "title": "GRWM", "hooks": ["Quick GRWM", "Last step bago umalis", "5-second lip"],
         "rows": [R(0, 3, "own", f"{m} nakaupo sa vanity, inaayos ang buhok", "Quick GRWM",
                    "She sits at the vanity, already dressed, and tucks her hair behind her ear"),
                  R(3, 9, "own", f"{m} naglalagay ng {n} sa labi habang nakatingin sa salamin", "Last step: lips",
                    "She applies the tint to her lips while looking into the round mirror"),
                  R(9, 14, "own", f"{m} kinukuha ang bag at isinisilid ang tube", "",
                    "She drops the tint tube into her small handbag and picks up the bag"),
                  R(14, 18, "seller", "Product photo (walang text)", F[0]),
                  end(18, 22)]},
        {"style": BEAUTY_STYLES[4], "title": "Reveal", "hooks": [f"{n}", "Ang cute ng packaging", "Bagong lip tint check"],
         "rows": [R(0, 4, "own", "Tube nakatayo sa vanity, mabagal na push-in ng camera", "New fave tint?",
                    "The tint tube stands on the white vanity; the camera slowly pushes in"),
                  R(4, 9, "own", f"Kamay ni {m} pinupulot ang tube at dahan-dahang iniikot para makita ang label", F[0],
                    "Her hand picks up the tube and slowly rotates it to show the label"),
                  R(9, 13, "seller", "Product photo (walang text)", F[1]),
                  R(13, 18, "own", f"{m} naglalagay sa labi, nakangiti", F[2], "She applies the tint to her lips and smiles at the camera"),
                  end(18, 22)]},
    ]
    tags = ["ad"] + CAT_TAGS[p["category"]] + ["liptint"]
    for v in vids:
        v["hook"] = v["hooks"][0]
        v["caption"] = f"{v['hooks'][0]}. {F[0]}, {f[1][:1].lower() + f[1][1:]} ayon sa label. Check the basket!"
        v["hashtags"] = list(dict.fromkeys(tags))[:5]
        v["pinned_comment"] = "Check the basket para sa shades!"
        v["no_vo"] = True
    return vids


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "product_lock": {"type": "string"},
        "videos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "style": {"type": "string", "enum": STYLES},
                    "title": {"type": "string"},
                    "hooks": {"type": "array", "items": {"type": "string"}},
                    "hook": {"type": "string"},
                    "rows": {"type": "array", "items": {
                        "type": "object",
                        "properties": {"start": {"type": "number"}, "end": {"type": "number"},
                                       "footage": {"type": "string", "enum": ["own", "seller"]},
                                       "visual": {"type": "string"}, "vo": {"type": "string"}, "text": {"type": "string"}},
                        "required": ["start", "end", "footage", "visual", "vo", "text"], "additionalProperties": False}},
                    "caption": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "pinned_comment": {"type": "string"},
                },
                "required": ["style", "title", "hooks", "hook", "rows", "caption", "hashtags", "pinned_comment"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["product_lock", "videos"],
    "additionalProperties": False,
}

PLAN_SYSTEM = """You write faceless short-form affiliate videos (9:16, 20-30 s) for a Filipino audience, in natural Taglish.
Write exactly 5 videos, one per style, in this order: """ + "; ".join(STYLES) + """.
The 5 videos must be clearly different (hook type, angle, structure): platforms penalise repetitive, near-duplicate content.
Structure that converts: hook (first 3 s, understandable on mute, product visible early) -> problem or desire -> product -> proof from the label/listing -> CTA.
Rows: consecutive, start at 0, end between 20 and 30. Max about 2.5 spoken words per second per row. Max 3 benefits per video.
footage: "own" = a shot the creator must film (faceless: hands, POV, product on table) or generate with an AI video tool; "seller" = a seller photo. At least half of the seconds must be "own"; use at most 3 seller rows.
Hard rules for every vo, text, hook, caption and pinned comment:
- No price, discount, voucher or sale talk. No platform names (TikTok, Shopee, Lazada, IG, Instagram, Facebook, FB, Threads, YouTube).
- CTA is "check the basket" (never "yellow basket"). Caption ends with a CTA. hashtags: 3-5, without '#', always include "ad".
- Only claim what the product facts support. Name features, not invented effects. No weight loss/slimming, whitening, curing, medical, before-and-after, guaranteed results, fake urgency, invented ratings or sold counts.
- If OWNS_PRODUCT is false, never say the creator used/tried it ("ginamit ko", "nasubukan ko", "gamit ko", "same tayo"); use "nakita ko 'to", "gusto kong i-try", "ito yung bet ko". No verdicts.
- Put label warnings in the caption when given.
product_lock: one sentence describing only what is known about the product's look (type, colors, visible text); write [unknown] for what is not known."""


def plan_videos(p: dict, owns: bool, model: dict | None = None) -> tuple[list[dict], str, str]:
    """Returns (videos, product_lock, author)."""
    if model and p["category"] == "fashion":  # OOTD: model displays the clothes, no voiceover
        return fashion_showcase_videos(p, model), f"the {p['name'] or 'garment'} exactly as in the product reference photo", "showcase template"
    if model and p["category"] == "beauty":   # beauty: model shows application, no voiceover, no fabricated proof
        return beauty_showcase_videos(p, model), f"the {p['name'] or 'product'} tube exactly as in the product reference photo", "beauty showcase template"
    facts = (f"Product name: {p['name'] or '[unknown]'}\nCategory: {p['category']}\n"
             f"Listing description: {p['description'][:3000] or '[none]'}\n"
             f"Creator notes - features: {', '.join(p['features']) or '[none]'}; problem it solves: {p['problem'] or '[none]'}; "
             f"label warnings: {p['warning'] or '[none]'}\nOWNS_PRODUCT: {str(owns).lower()}")
    res = ai._ask_json(PLAN_SYSTEM, facts, PLAN_SCHEMA)
    if res and len(res.get("videos", [])) == 5:
        return res["videos"], res["product_lock"], "Claude"
    lock = f"The {p['name'] or 'product'} exactly as in the product reference photo"
    return template_videos(p, owns), lock, "template"


# ───────────────────────── Reg Checker: platform policy ─────────────────────────
PLATFORMS = r"(tik ?tok( shop)?|shopee|lazada|instagram|ig|facebook|fb|threads|youtube|yt)"
PLATFORM_RE = re.compile(rf"\b{PLATFORMS}\b", re.I)
PLATFORM_PHRASE_RE = re.compile(rf"\s*\b(sa|on|in|from|ng|via)\s+(the\s+|my\s+|aming\s+)?{PLATFORMS}(\s+(page|shop|account))?\b", re.I)
PRICE_RE = re.compile(r"(₱|\bphp\b|\bpesos?\b|\bpiso\b|\bpresyo\b|\bprice\b|\d+\s?%\s?off|\bdiscount|\bvoucher|\bsale\b|\bpromo\b|\bmura na lang)", re.I)
CLAIMS_RE = re.compile(r"(slimming|pampapayat|pumayat|weight ?loss|fat ?burn|whitening|pampaputi|\bcure|gamot sa|nakakagaling|"
                       r"guaranteed|100% effective|before (and|&) after|glow from (the )?inside|guilt[- ]free|miracle|fda[- ]approved)", re.I)
URGENCY_RE = re.compile(r"(last stock|ubos na|mauubusan|limited time|ngayon lang|sold out|flash sale|\d+\s?k?\+? sold|best ?seller|"
                        r"\d(\.\d)? stars?|5-star)", re.I)
FIRST_PERSON = [(r"\bginamit ko\b", "nakita ko"), (r"\bnasubukan ko\b", "gusto kong i-try"), (r"\btinry ko\b", "gusto kong i-try"),
                (r"\bgamit ko\b", "bet ko"), (r"\bsame tayo\b", "baka bet mo rin"), (r"\bi tried\b", "I found"),
                (r"\bpara sa'kin,? sulit\b", "mukhang sulit")]
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _drop_sentences(text: str, pattern: re.Pattern) -> tuple[str, list[str]]:
    kept, dropped = [], []
    for s in SENT_SPLIT.split(text):
        (dropped if pattern.search(s) else kept).append(s)
    return " ".join(kept).strip(), dropped


def policy_check(v: dict, owns: bool) -> list[dict]:
    """Fixes what can be fixed in place and returns findings [{level, msg}]."""
    found = []
    note = lambda lvl, msg: found.append({"level": lvl, "msg": msg})

    def clean(text: str, where: str) -> str:
        t = re.sub(r"(click|i-?click|check)?\s*(the\s+)?yellow basket", "check the basket", text, flags=re.I)
        for pat, label in ((PRICE_RE, "presyo/sale"), (CLAIMS_RE, "bawal na claim"), (URGENCY_RE, "fake urgency/ratings")):
            if pat.search(t):
                t, dropped = _drop_sentences(t, pat)
                note("fixed", f"{where}: tinanggal ang {label}: “{' '.join(dropped)[:80]}”")
        if PLATFORM_RE.search(t):
            note("fixed", f"{where}: tinanggal ang pangalan ng platform")
            t = PLATFORM_RE.sub("", PLATFORM_PHRASE_RE.sub("", t))
        if not owns and any(re.search(pat, t, re.I) for pat, _ in FIRST_PERSON):
            fp = re.compile("|".join(pat for pat, _ in FIRST_PERSON), re.I)
            t, dropped = _drop_sentences(t, fp)
            note("fixed" if t else "warn", f"{where}: inalis ang first-person claim “{' '.join(dropped)[:60]}” (hindi mo pa hawak ang product)"
                 + ("" if t else "; magsulat ng bagong linya"))
        t = re.sub(r"\s+([!?.,])", r"\1", re.sub(r"\s{2,}", " ", t)).strip(" ,")
        return t[:1].upper() + t[1:]

    v["hooks"] = [h for h in (clean(h, "Hook") for h in v["hooks"]) if len(h) > 3]
    v["hook"] = clean(v["hook"], "Hook")
    if len(v["hook"]) <= 3:
        v["hook"] = v["hooks"][0] if v["hooks"] else ""
        note("warn" if not v["hook"] else "fixed", "Hook: pinalitan ng ibang hook" if v["hook"] else "Hook: kailangan ng bagong hook")
    if not v["hooks"] and v["hook"]:
        v["hooks"] = [v["hook"]]
    for i, r in enumerate(v["rows"], 1):
        r["vo"], r["text"] = clean(r["vo"], f"Row {i} VO"), clean(r["text"], f"Row {i} text")
        secs, words = max(0.5, r["end"] - r["start"]), len(r["vo"].split())
        if words > secs * 2.5 + 1:
            note("warn", f"Row {i}: {words} salita sa {secs:.0f}s, medyo mabilis (max ~{secs * 2.5:.0f})")
    v["caption"], v["pinned_comment"] = clean(v["caption"], "Caption"), clean(v["pinned_comment"], "Pinned comment")
    if len(v["pinned_comment"]) < 10:
        v["pinned_comment"] = "Check the basket para sa details at variants!"
    tags = [re.sub(r"[^\w]", "", h.lstrip("#")) for h in v["hashtags"]]
    tags = [t for t in tags if t and not PLATFORM_RE.fullmatch(t) and not re.match(r"(tiktok|shopee)", t, re.I)]
    if "ad" not in [t.lower() for t in tags]:
        tags.insert(0, "ad")
        note("fixed", "Caption: idinagdag ang #ad (affiliate disclosure)")
    v["hashtags"] = tags[:5]
    if len(v["caption"]) < 10:
        v["caption"] = (v["hook"] + "." if v["hook"] else "").strip()
        note("fixed", "Caption: ginawang bago mula sa hook")
    if "basket" not in v["caption"].lower():
        v["caption"] = v["caption"].rstrip() + " Check the basket!"
        note("fixed", "Caption: idinagdag ang CTA “check the basket”")
    own_secs = sum(r["end"] - r["start"] for r in v["rows"] if r["footage"] == "own")
    total = v["rows"][-1]["end"]
    if not 20 <= total <= 30:
        note("warn", f"Haba: {total:.0f}s (target 20-30s)")
    if own_secs < total / 2:
        note("warn", f"Original footage: {own_secs:.0f}s lang sa {total:.0f}s, dagdagan ng sariling shots")
    seller_rows = sum(r["footage"] == "seller" for r in v["rows"])
    if seller_rows > 3:
        note("warn", f"{seller_rows} seller-photo shots (max 3 para hindi ma-flag na unoriginal)")
    return found


def distinct_check(videos: list[dict]) -> list[str]:
    issues, seen = [], {}
    for i, v in enumerate(videos, 1):
        key = re.sub(r"\W", "", v["hook"].lower())[:30]
        if key in seen:
            issues.append(f"Video {i} at Video {seen[key]}: magkapareho ang hook. Palitan ang isa para hindi ma-flag na duplicate.")
        seen[key] = i
    return issues


# ───────────────────────── Video Editor ─────────────────────────
FONT_PATHS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
              "C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]


def _font(size: int):
    from PIL import ImageFont
    for p in FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def _plain(text: str) -> str:
    return re.sub(r"[^\w\s.,!?'\"’“”:;()/&%+#-]", "", text).strip()  # emoji-free for the PIL fonts


def _wrap(draw, text: str, font, width: int) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= width:
            cur = test
        else:
            lines.append(cur); cur = w
    return lines + [cur] if cur else lines


def _base_from_image(img_path: Path, out: Path):
    from PIL import Image, ImageFilter
    im = Image.open(img_path).convert("RGB")
    bg = im.copy()
    s = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * s) + 1, int(bg.height * s) + 1))
    left, top = (bg.width - W) // 2, (bg.height - H) // 2
    bg = bg.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(40))
    s2 = min((W - 80) / im.width, (H * 0.62) / im.height)
    fg = im.resize((int(im.width * s2), int(im.height * s2)))
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    bg.save(out, quality=92)


def _shot_card(row: dict, n: int, out: Path):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (W, H), (28, 22, 52))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((70, 560, W - 70, 1360), 40, outline=(255, 111, 174), width=6)
    d.text((W // 2, 650), f"SHOT {n}: KUNAN MO ITO", font=_font(52), fill=(255, 111, 174), anchor="mm")
    y = 760
    for line in _wrap(d, _plain(row["visual"]), _font(58), W - 220):
        d.text((W // 2, y), line, font=_font(58), fill=(255, 255, 255), anchor="mm"); y += 76
    d.text((W // 2, 1290), "sariling footage o AI clip, 9:16", font=_font(36), fill=(170, 160, 220), anchor="mm")
    im.save(out, quality=92)


def _overlay(text: str, out: Path, draft: bool, end_card: bool = False):
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    t = _plain(text)
    if t:
        f = _font(72)
        lines = _wrap(d, t, f, W - 260)[:3]
        y = 300  # safe zone: upper third, away from the bottom 20% and the right-side buttons
        for line in lines:
            tw = d.textlength(line, font=f)
            d.rounded_rectangle(((W - tw) / 2 - 30, y - 50, (W + tw) / 2 + 30, y + 50), 24, fill=(255, 255, 255, 235))
            d.text((W / 2, y), line, font=f, fill=(20, 16, 40), anchor="mm"); y += 112
    if end_card:
        d.polygon([(W / 2 - 70, 1390), (W / 2 + 70, 1390), (W / 2, 1490)], fill=(255, 210, 61, 255))
    if draft:
        d.rounded_rectangle((40, 40, 520, 120), 20, fill=(232, 74, 95, 230))
        d.text((280, 80), "DRAFT - hindi pa pang-post", font=_font(34), fill=(255, 255, 255), anchor="mm")
    im.save(out)


def _ff(*args, timeout=600):
    subprocess.run([content.FFMPEG, "-y", "-v", "error", *map(str, args)], check=True, timeout=timeout)


def render_video(v: dict, n: int, seller_imgs: list[Path], clips: list[Path], vo: Path | None, work: Path, out: Path) -> dict:
    """Draft when no clips (seller photos on seller rows, 'shot needed' cards on own rows).
    Final when clips are given: clips fill the rows in order; seller rows keep photos."""
    if not content.FFMPEG:
        raise RuntimeError("ffmpeg not found (pip install imageio-ffmpeg)")
    work.mkdir(parents=True, exist_ok=True)
    draft = not clips
    rows = v["rows"]
    total = rows[-1]["end"]
    scale = 1.0
    if vo:
        vo_len = content._duration(vo) or total
        scale = max(0.6, min(1.6, vo_len / total))  # stretch the timeline to the voiceover
    segs, ci, si = [], 0, 0
    clip_rows = [i for i, r in enumerate(rows) if r["footage"] == "own"] if clips else []
    for i, r in enumerate(rows):
        secs = max(1.0, (r["end"] - r["start"]) * scale)
        seg, ov = work / f"seg{i}.mp4", work / f"ov{i}.png"
        _overlay(r["text"] if i == 0 or r["text"] else "", ov, draft, end_card=(i == len(rows) - 1))
        if clips and (i in clip_rows or not seller_imgs):
            clip = clips[ci % len(clips)]; ci += 1
            if clip.suffix.lower() in content.IMAGE_EXT:
                base = work / f"base{i}.jpg"; _base_from_image(clip, base); src = ["-loop", "1", "-t", f"{secs:.2f}", "-i", base]
            else:
                src = ["-stream_loop", "-1", "-t", f"{secs:.2f}", "-i", clip]
            vf = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1[v];[v][1:v]overlay=0:0[o]"
            _ff(*src, "-i", ov, "-filter_complex", vf, "-map", "[o]", "-an", "-t", f"{secs:.2f}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", seg)
        else:
            base = work / f"base{i}.jpg"
            if r["footage"] == "seller" and seller_imgs:
                _base_from_image(seller_imgs[si % len(seller_imgs)], base); si += 1
            else:
                _shot_card(r, i + 1, base)
            frames = int(secs * FPS)
            zoom = f"zoompan=z='min(zoom+0.0009,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS}"
            _ff("-i", base, "-i", ov, "-filter_complex", f"[0:v]{zoom},setsar=1[v];[v][1:v]overlay=0:0[o]", "-map", "[o]",
                "-frames:v", frames, "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", seg)
        segs.append(seg)
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{s.resolve()}'\n" for s in segs))
    silent = work / "video_only.mp4"
    _ff("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", silent)
    if vo:
        _ff("-i", silent, "-i", vo, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-shortest", out)
    else:
        _ff("-i", silent, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-shortest", out)
    shutil.rmtree(work, ignore_errors=True)
    return {"draft": draft, "seconds": round(sum((r["end"] - r["start"]) * scale for r in rows), 1)}


# ───────────────────────── Pablo scene prompts ─────────────────────────
NEGATIVE = ("deformed hands, extra fingers, fused fingers, unnatural grip, plastic-looking skin, harsh lighting, oversaturated colors, "
            "floating objects, flickering, excessive camera shake, visual glitches, added text, captions, subtitles, logos, watermarks, "
            "distorted packaging, altered design, morphed text, misspelled branding, changed logo, duplicated products, shifting label, "
            "blurry product text, changing proportions, incorrect color, any human face")


MODEL_NEGATIVE = ("deformed hands, extra fingers, fused fingers, unnatural grip, distorted facial features, inconsistent identity, "
                  "plastic-looking skin, excessive retouching, harsh lighting, oversaturated colors, floating objects, flickering, "
                  "excessive camera shake, visual glitches, added text, captions, subtitles, logos, watermarks, warped fabric, "
                  "changing pattern, wrong fit, changing garment color, shifting hem, garment shape that differs from the product reference, "
                  "unnatural gait, stiff body, jittery camera, sudden zooms")
DEFAULT_SETTING = "a bright, tidy Filipino home, wooden table, soft natural window light from the left, a small green plant in the background"


def scene_prompts(v: dict, lock: str, model: dict | None = None) -> list[dict]:
    """Pablo Scene Format. Faceless hands-only by default; on-camera with MODEL LOCK when a model reference is given."""
    setting = (model or {}).get("setting") or DEFAULT_SETTING
    out, first = [], True
    for i, r in enumerate(v["rows"], 1):
        if r["footage"] != "own":
            continue
        secs = min(8, max(2, round(r["end"] - r["start"])))
        sa = (f"Vertical 9:16 video. {setting[:1].upper() + setting[1:]}. Calm, cozy, natural mood." if first else
              "Continue in the same setting from Scene 1, maintaining consistent surroundings, lighting, and atmosphere.")
        action = r.get("visual_en") or r["visual"]
        lookbook = bool(v.get("no_vo"))
        if model:
            wear = f"{r['outfit']} with the product from the product reference photo" if r.get("outfit") else model["outfit"]
            subject = (f"Use the same woman, model {model['name']}, from the model reference photo, preserving her facial features, "
                       f"{model['look']}, wearing {wear}. {action}. Slow, natural, relaxed movement; "
                       + ("natural, relaxed beauty-UGC energy, like filming her own makeup routine." if model.get("kind") == "beauty" else
                          "natural, confident, relaxed fashion-lookbook posing." if lookbook else
                          "she looks like a real person filming a casual try-on video."))
            if model.get("kind") == "beauty":
                placement = (f"When the product is in frame, show {lock}: same shape, color, logo, typography and printed text; label facing "
                             "the camera when held up. The tint color on lips, cheeks or skin must match the product's shade exactly. "
                             "Do not redesign the packaging. Show only normal application; no transfer tests, no before/after.")
            else:
                placement = (f"She wears {lock}, matching the product reference photo exactly: same cut, asymmetric shape, hem, "
                             "waistband, color and fabric texture. Do not redesign or reinterpret the garment. Keep it consistent throughout the clip.")
            camera = (("Close-up to medium close-up, eye level, steady phone-on-tripod look with gentle micro movement. Soft window daylight, "
                       "natural skin texture with pores, true-to-life color, clean beauty UGC feel.") if model.get("kind") == "beauty" else
                      ("Full-body to knees-up framing, eye level, smooth slow dolly or gentle pan following her, no shake. Soft diffused daylight, "
                       "airy neutral palette, natural skin texture, clean premium lookbook feel, subtle film grain.") if v.get("no_vo") else
                      ("Medium shot from the waist or knees up, eye-level phone camera, subtle handheld sway. Soft daylight, gentle shadows, "
                       "natural skin texture, warm color grading, subtle film grain. Looks like authentic UGC filmed on a phone at home."))
            cont = ("* Preserve the model's face and hair exactly as in Scene 1. Only the top changes; the skort stays identical.\n"
                    if r.get("outfit") else "* Preserve the model's face, hair and outfit exactly as in Scene 1.\n")
            neg = MODEL_NEGATIVE if model.get("kind") != "beauty" else (
                "deformed hands, extra fingers, distorted lips, smeared lipstick outside the lip line, color that differs from the product, "
                "glossy wet look, distorted facial features, inconsistent identity, plastic-looking skin, excessive retouching, "
                "distorted packaging, morphed text, misspelled branding, changed logo, duplicated products, added text, captions, "
                "subtitles, watermarks, flickering, jittery camera")
        else:
            subject = (f"Faceless: frame the shot as a close-up of a person's hands only, no face visible. {r['visual']}. "
                       "Slow, natural, relaxed movement.")
            placement = (f"Place {lock} in the frame. The front label must face the camera clearly and remain unobstructed. "
                         "Preserve the original packaging exactly, including shape, color, logo, typography, printed text and proportions. "
                         "Do not redesign or reinterpret it.")
            camera = ("Close-up, subtle handheld sway. Soft natural light, gentle shadows, shallow depth of field, "
                      "warm color grading, subtle film grain. Feels like an authentic product video filmed in a real home.")
            cont = "* Same hands and sleeves as Scene 1.\n"
            neg = NEGATIVE
        prompt = (f"Scene {i}: {action} ({secs} Seconds)\n\n"
                  f"{'Setting and Atmosphere' if first else 'Setting and Continuity'}\n{sa}\n\n"
                  f"Subject and Action\n{subject}\n\n"
                  f"Product Placement and Accuracy\n{placement}\n\n"
                  f"Camera and Visual Style\n{camera}\n\n"
                  + ("" if first else "Continuity Requirements\n* Match the setting, lighting, and visual style of Scene 1.\n"
                                      f"{cont}* Do not introduce new products, props, text, or logos.\n\n")
                  + f"Technical Requirements\n* Aspect ratio: 9:16 vertical\n* Duration: {secs} seconds\n"
                  f"* Style: {'Photorealistic beauty UGC' if model and model.get('kind') == 'beauty' else 'Photorealistic fashion lookbook' if lookbook else 'Photorealistic lifestyle UGC'}\n"
                  "* Motion: slow, subtle, natural\n* Text and logos: none added\n"
                  + ("* Subject consistency: match the model reference photo\n" if model else "")
                  + "* Audio: soft ambient room sound. No music, no speech, no subtitles.\n\n"
                  f"Negative Prompt\n{neg}")
        out.append({"row": i, "prompt": prompt})
        first = False
    return out


def model_visuals(v: dict, model: dict, fashion: bool) -> None:
    """On-camera shots for an AI model (replaces hands-only visuals on 'own' rows)."""
    name = model["name"]
    shots = ([f"{name} hawak ang skort sa harap ng camera, nakangiti", f"{name} suot ang skort, full body, dahan-dahang umiikot",
              f"Medium shot: {name} inaayos ang waistband, makikita ang high waist", f"{name} naglalakad papunta sa camera, kita ang asymmetric na hiwa",
              f"{name} nakaupo sa sofa, kita ang fit ng skort"] if fashion else
             [f"{name} hawak ang produkto sa harap ng camera", f"{name} ginagamit ang produkto, medium shot",
              f"Close-up: kamay ni {name} habang ginagamit ang produkto", f"{name} nakangiti habang hawak ang produkto sa tabi ng mukha"])
    k = 0
    for r in v["rows"]:
        if r["footage"] == "own":
            r["visual"] = shots[k % len(shots)]; k += 1


# ───────────────────────── result page ─────────────────────────

def _pack_html(job: dict) -> str:
    if not job.get("prompt_pack"):
        return ""
    import prompt_library
    return f"<style>{prompt_library.PACK_CSS}</style>" + prompt_library.render_pack(job["prompt_pack"], job["product"].get("name", ""))


def render_page(job: dict) -> str:
    e = html.escape
    p = job["product"]
    cards = []
    for n, v in enumerate(job["videos"], 1):
        rows = "".join(f"<tr><td>{r['start']:.0f}-{r['end']:.0f}s</td><td>{'🎥 ikaw' if r['footage'] == 'own' else '🖼 seller'}</td>"
                       f"<td>{e(r['visual'])}</td><td>{e(r['vo'])}</td><td>{e(r['text'])}</td></tr>" for r in v["rows"])
        pol = "".join(f"<li class='{f['level']}'>{'🔧' if f['level'] == 'fixed' else '⚠️'} {e(f['msg'])}</li>" for f in v["policy"]) or "<li class='ok'>✅ Pasado lahat</li>"
        prompts = "".join(f"<details><summary>Scene prompt para sa shot {s['row']} (Veo / Kling)</summary><pre>{e(s['prompt'])}</pre>"
                          f"<button class='copy'>📋 Copy prompt</button></details>" for s in v["prompts"])
        cap = f"{v['caption']}\n\n" + " ".join("#" + h for h in v["hashtags"])
        status = ("<span class='pill draft'>DRAFT · kailangan ng sariling footage</span>" if v["render"].get("draft", True)
                  else "<span class='pill ok'>FINAL · may original footage</span>")
        vid = f"/outbox/{job['id']}/video{n}.mp4"
        own = [i for i, r in enumerate(v["rows"], 1) if r["footage"] == "own"]
        st = v.get("auto", {}).get("stills", {})
        figs = "".join(
            (f"<figure><img src='/outbox/{job['id']}/{e(st[str(r)])}' alt=''><figcaption>Shot {r} "
             f"<button class='mini' data-act='redo' data-n='{n}' data-row='{r}'>🔄</button></figcaption></figure>") if str(r) in st
            else f"<figure class='empty'><div>Shot {r}</div><figcaption>wala pa</figcaption></figure>" for r in own)
        est = round(len(own) * job.get("est_per_clip", 0), 2)
        auto_box = (f"<h3>🤖 Auto (Google)</h3><div class='stills'>{figs}</div>"
                    f"<button class='btn' data-act='stills' data-n='{n}'>🖼 Gawa ng stills</button> "
                    f"<button class='btn' data-act='animate' data-n='{n}'>🎬 Animate ang video na 'to (≈${est})</button>"
                    "<p class='muted'>Tingnan muna ang stills: tama ba ang mukha at ang produkto? 🔄 para ulitin ang isa.</p>")
        cards.append(f"""<section class="card"><div class="vidwrap"><video src="{vid}?v={v['render'].get('rev', 0)}" controls playsinline></video>
<a class="btn" href="{vid}" download>⬇ Download</a></div><div class="body">
<h2>Video {n}: {e(v['style'])}</h2>{status} <span class="muted">📅 {e(v.get('slot', ''))}</span>
<h3>Hooks</h3><ol class="hooks">{''.join(f"<li{' class=pick' if h == v['hook'] else ''}>{e(h)}</li>" for h in v['hooks'])}</ol>
<h3>Script{' (walang voiceover: on-screen text lang, lagyan ng music mula sa music library ng platform)' if v.get('no_vo') else ''}</h3><table><tr><th>Oras</th><th>Footage</th><th>Visual</th><th>Voiceover (Taglish)</th><th>Text</th></tr>{rows}</table>
<h3>Caption</h3><pre class="cap">{e(cap)}</pre><button class="copy">📋 Copy caption</button>
<p class="muted">Pinned comment: {e(v['pinned_comment'])}</p>
<h3>Policy check</h3><ul class="pol">{pol}</ul>
<h3>Scene prompts{' (AI model)' if job.get('model') else ''}</h3>{prompts or '<p class="muted">Walang AI shots.</p>'}
{auto_box}
<h3>Gawing final (manual na clips)</h3><p class="muted">I-upload ang mga clip mo para sa 🎥 shots (sunod-sunod), at kung gusto mo, ang voiceover mo (mp3/m4a/wav).
Kung AI clips ang gamit mo, i-on ang AI-generated label pag nag-post.</p>
<form class="final" data-n="{n}"><input type="file" name="clips" multiple accept="video/*,image/*">
<label>Voiceover: <input type="file" name="vo" accept="audio/*,video/*"></label><button class="btn">🎬 Gawing final</button><span class="msg"></span></form>
</div></section>""")
    notes = "".join(f"<li>{e(x)}</li>" for x in job["notes"])
    total_est = round(sum(len([r for r in v["rows"] if r["footage"] == "own"]) for v in job["videos"]) * job.get("est_per_clip", 0), 2)
    busy = job.get("busy", "")
    auto_head = f"""<div class="head"><h2>🤖 Auto gamit ang Google</h2>
<p class="muted">1) Stills (mura) → 2) i-check mo → 3) Animate (Veo, may bayad) → 4) kusang final video. Nagastos sa job na 'to: ≈${job.get('auto_spent', 0):.2f}</p>
{'<p class="busy">⏳ Ginagawa: ' + e(busy) + '... (kusang magre-refresh)</p>' if busy else ''}
{'<p class="err">⚠️ ' + e(job['auto_error']) + '</p>' if job.get('auto_error') else ''}
<button class="btn" data-act="stills" data-n="0">🖼 Stills para sa lahat ng 5</button>
<button class="btn" data-act="animate" data-n="0">🎬 Animate lahat (≈${total_est})</button>
<span class="msg" id="automsg"></span></div>"""
    m = job.get("model")
    model_box = "" if not m else f"""<div class="head"><h2>🤖 AI model: {e(m['name'])}</h2>
<p class="muted">Lock (huwag baguhin sa bawat eksena): {e(m['look'])}; suot ang {e(m['outfit'])}. Setting: {e(m['setting'])}.</p>
<ol><li>Sa Google Flow (Ingredients/Frames) o Kling: i-attach ang <b>model reference photo</b> at ang <b>malinis na product photo</b> sa bawat eksena.</li>
<li>Gumawa muna ng <b>still image</b> ng bawat eksena, tingnan kung tama ang mukha at ang skort, saka i-animate (image-to-video).</li>
<li>2-3 takes kada eksena, 8s max. Kapag nag-iba ang itsura ng produkto, takpan ng totoong product photo sa edit.</li>
<li>I-upload ang clips sa "Gawing final" ng bawat video. <b>I-on ang AI-generated label</b> sa pag-post.</li></ol></div>"""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Affiliate videos: {e(p['name'] or 'product')}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">{'<meta http-equiv="refresh" content="8">' if busy else ''}<style>
body{{font:15px/1.5 system-ui,sans-serif;background:#0d0b1a;color:#e9e6ff;margin:0;padding:24px}} .wrap{{max-width:1100px;margin:0 auto}}
.head,.card{{background:#17132e;border:1px solid #3a3270;border-radius:16px;padding:18px 20px;margin-bottom:18px}}
.card{{display:flex;gap:22px;flex-wrap:wrap}} .vidwrap{{display:flex;flex-direction:column;gap:8px}} video{{width:270px;aspect-ratio:9/16;background:#000;border-radius:14px}}
.body{{flex:1;min-width:300px}} h1{{margin:0;font-size:22px}} h2{{margin:0 0 6px;font-size:18px}} h3{{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#9c96c9;margin:16px 0 6px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td,th{{border-bottom:1px solid #2a2550;padding:6px;text-align:left;vertical-align:top}} th{{color:#9c96c9}}
pre{{white-space:pre-wrap;background:#0d0b1a;border-radius:10px;padding:12px;font:13px/1.45 ui-monospace,monospace}} .muted{{color:#8d87b8;font-size:13px}}
.pill{{display:inline-block;border-radius:99px;padding:3px 10px;font-weight:700;font-size:12px}} .pill.draft{{background:#e84a5f33;color:#ff8a8a}} .pill.ok{{background:#3ddc8433;color:#3ddc84}}
.hooks li.pick{{color:#ffd23d;font-weight:700}} .pol li.fixed{{color:#7fd4ff}} .pol li.warn{{color:#ffb86b}} .pol li.ok{{color:#3ddc84}}
.btn,button{{background:#ff6fae;color:#1a0d18;border:0;border-radius:8px;padding:8px 12px;font-weight:700;cursor:pointer;text-decoration:none;text-align:center}}
summary{{cursor:pointer;color:#c4a6ff;margin:6px 0}}
.stills{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}} figure{{margin:0;width:96px}} figure img{{width:96px;aspect-ratio:9/16;object-fit:cover;border-radius:8px}}
figure.empty div{{width:96px;aspect-ratio:9/16;border:1px dashed #3a3270;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#6f6a99;font-size:12px}}
figcaption{{font-size:11px;color:#9c96c9}} .mini{{padding:1px 5px;font-size:11px}} .busy{{color:#ffd23d}} .err{{color:#ff8a8a}} form.final{{display:flex;gap:10px;flex-wrap:wrap;align-items:center}}</style></head><body><div class="wrap">
<div class="head"><h1>🛒 {e(p['name'] or 'Product')}</h1><div class="muted">{e(p['url'])} · scripts by {e(job['author'])} ·
{'hawak mo ang product' if job['owns'] else 'hindi pa hawak (walang first-person claims)'}</div><ul>{notes}</ul></div>
{auto_head}{model_box}{''.join(cards)}{_pack_html(job)}
<p class="muted">Automated policy screening batay sa TikTok Shop at Shopee content rules (originality, claims, disclosure). Nagbabago ang rules,
kaya i-double check sa Affiliate Center bago mag-post.</p></div>
<script>
document.querySelectorAll('button.copy').forEach(b => b.onclick = () => {{
  navigator.clipboard.writeText(b.previousElementSibling.innerText); b.textContent = 'Copied ✅'; }});
document.querySelectorAll('[data-act]').forEach(b => b.onclick = async () => {{
  const act = b.dataset.act, n = b.dataset.n || 0, row = b.dataset.row || 0;
  if (act === 'animate' && !confirm('Gagamit ito ng Veo at may bayad sa Google account mo. Ituloy?')) return;
  const url = act === 'animate' ? `/api/affiliate/{job['id']}/animate?n=${{n}}` : `/api/affiliate/{job['id']}/stills?n=${{n}}&row=${{row}}`;
  b.disabled = true; const r = await fetch(url, {{ method: 'POST' }}); const j = await r.json();
  document.getElementById('automsg').textContent = j.ok ? 'Nagsimula na…' : j.error; if (j.ok) setTimeout(() => location.reload(), 1500); else b.disabled = false;
}});
document.querySelectorAll('form.final').forEach(f => f.onsubmit = async (ev) => {{
  ev.preventDefault(); const msg = f.querySelector('.msg'); msg.textContent = 'Uploading…';
  const r = await fetch('/api/affiliate/{job['id']}/' + f.dataset.n + '/final', {{ method: 'POST', body: new FormData(f) }});
  const j = await r.json(); msg.textContent = j.ok ? 'Ginagawa na ng Video Editor… mag-reload pagkatapos ng ~1 minuto' : (j.error || 'Error');
}});
</script></body></html>"""
