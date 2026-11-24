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
from datetime import datetime, timedelta

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
import content_hub
import prompt_library
import inspo
import osint
import commander
import seo
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
MIN_STEP_SECS = {"taks": 5, "doc": 4, "reg": 5, "risk": 4, "vid": 5, "cap": 4, "sched": 3, "post": 3,
                 "jp": 5, "asher": 4, "shane": 3, "jacob": 3, "ashley": 3, "david": 3}  # so you can actually watch them work

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


BOT_ALIAS = {"vid": "jp", "cap": "asher", "sched": "ashley", "post": "david"}  # the old content team → the Content Hub team


def emit(**ev) -> None:
    ev["bot"] = BOT_ALIAS.get(ev.get("bot"), ev.get("bot"))
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
_osint_jobs: "queue.Queue[dict]" = queue.Queue()
_seo_jobs: "queue.Queue[dict]" = queue.Queue()   # Taks has his own queue so research never holds up KYB / reviews


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
            start_batch([{**job, "tiktok": "", "shopee": "", "notes": ""}], ["tiktok", "facebook", "instagram"], "slots")
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


@app.post("/api/research")
async def research_start(request: Request):
    form = {k: (v if isinstance(v, str) else "") for k, v in dict(await request.form()).items()}
    q = form.get("q", "").strip()
    if not q:
        return {"ok": False, "error": "Ano ang ire-research ni Taks?"}
    kind = form.get("kind", "auto")
    kind = kind if kind in osint.TYPES else osint.detect(q)
    purpose = form.get("purpose", "") or "General research"
    if kind == "person" and purpose == "General research":
        return {"ok": False, "error": "Para sa tao, pumili ng lehitimong purpose (hal. KYC, AML, fraud) — Data Privacy Act."}
    jid = uuid.uuid4().hex[:10]
    _osint_jobs.put({"kind": "osint", "id": jid, "name": q[:60], "q": q, "type": kind, "country": form.get("country", "").strip(),
               "purpose": purpose, "notes": form.get("notes", "").strip()[:1000], "web": form.get("web") == "1"})
    emit(bot="taks", type="task", task=f"{jid}-osint", text=f"OSINT · {osint.TYPES[kind]}: {q[:50]}", secs=MIN_STEP_SECS["taks"])
    return {"ok": True, "job": jid, "kind": kind}


