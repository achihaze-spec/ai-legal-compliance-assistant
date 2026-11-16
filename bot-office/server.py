"""Bot Office server: serves the office page and runs the real compliance bots.

    pip install -r bot-office/requirements.txt   # plus ffmpeg for video editing
    python bot-office/server.py          # then open http://localhost:8800

Upload a PDF/DOCX/HTML/TXT and watch Doc Reader -> Reg Checker -> Risk Scout
work on it. Upload a video/image and Video Editor -> Caption Writer -> Scheduler
-> Poster turn it into a ready-to-post package. Set ANTHROPIC_API_KEY to let
Claude review documents and write captions (optional).
"""
from __future__ import annotations

import os
import queue
import shutil
import re
import threading
import time
import uuid
from pathlib import Path

import json

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

import affiliate
import auth
import ai
import veo
import compliance
import kyc
import kyb_docs
import outputs
import content

HERE = Path(__file__).resolve().parent
UPLOADS = HERE / "data" / "uploads"
REPORTS = HERE / "data" / "reports"
OUTBOX = HERE / "data" / "outbox"
AFFILIATE = HERE / "data" / "affiliate"
CALENDAR = HERE / "data" / "calendar.json"
UPLOADS.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)
OUTBOX.mkdir(parents=True, exist_ok=True)
AFFILIATE.mkdir(parents=True, exist_ok=True)

DOC_EXT = {".pdf", ".docx", ".html", ".htm", ".txt", ".md"}
MEDIA_EXT = content.VIDEO_EXT | content.IMAGE_EXT
MAX_BYTES = 25 * 1024 * 1024
MAX_MEDIA_BYTES = 500 * 1024 * 1024
MIN_STEP_SECS = {"doc": 4, "reg": 5, "risk": 4, "vid": 5, "cap": 4, "sched": 3, "post": 3}  # so you can actually watch them work

app = FastAPI(title="Bot Office")
PHONE = auth.Phone(HERE / "data")


# ───────────────────────── phone access (PIN) ─────────────────────────
@app.middleware("http")
async def phone_guard(request: Request, call_next):
    host = request.client.host if request.client else ""
    if auth.is_local(host) or request.url.path in auth.PUBLIC:
        return await call_next(request)
    if not PHONE.enabled:
        return HTMLResponse(auth.blocked_page(), status_code=403)
    if PHONE.valid(request.cookies.get(auth.COOKIE)):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"ok": False, "error": "Login muna (PIN)."}, status_code=401)
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_form():
    return auth.login_page()


@app.post("/login")
def login(request: Request, pin: str = Form("")):
    if not PHONE.enabled:
        return HTMLResponse(auth.blocked_page(), status_code=403)
    ok, err = PHONE.check_pin(pin, request.client.host if request.client else "")
    if not ok:
        return HTMLResponse(auth.login_page(err), status_code=401)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(auth.COOKIE, PHONE.make_token(), max_age=auth.MAX_AGE, httponly=True, samesite="lax")
    return resp


@app.get("/manifest.webmanifest")
def manifest():
    return Response(auth.MANIFEST, media_type="application/manifest+json")


@app.get("/icon.png")
def icon():
    return FileResponse(auth.icon_png(HERE / "data" / "icon.png"))


def _local_only(request: Request):
    if not auth.is_local(request.client.host if request.client else ""):
        raise HTTPException(403, "Sa Mac lang puwedeng baguhin ito.")


@app.get("/api/phone")
def phone_status():
    return PHONE.status()


@app.post("/api/phone")
async def phone_set(request: Request, body: dict):
    _local_only(request)
    pin = str(body.get("pin") or "").strip()
    if pin and not re.fullmatch(r"\d{4,8}", pin):
        return {"ok": False, "error": "4-8 numero ang PIN."}
    try:
        return {"ok": True, **PHONE.set(bool(body.get("enabled")), pin or None)}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/phone/qr.png")
def phone_qr(request: Request):
    _local_only(request)
    return FileResponse(auth.qr_png(auth.phone_url(), HERE / "data" / "phone_qr.png"), headers={"Cache-Control": "no-store"})

# ───────────────────────── event log the page polls ─────────────────────────
_events: list[dict] = []
_lock = threading.Lock()


def emit(**ev) -> None:
    with _lock:
        ev["id"] = len(_events) + 1
        _events.append(ev)


@app.get("/api/health")
def health():
    return {"ok": True, "live": ["doc", "reg", "risk", "vid", "cap", "sched", "post"],
            "claude": ai.available(), "ffmpeg": bool(content.FFMPEG), "ffmpeg_source": content.FFMPEG_SOURCE}


@app.get("/api/bots/events")
def events(after: int = 0):
    with _lock:
        return {"events": _events[after:], "last": len(_events)}


