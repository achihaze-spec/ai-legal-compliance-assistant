# 🤖 Bot Office — 24/7 Bots

A cute isometric office where the **compliance** and **content** bots live. When a bot has work it walks to its desk.
When it doesn't, it hangs out in the lounge (sofa, beanbags, billiards, arcade) and chats with the others.

## Run it
Open `bot-office/index.html` in a browser. No install and no build step.

## What you can do
- **Click a bot** to open its panel (current task, queue, history, Give task / Upload / Break).
- **Drag files onto the office** (or onto a specific bot):
  - PDF / DOC / HTML / TXT → Compliance pipeline: Doc Reader → Reg Checker → Risk Scout
  - Video / image → Content pipeline: Video Editor → Caption Writer → Scheduler → Poster
- **Tabs** highlight the Compliance or Content team. Scroll or use the buttons to zoom, and drag to pan.
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
pip install -r bot-office/requirements.txt   # and install ffmpeg for video editing
python bot-office/server.py                  # open http://localhost:8800
```
A red **LIVE** badge appears. Drop files on the office:

| You drop | What happens | Result |
|---|---|---|
| PDF / DOCX / HTML / TXT | Doc Reader extracts it → Reg Checker checks it against RA 10173 or contract essentials (+ red flags) → Risk Scout scores it | Risk report (📄 link in the feed) |
| Video / image | Video Editor makes a 9:16 1080×1920 version (max 60s) + thumbnail → Caption Writer writes hook/caption/hashtags → Scheduler books the next 12NN/7PM Manila slot → Poster packages it | "Ready to post" page with preview, copy-caption and download |

Files land in `bot-office/data/` (`reports/`, `outbox/<job>/`, `calendar.json`; git-ignored).

**Claude (optional).** With the `anthropic` package and an `ANTHROPIC_API_KEY` (or `ant auth login`),
Reg Checker adds a Claude review (plain-language summary, issues with exact quotes and law sections,
corrections to the keyword check) and Caption Writer writes Taglish captions. Without a key the bots
use keyword checks and caption templates. `BOT_OFFICE_MODEL` changes the model; `BOT_OFFICE_AI=off` turns it off.

**Not automated yet:** actually posting to TikTok/Instagram/Facebook/YouTube needs each platform's API
and app approval, so Poster stops at "ready to post".

API: `GET /api/health`, `POST /api/upload` (multipart `files`), `GET /api/bots/events?after=N`,
`GET /api/calendar`, `GET /reports/<job>.html`.

## Swapping in real pixel art
All art is drawn in `office.js` with canvas shapes. The bots are cartoon kids (`LOOKS` sets each one's hair, skin, outfit and accessory), and the furniture is `drawFurniture` / `drawWalls`.
If you buy an isometric pixel-art pack, replace those functions with `ctx.drawImage(...)` calls.
The positions, pathfinding and animations stay the same.