@app.post("/api/command")
async def command(text: str = Form(""), files: list[UploadFile] = File(default=[])):
    """Hazel's command box: any instruction + any files, routed to the right team."""
    text = text.strip()
    if not text and not files:
        return {"ok": False, "error": "Isulat ang utos o mag-attach ng file."}
    cid = uuid.uuid4().hex[:10]
    folder = UPLOADS / f"cmd_{cid}"
    folder.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        data = await f.read()
        if not data or len(data) > MAX_MEDIA_BYTES:
            continue
        name = re.sub(r"[^\w.\- ()]+", "_", Path(f.filename or "file").name)[:120] or "file"
        (folder / name).write_bytes(data)
        saved.append(folder / name)
    if not saved and commander.is_cancel(text):
        n = cancel_posts()
        emit(bot="mgr", type="log", text=f"📨 “{text[:80]}” → ✖ David: cancel queued posts")
        return {"ok": True, "action": "cancel", "label": "✖ David (cancel posts)",
                "message": f"Cancelled {n} queued post(s)." if n else "Walang naka-queue na post na ica-cancel."}
    rt = commander.route(text, [p.name for p in saved])
    act, subj = rt["action"], rt["subject"]
    if act == "research" and rt["entity"] and rt["kind"] == "person" and rt["purpose"] == "General research":
        return {"ok": False, "error": "Para mag-research ng tao, sabihin ang purpose (hal. 'KYC', 'fraud', 'vendor check') — Data Privacy Act."}
    emit(bot="mgr", type="log", text=f"📨 “{text[:80]}”" + (f" + {len(saved)} file(s)" if saved else "") + f" → {commander.LABEL[act]}")
    if act == "seo":
        urls = [l for l in rt["links"] if l not in rt["product"]] or ([rt["entity"]] if rt["entity"] and "." in rt["entity"] else [])
        task = rt["seo_task"]
        kw = "" if rt["entity"] and "." in rt["entity"] else (rt["entity"] or re.sub(r"\b(seo|geo|check|competitor|ai search|keywords?|research|brief|content|audit|para sa|for|ng|ang|sa|mo|gawan)\b", " ",
                                                                             rt["notes"], flags=re.I).strip(" ,.:"))
        r = queue_seo(task, urls[0] if urls else "", kw, urls[1:], "30")
        return r
    if act == "kyb":
        form = {"kind": "business", "name": rt["entity"] or (subj if len(subj) > 2 and not saved else ""),
                "drive_link": rt["drive"][0] if rt["drive"] else (str(folder) if saved else ""),
                "country": next((c.title() for c in osint.COUNTRIES if re.search(rf"\b{re.escape(c)}\b", text, re.I)), "")}
        if not form["drive_link"] and not form["name"]:
            return {"ok": False, "error": "Para sa KYB: ilagay ang pangalan ng negosyo, i-attach ang documents, o i-paste ang Drive link."}
        jid = uuid.uuid4().hex[:10]
        _jobs.put({"kind": "kyc", "id": jid, "type": "business", "form": form})
        emit(bot="doc", type="task", task=f"{jid}-intake", text=f"KYB intake: {form['name'] or 'documents'}", secs=3)
        return {"ok": True, "action": act, "label": commander.LABEL[act]}
    if act == "affiliate":
        imgs = [p for p in saved if p.suffix.lower() in content.IMAGE_EXT]
        jid = uuid.uuid4().hex[:10]
        (AFFILIATE / jid).mkdir(parents=True, exist_ok=True)
        _affiliate_jobs.put({"kind": "plan", "id": jid, "url": rt["product"][0], "owns": False, "notes": rt["notes"], "photos": imgs, "model": None})
        emit(bot="cap", type="task", task=f"{jid}-cap", text=f"Write 5 affiliate scripts: {rt['product'][0][:60]}", secs=MIN_STEP_SECS["cap"])
        return {"ok": True, "action": act, "label": commander.LABEL[act], "page": f"/reports/{jid}.html"}
    if act == "content":
        def _cmd_topic(rt, p):
            """Caption topic: the named product/entity, else the instruction minus command words, else the file name."""
            subj = rt["entity"] or commander.subject(rt["notes"])
            if len([w for w in subj.split() if len(w) > 2]) < 2:
                subj = re.sub(r"[_\-]+", " ", p.stem).strip()
            return subj
        shopee = next((l for l in rt["product"] if "shope" in l), "")
        tiktok = next((l for l in rt["product"] if "tiktok" in l), "")
        inspo_links = [l for l in rt["links"] if l not in rt["product"]]
        items, refs = [], []
        for p in saved:
            vid = uuid.uuid4().hex[:10]
            if p.suffix.lower() in content_hub.VIDEO_EXTS | content_hub.IMAGE_EXTS:
                items.append({"id": vid, "name": p.name, "path": p, "tiktok": tiktok, "shopee": shopee,
                              "notes": _cmd_topic(rt, p) + ". " + rt["notes"][:500]})
            else:
                refs.append({"id": vid, "name": p.name, "path": str(p)})
        plats = [k for k, pat in (("tiktok", r"tiktok"), ("facebook", r"\b(fb|facebook)\b"), ("instagram", r"\b(ig|instagram)\b"))
                 if re.search(pat, text, re.I)] or ["tiktok", "facebook", "instagram"]
        when = "now" if re.search(r"\b(now|ngayon na|agad)\b", text, re.I) else "slots"
        start_batch(items, plats, when, refs, inspo_links, research=bool(rt["entity"] or rt["product"]))
        return {"ok": True, "action": act, "label": commander.LABEL[act]}
    if act == "review":
        for p in saved:
            if p.suffix.lower() in DOC_EXT:
                jid = uuid.uuid4().hex[:10]
                dest = UPLOADS / f"{jid}{p.suffix.lower()}"
                shutil.copyfile(p, dest)
                _jobs.put({"id": jid, "name": p.name, "path": dest})
                emit(bot="doc", type="task", task=f"{jid}-doc", text=f"Read & extract: {p.name}", secs=MIN_STEP_SECS["doc"])
        return {"ok": True, "action": act, "label": commander.LABEL[act]}
    # research (anything): a named thing gets its own type; otherwise the whole question is a topic
    q, kind = (rt["entity"], rt["kind"]) if rt["entity"] else (text, "topic")
    if rt["entity"] and len(text.split()) > len(rt["entity"].split()) + 6 and kind == "person":
        q, kind = text, "topic"
    purpose = rt["purpose"]
    if kind == "person" and purpose == "General research":
        return {"ok": False, "error": "Para mag-research ng tao, sabihin ang purpose (hal. 'KYC', 'fraud', 'vendor check') — Data Privacy Act."}
    notes = ""
    for p in saved:
        try:
            notes += " " + content_hub.read_reference(p, p.name).get("text", "")[:800]
        except Exception:
            pass
    jid = uuid.uuid4().hex[:10]
    _osint_jobs.put({"kind": "osint", "id": jid, "name": q[:60], "q": q, "type": kind, "country": "",
               "purpose": purpose, "notes": notes.strip()[:1000], "web": True})
    emit(bot="taks", type="task", task=f"{jid}-osint", text=f"OSINT · {osint.TYPES[kind]}: {q[:50]}", secs=MIN_STEP_SECS["taks"])
    return {"ok": True, "action": "research", "label": commander.LABEL["research"]}


@app.post("/api/seo")
async def seo_start(request: Request):
    form = {k: (v if isinstance(v, str) else "") for k, v in dict(await request.form()).items()}
    return queue_seo(form.get("task", "audit"), form.get("url", ""), form.get("keyword", ""),
                     [l.strip() for l in form.get("competitors", "").splitlines() if l.strip()], form.get("max_pages", "30"))


def queue_seo(task: str, url: str, keyword: str, competitors: list[str], max_pages="30") -> dict:
    task = task if task in seo.TASKS else "audit"
    url, keyword = url.strip(), keyword.strip()
    need = {"audit": url, "keywords": keyword, "brief": keyword, "competitor": url and competitors, "geo": keyword or url}[task]
    if not need:
        return {"ok": False, "error": {"audit": "Ilagay ang website URL.", "keywords": "Ilagay ang seed keyword.", "brief": "Ilagay ang keyword.",
                                       "competitor": "Ilagay ang website mo at kahit isang competitor.", "geo": "Ilagay ang brand o website."}[task]}
    jid = uuid.uuid4().hex[:10]
    try:
        mp = max(3, min(150, int(max_pages)))
    except ValueError:
        mp = 30
    _seo_jobs.put({"id": jid, "task": task, "url": url, "keyword": keyword, "competitors": competitors, "max_pages": mp})
    emit(bot="asher", type="task", task=f"{jid}-seo", text=f"SEO · {seo.TASKS[task]}: {(keyword or url)[:50]}", secs=MIN_STEP_SECS["asher"])
    return {"ok": True, "job": jid, "task": task, "label": "📈 Asher (SEO)"}