# ───────────────────────── uploads -> job queue ─────────────────────────
_jobs: "queue.Queue[dict]" = queue.Queue()
_content_jobs: "queue.Queue[dict]" = queue.Queue()
_affiliate_jobs: "queue.Queue[dict]" = queue.Queue()


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    accepted, skipped = [], []
    for f in files:
        name = Path(f.filename or "file").name
        ext = Path(name).suffix.lower()
        is_doc, is_media = ext in DOC_EXT, ext in MEDIA_EXT
        data = await f.read() if (is_doc or is_media) else b""
        if not (is_doc or is_media) or len(data) > (MAX_BYTES if is_doc else MAX_MEDIA_BYTES):
            skipped.append(name)
            continue
        job_id = uuid.uuid4().hex[:10]
        path = UPLOADS / f"{job_id}{ext}"
        path.write_bytes(data)
        job = {"id": job_id, "name": name, "path": path}
        if is_doc:
            _jobs.put(job)
            emit(bot="doc", type="task", task=f"{job_id}-doc", text=f"Read & extract: {name}", secs=MIN_STEP_SECS["doc"])
        else:
            _content_jobs.put(job)
            emit(bot="vid", type="task", task=f"{job_id}-vid", text=f"Edit to 9:16: {name}", secs=MIN_STEP_SECS["vid"])
        accepted.append({"job": job_id, "name": name, "team": "compliance" if is_doc else "content"})
    return {"accepted": accepted, "skipped": skipped}


# ───────────────────────── KYC / KYB / URL checks ─────────────────────────
KYC_DIR = HERE / "data" / "kyc"
LIST_CACHE = HERE / "data" / "sanctions_lists"


@app.post("/api/kyc")
async def kyc_start(request: Request):
    form = dict(await request.form())
    kind = form.get("kind", "")
    form = {k: (v if isinstance(v, str) else "") for k, v in form.items()}
    if kind not in ("person", "business", "url"):
        raise HTTPException(400, "kind must be person, business or url")
    if kind == "business" and form.get("drive_link", "").strip():
        try:
            kyb_docs.parse_link(form["drive_link"])
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
    elif kind in ("person", "business") and not form.get("name", "").strip():
        return {"ok": False, "error": "Kailangan ang pangalan."}
    if kind == "url" and not form.get("website", "").strip():
        return {"ok": False, "error": "Kailangan ang website / URL."}
    jid = uuid.uuid4().hex[:10]
    _jobs.put({"kind": "kyc", "id": jid, "type": kind, "form": form})
    label = {"person": "KYC", "business": "KYB", "url": "URL check"}[kind]
    emit(bot="doc", type="task", task=f"{jid}-intake", text=f"{label} intake: {form.get('name') or form.get('website')}", secs=3)
    return {"ok": True, "job": jid}


@app.post("/api/ai/test")
def ai_test():
    """Lists the models the chosen AI provider can use (Ollama), or says whether Claude is configured."""
    import requests
    st = veo.load()
    p = st.get("ai_provider", "claude")
    try:
        if p == "claude":
            return {"ok": ai.available(), "provider": p,
                    "message": "Claude ready" if ai.available() else "No Claude key (ANTHROPIC_API_KEY or ant auth login)"}
        if p == "ollama_local":
            r = requests.get((st.get("ollama_url") or "http://localhost:11434").rstrip("/") + "/api/tags", timeout=5,
                             proxies={"http": None, "https": None})
        else:
            if not st.get("ollama_api_key"):
                return {"ok": False, "provider": p, "message": "Add your Ollama API key (ollama.com/settings/keys)"}
            r = requests.get("https://ollama.com/api/tags", timeout=15, headers={"Authorization": f"Bearer {st['ollama_api_key']}"})
        r.raise_for_status()
        models = [m.get("name") or m.get("model") for m in r.json().get("models", [])]
        return {"ok": True, "provider": p, "models": models,
                "message": f"Connected: {len(models)} model(s)" + ("" if models else ". Run: ollama pull gemma4:e2b")}
    except Exception as exc:
        hint = " Is Ollama running? Open the Ollama app or run: ollama serve" if p == "ollama_local" else ""
        return {"ok": False, "provider": p, "message": f"{type(exc).__name__}: {str(exc)[:160]}.{hint}"}


@app.get("/api/drive/detect")
def drive_detect():
    return {"folders": outputs.detect(), "current": veo.load().get("drive_folder", "")}


def read_drive_docs(form: dict, work: Path) -> dict:
    """Drive link → documents → checklist, details and issues; returns the form with the blanks filled."""
    got = kyb_docs.fetch(form["drive_link"], work / "documents")
    docs = kyb_docs.read_docs(got["files"])
    ex, how = kyb_docs.extract(docs)
    rows = kyb_docs.checklist(docs)
    filled = kyb_docs.merge(form, ex, got["folder_name"])
    _, gaps = kyb_docs.owners_text(ex)
    return {"form": filled, "via": got["via"], "notes": got["notes"], "checklist": rows, "extracted": ex,
            "extracted_by": ai.provider() if how == "ai" else "rules", "mrz": kyb_docs.find_mrz(docs),
            "issues": kyb_docs.issues(form, ex, docs, rows) + gaps,
            "files": [{k: v for k, v in d.items() if k not in ("text", "path")} for d in docs]}


