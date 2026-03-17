"""
AnalysisManager - groups screenshots into time-based batches and processes them
with the configured AI provider (Ollama by default).

The manager runs in a background daemon thread and checks for new screenshots
every CHECK_INTERVAL_SECONDS seconds.
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Minimum age of the most-recent screenshot before we form a batch (avoids
# creating a batch that is still being actively filled).
BATCH_MATURITY_MINUTES = 10

# Minimum number of screenshots required to justify creating a batch.
MIN_SCREENSHOTS_PER_BATCH = 3

# Maximum time gap between consecutive screenshots inside one batch.
# A larger gap signals a new activity segment.
MAX_GAP_MINUTES = 5

# Maximum duration for a single batch (prevents very long cards).
MAX_BATCH_DURATION_HOURS = 1

# How often the analysis loop wakes up.
CHECK_INTERVAL_SECONDS = 60


class AnalysisManager:
    """Coordinates screenshot batching and AI analysis."""

    def __init__(self, storage, provider):
        self._storage = storage
        self._provider = provider
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._analysis_loop, daemon=True, name="AnalysisManager"
        )
        self._thread.start()
        logger.info("Analysis manager started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=CHECK_INTERVAL_SECONDS + 5)
        logger.info("Analysis manager stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _analysis_loop(self):
        while self._running:
            try:
                self._process_pending_screenshots()
                self._process_pending_batches()
            except Exception as exc:
                logger.error("Analysis loop error: %s", exc)

            deadline = time.monotonic() + CHECK_INTERVAL_SECONDS
            while self._running and time.monotonic() < deadline:
                time.sleep(1)

    # ------------------------------------------------------------------
    # Batching
    # ------------------------------------------------------------------

    def _process_pending_screenshots(self):
        """Group unprocessed screenshots into batches ready for analysis."""
        screenshots = self._storage.get_unprocessed_screenshots(limit=200)
        if len(screenshots) < MIN_SCREENSHOTS_PER_BATCH:
            return

        # Wait until the newest screenshot is at least BATCH_MATURITY_MINUTES old
        # so we do not split an ongoing activity mid-session.
        newest_time = datetime.fromisoformat(screenshots[-1]["captured_at"])
        if datetime.now() - newest_time < timedelta(minutes=BATCH_MATURITY_MINUTES):
            return

        groups = self._group_into_batches(screenshots)
        for group in groups:
            if len(group) < MIN_SCREENSHOTS_PER_BATCH:
                continue
            start_dt = datetime.fromisoformat(group[0]["captured_at"])
            end_dt = datetime.fromisoformat(group[-1]["captured_at"])

            # Skip groups whose newest screenshot is still "fresh".
            if datetime.now() - end_dt < timedelta(minutes=BATCH_MATURITY_MINUTES):
                continue

            ids = [s["id"] for s in group]
            batch_id = self._storage.create_batch(start_dt, end_dt, ids)
            logger.info(
                "Created batch %d with %d screenshots (%s – %s)",
                batch_id,
                len(ids),
                start_dt.strftime("%H:%M"),
                end_dt.strftime("%H:%M"),
            )

    @staticmethod
    def _group_into_batches(screenshots: List[dict]) -> List[List[dict]]:
        """Split *screenshots* into segments based on time gaps."""
        if not screenshots:
            return []

        max_gap = timedelta(minutes=MAX_GAP_MINUTES)
        max_duration = timedelta(hours=MAX_BATCH_DURATION_HOURS)

        groups: List[List[dict]] = []
        current: List[dict] = [screenshots[0]]

        for ss in screenshots[1:]:
            current_dt = datetime.fromisoformat(ss["captured_at"])
            prev_dt = datetime.fromisoformat(current[-1]["captured_at"])
            start_dt = datetime.fromisoformat(current[0]["captured_at"])

            if current_dt - prev_dt > max_gap or current_dt - start_dt > max_duration:
                groups.append(current)
                current = [ss]
            else:
                current.append(ss)

        if current:
            groups.append(current)
        return groups

    # ------------------------------------------------------------------
    # AI analysis
    # ------------------------------------------------------------------

    def _process_pending_batches(self):
        for batch in self._storage.get_pending_batches():
            if not self._running:
                break
            try:
                self._process_batch(batch["id"])
            except Exception as exc:
                logger.error("Failed to process batch %d: %s", batch["id"], exc)
                self._storage.update_batch_status(batch["id"], "failed")

    def _process_batch(self, batch_id: int):
        logger.info("Processing batch %d", batch_id)
        self._storage.update_batch_status(batch_id, "processing")

        screenshots = self._storage.get_screenshots_for_batch(batch_id)
        if not screenshots:
            self._storage.update_batch_status(batch_id, "failed")
            return

        if not self._provider.is_available():
            logger.warning(
                "Ollama is not reachable at %s – will retry later",
                self._provider.base_url,
            )
            self._storage.update_batch_status(batch_id, "pending")
            return

        # Sample at most 10 frames evenly spread across the batch to limit
        # the number of vision API calls (mirrors the original app's behaviour).
        stride = max(1, len(screenshots) // 10)
        sampled = screenshots[::stride]

        observations: List[str] = []
        for ss in sampled:
            image_path = Path(ss["file_path"])
            if not image_path.exists():
                continue
            desc = self._provider.describe_frame(image_path)
            if desc:
                observations.append(desc)
                logger.debug("Frame description: %s", desc[:100])

        if not observations:
            self._storage.update_batch_status(batch_id, "failed")
            return

        self._storage.save_observations(batch_id, observations)

        start_dt = datetime.fromisoformat(screenshots[0]["captured_at"])
        end_dt = datetime.fromisoformat(screenshots[-1]["captured_at"])

        summary = self._provider.generate_activity_summary(
            observations,
            start_dt.strftime("%H:%M"),
            end_dt.strftime("%H:%M"),
        )

        self._storage.save_timeline_card(
            batch_id=batch_id,
            title=summary["title"],
            summary=summary["summary"],
            start_time=start_dt,
            end_time=end_dt,
            category=summary["category"],
        )

        self._storage.update_batch_status(batch_id, "complete")
        logger.info("Batch %d complete – '%s'", batch_id, summary["title"])
