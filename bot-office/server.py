"""Bot Office server: serves the office page and runs the real compliance bots.

    pip install fastapi uvicorn python-multipart pypdf python-docx beautifulsoup4
    python bot-office/server.py          # then open http://localhost:8800

Upload a PDF/DOCX/HTML/TXT and watch Doc Reader -> Reg Checker -> Risk Scout
work on it. Videos/images are still simulated by the page (content bots).
"""
from __future__ import annotations

import queue
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

import compliance

HERE = Path(__file__).resolve().parent
UPLOADS = HERE / "data" / "uploads"
REPORTS = HERE / "data" / "reports"
UPLOADS.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)

DOC_EXT = {".pdf", ".docx", ".html", ".htm", ".txt", ".md"}
MAX_BYTES = 25 * 1024 * 1024
MIN_STEP_SECS = {"doc": 4, "reg": 5, "risk": 4}  # so you can actually watch them work

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
    return {"ok": True, "live": ["doc", "reg", "risk"]}


@app.get("/api/bots/events")
def events(after: int = 0):
    with _lock:
        return {"events": _events[after:], "last": len(_events)}


# ───────────────────────── uploads -> job queue ─────────────────────────
_jobs: "queue.Queue[dict]" = queue.Queue()


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    accepted, skipped = [], []
    for f in files:
        name = Path(f.filename or "file").name
        ext = Path(name).suffix.lower()
        if ext not in DOC_EXT:
            skipped.append(name)
            continue
        data = await f.read()
        if len(data) > MAX_BYTES:
            skipped.append(name)
            continue
        job_id = uuid.uuid4().hex[:10]
        path = UPLOADS / f"{job_id}{ext}"
        path.write_bytes(data)
        _jobs.put({"id": job_id, "name": name, "path": path})
        emit(bot="doc", type="task", task=f"{job_id}-doc", text=f"Read & extract: {name}", secs=MIN_STEP_SECS["doc"])
        accepted.append({"job": job_id, "name": name})
    return {"accepted": accepted, "skipped": skipped}


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
    _paced("reg", t0)
    if doc_type == "regulation":
        summary = f"{name}: {len(res.obligations)} key obligations found"
    else:
        n = len(res.passed) + len(res.missing)
        summary = f"{name}: {len(res.passed)}/{n} checks passed" + (f", {len(res.flags)} red flag(s) 🚩" if res.flags else "")
    emit(bot="reg", type="done", task=f"{jid}-reg", text=summary)

    # Risk Scout
    emit(bot="risk", type="task", task=f"{jid}-risk", text=f"Risk report: {name}", secs=MIN_STEP_SECS["risk"])
    t0 = time.time()
    risk, level = compliance.score(res)
    (REPORTS / f"{jid}.html").write_text(compliance.render_report(name, text, pages, res, risk, level), encoding="utf-8")
    _paced("risk", t0)
    verdict = "summary ready" if level == "INFO" else f"{level} risk ({risk}/100)"
    emit(bot="risk", type="done", task=f"{jid}-risk", level=level, url=f"/reports/{jid}.html", text=f"{name}: {verdict}")


def worker() -> None:
    while True:
        job = _jobs.get()
        try:
            run_job(job)
        except Exception as exc:  # never let one bad file kill the office
            emit(bot="mgr", type="log", text=f"May error sa {job['name']}: {exc}")


threading.Thread(target=worker, daemon=True).start()


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8800)