def run_kyc_job(job: dict) -> None:
    jid, t, f = job["id"], job["type"], job["form"]
    work = KYC_DIR / jid
    label = {"person": "KYC", "business": "KYB", "url": "URL"}[t]
    merchant = (f.get("name") or f.get("website", "")).strip()
    docs_info = None
    if t == "business" and f.get("drive_link", "").strip():
        emit(bot="doc", type="done", task=f"{jid}-intake", text=f"KYB: {merchant or 'Drive folder'} ✔ intake")
        emit(bot="doc", type="task", task=f"{jid}-drive", text="📂 Reading the KYB documents from Drive", secs=10)
        try:
            docs_info = read_drive_docs(f, work)
        except Exception as exc:
            emit(bot="doc", type="done", task=f"{jid}-drive", level="HIGH", text=f"Drive link: {exc}")
            emit(bot="mgr", type="log", text=f"⚠️ Drive link: {exc}")
            if not f.get("name", "").strip():
                return
        else:
            f = docs_info.pop("form")
            merchant = f.get("name", "").strip() or "Unnamed merchant"
            missing = [c["item"] for c in docs_info["checklist"] if c["status"] != "Received"]
            emit(bot="doc", type="done", task=f"{jid}-drive", level="MEDIUM" if missing or docs_info["issues"] else "LOW",
                 text=f"{merchant}: {len(docs_info['files'])} file(s) read · {len(missing)} missing · {len(docs_info['issues'])} issue(s)")
    else:
        time.sleep(2)
        emit(bot="doc", type="done", task=f"{jid}-intake", text=f"{label}: {merchant} ✔ intake")
    emit(bot="reg", type="task", task=f"{jid}-screen",
         text="Sanctions screening (OFAC · UN · EU · UK)" if t != "url" else "Website checks", secs=8)
    if t == "person":
        r = kyc.kyc_person(f, work, LIST_CACHE)
    elif t == "business":
        r = kyc.kyb_business(f, work, LIST_CACHE, docs_info)
    else:
        import url_check
        u = url_check.check(f["website"], f.get("name", ""))
        r = {**u, "kind": "URL", "subject": {"name": merchant}, "outcome": u["rating"],
             "why": "; ".join(x["msg"] for x in u["findings"] if x["level"] == "high")[:300] or "Tingnan ang findings sa ibaba."}
    if t != "url":
        hits = sum(len(h) for h in r["screen"]["results"].values())
        failed = [l["source"] for l in r["screen"]["lists"] if l["status"] != "ok"]
        emit(bot="reg", type="done", task=f"{jid}-screen",
             text=f"{merchant}: {hits} potential hit(s)" + (f"; not screened: {', '.join(failed)}" if failed else ""))
    else:
        emit(bot="reg", type="done", task=f"{jid}-screen", text=f"{merchant}: {len(r['findings'])} finding(s)")
    emit(bot="risk", type="task", task=f"{jid}-report", text=f"{label} report: {merchant}", secs=3)
    page = kyc.render(r) if t != "url" else kyc.render_url(r)
    (REPORTS / f"{jid}.html").write_text(page, encoding="utf-8")
    saved = None
    try:
        saved = outputs.save_case(merchant, label, r, page)
    except Exception as exc:
        emit(bot="mgr", type="log", text=f"Couldn't save to Drive: {exc}")
    level = {"STOP": "HIGH", "REJECT": "HIGH", "ESCALATE": "HIGH", "HIGH": "HIGH", "EDD": "MEDIUM", "PENDING": "MEDIUM",
             "MEDIUM": "MEDIUM"}.get(r["outcome"], "LOW")
    emit(bot="risk", type="done", task=f"{jid}-report", url=f"/reports/{jid}.html", level=level,
         text=f"{merchant}: {r['outcome']}" + (f" · 📁 Drive: {saved.name}" if saved else " · (no Drive folder set in ⚙️)"))
    if r["outcome"] == "STOP":
        emit(bot="mgr", type="log", text=f"🛑 {merchant}: possible sanctions TRUE MATCH. Escalate to the MLRO now. No tip-off.")


# ───────────────────────── Affiliate Studio ─────────────────────────
async def _save_uploads(files, folder: Path, allowed: set, prefix: str) -> list[Path]:
    saved = []
    for i, f in enumerate(files or []):
        if not f or not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        data = await f.read()
        if ext in allowed and 0 < len(data) <= MAX_MEDIA_BYTES:
            p = folder / f"{prefix}{i}{ext}"
            p.write_bytes(data)
            saved.append(p)
    return saved