def run_seo_job(job: dict) -> None:
    jid, task = job["id"], job["task"]
    out = OUTBOX / jid
    out.mkdir(parents=True, exist_ok=True)
    target = job["keyword"] or job["url"]
    if task == "audit":
        res = seo.audit(job["url"], job["max_pages"])
        res["_csv"] = [seo.save_csv([{k: v for k, v in i.items()} for i in res["issues"]], out / "seo_issues.csv"),
                       seo.save_csv([{k: p[k] for k in ("url", "status", "title", "desc", "h1", "words", "no_alt", "schema", "ms")} for p in res["pages"]], out / "seo_pages.csv")]
        summary = f"score {res['score']}/100 · {len(res['issues'])} issue(s) · {len(res['pages'])} page(s)"
        level = "LOW" if res["score"] >= 80 else "MEDIUM" if res["score"] >= 50 else "HIGH"
    elif task == "keywords":
        res = seo.keywords(job["keyword"])
        res["_csv"] = [seo.save_csv(res["rows"], out / "keywords.csv")]
        summary, level = f"{len(res['rows'])} keyword(s), {len(res['clusters'])} cluster(s)", None
    elif task == "brief":
        res = seo.brief(job["keyword"], job["url"])
        res["_csv"] = [seo.save_csv(res["kw"]["rows"], out / "keywords.csv")]
        summary, level = f"brief ready ({res['brief'].get('by')})", None
    elif task == "competitor":
        res = seo.competitor(job["url"], job["competitors"])
        res["_csv"] = [seo.save_csv([{k: v for k, v in x.items() if k != "titles"} for x in res["sites"]], out / "competitors.csv")]
        summary, level = f"{len(res['sites'])} site(s) compared", None
    else:
        res = seo.geo(job["keyword"] or job["url"], job["url"])
        summary, level = "AI search check " + ("with Claude web search" if (res.get("web") or {}).get("text") else "(signals only)"), None
    (REPORTS / f"{jid}.html").write_text(seo.render(task, target, res, f"/outbox/{jid}/"), encoding="utf-8")
    emit(bot="asher", type="done", task=f"{jid}-seo", url=f"/reports/{jid}.html", text=f"SEO · {target[:40]}: {summary}", **({"level": level} if level else {}))


