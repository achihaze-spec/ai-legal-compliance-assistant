# 🌴 Evercrestcorp Compliance Hub · Bot Office (24/7 Bots)

A beachfront resort office where the **compliance** and **content** teams live, drawn as Pixar-style cartoon people.
The office is a two-storey white villa: the **Content Hub** on the 1st floor and the **Evercrestcorp Compliance Hub** on
the 2nd floor (with a **jacuzzi** on the terrace), joined by stairs the team actually climbs. Out front: a coffee bar, a
**snack bar**, a curvy pool with floats and teak loungers, a dance floor, a cabana, beach volleyball, a **BBQ grilling
station** with a picnic table, the **Sunset Bar** (cocktails and drinks), bougainvillea, palms and a pier. When someone
has work they walk to their desk; when they don't, they get coffee or snacks, grill, have a drink, swim, soak in the
jacuzzi, play volleyball, dance or relax, and chat with the others.
🌗 switches day / night (auto follows Manila time): at night the pool, lanterns and pendant lights glow under the stars.

**The team**
- **Pablo, Doc Reader:** first on every case. Takes uploads and KYC/KYB forms, opens the Drive folder, reads every
  file, ticks the ✅/❌ checklist, and pulls out the business details, directors and shareholders.
- **Bailey, Reg Checker:** sanctions screening (OFAC, UN, EU, UK), Data Privacy Act (RA 10173) and contract checks,
  website checks (domain age, SSL, red flags, privacy page).
- **Charlie, Risk Scout:** gives the result (STOP, REJECT, ESCALATE, PENDING, EDD, INCOMPLETE, CLEAR*) and writes the
  HTML and Word report, saved to Drive as `dd.mm.yy_Merchant name`.
