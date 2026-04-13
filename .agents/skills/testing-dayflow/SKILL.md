# Testing the Dayflow App

## Overview
Dayflow is a privacy-focused work journal that captures desktop screenshots and uses a local AI vision model (via Ollama) to generate activity timeline cards. The Windows port runs on Python with Flask for the web UI.

## Devin Secrets Needed
No secrets required — Dayflow runs entirely locally with Ollama.

## Prerequisites
- Python 3.12+ with pip
- X11 display server (for screenshot capture via `mss`)
- Ollama installed and running locally
- A vision-capable model pulled (e.g., `llava`, `llava-phi3`)

## Setup Steps

### 1. Install System Dependencies
```bash
sudo apt-get install -y libx11-dev libxrandr-dev zstd
```

### 2. Install Ollama
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &  # Start in background if not already running
```

### 3. Pull a Vision Model
```bash
# For GPU systems (faster, better quality):
ollama pull llava

# For CPU-only systems (smaller, faster inference):
ollama pull llava-phi3
```

### 4. Install Python Dependencies
```bash
cd windows/
pip install -r requirements.txt
```

### 5. Start the App
```bash
DISPLAY=:0 python3 dayflow.py --no-tray --no-browser
```
The web UI is at `http://localhost:5000`.

## Key Architecture
- **screen_recorder.py**: Captures screenshots every N seconds (default 10) using `mss`, saves as JPEG
- **analysis_manager.py**: Groups screenshots into batches, triggers Ollama analysis
- **ollama_provider.py**: Sends images to Ollama for frame descriptions, then generates activity summaries
- **storage_manager.py**: SQLite database at `~/Dayflow/dayflow.sqlite`, screenshots at `~/Dayflow/recordings/`
- **web_ui/server.py**: Flask API endpoints for timeline, status, settings, recording control
- **web_ui/templates/index.html**: Timeline card rendering with auto-refresh every 30s

## Testing the Full Pipeline

### Screenshot Capture
- Open `http://localhost:5000` and verify green "Recording" indicator
- Check screenshot count: `SELECT COUNT(*) FROM screenshots` in `~/Dayflow/dayflow.sqlite`
- Verify files accumulate in `~/Dayflow/recordings/`

### Analysis Pipeline
**Important**: Batches only form when the **newest** unprocessed screenshot is older than `BATCH_MATURITY_MINUTES` (default 10 min). This means:
- You must **stop recording** and wait for the maturity period before analysis can trigger
- Continuously recording prevents batch formation by design
- For faster testing, temporarily set `BATCH_MATURITY_MINUTES = 2` in `analysis_manager.py` line 20

To trigger analysis:
1. Let screenshots accumulate for a few minutes
2. Stop recording via the UI
3. Wait for maturity period (or reduce it temporarily)
4. Click "Analyse now" or wait for the automatic 60s analysis loop

### Timeline Cards
- Cards appear in the UI with: category icon, title, time range, duration, summary
- Check DB: `SELECT * FROM timeline_cards`
- The UI auto-refreshes every 30 seconds

## CPU-Only Inference Notes
- `llava` (7B, 4.1GB): Very slow on CPU (~5+ min/frame), may timeout at default 120s
- `llava-phi3` (smaller, 2.3GB): Better for CPU (~3 min/frame)
- For CPU testing, consider:
  - Increasing timeout in `ollama_provider.py` (line 37) from 120 to 600
  - Reducing sampled frames by changing `stride = max(1, len(screenshots) // 3)` in `analysis_manager.py` line 182
  - Using `llava-phi3` model instead of `llava`
- On GPU hardware, the default settings should work fine

## Settings Page
- URL: `http://localhost:5000/settings`
- Shows: Ollama URL, model name, capture interval, max storage
- Green banner when Ollama is reachable, warning when not

## Common Issues
- **"No X11 library found"**: Install `libx11-dev libxrandr-dev` and set `DISPLAY=:0`
- **Ollama timeout**: Increase timeout or use a smaller model on CPU-only systems
- **No batches forming**: Recording must be stopped and screenshots must age past BATCH_MATURITY_MINUTES
- **zstd error during Ollama install**: Install `zstd` package first