def run_osint_job(job: dict) -> None:
    jid = job["id"]
    t0 = time.time()
    r = osint.run(job["q"], job["type"], job["country"], job["purpose"], job["notes"], KYC_DIR / jid, LIST_CACHE, job["web"])
    page = osint.render(r)
    (REPORTS / f"{jid}.html").write_text(page, encoding="utf-8")
    saved = None
    try:
        saved = outputs.save_case(job["q"][:60], "OSINT", r, page)
    except Exception as exc:
        emit(bot="mgr", type="log", text=f"Couldn't save to Drive: {exc}")
    _paced("taks", t0)
    level = {"ESCALATE": "HIGH", "REVIEW": "MEDIUM"}.get(r["outcome"], "LOW")
    emit(bot="taks", type="done", task=f"{jid}-osint", url=f"/reports/{jid}.html", level=level,
         text=f"{job['q'][:50]}: {r['outcome']} · {len(r['findings'])} finding(s)" + (f" · 📁 {saved.name}" if saved else ""))
    if r["outcome"] == "ESCALATE":
        emit(bot="mgr", type="log", text=f"🚩 Taks flagged {job['q'][:40]}: " + "; ".join(r["red"])[:160])


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
    sweep = []
    if t != "url":   # Taks: news mentions for the subject and the parties
        names = [merchant] + [s["name"] for s in r.get("subjects", [])[1:5]]
        emit(bot="taks", type="task", task=f"{jid}-sweep", text=f"OSINT sweep: {len(names)} name(s)", secs=MIN_STEP_SECS["taks"])
        for n in names:
            nw = osint.news(n, 8)
            sweep.append({"name": n, "ok": nw["ok"], "items": nw["items"]})
        r["osint_news"] = sweep
        emit(bot="taks", type="done", task=f"{jid}-sweep", text=f"OSINT sweep: {sum(len(x['items']) for x in sweep)} news mention(s)")
    emit(bot="risk", type="task", task=f"{jid}-report", text=f"{label} report: {merchant}", secs=3)
    page = kyc.render(r) if t != "url" else kyc.render_url(r)
    if sweep:
        import html as _h
        sec = "<h2>📰 Taks · OSINT news sweep (GDELT, 5 taon)</h2>" + "".join(
            f"<h3>{_h.escape(x['name'])}</h3>" + ("<ul>" + "".join(f"<li>{_h.escape(a['date'])} · <a href='{_h.escape(a['url'])}' target='_blank'>{_h.escape(a['title'])}</a> "
                                                              f"<small>{_h.escape(a['source'])}</small></li>" for a in x["items"]) + "</ul>" if x["items"]
                                                   else "<p class='muted'>" + ("Walang news mention." if x["ok"] else "Hindi naabot ang GDELT: Analyst to run.") + "</p>")
            for x in sweep) + "<p class='muted'>Ang news mention ay hindi patunay: i-verify kung parehong tao/kumpanya at kung allegation o napatunayan.</p>"
        page = page.replace("</body>", sec + "</body>", 1)
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
    m = req.get("model") or {}
    pk = prompt_library.pack(prod["name"] or "the product", f"{req['notes']} {prod['description'][:300]}", has_model=bool(m),
                             model_name=m.get("name", ""), setting=m.get("setting", ""),
                             script=videos[0].get("hook", "") if videos else "")
    emit(bot="asher", type="log", text=f"🎬 Prompt Pack for {prod['name'] or 'the product'}: {len(pk['items'])} prompts ({pk['subtype']})")
    job = {"id": jid, "prompt_pack": pk, "product": {k: prod[k] for k in ("url", "name", "description", "category")}, "owns": owns, "model": req.get("model"),
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


# ───────────────────────── Content Hub ─────────────────────────
BATCHES = HERE / "data" / "content_hub" / "batches"


def start_batch(items: list[dict], platforms: list[str], when: str, refs: list | None = None, links: list | None = None,
                research: bool = True) -> str:
    bid = uuid.uuid4().hex[:10]
    _content_jobs.put({"id": bid, "name": f"{len(items)} file(s)", "items": items, "platforms": platforms, "when": when, "refs": refs or [],
                       "inspo": links or [], "research": research})
    for u in links or []:
        b, plat = inspo.who(u)
        emit(bot=b, type="task", task=f"{bid}-inspo-{abs(hash(u)) % 10**8}", text=f"Watch inspo ({plat})", secs=12)
    if refs:
        emit(bot="asher", type="task", task=f"{bid}-refs", text=f"Read {len(refs)} reference file(s)", secs=MIN_STEP_SECS["asher"])
    for it in items:
        emit(bot="jp", type="task", task=f"{it['id']}-jp", text=f"Edit + review: {it['name']}", secs=MIN_STEP_SECS["jp"])
    return bid


@app.post("/api/content/batch")
async def content_batch(files: list[UploadFile] = File(default=[]), meta: str = Form("[]"), platforms: str = Form("tiktok,facebook,instagram"),
                        when: str = Form("slots"), inspo_links: str = Form(""), research: str = Form("1")):
    import json as _json
    try:
        rows = _json.loads(meta)
    except ValueError:
        rows = []
    plats = [p for p in platforms.split(",") if p in content_hub.PLATFORMS] or ["tiktok"]
    items, refs = [], []
    for i, f in enumerate(files):
        name = Path(f.filename or "file").name
        ext = Path(name).suffix.lower()
        data = await f.read()
        if not data or len(data) > MAX_MEDIA_BYTES:
            continue
        vid = uuid.uuid4().hex[:10]
        path = UPLOADS / f"{vid}{re.sub(r'[^.a-z0-9]', '', ext)[:8]}"
        path.write_bytes(data)
        r = rows[i] if i < len(rows) and isinstance(rows[i], dict) else {}
        if ext in content_hub.VIDEO_EXTS | content_hub.IMAGE_EXTS:
            items.append({"id": vid, "name": name, "path": path, "tiktok": str(r.get("tiktok", "")).strip(),
                          "shopee": str(r.get("shopee", "")).strip(), "notes": str(r.get("notes", "")).strip()[:500]})
        else:
            refs.append({"id": vid, "name": name, "path": str(path)})
    links = inspo.parse_links(inspo_links)
    if not items and not refs and not links:
        return {"ok": False, "error": "Walang file o inspo link na natanggap."}
    bid = start_batch(items, plats, when if when in ("slots", "now") else "slots", refs, links, research == "1")
    return {"ok": True, "batch": bid, "videos": len(items), "refs": len(refs), "inspo": len(links)}


def read_batch_refs(bid: str, items: list[dict], refs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Asher reads briefs and product lists; matches them to the media by file name. Returns (ref summaries, plan rows)."""
    t0 = time.time()
    by_stem = {content_hub.stem_key(it["name"]): it for it in items}
    read, briefs, plan = [], [], []
    for r in refs:
        info = content_hub.read_reference(Path(r["path"]), r["name"])
        info["file"] = Path(r["path"]).name
        read.append({k: v for k, v in info.items() if k != "rows"} | {"text": info["text"][:3000]})
        if info["kind"] == "brief" and info["text"]:
            target = by_stem.get(content_hub.stem_key(r["name"]))
            if target:
                target["notes"] = (target["notes"] + " " + info["text"][:1500]).strip()
            else:
                briefs.append(info["text"][:1500])
        for row in info["rows"]:
            target = by_stem.get(content_hub.stem_key(row["file"])) if row["file"] else None
            if target:
                for k in ("tiktok", "shopee", "notes"):
                    if row[k] and not target[k]:
                        target[k] = row[k]
                if row["name"] and row["name"] not in target["notes"]:
                    target["notes"] = (row["name"] + ". " + target["notes"]).strip()
            elif row["name"] or row["notes"]:
                plan.append(row)
    if briefs:
        for it in items:
            if len(it["notes"]) < 400:
                it["notes"] = (it["notes"] + " " + " ".join(briefs)[:1500]).strip()
    _paced("asher", t0)
    emit(bot="asher", type="done", task=f"{bid}-refs",
         text=f"Read {len(refs)} file(s): " + ", ".join(f"{x['name']} ({x['note']})" for x in read)[:220])
    return read, plan


BOT_NAMES = {"shane": "Shane", "jacob": "Jacob", "asher": "Asher", "jp": "JP"}


def watch_inspo(bid: str, links: list[str]) -> list[dict]:
    """The right teammate watches each inspo link: fetch, measure, contact sheet, AI breakdown."""
    reports = []
    for u in links:
        b, plat = inspo.who(u)
        task = f"{bid}-inspo-{abs(hash(u)) % 10**8}"
        iid = uuid.uuid4().hex[:10]
        work = OUTBOX / iid
        r = {"id": iid, "url": u, "platform": plat, "bot": b, "bot_name": BOT_NAMES.get(b, b)}
        try:
            got = inspo.fetch(u, work)
            r.update(title=got["title"], via=got["via"], note=got["note"])
            if got["kind"] in ("video", "image"):
                media = Path(got["path"])
                if media.parent != work:
                    shutil.copyfile(media, work / media.name)
                    media = work / media.name
                facts = inspo.analyze_video(media, work) if got["kind"] == "video" else inspo.analyze_image(media, work)
                r.update(media=media.name, sheet=facts.pop("sheet", ""), facts=facts, kind=got["kind"])
                bd = inspo.ai_describe(work / r["sheet"], facts, got["title"]) if r["sheet"] else None
                r.update(breakdown=bd or inspo.template_breakdown(got["kind"], facts), by=ai.provider() if bd else "measurements")
            else:
                r.update(breakdown={"summary": got["description"] or "Hindi nakuha ang video o larawan.", "hook": "", "style": "", "shots": [],
                                    "pacing": "", "on_screen_text": "", "recreate": [], "avoid": []}, by="page text")
            emit(bot=b, type="done", task=task, url=f"/content/{bid}", text=f"Watched {plat} inspo: {r['breakdown']['summary'][:140]}")
        except Exception as exc:
            r.update(breakdown={"summary": f"Hindi napanood: {exc}", "hook": "", "style": "", "shots": [], "pacing": "", "on_screen_text": "",
                                "recreate": [], "avoid": []}, by="-")
            emit(bot=b, type="done", task=task, ok=False, text=f"Couldn't watch the {plat} inspo: {str(exc)[:100]}")
        reports.append(r)
    return reports


def run_content_batch(job: dict) -> None:
    bid, items, plats = job["id"], job["items"], job["platforms"]
    videos, posts = [], []
    inspo_reports = watch_inspo(bid, job.get("inspo", [])) if job.get("inspo") else []
    research = []
    if job.get("research") and items:   # Taks: product research for the captions (one run per product)
        done = {}
        for it in items:
            pname = content_hub.product_name(it["tiktok"] or it["shopee"]) or (it["notes"].split(",")[0].strip()[:80] if it["notes"] else "") \
                    or content._topic(it["name"])
            if pname not in done:
                emit(bot="taks", type="task", task=f"{bid}-cr-{len(done)}", text=f"Product research: {pname[:50]}", secs=MIN_STEP_SECS["taks"])
                try:
                    done[pname] = osint.content_research(pname, it["notes"])
                    emit(bot="taks", type="done", task=f"{bid}-cr-{len(done) - 1}", text=f"Researched {pname[:50]} for Asher 🔎")
                except Exception as exc:
                    done[pname] = None
                    emit(bot="taks", type="done", task=f"{bid}-cr-{len(done) - 1}", ok=False, text=f"Research failed: {str(exc)[:80]}")
            if done[pname] and done[pname]["summary"]:
                it["notes"] = (it["notes"] + " " + done[pname]["summary"]).strip()
        research = [r for r in done.values() if r]
    inspo_note = " ".join(inspo.summary_line(r) for r in inspo_reports)[:1500]
    for it in items:   # Asher writes captions in the inspo's style
        if inspo_note:
            it["notes"] = (it["notes"] + " " + inspo_note).strip()
    refs_read, plan = read_batch_refs(bid, items, job.get("refs", [])) if job.get("refs") else ([], [])
    for row in plan:   # products from a sheet with no media yet: caption drafts + Prompt Pack
        name = row["name"] or row["notes"][:60]
        product = content_hub.product_name(row["tiktok"] or row["shopee"]) or name
        cap = content_hub.seo_caption(name, row["notes"], product)
        drafts = {pl: content_hub.platform_caption(cap, pl, row["shopee"] if content_hub.check_link(row["shopee"], "shopee")[0] in ("ok", "warn") else "",
                                                   row["tiktok"] if content_hub.check_link(row["tiktok"], "tiktok")[0] in ("ok", "warn") else "")[0]
                  for pl in plats}
        videos.append({"id": content_hub.new_id(), "kind": "plan", "name": name, "drafts": drafts, "row": row,
                       "prompt_pack": prompt_library.pack(name, row["notes"], script=cap["hook"], inspo=bool(inspo_reports))})
    if plan:
        emit(bot="asher", type="log", text=f"📊 {len(plan)} product(s) from the sheet: caption drafts + Prompt Packs ready (no media yet)")
    for it in items:
        vid, name = it["id"], it["name"]
        out = OUTBOX / vid
        # JP: edit + review
        t0 = time.time()
        try:
            if Path(it["path"]).suffix.lower() in content_hub.IMAGE_EXTS:
                it["path"] = content_hub.normalize_image(Path(it["path"]), out)
            media = content.make_vertical(it["path"], out)
        except Exception as exc:
            _paced("jp", t0)
            emit(bot="jp", type="done", task=f"{vid}-jp", ok=False, text=f"Couldn't edit {name}: {exc}")
            continue
        mkind = "photo" if media["kind"] == "image" else "video"
        photo = content_hub.make_photo(it["path"], out) if mkind == "photo" else None
        review = content_hub.review_edit(it["path"], media, out) if mkind == "video" else (
            [f"Maliit ang larawan ({i['width']}x{i['height']}): baka malabo"] if (i := content_hub.probe(it["path"])).get("width") and min(i["width"], i["height"]) < 720 else [])
        _paced("jp", t0)
        emit(bot="jp", type="done", task=f"{vid}-jp", level="MEDIUM" if review else "LOW",
             text=f"{name}: {media['note']}" + (f" · review: {len(review)} note(s)" if review else " · review ✅"))
        # Asher: SEO caption + link checks
        emit(bot="asher", type="task", task=f"{vid}-asher", text=f"SEO caption + link check: {name}", secs=MIN_STEP_SECS["asher"])
        t0 = time.time()
        product = content_hub.product_name(it["tiktok"] or it["shopee"])
        cap = content_hub.seo_caption(name, it["notes"], product)
        links = []
        for kind, url in (("TikTok Shop", it["tiktok"]), ("Shopee", it["shopee"])):
            st, notes = content_hub.check_link(url, "tiktok" if kind == "TikTok Shop" else "shopee")
            links.append([kind, url, st, notes])
        bad = [l for l in links if l[2] in ("warn", "bad")]
        _paced("asher", t0)
        emit(bot="asher", type="done", task=f"{vid}-asher", level="MEDIUM" if bad else "LOW",
             text=f"“{cap['hook']}” (+{len(cap['hashtags'])} hashtags, by {cap['by']})" + (f" · ⚠️ {len(bad)} link issue(s)" if bad else ""))
        tiktok = it["tiktok"] if links[0][2] in ("ok", "warn") else ""
        shopee = it["shopee"] if links[1][2] in ("ok", "warn") else ""
        file_name = f"{Path(name).stem}_9x16." + ("jpg" if mkind == "photo" else "mp4")
        for plat in plats:
            caption, comment = content_hub.platform_caption(cap, plat, shopee, tiktok)
            posts.append({"id": content_hub.new_id(), "batch": bid, "video": vid, "job": vid, "platform": plat, "caption": caption,
                          "comment": comment, "tiktok_link": tiktok, "shopee_link": shopee,
                          "media": photo if (photo and plat in ("facebook", "instagram")) else media["media"], "kind": mkind,
                          "file_name": file_name if plat == "tiktok" or not photo else f"{Path(name).stem}_4x5.jpg", "name": name, "status": "new"})
        # Shane + Jacob
        if "tiktok" in plats:
            emit(bot="shane", type="task", task=f"{vid}-shane", text=f"TikTok post + basket: {name}", secs=MIN_STEP_SECS["shane"])
            time.sleep(MIN_STEP_SECS["shane"])
            emit(bot="shane", type="done", task=f"{vid}-shane",
                 text=f"{name}: TikTok caption ready" + (" · 🛒 basket product added to the post plan" if tiktok else " · no TikTok Shop link"))
        if {"facebook", "instagram"} & set(plats):
            emit(bot="jacob", type="task", task=f"{vid}-jacob", text=f"Shopee link on FB/IG: {name}", secs=MIN_STEP_SECS["jacob"])
            time.sleep(MIN_STEP_SECS["jacob"])
            emit(bot="jacob", type="done", task=f"{vid}-jacob",
                 text=f"{name}: " + ("🛒 Shopee link in the Facebook caption + Instagram first comment" if shopee else "captions ready (no Shopee link)"))
        pk = prompt_library.pack(product or (it["notes"].split(",")[0].strip()[:80] if it["notes"] else content._topic(name)), it["notes"],
                                 script=cap["hook"], inspo=bool(inspo_reports))
        videos.append({"id": vid, "job": vid, "name": name, "file_name": file_name, "media": media["media"], "kind": mkind, "photo": photo,
                       "review": review, "links": links,
                       "prompt_pack": pk})
    real = [v for v in videos if v.get("kind") != "plan"]
    BATCHES.mkdir(parents=True, exist_ok=True)
    if not real:
        (BATCHES / f"{bid}.json").write_text(json.dumps({"videos": videos, "refs": refs_read, "inspo": inspo_reports, "research": research}, ensure_ascii=False, default=str))
        if videos or refs_read or inspo_reports:
            emit(bot="asher", type="log", url=f"/content/{bid}", text="✨📎 Done: open the batch page for the inspo breakdown, drafts and Prompt Packs")
        return
    videos_all, videos = videos, real
    # Ashley: one slot per video, shared by its platforms
    emit(bot="ashley", type="task", task=f"{bid}-ashley", text=f"Pick posting slots: {len(videos)} video(s)", secs=MIN_STEP_SECS["ashley"])
    t0 = time.time()
    with content_hub._lock:
        allp = content_hub.load_posts()
        taken = {p["slot"] for p in allp if p["status"] in ("scheduled", "handoff")}
        if job.get("when") == "now":
            now = datetime.now(content.MANILA)
            slots = [now + timedelta(minutes=2 * i) for i in range(len(videos))]
        else:
            slots = content_hub.next_slots(len(videos), taken)
        slot_of = {v["id"]: s.isoformat() for v, s in zip(videos, slots)}
        for p in posts:
            route = ("zapier" if content_hub.zapier_ready(p["platform"], p["kind"]) else
                     "meta" if content_hub.meta_ready(p["platform"]) and not (p["kind"] == "photo" and p["platform"] == "instagram") else "")
            p.update(slot=slot_of[p["video"]], status="scheduled", auto=bool(route), route=route)
            if route == "zapier":   # copy now, so Drive for desktop has uploaded it by the time it's due
                try:
                    p["drive_file"] = str(content_hub.stage_to_drive(p, OUTBOX / p["job"] / p["media"]))
                except OSError as exc:
                    p.update(route="", auto=False, error=f"Couldn't copy to the Drive folder: {exc}")
        content_hub.save_posts(allp + posts)
    BATCHES.mkdir(parents=True, exist_ok=True)
    (BATCHES / f"{bid}.json").write_text(json.dumps({"videos": videos_all, "refs": refs_read, "inspo": inspo_reports, "research": research}, ensure_ascii=False, default=str))
    _paced("ashley", t0)
    first = min(slots)
    emit(bot="ashley", type="done", task=f"{bid}-ashley", url=f"/content/{bid}",
         text=f"{len(videos)} video(s) scheduled from {content.fmt_slot(first)} ({', '.join(content_hub.PLATFORMS[p] for p in plats)})")
    emit(bot="david", type="log", text=f"Got it: {len(posts)} post(s) queued. FB/IG post by themselves when Meta is connected; TikTok goes to Claude.")


@app.get("/prompts", response_class=HTMLResponse)
def prompts_page():
    return HTMLResponse(prompt_library.render_library())


@app.get("/content/{bid}", response_class=HTMLResponse)
def content_page(bid: str):
    if not re.fullmatch(r"[0-9a-f]{10}", bid) or not (BATCHES / f"{bid}.json").exists():
        raise HTTPException(404)
    data = json.loads((BATCHES / f"{bid}.json").read_text())
    videos, refs, insp = (data, [], []) if isinstance(data, list) else (data["videos"], data.get("refs", []), data.get("inspo", []))
    posts = [p for p in content_hub.load_posts() if p["batch"] == bid]
    page = content_hub.render_batch(bid, posts, videos, refs, insp)
    if isinstance(data, dict) and data.get("research"):
        page = page.replace("<section class=", osint.render_content(data["research"]) + "<section class=", 1)
    return HTMLResponse(page)


@app.get("/api/content/posts")
def content_posts():
    return content_hub.load_posts()[-300:]


@app.post("/api/content/post/{pid}/{action}")
def content_post_action(pid: str, action: str):
    if action == "done":
        p = content_hub.update_post(pid, status="posted", error="")
        return {"ok": bool(p), "message": "Marked as posted ✅" if p else "Not found"}
    if action == "cancel":
        p = next((x for x in content_hub.load_posts() if x["id"] == pid), None)
        if not p or p.get("status") not in PENDING:
            return {"ok": False, "message": "Hindi na ma-cancel (posted na o wala na)." if p else "Not found"}
        content_hub.update_post(pid, status="cancelled", error="")
        emit(bot="david", type="log", text=f"✖ Cancelled: {content_hub.PLATFORMS[p['platform']]} · {p['name']}")
        return {"ok": True, "message": "Cancelled ✖ David won't post it."}
    if action == "restore":
        p = content_hub.update_post(pid, status="scheduled", error="")
        return {"ok": bool(p), "message": "Back on the schedule 📅" if p else "Not found"}
    if action == "now":
        p = content_hub.update_post(pid, slot=datetime.now(content.MANILA).isoformat(), status="scheduled", error="")
        return {"ok": bool(p), "message": "David will post it within a minute 🚀" if p else "Not found"}
    raise HTTPException(400)


PENDING = {"scheduled", "handoff", "failed"}


def cancel_posts(batch: str = "") -> int:
    """Cancel every post David hasn't posted yet (one batch, or all)."""
    n = 0
    for p in content_hub.load_posts():
        if p.get("status") in PENDING and (not batch or p["batch"] == batch):
            content_hub.update_post(p["id"], status="cancelled", error="")
            n += 1
    if n:
        emit(bot="david", type="done", task=f"cancel-{uuid.uuid4().hex[:6]}", text=f"✖ Cancelled {n} queued post(s). Wala akong ipo-post sa mga 'yan.")
    return n


@app.post("/api/content/cancel")
def content_cancel(batch: str = Form("")):
    n = cancel_posts(batch)
    return {"ok": True, "cancelled": n, "message": f"Cancelled {n} post(s) ✖" if n else "Walang naka-queue na post."}


@app.post("/api/zapier/test")
def zapier_test(key: str = Form(...)):
    if key not in content_hub.ZAP_KEYS.values():
        raise HTTPException(400)
    try:
        return content_hub.zapier_test(key)
    except Exception as exc:
        return {"ok": False, "message": f"{type(exc).__name__}: {str(exc)[:160]}"}


@app.post("/api/meta/test")
def meta_test():
    try:
        return content_hub.meta_test()
    except Exception as exc:
        return {"ok": False, "message": f"{type(exc).__name__}: {str(exc)[:200]}"}


def run_due_post(p: dict) -> None:
    plat = content_hub.PLATFORMS[p["platform"]]
    media = OUTBOX / p["job"] / p["media"]
    if p.get("route") == "zapier" and content_hub.zapier_ready(p["platform"], p.get("kind", "video")):
        df = Path(p.get("drive_file") or content_hub.stage_to_drive(p, media))
        url = content_hub.drive_public_url(df)
        if not url:   # Drive for desktop hasn't uploaded it yet: try again on the next round, give up after 45 minutes
            late = (datetime.now(content.MANILA) - datetime.fromisoformat(p["slot"])).total_seconds() / 60
            if late < 45:
                return
            content_hub.update_post(p["id"], status="failed", error="Hindi pa na-upload ng Google Drive for desktop ang file. Naka-on ba ang Drive?")
            emit(bot="david", type="done", task=f"{p['id']}-david", ok=False, url=f"/content/{p['batch']}", text=f"{plat}: Drive didn't upload {p['name']}")
            return
        emit(bot="david", type="task", task=f"{p['id']}-david", text=f"Zapier → {plat}: {p['name']}", secs=6)
        try:
            content_hub.send_zapier(p, url)
            content_hub.update_post(p["id"], status="posted", error="", note="Sent to Zapier: check the Zap history if it doesn't show up")
            emit(bot="david", type="done", task=f"{p['id']}-david", url=f"/content/{p['batch']}", text=f"Sent to Zapier → {plat}: {p['name']} ✅")
        except Exception as exc:
            content_hub.update_post(p["id"], status="failed", error=str(exc)[:300])
            emit(bot="david", type="done", task=f"{p['id']}-david", ok=False, url=f"/content/{p['batch']}", text=f"Zapier failed: {str(exc)[:120]}")
        return
    if p.get("route", "meta" if p.get("auto") else "") == "meta" and content_hub.meta_ready(p["platform"]):
        content_hub.update_post(p["id"], status="posting")
        emit(bot="david", type="task", task=f"{p['id']}-david", text=f"Posting on {plat}: {p['name']}", secs=20)
        try:
            if p.get("kind") == "photo":
                url = content_hub.post_facebook_photo(media, p["caption"])
            else:
                url = (content_hub.post_facebook_reel(media, p["caption"]) if p["platform"] == "facebook"
                       else content_hub.post_instagram_reel(media, p["caption"], p.get("comment", "")))
            content_hub.update_post(p["id"], status="posted", post_url=url, error="")
            emit(bot="david", type="done", task=f"{p['id']}-david", url=url or f"/content/{p['batch']}", text=f"Posted on {plat}: {p['name']} ✅")
        except Exception as exc:
            content_hub.update_post(p["id"], status="failed", error=str(exc)[:300])
            emit(bot="david", type="done", task=f"{p['id']}-david", ok=False, url=f"/content/{p['batch']}",
                 text=f"{plat} post failed: {str(exc)[:120]}. Open the batch page to hand it to Claude.")
        return
    content_hub.update_post(p["id"], status="handoff")
    emit(bot="david", type="task", task=f"{p['id']}-david", text=f"Hand to Claude: {plat} · {p['name']}", secs=4)
    time.sleep(4)
    emit(bot="david", type="done", task=f"{p['id']}-david", level="MEDIUM", url=f"/content/{p['batch']}",
         text=f"⏰ Time to post on {plat}: {p['name']}. Open the page → Copy Claude prompt → paste it in Claude in Chrome")


def david_loop() -> None:
    """Checks the schedule every 30 seconds and posts what is due."""
    while True:
        try:
            now = datetime.now(content.MANILA)
            due = [p for p in content_hub.load_posts() if p.get("status") == "scheduled" and datetime.fromisoformat(p["slot"]) <= now]
            for p in due:
                run_due_post(p)
        except Exception as exc:
            emit(bot="mgr", type="log", text=f"Autopost error: {exc}")
        time.sleep(30)


def content_worker() -> None:
    while True:
        job = _content_jobs.get()
        try:
            run_content_batch(job)
        except Exception as exc:
            emit(bot="mgr", type="log", text=f"Error on {job['name']}: {exc}")


def worker() -> None:
    while True:
        job = _jobs.get()
        try:
            {"kyc": run_kyc_job, "osint": run_osint_job}.get(job.get("kind"), run_job)(job)
        except Exception as exc:  # never let one bad file kill the office
            emit(bot="mgr", type="log", text=f"Error on {job['name']}: {exc}")


threading.Thread(target=worker, daemon=True).start()
threading.Thread(target=content_worker, daemon=True).start()
threading.Thread(target=david_loop, daemon=True).start()


def osint_worker() -> None:
    while True:
        job = _osint_jobs.get()
        try:
            run_osint_job(job)
        except Exception as exc:
            emit(bot="taks", type="done", task=f"{job['id']}-osint", ok=False, text=f"Research error: {str(exc)[:120]}")


threading.Thread(target=osint_worker, daemon=True).start()


def seo_worker() -> None:
    while True:
        job = _seo_jobs.get()
        try:
            run_seo_job(job)
        except Exception as exc:
            emit(bot="asher", type="done", task=f"{job['id']}-seo", ok=False, text=f"SEO error: {str(exc)[:120]}")


threading.Thread(target=seo_worker, daemon=True).start()
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