- **Hazel, Bot Manager:** helps everyone and sends the alerts (e.g. sanctions TRUE MATCH → MLRO, no tip-off).
- **Content Hub** (its own nipa hut):
  - **JP, Video Editor:** edits every clip to 9:16 and reviews the edit (length, sound, quality).
  - **Asher, Content Manager:** SEO caption and hashtags (plus your caption rules in ⚙️), checks every affiliate link.
  - **Shane, Affiliate · TikTok:** TikTok caption ("check the basket", #ad) and the TikTok Shop product for the yellow basket.
  - **Jacob, Affiliate · Shopee:** Shopee affiliate link in the Facebook caption and as the first comment on Instagram.
  - **Ashley, Scheduler:** picks the posting slots (Asia/Manila; times set in ⚙️).
  - **David, Autopost:** posts at each slot (see below).
- **Mikay (Muse)** and **Taks (Resident Pogi):** no tasks at all. They pose at the flower-arch Muse Spot, dance and drink coffee.

## 📱 Content Hub
Click **📱 Content**, pick one or more videos, add per video the TikTok Shop product link, the Shopee affiliate link
and a line about the video, tick TikTok / Facebook / Instagram, then **▶ Run everything**. (Videos dropped on the
office go through the same flow, without links.) Each batch gets a page with the edited video, JP's review, Asher's
link check, and one card per platform with the caption, status, **Copy caption**, **🤖 Copy Claude prompt**,
**Post now** and **Mark posted**.

How David posts:
- **Facebook and Instagram Reels:** automatically at the slot through the Meta Graph API, once the Page is
  connected in ⚙️ → Content Hub. Instagram gets the Shopee link as the first comment (caption links aren't clickable).
- **TikTok:** TikTok has no public API for adding products (the yellow basket), so at the slot David alerts you and
  the batch page gives a ready-made prompt for **Claude in Chrome**: open TikTok Studio, upload, paste the caption, add the
  product link, post. Browser bots that post for you break TikTok's terms, so they are not used.

### 📚 Prompt Library and Prompt Packs
`prompt_library.py` holds your collected AI image/video prompts (optimized for strict consistency): the Photos-to-AI-Video
master prompt and hybrid technique, fashion poses and try-on display, talking model, selfie/UGC, faceless product shots,
the perfume set, hooks and slash commands, model swap, character sheet, reference-locked video, the consistency
prompts, CapCut steps and posting templates. Open it at **/prompts** (search + copy). For every product in the Content Hub
and the Affiliate Studio, **Asher picks a Prompt Pack**: the right prompts for the product type (apparel, dress, bag,
serum, skincare, makeup, perfume, decor, food, gadgets...) and for what you have (model photo, background photo), in the
order to use them, with the known [placeholders] filled in (product, model name, setting, voice, script hook).

### ⚡ Post to Facebook and Instagram with Zapier (easiest)
Pictures (JPG/PNG) work too: JP makes a 9:16 version for TikTok and a 4:5 version for the Facebook/Instagram feed.
Zapier can't schedule and needs a public link to the file, so David keeps the schedule and Google Drive hosts the file:
1. In Google Drive make a folder, e.g. **Content Hub Posts**, and share it as **Anyone with the link · Viewer**
   (only put post media in it). In Bot Office ⚙️ → 📱 Content Hub, put that folder's path on your Mac
   (Google Drive for desktop: ~/Library/CloudStorage/GoogleDrive-…/My Drive/Content Hub Posts).
2. In Zapier make one Zap per post type (2-step Zaps work on the free plan):
   - Trigger **Webhooks by Zapier → Catch Hook**. Copy the hook URL into the matching ⚙️ field, press
     **⚡ Send a test to Zapier**, then **Test trigger** in Zapier so it sees the fields.
   - Action:
     - Instagram Reel: **Instagram for Business → Publish Video**: Video = `media_url`, Caption = `caption`, account @achifindsph.
     - Instagram photo: **Instagram for Business → Publish Photo(s)**: Photo = `media_url`, Caption = `caption`.
     - Facebook video: **Facebook Pages → Create Page Video**: Page = achiinspires, Video = `media_url`,
       Description = `caption`, Title = `title`.
     - Facebook photo: **Facebook Pages → Create Page Photo**: Photo = `media_url`, Message = `caption`.
   - Turn the Zap on.
3. At each slot David sends `{platform, kind, media_url, caption, first_comment, title}` to the right hook.
   If Drive for desktop hasn't uploaded the file yet, he waits and retries for up to 45 minutes.

Notes: Instagram publishing through Zapier needs an Instagram **Business** account linked to the Facebook Page.
Zapier's Facebook action posts a Page video (not the Reels tab). The 2-step Zap can't add the Instagram first comment, so the
caption says "Link sa bio o comments". TikTok still goes to Claude in Chrome (no product-link API).
From Canva: download the design (MP4 or PNG) and upload it in 📱 Content, or ask Claude in chat to export it.

### Connect Facebook and Instagram
1. Your Instagram must be a Professional (Business or Creator) account linked to your Facebook Page.
2. At developers.facebook.com create an app (type Business), add the Facebook Login for Business and Instagram products.
3. In the Graph API Explorer pick your app, ask for `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`,
   `instagram_basic`, `instagram_content_publish`, `instagram_manage_comments`, then generate a **Page** access token
   (for a long-lived one, exchange it in the Access Token Debugger).
4. In Bot Office ⚙️ → 📱 Content Hub paste the Page ID and the Page access token, then **Test**: it fills in the
   Instagram user ID. The token stays in `data/settings.json` on your Mac.


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

## 🛡️ KYC · KYB · sanctions · URL checks
Click **🛡️ KYC** and pick a tab:
- **👤 Person (KYC):** name, DOB, nationality, ID number, optional MRZ lines. Screens OFAC SDN + Consolidated, UN, EU and UK
  official lists (downloaded and cached for 24 h, every version logged with SHA-256), runs the MRZ check digits and compares
  the MRZ with the application, checks the FATF black/grey lists, and builds PEP / adverse-media searches from the SOP
  library (incl. local-language terms).
- **🏢 Business (KYB / UBO):** company details, shareholders (`Name | % | owns (blank = the business) | country`, one per
  line) and directors. Computes UBOs through every layer (25%, or 10% for offshore / FATF grey), applies the OFAC 50% Rule,
  screens the company and every party, checks the website, and lists the KYB documents to collect.
- **📂 Drive link (KYB):** paste the Google Drive link of the merchant's KYB folder. The bots find it in
  Google Drive for desktop on this Mac (private, works for folders that are not shared; for "Shared with me"
  folders, right-click → Organize → Add shortcut to My Drive), or download it if it is shared as "Anyone with
  the link" (switch it back to Restricted afterwards: it is personal data). They read every PDF / Word / text
  file, tick the KYB checklist (missing items become RFIs), pull the business details, directors and
  shareholders with % (using the AI provider in ⚙️, or simple rules), find MRZ lines on IDs, flag expired
  documents and name mismatches, then run the normal KYB checks. Typed fields always win over the documents.
  The report adds a document inventory with each file's Drive ID and last-modified time. Scanned PDFs and
  photos are listed for the analyst to read.
- **🌐 Website:** domain age (RDAP), HTTPS/SSL, redirects, first Wayback snapshot, privacy / terms / contact pages, red-flag
  keywords (gambling, crypto, counterfeit...), business-name match, and a Data Privacy Act check of the privacy policy.

Outcomes: STOP (possible sanctions true match: escalate to the MLRO, no tip-off), REJECT, ESCALATE, PENDING (RFI), EDD,
INCOMPLETE, CLEAR* (lists screened only; finish PEP / adverse media). All dispositions are suggestions for the analyst.
The screening maths comes from the evercrest-kyb toolkit in `kyb/`.

**Saving to Google Drive:** install Google Drive for desktop, then ⚙️ → 📁 Google Drive folder → pick the folder. Every case
gets a folder `dd.mm.yy_Merchant name` with a .docx report, the .html report and a .json audit file (document compliance
reviews too, with the original file).

## 🧠 AI provider
⚙️ → 🧠 AI provider: **Claude** (Anthropic key), **Ollama Cloud** (open models on ollama.com: create a key at
ollama.com/settings/keys or run `ollama signin`) or **Ollama Local** (models on this Mac: install Ollama, then e.g.
`ollama pull gemma4:e2b`). Ollama is called through its Anthropic-compatible API; replies are checked against the expected
JSON and anything malformed falls back to the templates. **Test AI provider** lists the models it can see.

## 🎵 Fun stuff
The team speaks English and tells jokes, gets coffee and cookies at the coffee bar, plays beach volleyball (the ball
flies over the net), dances under the party lights, and relaxes on the loungers. 🎵 toggles an optional lo-fi background loop (synthesized in the browser, no audio files); 🔊 mutes everything.

## 📱 Gamitin sa phone (same Wi-Fi)
1. Sa Mac: ⚙️ → **📱 Phone access** → maglagay ng PIN (4-8 numero) → **I-on**. May lalabas na QR code at address.
2. Sa phone (parehong Wi-Fi): i-scan ang QR o i-type ang address, ilagay ang PIN. Para parang app: browser menu → **Add to Home screen**.
3. Kung magtanong ang Mac ng "Allow incoming connections" para sa Python, pindutin ang **Allow**.

The Mac never needs the PIN. Every other device is blocked unless phone access is on and it logged in with the PIN;
only the Mac can change the PIN or turn it off. The PIN is stored as a salted hash; a new PIN logs every phone out.

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

**Beauty products (beauty + model).** No voiceover: 5 application styles (swipe/set/go, multi-use lips and cheeks,
shade check, quick GRWM, product reveal). On-screen text only from label features. The AI never "proves" claims
(no transfer tests, no before/after); prompts require the tint color to match the product shade. Crop seller promo
graphics to the product only: no prices, vouchers, ratings, sold counts or before/after panels.

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
The server listens on the network so a phone can connect, but only the Mac gets in without the PIN (`BOT_OFFICE_HOST=127.0.0.1` to lock it to the Mac). `BOT_OFFICE_FAKE_GOOGLE=1` runs the flow without Google.

If the shop blocks the link, the product name is taken from the URL itself and your photos/notes are used.

## Swapping in real pixel art
All art is drawn in `office.js` with canvas shapes. The team are Pixar-style cartoon people (`LOOKS` sets each one's hair, skin, eyes, outfit and accessories; `person()` draws them), the beach and huts are `drawGround` / `drawHutWalls` / `drawRoof`, and the furniture is `drawFurniture`.
If you buy an isometric pixel-art pack, replace those functions with `ctx.drawImage(...)` calls.
The positions, pathfinding and animations stay the same.
