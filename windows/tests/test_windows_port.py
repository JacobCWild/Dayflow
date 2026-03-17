"""
Unit tests for the Dayflow Windows port.

These tests cover the core non-UI components and can be run on any platform
without a display or Ollama instance:

    cd windows
    python -m pytest tests/ -v

or simply:

    python -m unittest discover -s tests
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Make sure the windows/ package is importable regardless of CWD.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent.parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


# ===========================================================================
# StorageManager tests
# ===========================================================================

class TestStorageManager(unittest.TestCase):
    """Test the SQLite storage layer using a temporary directory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # Redirect AppData to the temp dir so we don't touch real user data.
        self._orig_appdata = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name

        from storage_manager import StorageManager
        self.storage = StorageManager()

    def tearDown(self):
        if self._orig_appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._orig_appdata
        self._tmp.cleanup()

    # ── screenshots ─────────────────────────────────────────────────────

    def test_save_and_fetch_screenshot(self):
        path = self.storage.next_screenshot_path()
        path.touch()                         # create a dummy file
        sid = self.storage.save_screenshot(path, datetime.now())
        self.assertIsInstance(sid, int)
        self.assertGreater(sid, 0)

        unprocessed = self.storage.get_unprocessed_screenshots()
        self.assertEqual(len(unprocessed), 1)
        self.assertEqual(unprocessed[0]["id"], sid)

    def test_unprocessed_excludes_batched(self):
        path = self.storage.next_screenshot_path()
        path.touch()
        sid = self.storage.save_screenshot(path, datetime.now())

        # Assign the screenshot to a batch.
        now = datetime.now()
        self.storage.create_batch(now, now, [sid])

        self.assertEqual(self.storage.get_unprocessed_screenshots(), [])

    # ── batches ──────────────────────────────────────────────────────────

    def test_create_batch_and_fetch_pending(self):
        now = datetime.now()
        path = self.storage.next_screenshot_path()
        path.touch()
        sid = self.storage.save_screenshot(path, now)

        batch_id = self.storage.create_batch(now, now, [sid])
        self.assertIsInstance(batch_id, int)

        pending = self.storage.get_pending_batches()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["id"], batch_id)

    def test_update_batch_status(self):
        now = datetime.now()
        path = self.storage.next_screenshot_path()
        path.touch()
        sid = self.storage.save_screenshot(path, now)
        batch_id = self.storage.create_batch(now, now, [sid])

        self.storage.update_batch_status(batch_id, "complete")
        pending = self.storage.get_pending_batches()
        self.assertEqual(pending, [])

    # ── timeline cards ───────────────────────────────────────────────────

    def test_save_and_get_timeline_card(self):
        now = datetime.now()
        path = self.storage.next_screenshot_path()
        path.touch()
        sid = self.storage.save_screenshot(path, now)
        batch_id = self.storage.create_batch(now, now, [sid])

        self.storage.save_timeline_card(
            batch_id=batch_id,
            title="Writing tests",
            summary="Unit-testing the storage layer.",
            start_time=now,
            end_time=now + timedelta(minutes=10),
            category="development",
        )

        cards = self.storage.get_timeline_cards(now)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["title"], "Writing tests")
        self.assertEqual(cards[0]["category"], "development")

    def test_4am_day_boundary(self):
        """Cards before 4 AM belong to the previous calendar day's timeline."""
        late_night = datetime.now().replace(hour=2, minute=0, second=0, microsecond=0)
        if late_night > datetime.now():
            # Already past 2 AM; adjust to yesterday at 2 AM.
            late_night -= timedelta(days=1)

        path = self.storage.next_screenshot_path()
        path.touch()
        sid = self.storage.save_screenshot(path, late_night)
        batch_id = self.storage.create_batch(late_night, late_night, [sid])
        self.storage.save_timeline_card(
            batch_id=batch_id,
            title="Night owl card",
            summary="",
            start_time=late_night,
            end_time=late_night + timedelta(minutes=5),
        )

        # Querying for the same night (< 4 AM) should find it.
        cards = self.storage.get_timeline_cards(late_night)
        titles = [c["title"] for c in cards]
        self.assertIn("Night owl card", titles)

        # Querying for the next calendar day (daytime) should NOT find it.
        next_day = late_night + timedelta(hours=20)
        cards_next = self.storage.get_timeline_cards(next_day)
        self.assertNotIn("Night owl card", [c["title"] for c in cards_next])

    # ── settings ─────────────────────────────────────────────────────────

    def test_settings_round_trip(self):
        self.storage.set_setting("ollama_model", "llava-llama3")
        self.assertEqual(self.storage.get_setting("ollama_model"), "llava-llama3")

    def test_settings_default(self):
        val = self.storage.get_setting("nonexistent_key", "fallback")
        self.assertEqual(val, "fallback")


