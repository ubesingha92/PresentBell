#!/usr/bin/env python3
"""PresentBell: stdlib-only presentation timer with web remote.

Timer window: borderless always-on-top top-center countdown.
Web UI: LAN + localhost on port 8765 with per-run 6-digit password.
See PROJECT.md for settled decisions.
"""
from __future__ import annotations

import argparse
import hmac
import http.server
import json
import math
import secrets
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DEFAULT_PORT = 8765
DEFAULT_PRESENTATION_SECONDS = 600
DEFAULT_QA_SECONDS = 300
WARNING_SECONDS = 120
QA_WARNING_SECONDS = 120
WINDOW_WIDTH = 260
WINDOW_HEIGHT = 64
MIN_DURATION = 10
MAX_DURATION = 10800
BELL_FILENAME = "bell.mp3"
WAV_FALLBACK_FILENAME = "bell.wav"
CONFIG_FILENAME = "presentbell_config.json"

PHASE_LABELS = {
    "idle": "Ready",
    "presentation": "Presentation",
    "qa": "Q&A",
    "done": "Done",
}


def format_remaining(seconds: float) -> str:
    """Seconds -> MM:SS (H:MM:SS past an hour)."""
    total = max(0, int(math.ceil(seconds)))
    if total >= 3600:
        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60
        return f"{h}:{m:02d}:{s:02d}"
    return f"{total // 60:02d}:{total % 60:02d}"