@app.post("/api/affiliate")
async def affiliate_start(url: str = Form(""), owns: str = Form("0"), notes: str = Form(""),
                          photos: list[UploadFile] = File(default=[]), model_photo: UploadFile | None = File(default=None),
                          model_name: str = Form(""), model_look: str = Form(""), model_outfit: str = Form(""), model_setting: str = Form("")):
    url = url.strip()
    if not url and not any(p.filename for p in photos):
        raise HTTPException(400, "Maglagay ng product link o photos.")
    if url and not re.match(r"https?://", url):
        raise HTTPException(400, "Dapat nagsisimula sa http:// o https:// ang link.")
    jid = uuid.uuid4().hex[:10]
    folder = AFFILIATE / jid
    folder.mkdir(parents=True)
    imgs = await _save_uploads(photos, folder, content.IMAGE_EXT, "photo")
    mph = await _save_uploads([model_photo] if model_photo else [], folder, content.IMAGE_EXT, "model")
    model = None
    if mph:
        model = {"photo": str(mph[0]), "name": (model_name.strip() or "Mira-V2")[:40],
                 "look": model_look.strip() or "exactly as in the model reference photo (same face, hair and skin tone)",
                 "outfit": model_outfit.strip() or "a simple fitted black top and the product",
                 "setting": model_setting.strip()}
    _affiliate_jobs.put({"kind": "plan", "id": jid, "url": url, "owns": owns in ("1", "true", "on"), "notes": notes,
                         "photos": imgs, "model": model})
    emit(bot="cap", type="task", task=f"{jid}-cap", text=f"Write 5 affiliate scripts: {url or 'uploaded photos'}", secs=MIN_STEP_SECS["cap"])
    return {"ok": True, "job": jid, "page": f"/reports/{jid}.html"}


@app.post("/api/affiliate/{jid}/{n}/final")
async def affiliate_final(jid: str, n: int, clips: list[UploadFile] = File(default=[]), vo: UploadFile | None = File(default=None)):
    folder = AFFILIATE / jid
    if not re.fullmatch(r"[0-9a-f]{10}", jid) or not (folder / "job.json").exists() or not 1 <= n <= 5:
        raise HTTPException(404)
    sub = folder / f"final{n}"
    shutil.rmtree(sub, ignore_errors=True)
    sub.mkdir()
    saved = await _save_uploads(clips, sub, MEDIA_EXT, "clip")
    if not saved:
        return {"ok": False, "error": "Walang valid na clip (video o image)."}
    vo_files = await _save_uploads([vo] if vo else [], sub, {".mp3", ".m4a", ".wav", ".aac", ".mp4", ".mov"}, "vo")
    _affiliate_jobs.put({"kind": "final", "id": jid, "n": n, "clips": saved, "vo": vo_files[0] if vo_files else None})
    emit(bot="vid", type="task", task=f"{jid}-final{n}", text=f"Final edit: affiliate video {n}", secs=MIN_STEP_SECS["vid"])
    return {"ok": True}


