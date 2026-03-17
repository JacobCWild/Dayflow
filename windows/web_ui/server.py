"""
Flask web server that provides the Dayflow UI and REST API endpoints.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from flask import Flask, jsonify, render_template, request

logger = logging.getLogger(__name__)


def create_app(storage, recorder, analysis_manager, provider):
    """
    Build and return the Flask application.

    Parameters
    ----------
    storage          : StorageManager instance
    recorder         : ScreenRecorder instance
    analysis_manager : AnalysisManager instance
    provider         : OllamaProvider instance
    """
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # ------------------------------------------------------------------ #
    # Page routes                                                          #
    # ------------------------------------------------------------------ #

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/settings")
    def settings():
        return render_template(
            "settings.html",
            ollama_url=storage.get_setting("ollama_url", "http://localhost:11434"),
            ollama_model=storage.get_setting("ollama_model", "llava"),
            capture_interval=storage.get_setting("capture_interval", "10"),
            max_storage_gb=storage.get_setting("max_storage_gb", "5"),
        )

    # ------------------------------------------------------------------ #
    # API – status                                                         #
    # ------------------------------------------------------------------ #

    @app.route("/api/status")
    def api_status():
        return jsonify(
            {
                "recording": recorder.is_running,
                "ollama_available": provider.is_available(),
                "ollama_url": provider.base_url,
                "ollama_model": provider.model,
                "data_dir": str(storage.app_dir),
            }
        )

    # ------------------------------------------------------------------ #
    # API – recording control                                              #
    # ------------------------------------------------------------------ #

    @app.route("/api/recording/start", methods=["POST"])
    def api_recording_start():
        recorder.start()
        storage.set_setting("recording_enabled", "true")
        return jsonify({"ok": True, "recording": recorder.is_running})

    @app.route("/api/recording/stop", methods=["POST"])
    def api_recording_stop():
        recorder.stop()
        storage.set_setting("recording_enabled", "false")
        return jsonify({"ok": True, "recording": recorder.is_running})

    # ------------------------------------------------------------------ #
    # API – timeline                                                       #
    # ------------------------------------------------------------------ #

    @app.route("/api/timeline")
    def api_timeline():
        """Return timeline cards for the requested date (YYYY-MM-DD)."""
        date_str = request.args.get("date")
        if date_str:
            try:
                # Parse as noon so the 4 AM boundary logic selects the correct
                # calendar day regardless of the time the request is made.
                date = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=12)
            except ValueError:
                return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400
        else:
            date = datetime.now()

        cards = storage.get_timeline_cards(date)

        # Format timestamps for the UI.
        formatted = []
        for card in cards:
            start = datetime.fromisoformat(card["start_time"])
            end = datetime.fromisoformat(card["end_time"])
            duration_min = max(1, int((end - start).total_seconds() / 60))
            formatted.append(
                {
                    **card,
                    "start_label": start.strftime("%H:%M"),
                    "end_label": end.strftime("%H:%M"),
                    "duration_min": duration_min,
                }
            )
        return jsonify({"cards": formatted, "date": date.strftime("%Y-%m-%d")})

    # ------------------------------------------------------------------ #
    # API – settings                                                       #
    # ------------------------------------------------------------------ #

    @app.route("/api/settings", methods=["GET"])
    def api_settings_get():
        return jsonify(
            {
                "ollama_url": storage.get_setting("ollama_url", "http://localhost:11434"),
                "ollama_model": storage.get_setting("ollama_model", "llava"),
                "capture_interval": int(storage.get_setting("capture_interval", "10")),
                "max_storage_gb": float(storage.get_setting("max_storage_gb", "5")),
            }
        )

    @app.route("/api/settings", methods=["POST"])
    def api_settings_post():
        data = request.get_json(force=True) or {}

        if "ollama_url" in data:
            storage.set_setting("ollama_url", str(data["ollama_url"]))
            provider.base_url = str(data["ollama_url"]).rstrip("/")

        if "ollama_model" in data:
            storage.set_setting("ollama_model", str(data["ollama_model"]))
            provider.model = str(data["ollama_model"])

        if "capture_interval" in data:
            interval = max(5, int(data["capture_interval"]))
            storage.set_setting("capture_interval", str(interval))
            recorder.interval_seconds = interval

        if "max_storage_gb" in data:
            storage.set_setting("max_storage_gb", str(float(data["max_storage_gb"])))

        return jsonify({"ok": True})

    @app.route("/api/models")
    def api_models():
        """Return the models available in the connected Ollama instance."""
        return jsonify({"models": provider.get_available_models()})

    # ------------------------------------------------------------------ #
    # API – manual analysis trigger                                        #
    # ------------------------------------------------------------------ #

    @app.route("/api/analyze", methods=["POST"])
    def api_analyze():
        """Trigger an immediate analysis pass (useful during setup/testing)."""
        import threading

        def run():
            try:
                analysis_manager._process_pending_screenshots()
                analysis_manager._process_pending_batches()
            except Exception as exc:
                logger.error("Manual analysis error: %s", exc)

        threading.Thread(target=run, daemon=True).start()
        return jsonify({"ok": True, "message": "Analysis triggered"})

    return app