def parse_duration(text: str) -> int | None:
    """MM:SS / H:MM:SS / plain seconds -> seconds, or None when invalid."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        if ":" in text:
            parts = text.split(":")
            if len(parts) == 2:
                m, s = parts
                total = int(m) * 60 + int(s)
            elif len(parts) == 3:
                h, m, s = parts
                total = int(h) * 3600 + int(m) * 60 + int(s)
            else:
                return None
        else:
            total = int(text)
    except ValueError:
        return None
    if total < MIN_DURATION or total > MAX_DURATION:
        return None
    return total


def generate_password() -> str:
    """Per-run 6-digit console-only password."""
    return f"{secrets.randbelow(900000) + 100000:06d}"


def get_lan_ips() -> list[str]:
    """Non-loopback IPv4 addresses for the console banner."""
    ips: list[str] = []
    try:
        _, _, addrlist = socket.gethostbyname_ex(socket.gethostname())
        for ip in addrlist:
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return ips


def get_monitors_ctypes() -> list[dict]:
    """Monitor rectangles via Win32; [] on failure."""
    try:
        import ctypes

        rects: list[tuple[int, int, int, int]] = []

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        try:
            functype = ctypes.WINFUNCTYPE
        except AttributeError:
            functype = ctypes.CFUNCTYPE
        MONITORENUMPROC = functype(
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(RECT),
            ctypes.c_void_p,
        )

        def _cb(hmon, hdc, lprc, data):
            r = lprc.contents
            rects.append((r.left, r.top, r.right, r.bottom))
            return 1

        cb = MONITORENUMPROC(_cb)
        ctypes.windll.user32.EnumDisplayMonitors(None, None, cb, 0)
        monitors = []
        for i, (left, top, right, bottom) in enumerate(rects):
            w, h = right - left, bottom - top
            monitors.append(
                {
                    "index": i,
                    "left": left,
                    "top": top,
                    "width": w,
                    "height": h,
                    "label": f"Display {i + 1} ({w}x{h} @ {left},{top})",
                }
            )
        return monitors
    except Exception:
        return []


def try_dpi_awareness() -> None:
    """Best-effort DPI awareness for crisp timer text."""
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            return
        except Exception:
            pass
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    except Exception:
        pass


# Bell audio: MP3 via Windows MCI, WAV/beep fallback.
MCI_ALIAS = "presentbell_bell"
_MCI_LOCK = threading.Lock()


def mci_send(command: str) -> int:
    """Send one MCI command string; returns 0 on success (Windows only)."""
    import ctypes

    mci = ctypes.windll.winmm.mciSendStringW
    mci.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p]
    mci.restype = ctypes.c_uint32
    return int(mci(command, None, 0, None))


_MCI_SLOTS = 8
_MCI_NEXT = 0


def play_mp3_mci(path: Path) -> bool:
    """Play an MP3 file via Windows MCI (async). Returns True if started.

    Rotates MCI aliases so rapid bells (e.g. double timeout) overlap
    instead of cutting each other off.
    """
    global _MCI_NEXT
    try:
        with _MCI_LOCK:
            alias = f"{MCI_ALIAS}_{_MCI_NEXT % _MCI_SLOTS}"
            _MCI_NEXT += 1
            mci_send(f"close {alias}")
            if mci_send(f'open "{path}" type mpegvideo alias {alias}') != 0:
                return False
            return mci_send(f"play {alias}") == 0
    except Exception:
        return False


def play_bell_async(bell_path: Path) -> None:
    def _run() -> None:
        if bell_path.is_file() and bell_path.suffix.lower() == ".mp3":
            if play_mp3_mci(bell_path):
                return
        try:
            import winsound

            try:
                wav = bell_path.with_name(WAV_FALLBACK_FILENAME)
                if bell_path.suffix.lower() == ".wav" and bell_path.is_file():
                    wav = bell_path
                if wav.is_file():
                    winsound.PlaySound(
                        str(wav),
                        winsound.SND_FILENAME | winsound.SND_ASYNC,
                    )
                    return
            except Exception:
                pass
            try:
                winsound.Beep(880, 600)
            except Exception:
                pass
        except ImportError:
            pass

    threading.Thread(target=_run, daemon=True).start()


# Shared timer state (thread-safe; web server and window meet here).
class BellState:
    """Countdown phases, settings, and visibility behind one lock."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.phase = "idle"
        self.presentation_duration = DEFAULT_PRESENTATION_SECONDS
        self.qa_duration = DEFAULT_QA_SECONDS
        self.warning_seconds = WARNING_SECONDS
        self.qa_warning_seconds = QA_WARNING_SECONDS
        self.ends_at = 0.0
        self.warning_fired = False
        self.qa_warning_fired = False
        self.pres_timeout_fired = False
        self.bell_pres_end = True
        self.bell_qa_end = True
        self.bell_pres_warning = True
        self.bell_qa_warning = True
        self.visible = True
        self.display_indices: list[int] = [0]
        self.monitors: list[dict] = []
        self.quit_requested = False

    def _remaining_locked(self) -> float:
        if self.phase == "presentation" or self.phase == "qa":
            return max(0.0, self.ends_at - time.monotonic())
        if self.phase == "idle":
            return float(self.presentation_duration)
        return 0.0

    def snapshot(self) -> dict:
        """Point-in-time copy for the web UI and timer window."""
        with self._lock:
            remaining = self._remaining_locked()
            return {
                "phase": self.phase,
                "phase_label": PHASE_LABELS.get(self.phase, self.phase),
                "remaining": remaining,
                "remaining_str": format_remaining(remaining),
                "visible": self.visible,
                "display_index": (
                    self.display_indices[0] if self.display_indices else 0
                ),
                "display_indices": list(self.display_indices),
                "displays": list(self.monitors),
                "presentation_duration": self.presentation_duration,
                "presentation_str": format_remaining(self.presentation_duration),
                "qa_duration": self.qa_duration,
                "qa_str": format_remaining(self.qa_duration),
                "warning_seconds": self.warning_seconds,
                "warning_str": format_remaining(self.warning_seconds),
                "qa_warning_seconds": self.qa_warning_seconds,
                "qa_warning_str": format_remaining(self.qa_warning_seconds),
                "bell_pres_end": self.bell_pres_end,
                "bell_qa_end": self.bell_qa_end,
                "bell_pres_warning": self.bell_pres_warning,
                "bell_qa_warning": self.bell_qa_warning,
            }

    def tick(self) -> tuple[dict, int]:
        """Advance timers; returns (snapshot, bells to ring). Never auto-starts Q&A."""
        bells = 0
        with self._lock:
            now = time.monotonic()
            if self.phase == "presentation":
                remaining = max(0.0, self.ends_at - now)
                if (
                    self.bell_pres_warning
                    and not self.warning_fired
                    and self.presentation_duration > self.warning_seconds
                    and 0.0 < remaining <= self.warning_seconds
                ):
                    self.warning_fired = True
                    bells += 1
                if remaining <= 0.0 and not self.pres_timeout_fired:
                    self.pres_timeout_fired = True
                    if self.bell_pres_end:
                        bells += 2
            elif self.phase == "qa":
                remaining = max(0.0, self.ends_at - now)
                if (
                    self.bell_qa_warning
                    and not self.qa_warning_fired
                    and self.qa_duration > self.qa_warning_seconds
                    and 0.0 < remaining <= self.qa_warning_seconds
                ):
                    self.qa_warning_fired = True
                    bells += 1
                if remaining <= 0.0:
                    self.phase = "done"
                    if self.bell_qa_end:
                        bells += 2
            return self.snapshot(), bells

    def start_presentation(self) -> bool:
        """Start (or restart) the presentation countdown with rearmed bells."""
        with self._lock:
            self.phase = "presentation"
            self.ends_at = time.monotonic() + self.presentation_duration
            self.warning_fired = False
            self.qa_warning_fired = False
            self.pres_timeout_fired = False
            return True

    def end_presentation_start_qa(self) -> bool:
        """Start (or restart) Q&A. Silent; bells fire only on timer expiry."""
        with self._lock:
            self.phase = "qa"
            self.ends_at = time.monotonic() + self.qa_duration
            self.qa_warning_fired = False
            return True

    def end_qa(self) -> bool:
        """Finish Q&A if running. Returns False in any other phase."""
        with self._lock:
            if self.phase != "qa":
                return False
            self.phase = "done"
            return True

    def set_visible(self, visible: bool) -> None:
        """Show or hide the window; the clock keeps running."""
        with self._lock:
            self.visible = visible

    def set_durations(
        self,
        pres: int | None,
        qa: int | None,
        warn: int | None = None,
        qa_warn: int | None = None,
    ) -> bool:
        """Update durations; None keeps the current value."""
        with self._lock:
            if pres is not None:
                self.presentation_duration = pres
            if qa is not None:
                self.qa_duration = qa
            if warn is not None:
                self.warning_seconds = warn
            if qa_warn is not None:
                self.qa_warning_seconds = qa_warn
            return True

    def set_bells(
        self,
        pres_end: bool | None = None,
        qa_end: bool | None = None,
        qa_warning: bool | None = None,
        pres_warning: bool | None = None,
    ) -> bool:
        """Enable/disable bells; None keeps the current value."""
        with self._lock:
            if pres_end is not None:
                self.bell_pres_end = pres_end
            if qa_end is not None:
                self.bell_qa_end = qa_end
            if qa_warning is not None:
                self.bell_qa_warning = qa_warning
            if pres_warning is not None:
                self.bell_pres_warning = pres_warning
            return True

    def reset_to_idle(self) -> None:
        """Back to idle with a full presentation clock and rearmed bells."""
        with self._lock:
            self.phase = "idle"
            self.ends_at = 0.0
            self.warning_fired = False
            self.qa_warning_fired = False
            self.pres_timeout_fired = False

    def settings_snapshot(self) -> dict:
        """Persistable subset of state for the config file."""
        with self._lock:
            return {
                "_comments": CONFIG_COMMENTS,
                "presentation_duration": self.presentation_duration,
                "qa_duration": self.qa_duration,
                "warning_seconds": self.warning_seconds,
                "qa_warning_seconds": self.qa_warning_seconds,
                "bell_pres_end": self.bell_pres_end,
                "bell_qa_end": self.bell_qa_end,
                "bell_pres_warning": self.bell_pres_warning,
                "bell_qa_warning": self.bell_qa_warning,
                "display_index": (
                    self.display_indices[0]
                    if len(self.display_indices) == 1
                    else list(self.display_indices)
                ),
            }

    def request_quit(self) -> None:
        """Ask the app to exit."""
        with self._lock:
            self.quit_requested = True

    def should_quit(self) -> bool:
        """True once Quit was requested."""
        with self._lock:
            return self.quit_requested