def _save_job(job: dict) -> None:
    job["est_per_clip"] = veo.estimate(1)
    (AFFILIATE / job["id"] / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    (REPORTS / f"{job['id']}.html").write_text(affiliate.render_page(job), encoding="utf-8")


def run_affiliate_plan(req: dict) -> None:
    jid = req["id"]
    folder, out = AFFILIATE / jid, OUTBOX / jid
    out.mkdir(parents=True, exist_ok=True)

    # Caption Writer: read the product, write 5 scripts
    t0 = time.time()
    prod = affiliate.fetch_product(req["url"]) if req["url"] else {"url": "", "name": "", "description": "", "images": [], "ok": False, "note": ""}
    seller = affiliate.download_images(prod["images"], folder) if prod["images"] else []
    seller = req["photos"] + seller
    notes = affiliate.parse_notes(req["notes"])
    prod["name"] = notes["name"] or prod["name"]
    prod.update(features=notes["features"], problem=notes["problem"], warning=notes["warning"],
                category=affiliate.categorize(prod["name"], f"{prod['description']} {req['notes']}"))
    # an AI model never actually used the product, so no first-person use claims when one is in the video
    owns = req["owns"] and not req.get("model")
    if req.get("model"):
        req["model"]["kind"] = prod["category"]
        if not req["model"]["setting"]:
            req["model"]["setting"] = {"fashion": affiliate.LOOKBOOK_SETTING, "beauty": affiliate.BEAUTY_SETTING}.get(
                prod["category"], "a bright, cozy living room with soft daylight from a window")
    videos, lock, author = affiliate.plan_videos(prod, owns, req.get("model"))
    if req.get("model") and not videos[0].get("no_vo"):
        for v in videos:
            affiliate.model_visuals(v, req["model"], prod["category"] == "fashion")
    _paced("cap", t0)
    emit(bot="cap", type="done", task=f"{jid}-cap", text=f"5 scripts for {prod['name'] or 'the product'} (by {author})")

    # Reg Checker: platform policy
    emit(bot="reg", type="task", task=f"{jid}-policy", text="Platform policy check: 5 affiliate videos", secs=MIN_STEP_SECS["reg"])
    t0 = time.time()
    job_notes = []
    if prod["note"]:
        job_notes.append(prod["note"])
    if not seller:
        job_notes.append("Walang product photo: mag-upload ng 2-3 malinaw na photos para sa seller shots at sa AI reference.")
    if not notes["features"] and author == "template":
        job_notes.append("Walang features sa notes: may [placeholder] sa scripts. Ilagay ang features (galing sa label/listing) at gumawa ulit.")
    fixes = 0
    for v in videos:
        v["policy"] = affiliate.policy_check(v, owns)
        fixes += sum(f["level"] == "fixed" for f in v["policy"])
        v["prompts"] = affiliate.scene_prompts(v, lock, req.get("model"))
        if req.get("model"):
            v["policy"].append({"level": "warn", "msg": "AI model: i-on ang AI-generated label sa pag-post; walang 'suot/ginamit ko' na linya"})
    job_notes += affiliate.distinct_check(videos)
    _paced("reg", t0)
    emit(bot="reg", type="done", task=f"{jid}-policy", text=f"Policy check: {fixes} auto-fix, drafts need original footage before posting")

    # Video Editor: 5 storyboard drafts
    emit(bot="vid", type="task", task=f"{jid}-vid", text="Render 5 draft videos", secs=MIN_STEP_SECS["vid"])
    t0 = time.time()
    for n, v in enumerate(videos, 1):
        try:
            v["render"] = affiliate.render_video(v, n, seller, [], None, folder / f"work{n}", out / f"video{n}.mp4")
        except Exception as exc:
            v["render"] = {"draft": True, "error": str(exc)}
            job_notes.append(f"Video {n}: hindi na-render ({exc})")
    _paced("vid", t0)
    emit(bot="vid", type="done", task=f"{jid}-vid", text="5 draft videos (storyboard) ready")

    # Scheduler: spread the 5 posts over different slots
    emit(bot="sched", type="task", task=f"{jid}-sched", text="Schedule 5 affiliate posts", secs=MIN_STEP_SECS["sched"])
    t0 = time.time()
    for n, v in enumerate(videos, 1):
        v["slot"] = content.fmt_slot(content.next_slot(CALENDAR, f"{jid}-{n}", f"{prod['name'] or 'affiliate'} #{n}"))
    _paced("sched", t0)
    emit(bot="sched", type="done", task=f"{jid}-sched", text=f"5 posts: {videos[0]['slot']} → {videos[-1]['slot']}")

    if req.get("model"):
        job_notes.append("AI model sa video: dapat AI-generated persona mo ito o ikaw mismo, hindi totoong tao na walang pahintulot. "
                         "Gumamit ng totoong product photos para sa close-up ng detalye; puwedeng iba ang fit na gawa ng AI.")
    job = {"id": jid, "product": {k: prod[k] for k in ("url", "name", "description", "category")}, "owns": owns, "model": req.get("model"),
           "author": author, "lock": lock, "seller": [str(p) for p in seller], "videos": videos, "notes": job_notes}
    _save_job(job)
    emit(bot="post", type="task", task=f"{jid}-post", text="Package affiliate videos", secs=MIN_STEP_SECS["post"])
    emit(bot="post", type="done", task=f"{jid}-post", url=f"/reports/{jid}.html",
         text=f"{prod['name'] or 'Product'}: 5 affiliate videos ready for review 🛒")


def run_affiliate_final(req: dict) -> None:
    jid, n = req["id"], req["n"]
    job = json.loads((AFFILIATE / jid / "job.json").read_text(encoding="utf-8"))
    v = job["videos"][n - 1]
    t0 = time.time()
    render = affiliate.render_video(v, n, [Path(p) for p in job["seller"]], req["clips"], req["vo"],
                                    AFFILIATE / jid / f"work{n}", OUTBOX / jid / f"video{n}.mp4")
    render["rev"] = v.get("render", {}).get("rev", 0) + 1
    v["render"] = render
    v["policy"] = [f for f in v["policy"] if "Original footage" not in f["msg"]]
    _save_job(job)
    _paced("vid", t0)
    emit(bot="vid", type="done", task=f"{jid}-final{n}", url=f"/reports/{jid}.html",
         text=f"Affiliate video {n} is final ({render['seconds']}s) 🎬")


# ───────────────────────── Auto (Google Veo) ─────────────────────────
@app.get("/api/settings")
def get_settings():
    return veo.public()


@app.post("/api/settings")
async def set_settings(body: dict):
    return veo.save(body)


@app.post("/api/settings/test")
def test_settings():
    if not veo.configured():
        return {"ok": False, "error": "Wala pang API key / project."}
    try:
        return veo.test_connection()
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}


def _load_job(jid: str) -> dict:
    p = AFFILIATE / jid / "job.json"
    if not re.fullmatch(r"[0-9a-f]{10}", jid) or not p.exists():
        raise HTTPException(404)
    return json.loads(p.read_text(encoding="utf-8"))


def _own_rows(v: dict) -> list[int]:
    return [i for i, r in enumerate(v["rows"], 1) if r["footage"] == "own"]


