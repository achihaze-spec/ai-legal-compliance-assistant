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
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

import ai
import compliance
import content

HERE = Path(__file__).resolve().parent
UPLOADS = HERE / "data" / "uploads"
REPORTS = HERE / "data" / "reports"
OUTBOX = HERE / "data" / "outbox"
CALENDAR = HERE / "data" / "calendar.json"
UPLOADS.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)
OUTBOX.mkdir(parents=True, exist_ok=True)

DOC_EXT = {".pdf", ".docx", ".html", ".htm", ".txt", ".md"}
MEDIA_EXT = content.VIDEO_EXT | content.IMAGE_EXT
MAX_BYTES = 25 * 1024 * 1024
MAX_MEDIA_BYTES = 500 * 1024 * 1024
MIN_STEP_SECS = {"doc": 4, "reg": 5, "risk": 4, "vid": 5, "cap": 4, "sched": 3, "post": 3}  # so you can actually watch them work

app = FastAPI(title="Bot Office")

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
        emit(bot="doc", type="done", task=f"{jid}-doc", ok=False, text=f"Hindi mabasa ang {name}: {exc}")
        return
    doc_type = compliance.classify(text)
    words = len(text.split())
    _paced("doc", t0)
    if words < 20:
        emit(bot="doc", type="done", task=f"{jid}-doc", ok=False,
             text=f"{name}: halos walang text (scanned PDF?). Kailangan ng OCR.")
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
        emit(bot="vid", type="done", task=f"{jid}-vid", ok=False, text=f"Hindi ma-edit ang {name}: {exc}")
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
            emit(bot="mgr", type="log", text=f"May error sa {job['name']}: {exc}")


def worker() -> None:
    while True:
        job = _jobs.get()
        try:
            run_job(job)
        except Exception as exc:  # never let one bad file kill the office
            emit(bot="mgr", type="log", text=f"May error sa {job['name']}: {exc}")


threading.Thread(target=worker, daemon=True).start()
threading.Thread(target=content_worker, daemon=True).start()


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
    print(f"  Claude : {'on' if ai.available() else 'off (set ANTHROPIC_API_KEY to enable)'}")
    print(f"  Open http://localhost:{PORT}")
    if os.environ.get("BOT_OFFICE_OPEN") == "1":  # set by the start-* scripts
        import webbrowser
        threading.Timer(2.0, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    uvicorn.run(app, host="0.0.0.0", port=PORT)