# Config file (presentbell_config.json): the only way to change settings.
CONFIG_COMMENTS = {
    "presentation_duration": "seconds (600 = 10:00, range 10-10800)",
    "qa_duration": "seconds (300 = 5:00, range 10-10800)",
    "warning_seconds": "presentation remaining-mark bell at this many seconds left",
    "qa_warning_seconds": "Q&A remaining-mark bell at this many seconds left",
    "bell_pres_end": "true = double bell at presentation timeout",
    "bell_qa_end": "true = double bell at Q&A timeout",
    "bell_pres_warning": "true = bell at presentation remaining mark",
    "bell_qa_warning": "true = bell at Q&A remaining mark",
    "display_index": "display(s) for the timer: 0-based int, or list like [0, 1] to mirror",
}


def load_config(path: Path) -> dict:
    """Read config JSON; {} when missing or broken."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_config(state: BellState, data: dict) -> None:
    """Copy validated config values into state; skips anything invalid."""
    def _dur(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            total = int(value)
            if total < MIN_DURATION or total > MAX_DURATION:
                return None
            return total
        if isinstance(value, str):
            return parse_duration(value)
        return None

    def _flag(value: object, default: bool) -> bool:
        return value if isinstance(value, bool) else default

    state.set_durations(
        _dur(data.get("presentation_duration")),
        _dur(data.get("qa_duration")),
        _dur(data.get("warning_seconds")),
        _dur(data.get("qa_warning_seconds")),
    )
    state.set_bells(
        _flag(data.get("bell_pres_end"), True),
        _flag(data.get("bell_qa_end"), True),
        _flag(data.get("bell_qa_warning"), True),
        _flag(data.get("bell_pres_warning"), True),
    )
    idx = data.get("display_index")
    if isinstance(idx, int) and not isinstance(idx, bool) and idx >= 0:
        state.display_indices = [idx]
    elif isinstance(idx, list):
        cleaned = [
            i
            for i in dict.fromkeys(idx)
            if isinstance(i, int) and not isinstance(i, bool) and i >= 0
        ]
        if cleaned:
            state.display_indices = cleaned


def save_config(state: BellState, path: Path) -> None:
    """Atomically persist settings plus the guide-comment block."""
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(state.settings_snapshot(), indent=2), encoding="utf-8"
        )
        tmp.replace(path)
    except OSError:
        pass


def ensure_config(state: BellState, path: Path) -> bool:
    """Load settings from path, or generate a commented default file.

    Returns True when a new file was generated.
    """
    if path.is_file():
        apply_config(state, load_config(path))
        return False
    save_config(state, path)
    return True


# Web pages (single-file templates; MAIN_HTML is served as-is, no .format).
LOGIN_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PresentBell login</title>
<style>
body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:24px;background:#fff;color:#111}}
main{{max-width:420px;margin:0 auto}}
input{{font-size:20px;padding:8px;width:100%;box-sizing:border-box}}
button{{font-size:18px;padding:10px 16px;margin-top:12px}}
.err{{color:#a00}}
</style></head><body><main>
<h1>PresentBell</h1>
<p>Enter the 6-digit password shown in the operator console.</p>
{err}
<form method="post" action="/login">
<input type="password" name="password" inputmode="numeric" autocomplete="off" maxlength="6" autofocus>
<button type="submit">Sign in</button>
</form></main></body></html>"""