@app.post("/api/affiliate/{jid}/stills")
def auto_stills(jid: str, n: int = 0, row: int = 0):
    job = _load_job(jid)
    if not veo.configured():
        return {"ok": False, "error": "I-set up muna ang Google key sa ⚙️ Settings."}
    job["busy"] = "stills"
    _save_job(job)
    _affiliate_jobs.put({"kind": "stills", "id": jid, "n": n, "row": row})
    return {"ok": True}


@app.post("/api/affiliate/{jid}/animate")
def auto_animate(jid: str, n: int = 0):
    job = _load_job(jid)
    s = veo.load()
    targets = [n] if n else list(range(1, 6))
    clips = 0
    for k in targets:
        v = job["videos"][k - 1]
        stills = v.get("auto", {}).get("stills", {})
        missing = [r for r in _own_rows(v) if str(r) not in stills]
        if missing:
            return {"ok": False, "error": f"Video {k}: wala pang still ang shot {missing}. Gawin muna ang stills."}
        clips += len(_own_rows(v))
    cost = veo.estimate(clips, s)
    spent = job.get("auto_spent", 0.0)
    if spent + cost > s["budget_per_job"]:
        return {"ok": False, "error": f"Lalampas sa budget: ≈${cost} + nagastos na ${spent:.2f} > limit ${s['budget_per_job']}. "
                                      "Taasan ang budget sa Settings o mag-animate ng isang video lang."}
    job["busy"] = "animate"
    _save_job(job)
    _affiliate_jobs.put({"kind": "animate", "id": jid, "targets": targets})
    return {"ok": True, "estimate": cost}


def _refs(job: dict) -> list[Path]:
    refs = [Path(job["model"]["photo"])] if job.get("model") else []
    if job["seller"]:
        refs.append(Path(job["seller"][0]))  # first photo = product reference
    return refs


def run_auto_stills(req: dict) -> None:
    jid = req["id"]
    job = json.loads((AFFILIATE / jid / "job.json").read_text(encoding="utf-8"))
    refs = _refs(job)
    targets = [req["n"]] if req["n"] else list(range(1, 6))
    emit(bot="vid", type="task", task=f"{jid}-stills", text="Making stills (Gemini image)", secs=8)
    made, errors = 0, []
    for k in targets:
        v = job["videos"][k - 1]
        auto = v.setdefault("auto", {"stills": {}, "clips": {}})
        prompts = {p["row"]: p["prompt"] for p in v["prompts"]}
        for r in ([req["row"]] if req["row"] else _own_rows(v)):
            out = OUTBOX / jid / f"still_v{k}_r{r}_{int(time.time())}.png"
            try:
                veo.make_still(prompts[r], refs, out)
                auto["stills"][str(r)] = out.name
                made += 1
            except Exception as exc:
                errors.append(f"V{k} shot {r}: {str(exc)[:160]}")
        _save_job(job)
    job["busy"] = ""
    job["auto_error"] = "; ".join(errors)
    _save_job(job)
    emit(bot="vid", type="done", task=f"{jid}-stills", url=f"/reports/{jid}.html", ok=not errors or made > 0,
         text=f"{made} stills ready, check them before animating" + (f" ({len(errors)} error)" if errors else ""))


def run_auto_animate(req: dict) -> None:
    jid = req["id"]
    job = json.loads((AFFILIATE / jid / "job.json").read_text(encoding="utf-8"))
    s = veo.load()
    emit(bot="vid", type="task", task=f"{jid}-veo", text="Veo: making the video clips", secs=30)
    done, errors = 0, []
    for k in req["targets"]:
        v = job["videos"][k - 1]
        auto = v.setdefault("auto", {"stills": {}, "clips": {}})
        prompts = {p["row"]: p["prompt"] for p in v["prompts"]}
        neg = affiliate.MODEL_NEGATIVE if job.get("model") else affiliate.NEGATIVE
        clips = []
        for r in _own_rows(v):
            out = OUTBOX / jid / f"clip_v{k}_r{r}.mp4"
            try:
                veo.make_clip(OUTBOX / jid / auto["stills"][str(r)], veo.motion_prompt(prompts[r]), neg, out, s)
                job["auto_spent"] = round(job.get("auto_spent", 0.0) + veo.estimate(1, s), 2)
                auto["clips"][str(r)] = out.name
                clips.append(out)
            except Exception as exc:
                errors.append(f"V{k} shot {r}: {str(exc)[:160]}")
                break
            _save_job(job)
        if len(clips) == len(_own_rows(v)):
            render = affiliate.render_video(v, k, [Path(p) for p in job["seller"]], clips, None,
                                            AFFILIATE / jid / f"work{k}", OUTBOX / jid / f"video{k}.mp4")
            render["rev"] = v.get("render", {}).get("rev", 0) + 1
            v["render"] = render
            v["policy"] = [f for f in v["policy"] if "Original footage" not in f["msg"]]
            done += 1
        _save_job(job)
    job["busy"] = ""
    job["auto_error"] = "; ".join(errors)
    _save_job(job)
    emit(bot="vid", type="done", task=f"{jid}-veo", url=f"/reports/{jid}.html", ok=done > 0,
         text=f"Veo: {done} final video(s) ready 🎬 (≈${job.get('auto_spent', 0):.2f} so far)" + (f"; {errors[0]}" if errors else ""))


