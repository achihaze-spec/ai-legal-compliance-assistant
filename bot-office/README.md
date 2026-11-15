# 🤖 Bot Office — 24/7 Bots

A cute isometric office where the **compliance** and **content** bots live. When a bot has work it walks to its desk.
When it doesn't, it hangs out in the lounge (sofa, beanbags, billiards, arcade) and chats with the others.

## Run it
Open `bot-office/index.html` in a browser. No install and no build step.

## Pinakamadaling paraan (walang terminal)
1. Kailangan ng **Python** (libre): https://www.python.org/downloads/. Sa Windows, i-check ang **"Add python.exe to PATH"** sa installer.
2. I-double-click ang:
   - **Windows:** `start-windows.bat`
   - **Mac:** `start-mac.command` (kung ayaw buksan: right-click → Open → Open)
   - **Linux:** `start-linux.sh`
3. Sa unang beses, mag-i-install muna ito (1-3 minuto). Pagkatapos, kusang bubukas ang opisina sa browser.
4. Huwag isara ang itim na window habang ginagamit. Isara ito para ihinto.

## What you can do
- **Click a bot** to open its panel (current task, queue, history, Give task / Upload / Break).
- **Drag files onto the office** (or onto a specific bot):
  - PDF / DOC / HTML / TXT → Compliance pipeline: Doc Reader → Reg Checker → Risk Scout
  - Video / image → Content pipeline: Video Editor → Caption Writer → Scheduler → Poster
- **Tabs** highlight the Compliance or Content team. Scroll or use the buttons to zoom, and drag to pan.
- **🔊 Sound**: a pop-ding when a bot gets a task, a chime when it finishes, an "uh-oh" for HIGH risk, a bonk on errors. Click 🔊/🔇 to mute (remembered). Sound starts after your first click, since browsers block audio until then.
- **demo** checkbox: random sample tasks keep arriving so the office always looks alive.

## The bots
| Team | Bot | Job |
|---|---|---|
| Compliance | Doc Reader | Reads & extracts regulation PDFs |
| Compliance | Reg Checker | Checks business rules vs. the law |
| Compliance | Risk Scout | Writes risk-level reports |
| Content | Video Editor | Cuts & edits raw videos |
| Content | Caption Writer | Hooks, captions & hashtags |
| Content | Scheduler | Plans the posting calendar |
| Content | Poster | Publishes to the platforms |
| — | Bot Manager | Status reports, checks on busy bots |

## Live mode: the bots do real work
```bash
pip install -r bot-office/requirements.txt   # includes imageio-ffmpeg, a bundled ffmpeg
python bot-office/server.py                  # open http://localhost:8800
```
A red **LIVE** badge appears. Drop files on the office:

| You drop | What happens | Result |
|---|---|---|
| PDF / DOCX / HTML / TXT | Doc Reader extracts it → Reg Checker checks it against RA 10173 or contract essentials (+ red flags) → Risk Scout scores it | Risk report (📄 link in the feed) |
| Video / image | Video Editor makes a 9:16 1080×1920 version (max 60s) + thumbnail → Caption Writer writes hook/caption/hashtags → Scheduler books the next 12NN/7PM Manila slot → Poster packages it | "Ready to post" page with preview, copy-caption and download |

**ffmpeg** is found in this order: the `FFMPEG_PATH` env var, `ffmpeg` on your PATH, then the copy bundled
with `imageio-ffmpeg` (installed by requirements.txt, works on Windows/Mac/Linux). `server.py` prints which one it uses
at startup.

Files land in `bot-office/data/` (`reports/`, `outbox/<job>/`, `calendar.json`; git-ignored).

**Claude (optional).** With the `anthropic` package and an `ANTHROPIC_API_KEY` (or `ant auth login`),
Reg Checker adds a Claude review (plain-language summary, issues with exact quotes and law sections,
corrections to the keyword check) and Caption Writer writes Taglish captions. Without a key the bots
use keyword checks and caption templates. `BOT_OFFICE_MODEL` changes the model; `BOT_OFFICE_AI=off` turns it off.

**Not automated yet:** actually posting to TikTok/Instagram/Facebook/YouTube needs each platform's API
and app approval, so Poster stops at "ready to post".