MAIN_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PresentBell</title>
<style>
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:16px;background:#fff;color:#111}
main{max-width:640px;margin:0 auto;padding-bottom:60px}
h1{font-size:24px;margin:0 0 12px}
h2{font-size:17px;margin:16px 0 8px}
.status{border:1px solid #ccc;padding:16px;margin-bottom:16px;text-align:center}
.status .phase{font-size:17px;font-weight:bold}
.status .time{font-size:56px;font-variant-numeric:tabular-nums;line-height:1.1}
.status .meta{font-size:14px;color:#444;margin-top:6px}
.row{margin:12px 0}
.btnrow{display:flex;flex-wrap:wrap;gap:8px}
.btnrow button{flex:1 1 140px}
button{font-size:16px;padding:10px 14px;margin:0;min-height:44px}
label{display:block;margin:8px 0}
hr{border:none;border-top:1px solid #ccc;margin:12px 0}
footer{position:fixed;left:0;right:0;bottom:0;background:#fff;border-top:1px solid #ccc;font-size:13px;color:#555;padding:14px 12px;text-align:center}
</style></head><body><main>
<h1>PresentBell</h1>
<div class="status">
<div class="phase" id="phase">-</div>
<div class="time" id="remaining">--:--</div>
<div class="meta" id="meta">-</div>
</div>
<div class="row btnrow">
<button onclick="post('/api/start')">Presentation Start</button>
<button onclick="post('/api/end_presentation')">Presentation End (Q&amp;A Start)</button>
<button onclick="post('/api/end_qa')">Q&amp;A End</button>
<button onclick="post('/api/reset')">Reset</button>
</div>
<div class="row btnrow">
<button onclick="post('/api/show')">Show</button>
<button onclick="post('/api/hide')">Hide</button>
<button onclick="if(confirm('Quit PresentBell?'))post('/api/quit')">Quit</button>
</div>
<footer>Developed by Chanaka Chathuranga · <a href="https://github.com/ubesingha92/PresentBell" target="_blank" rel="noopener">GitHub repo</a></footer>
<script>
async function fetchStatus(){
  const r = await fetch('/api/status', {credentials:'same-origin'});
  if(!r.ok){ location.reload(); return; }
  const s = await r.json();
  document.getElementById('phase').textContent = s.phase_label;
  document.getElementById('remaining').textContent = s.remaining_str;
  document.getElementById('meta').textContent =
    (s.visible ? 'visible' : 'hidden') + ' | display ' +
    s.display_indices.map((i)=>i+1).join(',') + ' of ' + s.displays.length;
}
async function post(path, body){
  await fetch(path, {method:'POST', credentials:'same-origin',
    headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body: body || ''});
  fetchStatus();
}
fetchStatus();
setInterval(fetchStatus, 1000);
</script></main></body></html>"""


# HTTP server (threaded, single cookie authed by per-run password).
class PresentBellServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """HTTP server carrying shared state and the run password."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, handler, state: BellState, password: str):
        super().__init__(addr, handler)
        self.state = state
        self.password = password


class Handler(http.server.BaseHTTPRequestHandler):
    """Routes login, status, transport controls, and quit."""

    server: PresentBellServer

    def log_message(self, fmt, *args):
        # Request logging disabled; the console shows only the startup banner.
        return

    def _cookies(self) -> dict[str, str]:
        raw = self.headers.get("Cookie", "")
        out: dict[str, str] = {}
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                out[k] = v
        return out

    def _authed(self) -> bool:
        got = self._cookies().get("pb_auth", "")
        return bool(got) and hmac.compare_digest(got, self.server.password)

    def _send_html(self, body: str, status: int = 200) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj: dict, status: int = 200) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_form(self) -> dict[str, str]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        parsed = parse_qs(raw, keep_blank_values=True)
        return {k: v[0] if v else "" for k, v in parsed.items()}

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/status":
            if not self._authed():
                self._send_json({"error": "auth"}, 401)
                return
            self._send_json(self.server.state.snapshot())
            return
        if path in ("/", "/index.html"):
            if not self._authed():
                self._send_html(LOGIN_HTML.format(err=""))
                return
            self._send_html(MAIN_HTML)
            return
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/login":
            form = self._read_form()
            if hmac.compare_digest(form.get("password", ""), self.server.password):
                self.send_response(303)
                self.send_header(
                    "Set-Cookie", f"pb_auth={self.server.password}; Path=/; HttpOnly"
                )
                self.send_header("Location", "/")
                self.end_headers()
            else:
                self._send_html(
                    LOGIN_HTML.format(err='<p class="err">Wrong password.</p>'), 401
                )
            return
        if not self._authed():
            self._send_json({"error": "auth"}, 401)
            return
        form = self._read_form()
        state = self.server.state
        if path == "/api/start":
            state.start_presentation()
            self._send_json({"ok": True})
        elif path == "/api/end_presentation":
            state.end_presentation_start_qa()
            self._send_json({"ok": True})
        elif path == "/api/end_qa":
            state.end_qa()
            self._send_json({"ok": True})
        elif path == "/api/reset":
            state.reset_to_idle()
            self._send_json({"ok": True})
        elif path == "/api/show":
            state.set_visible(True)
            self._send_json({"ok": True})
        elif path == "/api/hide":
            state.set_visible(False)
            self._send_json({"ok": True})
        elif path == "/api/quit":
            state.request_quit()
            self._send_json({"ok": True})
        else:
            self.send_error(404)


def app_dir() -> Path:
    """Writable app dir: exe folder when frozen, script folder otherwise."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(name: str) -> Path:
    """Bundled read-only file (PyInstaller MEIPASS-aware)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / name
    return Path(__file__).with_name(name)


BELL_PATH = resource_path(BELL_FILENAME)
CONFIG_PATH = app_dir() / CONFIG_FILENAME


# Timer window (tkinter): borderless always-on-top, mirrored per config.
def top_center_geometry(monitor: dict) -> str:
    """WxH geometry string pinned to a monitor's top-center."""
    x = monitor["left"] + max(0, (monitor["width"] - WINDOW_WIDTH) // 2)
    y = monitor["top"]
    return f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{x}+{y}"


def resolve_display_indices(indices: list[int], n_monitors: int) -> list[int]:
    """Dedupe and clamp wanted display indices; always returns >= 1."""
    if n_monitors <= 0:
        return [0]
    out = [i for i in dict.fromkeys(indices) if 0 <= i < n_monitors]
    return out or [0]


def run_timer_window(state: BellState) -> None:
    """Countdown window(s); ticks state and rings bells until Quit."""
    import tkinter as tk
    import tkinter.font as tkfont

    root = tk.Tk()
    root.title("PresentBell")
    root.configure(bg="white")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.resizable(False, False)

    phase_font = tkfont.Font(size=9)
    time_font = tkfont.Font(size=32, weight="bold")

    def make_labels(parent):
        pv = tk.StringVar(value="Ready")
        tv = tk.StringVar(value=format_remaining(DEFAULT_PRESENTATION_SECONDS))
        tk.Label(
            parent, textvariable=pv, bg="white", fg="black", font=phase_font
        ).pack(pady=(2, 0))
        tk.Label(
            parent, textvariable=tv, bg="white", fg="black", font=time_font
        ).pack()
        return pv, tv

    phase_var, time_var = make_labels(root)

    if not state.monitors:
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        state.monitors = [
            {
                "index": 0,
                "left": 0,
                "top": 0,
                "width": sw,
                "height": sh,
                "label": f"Display 1 ({sw}x{sh})",
            }
        ]

    shown = True
    applied: list[int] = []
    extra: dict[int, tuple] = {}

    def make_window() -> tk.Toplevel:
        top = tk.Toplevel(root)
        top.title("PresentBell")
        top.configure(bg="white")
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.resizable(False, False)
        if not shown:
            top.withdraw()
        return top

    def sync_windows(idxs: list[int]) -> None:
        for i in [k for k in extra if k not in idxs]:
            try:
                extra[i][0].destroy()
            except Exception:
                pass
            del extra[i]
        for i in idxs:
            if i != idxs[0] and i not in extra:
                top = make_window()
                extra[i] = (top,) + make_labels(top)
        root.geometry(top_center_geometry(state.monitors[idxs[0]]))
        for i, (top, _pv, _tv) in extra.items():
            top.geometry(top_center_geometry(state.monitors[i]))

    def all_vars():
        yield phase_var, time_var
        for _top, pv, tv in extra.values():
            yield pv, tv

    def set_shown(visible: bool) -> None:
        wins = [root] + [t for t, _p, _t in extra.values()]
        for win in wins:
            try:
                if visible:
                    win.deiconify()
                    win.attributes("-topmost", True)
                else:
                    win.withdraw()
            except Exception:
                pass

    applied = resolve_display_indices(state.display_indices, len(state.monitors))
    sync_windows(applied)

    def update() -> None:
        nonlocal shown, applied
        if state.should_quit():
            try:
                root.destroy()
            except Exception:
                pass
            return
        snap, bells = state.tick()
        for _ in range(bells):
            play_bell_async(BELL_PATH)
        for pv, tv in all_vars():
            pv.set(snap["phase_label"])
            tv.set(snap["remaining_str"])
        idxs = resolve_display_indices(snap["display_indices"], len(state.monitors))
        if idxs != applied:
            applied = idxs
            sync_windows(idxs)
        if snap["visible"] and not shown:
            set_shown(True)
            sync_windows(applied)
            shown = True
        elif not snap["visible"] and shown:
            set_shown(False)
            shown = False
        root.after(200, update)

    root.after(200, update)
    root.mainloop()


# Entry point: config, web server, then the timer window.
def main() -> int:
    """Boot the server and timer window; return the exit code."""
    parser = argparse.ArgumentParser(description="PresentBell presentation timer")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    try_dpi_awareness()
    state = BellState()
    state.monitors = get_monitors_ctypes()
    config_created = ensure_config(state, CONFIG_PATH)

    password = generate_password()
    server = PresentBellServer(("0.0.0.0", args.port), Handler, state, password)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    lan_ips = get_lan_ips()
    print("PresentBell running (stdlib only).")
    print(f"Local:  http://localhost:{args.port}")
    for ip in lan_ips:
        print(f"LAN:    http://{ip}:{args.port}")
    print(f"Password (console only, per run): {password}")
    print("Timer: top-center of selected display. Web Quit exits.")
    if config_created:
        print(
            f"Settings: {CONFIG_FILENAME} created with defaults"
            " (edit while stopped to change)."
        )
    else:
        print(
            f"Settings: {CONFIG_FILENAME} loaded"
            " (edit while stopped to change durations/bells)."
        )
    if not BELL_PATH.is_file():
        print(
            f"Warning: {BELL_FILENAME} missing;"
            f" {WAV_FALLBACK_FILENAME} fallback or beep will be used."
        )
    print(f"Displays found: {len(state.monitors) if state.monitors else 1} (picker in web UI).")

    try:
        run_timer_window(state)
    except KeyboardInterrupt:
        state.request_quit()
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
    print("PresentBell exited.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
