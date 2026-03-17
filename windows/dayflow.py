"""
Dayflow for Windows – main entry point.

Starts the screen recorder, analysis manager, and web UI server.
A system-tray icon is shown when pystray + Pillow are available.
The web UI is opened in the default browser automatically on first launch.

Usage
-----
  python dayflow.py            # start with recording enabled
  python dayflow.py --no-tray  # run without tray icon (headless / testing)
"""

import argparse
import logging
import os
import signal
import sys
import threading
import time
import webbrowser
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the windows/ directory is on the Python path so that imports work
# regardless of where the user calls this script from.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from analysis_manager import AnalysisManager
from ollama_provider import DEFAULT_MODEL, DEFAULT_OLLAMA_URL, OllamaProvider
from screen_recorder import ScreenRecorder
from storage_manager import StorageManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dayflow")

WEB_HOST = "127.0.0.1"
WEB_PORT = 5000


# ---------------------------------------------------------------------------
# Tray icon (optional – requires pystray + Pillow)
# ---------------------------------------------------------------------------

def _build_tray_image():
    """Create a simple coloured square as the tray icon."""
    from PIL import Image, ImageDraw

    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Dark background
    draw.ellipse([2, 2, size - 2, size - 2], fill="#1a1d27")
    # Accent ring
    draw.ellipse([6, 6, size - 6, size - 6], outline="#4f8ef7", width=4)
    # Small clock hands (simplified)
    cx, cy = size // 2, size // 2
    draw.line([(cx, cy), (cx, cy - 16)], fill="#4f8ef7", width=3)
    draw.line([(cx, cy), (cx + 10, cy + 5)], fill="#4f8ef7", width=3)
    return img


def _start_tray(recorder, open_ui_fn, stop_all_fn):
    """Run the system-tray icon in the current thread (blocking)."""
    try:
        import pystray
    except ImportError:
        logger.info("pystray not installed – skipping tray icon")
        return

    icon_image = _build_tray_image()

    def on_open(_icon, _item):
        open_ui_fn()

    def on_toggle_recording(_icon, _item):
        if recorder.is_running:
            recorder.stop()
        else:
            recorder.start()

    def on_quit(_icon, _item):
        _icon.stop()
        stop_all_fn()

    menu = pystray.Menu(
        pystray.MenuItem("Open Dayflow", on_open, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "Recording",
            pystray.Menu(
                pystray.MenuItem(
                    "Start",
                    lambda i, it: recorder.start(),
                ),
                pystray.MenuItem(
                    "Stop",
                    lambda i, it: recorder.stop(),
                ),
            ),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )

    icon = pystray.Icon("Dayflow", icon_image, "Dayflow", menu)
    icon.run()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Dayflow for Windows")
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Disable the system-tray icon (useful for headless / CI environments)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the browser automatically on startup",
    )
    args = parser.parse_args()

    logger.info("Starting Dayflow for Windows")
    logger.info("Data directory: %s", _get_data_dir())

    # ------------------------------------------------------------------
    # Initialise core components
    # ------------------------------------------------------------------
    storage  = StorageManager()
    provider = OllamaProvider(
        base_url=storage.get_setting("ollama_url",  DEFAULT_OLLAMA_URL),
        model   =storage.get_setting("ollama_model", DEFAULT_MODEL),
    )
    recorder = ScreenRecorder(
        storage,
        interval_seconds=int(storage.get_setting("capture_interval", "10")),
    )
    analysis = AnalysisManager(storage, provider)

    # ------------------------------------------------------------------
    # Start background services
    # ------------------------------------------------------------------
    recording_enabled = storage.get_setting("recording_enabled", "true") == "true"
    if recording_enabled:
        recorder.start()
    analysis.start()

    # ------------------------------------------------------------------
    # Build Flask app (import here to avoid circular imports)
    # ------------------------------------------------------------------
    # Add web_ui package to path
    web_ui_dir = _HERE / "web_ui"
    if str(web_ui_dir) not in sys.path:
        sys.path.insert(0, str(web_ui_dir))

    from web_ui.server import create_app

    flask_app = create_app(storage, recorder, analysis, provider)

    # ------------------------------------------------------------------
    # Helpers for graceful shutdown
    # ------------------------------------------------------------------
    _stop_event = threading.Event()

    def stop_all():
        logger.info("Shutting down Dayflow…")
        recorder.stop()
        analysis.stop()
        _stop_event.set()
        # Give Flask a moment to finish serving pending requests, then exit.
        threading.Timer(1.0, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()

    def open_ui():
        webbrowser.open(f"http://{WEB_HOST}:{WEB_PORT}")

    signal.signal(signal.SIGINT,  lambda *_: stop_all())
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    # ------------------------------------------------------------------
    # Open browser (optional, slightly delayed so Flask is ready)
    # ------------------------------------------------------------------
    if not args.no_browser:
        threading.Timer(1.5, open_ui).start()

    # ------------------------------------------------------------------
    # System tray (runs in a separate thread on Windows)
    # ------------------------------------------------------------------
    if not args.no_tray:
        tray_thread = threading.Thread(
            target=_start_tray,
            args=(recorder, open_ui, stop_all),
            daemon=True,
            name="TrayIcon",
        )
        tray_thread.start()

    # ------------------------------------------------------------------
    # Flask server (blocking – runs in the main thread)
    # ------------------------------------------------------------------
    logger.info("Web UI available at http://%s:%d", WEB_HOST, WEB_PORT)
    try:
        flask_app.run(
            host=WEB_HOST,
            port=WEB_PORT,
            debug=False,
            use_reloader=False,
        )
    except SystemExit:
        pass
    except Exception as exc:
        logger.error("Flask server error: %s", exc)
    finally:
        stop_all()


def _get_data_dir() -> str:
    """Return the data directory path as a string (for display only)."""
    import os
    return os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), "Dayflow"
    )


if __name__ == "__main__":
    main()