# ===========================================================================
# OllamaProvider tests (no real network calls)
# ===========================================================================

class TestOllamaProvider(unittest.TestCase):

    def setUp(self):
        from ollama_provider import OllamaProvider
        self.provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="llava",
        )

    def test_is_available_false_when_unreachable(self):
        """is_available() must return False when Ollama is not running."""
        with patch("requests.get", side_effect=ConnectionError("refused")):
            self.assertFalse(self.provider.is_available())

    def test_is_available_true_on_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("requests.get", return_value=mock_resp):
            self.assertTrue(self.provider.is_available())

    def test_get_available_models(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [{"name": "llava:latest"}, {"name": "llava-llama3:latest"}]
        }
        with patch("requests.get", return_value=mock_resp):
            models = self.provider.get_available_models()
        self.assertIn("llava:latest", models)

    def test_describe_frame_returns_none_on_missing_file(self):
        result = self.provider.describe_frame(Path("/nonexistent/file.jpg"))
        self.assertIsNone(result)

    def test_describe_frame_calls_ollama(self):
        """describe_frame() should POST to /api/chat with image data."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": "Writing code in VS Code."}
        }

        # Create a minimal JPEG in a temp file.
        import io
        from PIL import Image
        img = Image.new("RGB", (1, 1), color=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            tf.write(buf.getvalue())
            tmp_path = Path(tf.name)

        try:
            with patch("requests.post", return_value=mock_resp) as mock_post:
                result = self.provider.describe_frame(tmp_path)

            self.assertEqual(result, "Writing code in VS Code.")
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            payload = call_args[1].get("json") or call_args[0][1]
            self.assertEqual(payload["model"], "llava")
            self.assertIn("images", payload["messages"][0])
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_generate_activity_summary_parses_json(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {
                "content": json.dumps(
                    {
                        "title": "Coding in Python",
                        "summary": "The user was writing unit tests.",
                        "category": "development",
                    }
                )
            }
        }
        with patch("requests.post", return_value=mock_resp):
            result = self.provider.generate_activity_summary(
                ["Writing tests in VS Code"], "09:00", "09:10"
            )
        self.assertEqual(result["title"], "Coding in Python")
        self.assertEqual(result["category"], "development")

    def test_generate_activity_summary_handles_markdown_fences(self):
        """The provider should strip ```json ... ``` fences some models add."""
        raw = '```json\n{"title": "A", "summary": "B", "category": "work"}\n```'
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"content": raw}}
        with patch("requests.post", return_value=mock_resp):
            result = self.provider.generate_activity_summary(["x"], "10:00", "10:10")
        self.assertEqual(result["title"], "A")

    def test_generate_activity_summary_fallback_on_bad_json(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"content": "Not JSON at all"}}
        with patch("requests.post", return_value=mock_resp):
            result = self.provider.generate_activity_summary(["x"], "10:00", "10:10")
        self.assertEqual(result["title"], "Activity")

    def test_call_ollama_retries_on_failure(self):
        """_call_ollama should retry up to max_retries times."""
        self.provider.max_retries = 3
        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200
        mock_resp_ok.json.return_value = {"message": {"content": "ok"}}

        mock_resp_fail = MagicMock()
        mock_resp_fail.status_code = 500
        mock_resp_fail.text = "internal error"

        with patch("requests.post", side_effect=[mock_resp_fail, mock_resp_ok]) as mock_post:
            with patch("time.sleep"):          # skip real sleep in tests
                result = self.provider._call_ollama([{"role": "user", "content": "hi"}])

        self.assertEqual(result, "ok")
        self.assertEqual(mock_post.call_count, 2)


# ===========================================================================
# AnalysisManager batching logic tests
# ===========================================================================

class TestAnalysisManagerBatching(unittest.TestCase):

    def _make_screenshot(self, ts: datetime) -> dict:
        return {"id": id(ts), "captured_at": ts.isoformat(), "file_path": "/fake.jpg"}

    def test_group_single_batch(self):
        from analysis_manager import AnalysisManager

        now = datetime(2024, 1, 15, 9, 0, 0)
        screenshots = [
            self._make_screenshot(now + timedelta(seconds=10 * i))
            for i in range(20)
        ]
        groups = AnalysisManager._group_into_batches(screenshots)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 20)

    def test_group_splits_on_large_gap(self):
        from analysis_manager import AnalysisManager

        now = datetime(2024, 1, 15, 9, 0, 0)
        batch_a = [self._make_screenshot(now + timedelta(seconds=10 * i)) for i in range(5)]
        # 10-minute gap
        gap_start = now + timedelta(minutes=11)
        batch_b = [self._make_screenshot(gap_start + timedelta(seconds=10 * i)) for i in range(5)]

        groups = AnalysisManager._group_into_batches(batch_a + batch_b)
        self.assertEqual(len(groups), 2)

    def test_group_empty(self):
        from analysis_manager import AnalysisManager
        self.assertEqual(AnalysisManager._group_into_batches([]), [])

    def test_group_single_item(self):
        from analysis_manager import AnalysisManager
        ss = [self._make_screenshot(datetime.now())]
        groups = AnalysisManager._group_into_batches(ss)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 1)


# ===========================================================================
# Flask web API tests
# ===========================================================================

class TestWebAPI(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_appdata = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name

        from storage_manager import StorageManager
        from ollama_provider import OllamaProvider
        from screen_recorder import ScreenRecorder
        from analysis_manager import AnalysisManager
        from web_ui.server import create_app

        storage  = StorageManager()
        provider = OllamaProvider()
        recorder = ScreenRecorder(storage)
        analysis = AnalysisManager(storage, provider)

        flask_app = create_app(storage, recorder, analysis, provider)
        flask_app.config["TESTING"] = True
        self.client  = flask_app.test_client()
        self.storage = storage

    def tearDown(self):
        if self._orig_appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._orig_appdata
        self._tmp.cleanup()

    def test_index_returns_200(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)

    def test_settings_page_returns_200(self):
        resp = self.client.get("/settings")
        self.assertEqual(resp.status_code, 200)

    def test_api_status(self):
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("recording", data)
        self.assertIn("ollama_available", data)

    def test_api_timeline_today(self):
        resp = self.client.get("/api/timeline")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("cards", data)
        self.assertIn("date", data)

    def test_api_timeline_specific_date(self):
        resp = self.client.get("/api/timeline?date=2024-01-15")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["date"], "2024-01-15")

    def test_api_timeline_invalid_date(self):
        resp = self.client.get("/api/timeline?date=not-a-date")
        self.assertEqual(resp.status_code, 400)

    def test_api_settings_get(self):
        resp = self.client.get("/api/settings")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("ollama_url", data)
        self.assertIn("ollama_model", data)

    def test_api_settings_post(self):
        payload = {
            "ollama_url":       "http://localhost:11434",
            "ollama_model":     "llava-llama3",
            "capture_interval": 15,
            "max_storage_gb":   10.0,
        }
        resp = self.client.post(
            "/api/settings",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

        # Verify persistence
        saved_model = self.storage.get_setting("ollama_model")
        self.assertEqual(saved_model, "llava-llama3")

    def test_api_models(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"name": "llava:latest"}]}
        with patch("requests.get", return_value=mock_resp):
            resp = self.client.get("/api/models")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("llava:latest", data["models"])

    def test_api_timeline_shows_saved_card(self):
        """A saved timeline card must appear in the API response for its date."""
        now = datetime.now()
        path = self.storage.next_screenshot_path()
        path.touch()
        sid = self.storage.save_screenshot(path, now)
        batch_id = self.storage.create_batch(now, now, [sid])
        self.storage.save_timeline_card(
            batch_id=batch_id,
            title="Test card",
            summary="A summary.",
            start_time=now,
            end_time=now + timedelta(minutes=5),
            category="work",
        )

        resp = self.client.get(f"/api/timeline?date={now.strftime('%Y-%m-%d')}")
        data = resp.get_json()
        titles = [c["title"] for c in data["cards"]]
        self.assertIn("Test card", titles)


if __name__ == "__main__":
    unittest.main()
