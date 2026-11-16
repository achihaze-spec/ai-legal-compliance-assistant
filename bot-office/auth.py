"""Phone access over Wi-Fi, protected by a PIN.

The Mac itself (localhost) never needs to log in. Any other device on the network
is blocked unless "Phone access" is turned on in ⚙️ Settings, and then it needs the
PIN once (a signed cookie keeps it logged in for 30 days). Only the Mac can change
the PIN or turn phone access on/off.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import secrets
import socket
import time
from collections import defaultdict
from pathlib import Path

COOKIE = "bo_session"
MAX_AGE = 30 * 24 * 3600
PUBLIC = {"/login", "/manifest.webmanifest", "/icon.png"}
LOCAL = {"127.0.0.1", "::1", "localhost"}

_failures: dict[str, list[float]] = defaultdict(list)


class Phone:
    def __init__(self, data_dir: Path):
        self.dir = data_dir
        self.file = data_dir / "phone.json"

    def _load(self) -> dict:
        return json.loads(self.file.read_text()) if self.file.exists() else {"enabled": False}

    def _save(self, d: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(d))
        os.chmod(self.file, 0o600)

    @property
    def enabled(self) -> bool:
        d = self._load()
        return bool(d.get("enabled") and d.get("pin_hash"))

    def set(self, enabled: bool, pin: str | None) -> dict:
        d = self._load()
        if pin:
            salt = secrets.token_hex(8)
            d.update(salt=salt, pin_hash=hashlib.sha256((salt + pin).encode()).hexdigest(),
                     secret=secrets.token_hex(32))  # new PIN logs every phone out
        if enabled and not d.get("pin_hash"):
            raise ValueError("Maglagay muna ng PIN (4-8 numero).")
        d["enabled"] = enabled
        self._save(d)
        return self.status()

    def status(self) -> dict:
        return {"enabled": self.enabled, "has_pin": bool(self._load().get("pin_hash")), "url": phone_url()}

    def _secret(self) -> bytes:
        d = self._load()
        if not d.get("secret"):
            d["secret"] = secrets.token_hex(32)
            self._save(d)
        return d["secret"].encode()

    def check_pin(self, pin: str, ip: str) -> tuple[bool, str]:
        now = time.time()
        _failures[ip] = [t for t in _failures[ip] if now - t < 600]
        if len(_failures[ip]) >= 6:
            return False, "Masyadong maraming maling subok. Maghintay ng 10 minuto."
        d = self._load()
        if d.get("pin_hash") and hmac.compare_digest(hashlib.sha256((d["salt"] + pin).encode()).hexdigest(), d["pin_hash"]):
            _failures.pop(ip, None)
            return True, ""
        _failures[ip].append(now)
        time.sleep(1)
        return False, "Mali ang PIN."

    def make_token(self) -> str:
        exp = str(int(time.time()) + MAX_AGE)
        return f"{exp}.{hmac.new(self._secret(), exp.encode(), hashlib.sha256).hexdigest()}"

    def valid(self, token: str | None) -> bool:
        if not token or "." not in token:
            return False
        exp, sig = token.split(".", 1)
        good = hmac.new(self._secret(), exp.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, good) and exp.isdigit() and int(exp) > time.time()


def lan_ip() -> str:
    """The Mac's address on the Wi-Fi (no packets are sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def phone_url() -> str:
    return f"http://{lan_ip()}:{os.environ.get('BOT_OFFICE_PORT', '8800')}"


def is_local(host: str | None) -> bool:
    return (host or "") in LOCAL


def page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/icon.png"><meta name="theme-color" content="#15122a">
<style>body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0d0b1a;color:#e9e6ff;
font:16px system-ui,sans-serif}} form,.box{{background:#17132e;border:1px solid #3a3270;border-radius:18px;padding:26px;width:min(340px,88vw);
display:flex;flex-direction:column;gap:14px;text-align:center}} img{{width:72px;margin:0 auto;border-radius:18px}}
input{{background:#0d0b1a;color:#fff;border:1px solid #3a3270;border-radius:10px;padding:12px;font-size:22px;text-align:center;letter-spacing:.3em}}
button{{background:#ff6fae;color:#1a0d18;border:0;border-radius:10px;padding:12px;font-weight:800;font-size:16px}}
.err{{color:#ff8a8a;margin:0}} h1{{margin:0;font-size:20px}} p{{margin:0;color:#b9b3e6}}</style></head><body>{body}</body></html>"""


def login_page(error: str = "") -> str:
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return page("Bot Office: PIN", f"""<form method="post" action="/login"><img src="/icon.png" alt=""><h1>Evercrestcorp Compliance</h1>{err}
<input type="password" name="pin" inputmode="numeric" pattern="[0-9]*" placeholder="PIN" autocomplete="current-password" autofocus>
<button>Pasok 🔓</button></form>""")


def blocked_page() -> str:
    return page("Bot Office", """<div class="box"><img src="/icon.png" alt=""><h1>Naka-off ang phone access</h1>
<p>Sa Mac: buksan ang Bot Office → ⚙️ → Phone access → maglagay ng PIN at i-on.</p></div>""")


MANIFEST = """{"name": "Evercrestcorp Compliance", "short_name": "Evercrest", "start_url": "/", "display": "standalone",
 "background_color": "#0d0b1a", "theme_color": "#15122a", "icons": [{"src": "/icon.png", "sizes": "512x512", "type": "image/png"}]}"""


def icon_png(path: Path) -> Path:
    """A cute bot-face app icon, drawn once."""
    if path.exists():
        return path
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (512, 512), (21, 18, 42))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((96, 120, 416, 420), 70, fill=(255, 111, 174))
    d.line((256, 120, 256, 70), fill=(232, 232, 240), width=12)
    d.ellipse((232, 40, 280, 88), fill=(61, 220, 132))
    for x in (190, 322):
        d.ellipse((x - 34, 220, x + 34, 300), fill=(27, 21, 48))
        d.ellipse((x - 4, 232, x + 18, 254), fill=(255, 255, 255))
    d.arc((206, 290, 306, 360), 20, 160, fill=(27, 21, 48), width=12)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


def qr_png(text: str, path: Path) -> Path:
    import qrcode
    qrcode.make(text, box_size=8, border=2).save(path)
    return path