def affiliate_worker() -> None:
    runners = {"plan": run_affiliate_plan, "final": run_affiliate_final, "stills": run_auto_stills, "animate": run_auto_animate}
    while True:
        req = _affiliate_jobs.get()
        try:
            runners[req["kind"]](req)
        except Exception as exc:
            emit(bot="mgr", type="log", text=f"Affiliate error: {exc}")
            if req.get("id") and (AFFILIATE / req["id"] / "job.json").exists():
                job = json.loads((AFFILIATE / req["id"] / "job.json").read_text(encoding="utf-8"))
                job["busy"], job["auto_error"] = "", str(exc)[:300]
                _save_job(job)


@app.get("/outbox/{job_id}/{fname}")
def outbox_file(job_id: str, fname: str):
    if not re.fullmatch(r"[0-9a-f]{10}", job_id) or not re.fullmatch(r"[\w.-]+", fname):
        raise HTTPException(404)
    p = OUTBOX / job_id / fname
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/api/calendar")
def calendar():
    import json
    return json.loads(CALENDAR.read_text()) if CALENDAR.exists() else []


@app.get("/reports/{job_id}.html", response_class=HTMLResponse)
def report(job_id: str):
    if not re.fullmatch(r"[0-9a-f]{10}", job_id):
        raise HTTPException(404)
    p = REPORTS / f"{job_id}.html"
    if not p.exists():
        raise HTTPException(404)
    return HTMLResponse(p.read_text(encoding="utf-8"))


# ───────────────────────── the bots' actual work ─────────────────────────

def _paced(bot: str, started: float) -> None:
    left = MIN_STEP_SECS[bot] - (time.time() - started)
    if left > 0:
        time.sleep(left)


def run_job(job: dict) -> None:
    jid, name = job["id"], job["name"]

    # Doc Reader
    t0 = time.time()
    try:
        text, pages = compliance.extract_text(job["path"])
    except Exception as exc:  # unreadable / encrypted file
        _paced("doc", t0)
        emit(bot="doc", type="done", task=f"{jid}-doc", ok=False, text=f"Couldn't read {name}: {exc}")
        return
    doc_type = compliance.classify(text)
    words = len(text.split())
    _paced("doc", t0)
    if words < 20:
        emit(bot="doc", type="done", task=f"{jid}-doc", ok=False,
             text=f"{name}: barely any text (scanned PDF?). Needs OCR.")
        return
    emit(bot="doc", type="done", task=f"{jid}-doc",
         text=f"{name}: {pages} page(s), {words:,} words — {compliance.TYPE_LABEL[doc_type]}")

    # Reg Checker
    label = "Extract obligations" if doc_type == "regulation" else "Compliance check"
    emit(bot="reg", type="task", task=f"{jid}-reg", text=f"{label}: {name}", secs=MIN_STEP_SECS["reg"])
    t0 = time.time()
    res = compliance.check(text, doc_type)
    review = None
    if doc_type != "regulation":
        rule_summary = "\n".join(
            [f"PRESENT: {c['title']}" for c in res.passed] + [f"MISSING: {c['title']}" for c in res.missing]
            + [f"RED FLAG: {f['title']}" for f in res.flags])
        review = ai.review_document(name, compliance.TYPE_LABEL[doc_type], text, rule_summary)
    _paced("reg", t0)
    if doc_type == "regulation":
        summary = f"{name}: {len(res.obligations)} key obligations found"
    else:
        n = len(res.passed) + len(res.missing)
        summary = f"{name}: {len(res.passed)}/{n} checks passed" + (f", {len(res.flags)} red flag(s) 🚩" if res.flags else "")
        if review:
            summary += f" · Claude found {len(review['issues'])} issue(s) ✨"
    emit(bot="reg", type="done", task=f"{jid}-reg", text=summary)

    # Risk Scout
    emit(bot="risk", type="task", task=f"{jid}-risk", text=f"Risk report: {name}", secs=MIN_STEP_SECS["risk"])
    t0 = time.time()
    risk, level = compliance.score(res)
    if review:
        level = review["risk_level"]  # Claude read the whole document; prefer its judgement
    (REPORTS / f"{jid}.html").write_text(compliance.render_report(name, text, pages, res, risk, level, review), encoding="utf-8")
    _paced("risk", t0)
    verdict = "summary ready" if level == "INFO" else f"{level} risk" + (" (Claude)" if review else f" ({risk}/100)")
    try:
        saved = outputs.save_case(Path(name).stem, "Compliance", {"file": name, "type": doc_type, "risk": risk, "outcome": level,
                                  "why": f"{compliance.TYPE_LABEL[doc_type]} · keyword score {risk}/100",
                                  "missing": [c["title"] for c in res.missing], "flags": [x["title"] for x in res.flags],
                                  "obligations": res.obligations, "claude": review},
                                  (REPORTS / f"{jid}.html").read_text(encoding="utf-8"), [(job["path"], name)])
        if saved:
            verdict += f" · 📁 {saved.name}"
    except Exception as exc:
        emit(bot="mgr", type="log", text=f"Couldn't save to Drive: {exc}")
    emit(bot="risk", type="done", task=f"{jid}-risk", level=level, url=f"/reports/{jid}.html", text=f"{name}: {verdict}")


