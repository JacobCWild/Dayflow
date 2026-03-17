# Dayflow for Windows

A Windows 11 port of [Dayflow](https://github.com/JacobCWild/Dayflow) – a private, automatic timeline of your day.

Screenshots are taken every few seconds, analysed locally with **Ollama** (a vision-capable model), and displayed as a timeline in your browser.

---

## Requirements

| Requirement | Notes |
|-------------|-------|
| **Windows 11** | Windows 10 should also work |
| **Python 3.9+** | [python.org/downloads](https://www.python.org/downloads/) |
| **Ollama** | [ollama.com](https://ollama.com/) – must be installed and running |
| A **vision model** | e.g. `llava` (see below) |

---

## Quick Start

### 1 – Install Ollama and pull a vision model

Download Ollama from <https://ollama.com/> and install it.  
Then open a terminal and pull the `llava` model (≈ 4 GB):

```
ollama pull llava
```

Leave Ollama running in the background (it starts automatically with Windows after installation).

### 2 – Install Python dependencies

```
cd windows
pip install -r requirements.txt
```

### 3 – Start Dayflow

**Option A – double-click** `run.bat`

**Option B – terminal**

```
python dayflow.py
```

Dayflow opens your default browser at <http://localhost:5000> and starts recording immediately.

---

## How it works

```
Every 10 seconds
  └─ Capture a screenshot (primary monitor)
     └─ Save as JPEG to %APPDATA%\Dayflow\recordings\

Every 60 seconds
  └─ Group screenshots into ~10-minute batches
     └─ For each batch:
          1. Sample up to 10 frames
          2. Ask Ollama (llava) to describe each frame
          3. Ask Ollama to produce a title + summary
          4. Save as a "timeline card"

Browser UI (http://localhost:5000)
  └─ Shows timeline cards for the selected day
  └─ Date navigation, recording toggle, manual analysis trigger
```

---

## Data storage

All data is stored locally in:

```
%APPDATA%\Dayflow\
├── dayflow.sqlite        ← database (timeline cards, settings, …)
└── recordings\           ← screenshot JPEG files
```

`%APPDATA%` is typically `C:\Users\<YourName>\AppData\Roaming`.

To reset Dayflow, quit the app and delete the `Dayflow` folder.

---

## Settings

Open <http://localhost:5000/settings> to configure:

| Setting | Default | Notes |
|---------|---------|-------|
| Ollama URL | `http://localhost:11434` | Change if you run Ollama on a different port |
| Model | `llava` | Any Ollama vision model works (e.g. `llava-llama3`, `bakllava`) |
| Capture interval | `10` seconds | Minimum 5 s |
| Max storage | `5` GB | Oldest screenshots are deleted automatically |

---

## Vision models

| Model | Size | Notes |
|-------|------|-------|
| `llava` | ~4 GB | Good general-purpose vision model |
| `llava-llama3` | ~5 GB | Higher quality, based on LLaMA 3 |
| `llava-phi3` | ~2 GB | Smaller and faster |
| `bakllava` | ~4 GB | Alternative base |

Pull any model with `ollama pull <name>`, then update the model name in Settings.

---

## Troubleshooting

**"Ollama is not reachable"**  
→ Make sure Ollama is running (`ollama serve` in a terminal, or check the system tray).  
→ Verify the URL in Settings matches your Ollama port.

**No timeline cards appear**  
→ Recording must be active (green dot in the header).  
→ Analysis runs every 60 seconds; click **Analyse now** for an immediate pass.  
→ At least 3 screenshots in a 10-minute window are needed to form a batch.

**ImportError on startup**  
→ Run `pip install -r requirements.txt` again.

**Blank / dark screenshots**  
→ Make sure no full-screen DRM-protected application (e.g. Netflix in a browser) is covering the screen during capture.

---

## Command-line options

```
python dayflow.py [--no-tray] [--no-browser]

  --no-tray      Skip the system-tray icon (useful for headless environments)
  --no-browser   Do not open the browser automatically on startup
```

---

## Privacy

- All screenshots stay on your machine in `%APPDATA%\Dayflow\`.
- The only data that leaves your PC is sent to your local Ollama instance (running at `localhost`).
- No analytics, no telemetry, no cloud.

---

## License

MIT – same as the original Dayflow project.