API: `GET /api/health`, `POST /api/upload` (multipart `files`), `GET /api/bots/events?after=N`,
`GET /api/calendar`, `GET /reports/<job>.html`.

## 🛒 Affiliate Studio (5 faceless affiliate videos from a product link)
Click **🛒 Affiliate** in the top bar (live mode). Paste a Shopee / TikTok Shop link, tick **"Hawak ko ang product"** if you
have it, optionally add 2-3 product photos and notes (features from the label/listing, one per line; `problem:` and
`warning:` lines are understood). The content team then:

1. **Caption Writer** writes 5 videos in 5 different styles (hands-only unboxing, POV problem→solution, aesthetic b-roll,
   "Totoo ba?" label check, 3-reasons listicle): 3 hooks each, a timed Taglish script, caption, hashtags, pinned comment.
   Claude writes them when a key is set; otherwise templates fill in from your notes.
2. **Reg Checker** runs the platform policy check and fixes what it can: no price/sale talk, no platform names,
   CTA "check the basket" (never "yellow basket"), `#ad`, no slimming/whitening/medical/before-after claims, no fake
   urgency or invented ratings, no "ginamit ko" lines unless you have the product, pacing (~2.5 words/s), 5 distinct hooks.
3. **Video Editor** renders 5 **draft** videos: storyboards where seller photos fill the seller shots and "SHOT N: KUNAN MO
   ITO" cards mark the shots you need to film (or generate with Veo/Kling using the scene prompts on the page).
4. **Scheduler** spreads the 5 posts over different slots.

On the results page, upload your clips (and optionally your voiceover) under each video and press **Gawing final**: the
clips replace the cards, the timeline stretches to your voiceover, and the DRAFT badge is gone.

Why drafts first: TikTok Shop and Shopee penalise unoriginal content (seller-photo slideshows, reposts, near-duplicates).
Every posted video needs original footage. If you use AI clips, turn on the AI-generated label when posting. Rules change,
so double-check the platforms' affiliate content guidelines.

**AI model reference (UGC with a model).** Open "🤖 AI model reference" in the form and add your model photo (your own AI
persona or yourself, never a real person without consent), a unique model name (e.g. `Mira-V2`), her look, the outfit and
the setting. Scene prompts then lock the same face, outfit and setting in every scene (Pablo consistency workflow: attach
the model photo and a clean product photo to every scene, make a still first, then animate). An AI model never used the
product, so scripts drop "suot/ginamit ko" lines, and every video reminds you to turn on the AI-generated label.

**OOTD products (fashion + model).** No voiceover: the model displays the clothes in a lookbook style (walk-in and poses,
3 ways to style, walk/runway, detail check, galaw test), with only the hook and "Check the basket" on screen. The default
setting is a bright minimalist studio; add music from the platform's own music library when posting.

**🤖 Auto with Google (Veo).** Click ⚙️ in the office, paste a Gemini API key from aistudio.google.com (billing must be
on: Veo has no free tier; a Google AI Pro/Ultra subscription's Flow credits do not cover the API, but its monthly Google
Cloud credits can be applied to the billing account), press **Test connection** and pick the image and video models it
lists. Vertex AI also works (API key in express mode, or a project with `gcloud auth application-default login`).
On a results page: **🖼 Stills** makes a 9:16 first frame per AI shot from your model + product photos (the first product
photo is the product reference). Check them, 🔄 redo any, then **🎬 Animate**: Veo turns each still into a clip and the
final video is edited automatically. A cost estimate is shown and a per-product budget cap blocks overspending.
Posting stays manual (TikTok's API needs an audited app and can't add library music; Shopee has no posting API).
The server listens on localhost only (`BOT_OFFICE_HOST` to change). `BOT_OFFICE_FAKE_GOOGLE=1` runs the flow without Google.

If the shop blocks the link, the product name is taken from the URL itself and your photos/notes are used.

## Swapping in real pixel art
All art is drawn in `office.js` with canvas shapes. The bots are cartoon kids (`LOOKS` sets each one's hair, skin, outfit and accessory), and the furniture is `drawFurniture` / `drawWalls`.
If you buy an isometric pixel-art pack, replace those functions with `ctx.drawImage(...)` calls.
The positions, pathfinding and animations stay the same.