def run_content_job(job: dict) -> None:
    jid, name = job["id"], job["name"]
    out = OUTBOX / jid

    # Video Editor
    t0 = time.time()
    try:
        media = content.make_vertical(job["path"], out)
    except Exception as exc:
        _paced("vid", t0)
        emit(bot="vid", type="done", task=f"{jid}-vid", ok=False, text=f"Couldn't edit {name}: {exc}")
        return
    _paced("vid", t0)
    secs = f", {media['seconds']:.0f}s" if media["seconds"] else ""
    emit(bot="vid", type="done", task=f"{jid}-vid", text=f"{name}: {media['note']}{secs}")

    # Caption Writer
    emit(bot="cap", type="task", task=f"{jid}-cap", text=f"Write captions: {name}", secs=MIN_STEP_SECS["cap"])
    t0 = time.time()
    cap = content.write_caption(name)
    _paced("cap", t0)
    emit(bot="cap", type="done", task=f"{jid}-cap", text=f"“{cap['hook']}” (+{len(cap['hashtags'])} hashtags, by {cap['by']})")

    # Scheduler
    emit(bot="sched", type="task", task=f"{jid}-sched", text=f"Schedule post: {name}", secs=MIN_STEP_SECS["sched"])
    t0 = time.time()
    slot = content.next_slot(CALENDAR, jid, name)
    _paced("sched", t0)
    emit(bot="sched", type="done", task=f"{jid}-sched", text=f"{name}: booked {content.fmt_slot(slot)}")

    # Poster
    emit(bot="post", type="task", task=f"{jid}-post", text=f"Prepare post: {name}", secs=MIN_STEP_SECS["post"])
    t0 = time.time()
    content.package(out, name, media, cap, slot)
    (REPORTS / f"{jid}.html").write_text(content.render_page(jid, name, media, cap, slot), encoding="utf-8")
    _paced("post", t0)
    emit(bot="post", type="done", task=f"{jid}-post", url=f"/reports/{jid}.html",
         text=f"{name}: ready to post {content.fmt_slot(slot)} 📦")


def content_worker() -> None:
    while True:
        job = _content_jobs.get()
        try:
            run_content_job(job)
        except Exception as exc:
            emit(bot="mgr", type="log", text=f"Error on {job['name']}: {exc}")


def worker() -> None:
    while True:
        job = _jobs.get()
        try:
            (run_kyc_job if job.get("kind") == "kyc" else run_job)(job)
        except Exception as exc:  # never let one bad file kill the office
            emit(bot="mgr", type="log", text=f"Error on {job['name']}: {exc}")


threading.Thread(target=worker, daemon=True).start()
threading.Thread(target=content_worker, daemon=True).start()
threading.Thread(target=affiliate_worker, daemon=True).start()


# ───────────────────────── the office page ─────────────────────────
STATIC = {"index.html", "office.js", "style.css"}


@app.get("/")
def index():
    return FileResponse(HERE / "index.html")


@app.get("/{name}")
def static(name: str):
    if name not in STATIC:
        raise HTTPException(404)
    return FileResponse(HERE / name)


PORT = int(os.environ.get("BOT_OFFICE_PORT", "8800"))

if __name__ == "__main__":
    import uvicorn
    print("Bot Office setup check:")
    print(f"  ffmpeg : {content.FFMPEG or 'MISSING'} ({content.FFMPEG_SOURCE})"
          + ("" if content.FFMPEG else "  -> run: pip install imageio-ffmpeg"))
    print(f"  AI     : {ai.provider()} ({'ready' if ai.available() else 'not set up: ⚙️ Settings'})")
    print(f"  Google : {'configured' if veo.configured() else 'not set (⚙️ Settings in the office)'}")
    print(f"  Open http://localhost:{PORT}")
    if os.environ.get("BOT_OFFICE_OPEN") == "1":  # set by the start-* scripts
        import webbrowser
        threading.Timer(2.0, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    # Reachable on the Wi-Fi so a phone can connect, but every non-Mac request is blocked
    # unless Phone access is on and the device logged in with the PIN (see phone_guard).
    print(f"  Phone  : {'ON → ' + auth.phone_url() if PHONE.enabled else 'off (⚙️ Settings → Phone access)'}")
    uvicorn.run(app, host=os.environ.get("BOT_OFFICE_HOST", "0.0.0.0"), port=PORT)
