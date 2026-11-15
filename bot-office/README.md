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

## Hooking up real bots (later)
Right now the work is simulated. To drive it from a real backend:

- Open `index.html?feed=/api/bots/events`. The page polls that URL every 3s and expects
  `[{ "bot": "reg", "type": "task" | "done" | "log", "text": "...", "secs": 8 }]`.
- Or call it from JS: `BotOffice.assign('reg', 'Check DPA Sec. 12')`,
  `BotOffice.startPipeline('content', 'vlog.mp4')`, `BotOffice.applyEvent({...})`.

## Swapping in real pixel art
All art is drawn in `office.js` (`drawFurniture`, `drawBot`, `drawWalls`) with canvas shapes.
If you buy an isometric pixel-art pack, replace those functions with `ctx.drawImage(...)` calls.
The positions, pathfinding and animations stay the same.
