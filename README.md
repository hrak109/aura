# Aura by Haistellar

**Aura** is a low-latency home security streaming matrix designed for Wyze cameras. It bridges your Wyze camera network with high-performance local WebRTC live feeds via an interactive glassmorphic web dashboard and a native Windows GUI control panel.

---

## ✨ Key Features

- **Low-Latency WebRTC Streaming:**
  - Powered by the native `go2rtc` streaming engine, delivering real-time peer-to-peer WebRTC streams directly to your browser and local network devices.
  - Automatic HD/SD stream quality switching based on tile size, DTLS fallbacks, and an intelligent stream watchdog with PC sleep/wake recovery.
- **Native Windows GUI Control Panel:**
  - Dedicated dark-themed desktop launcher (`launcher.py`) with live color-coded system logs, configurable auto-restart intervals, one-click stream reboot, and clean shutdown controls.
- **Interactive Matrix Dashboard:**
  - Drag-and-drop camera reordering and direct corner-drag column span resizing (`1` to `5` columns).
  - Customizable video aspect schemes (*Stretch*, *Crop*, *Fit*) and system accent themes (*Emerald*, *Cyan*, *Violet*, *Amber*).
- **Plug-and-Play Setup Wizard:**
  - Step-by-step web wizard (`/setup`) that validates Wyze credentials, writes persistent `.env` configurations, and hot-boots camera discovery without manual file editing.
- **Hardened Local Controls:**
  - Administrative operations (Stream Reboot, Core Server Shutdown) are protected by host loopback origin checks (`127.0.0.1` / `::1`) and session authentication.

---

## 🚀 Quick Start

### Option 1: Standalone Windows Executable (`Aura.exe`)
1. Build `dist\Aura.exe` using `build_exe_windows.bat` (or download a pre-built release).
2. Place `Aura.exe` in a dedicated folder (e.g., `C:\Aura\`) and double-click to launch.
3. The Aura Control Panel will start the background server and automatically open `http://localhost:8000` in your browser.
4. Complete the **Aura Setup Wizard** on first launch.

### Option 2: Run from Python Source
1. Ensure **Python 3.10+** is installed and added to your `PATH`.
2. Right-click `run_aura.bat` and select **Run as Administrator** (or run `python launcher.py` / `python main.py`).
   - `run_aura.bat` automatically configures Windows Defender Firewall inbound rules for Ports `8000` (Web UI), `1984` (go2rtc API), and `8555` (WebRTC Media TCP/UDP), installs `requirements.txt`, and launches the portal.
3. Open `http://localhost:8000` in your browser.

---

## 🔑 Initial Setup Wizard

On first launch, Aura redirects to `/setup`:

1. **Wyze Account Credentials:** Enter your Wyze account email and password.
2. **Wyze Developer API Keys:** Enter your **Key ID** (`WYZE_CLIENT_ID`) and **Key Secret** (`WYZE_API_KEY`) from the [Wyze Developer Console](https://developer-api-console.wyze.com/).
3. **Aura Local Dashboard Password:** Set an access code used to log into the dashboard from devices on your local network.
4. Click **Launch Aura!**:
   - Credentials are saved locally to `.env` (excluded from version control via `.gitignore`).
   - Aura discovers your cameras via the Wyze API, downloads `go2rtc.exe` if needed, generates `go2rtc.yaml`, and starts live WebRTC streaming.

---

## 🛠️ Project Structure

```
aura/
├── launcher.py               # Native Windows Tkinter GUI control panel & server manager
├── main.py                   # FastAPI backend, Wyze discovery, and go2rtc lifecycle controller
├── templates/
│   ├── dashboard.html        # Live WebRTC camera grid dashboard
│   ├── login.html            # Session authentication gateway
│   └── setup.html            # First-run credential setup wizard
├── aura.spec                 # PyInstaller standalone executable specification
├── aura.ico                  # Application icon
├── build_exe_windows.bat     # One-click Windows .exe builder
├── build_exe.sh              # CLI PyInstaller build script
├── run_aura.bat              # Direct administrator launcher with firewall setup
└── requirements.txt          # Python dependencies
```

---

## 📄 License

MIT License — Haistellar.
