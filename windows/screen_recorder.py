"""
ScreenRecorder - captures screenshots on Windows using the `mss` library.

Screenshots are saved as JPEG files and registered in the database.
The recorder runs in a background daemon thread and pauses automatically
when the screen is locked.
"""

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

try:
    import mss
    import mss.tools

    HAS_MSS = True
except ImportError:  # pragma: no cover
    HAS_MSS = False
    logger.warning("mss is not installed. Run: pip install mss")

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:  # pragma: no cover
    HAS_PIL = False
    logger.warning("Pillow is not installed. Run: pip install Pillow")


def _is_screen_locked() -> bool:
    """Return True if the Windows workstation is currently locked."""
    try:
        import ctypes

        # GetForegroundWindow returns NULL (0) when the desktop is locked.
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        return hwnd == 0
    except Exception:
        return False


class ScreenRecorder:
    """Periodically captures a JPEG screenshot and registers it in *storage*."""

    # Maximum dimension (in pixels) to which screenshots are downscaled.
    _MAX_DIM = 1920

    def __init__(self, storage, interval_seconds: int = 10):
        self._storage = storage
        self.interval_seconds = interval_seconds
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._on_screenshot: Optional[Callable[[int, Path], None]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        """Start the background capture loop."""
        if self._running:
            return
        if not HAS_MSS or not HAS_PIL:
            logger.error(
                "Cannot start recorder: mss and/or Pillow are not installed."
            )
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop, daemon=True, name="ScreenRecorder"
        )
        self._thread.start()
        logger.info("Screen recorder started (interval=%ds)", self.interval_seconds)

    def stop(self):
        """Stop the capture loop and wait for the thread to finish."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=self.interval_seconds + 2)
        logger.info("Screen recorder stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def set_on_screenshot(self, callback: Callable[[int, Path], None]):
        """Register a callback invoked after each successful capture."""
        self._on_screenshot = callback

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _capture_loop(self):
        while self._running:
            try:
                if not _is_screen_locked():
                    self._capture_screenshot()
            except Exception as exc:
                logger.error("Capture loop error: %s", exc)

            # Sleep in small increments so we can react to stop() quickly.
            deadline = time.monotonic() + self.interval_seconds
            while self._running and time.monotonic() < deadline:
                time.sleep(0.5)

    def _capture_screenshot(self):
        output_path = self._storage.next_screenshot_path()

        with mss.mss() as sct:
            # monitors[0] is the "all monitors" virtual screen;
            # monitors[1] is the primary monitor.
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            raw = sct.grab(monitor)

        # Convert the raw BGRA buffer to an RGB PIL Image.
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        # Downscale very large screens (e.g. 4K) to keep file sizes reasonable.
        if img.width > self._MAX_DIM or img.height > self._MAX_DIM:
            ratio = min(self._MAX_DIM / img.width, self._MAX_DIM / img.height)
            img = img.resize(
                (int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS
            )

        img.save(str(output_path), "JPEG", quality=85)

        captured_at = datetime.now()
        screenshot_id = self._storage.save_screenshot(output_path, captured_at)

        logger.debug("Captured screenshot id=%d path=%s", screenshot_id, output_path.name)

        if self._on_screenshot:
            try:
                self._on_screenshot(screenshot_id, output_path)
            except Exception as exc:
                logger.warning("on_screenshot callback raised: %s", exc)
