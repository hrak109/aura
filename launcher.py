"""
Aura Home Security Matrix — Windows Control Panel
Replaces the raw CMD window with a native dark-themed GUI.
Entry point for the PyInstaller .exe build.
"""

import sys
import os
import io
import threading
import queue
import time
import webbrowser
import logging
import tkinter as tk
from tkinter import messagebox, ttk

# ── Dynamic path resolution (mirrors main.py) ──────────────────────────────
if getattr(sys, 'frozen', False):
    bundle_dir = sys._MEIPASS
    current_dir = os.path.dirname(sys.executable)
else:
    bundle_dir = os.path.dirname(os.path.abspath(__file__))
    current_dir = bundle_dir

sys.path.insert(0, bundle_dir)

# ── Design Tokens (matches Aura web palette) ────────────────────────────────
BG_DEEPEST  = "#020617"   # slate-950
BG_DARK     = "#0f172a"   # slate-900
BG_MID      = "#1e293b"   # slate-800
BG_PANEL    = "#0f172a"
BORDER      = "#334155"   # slate-700
ACCENT      = "#c084fc"   # purple-400 (was emerald-500)
ACCENT_GLOW = "#7e22ce"   # purple-700 (was emerald-950)
TEXT_WHITE  = "#f1f5f9"
TEXT_GRAY   = "#94a3b8"   # slate-400
TEXT_DIM    = "#475569"   # slate-600
COL_GREEN   = "#4ade80"
COL_BLUE    = "#60a5fa"
COL_YELLOW  = "#fbbf24"
COL_RED     = "#f87171"
COL_PURPLE  = "#c084fc"

# Log colorization rules — checked in order
LOG_TAGS = [
    ("error",   COL_RED,    ["[ERROR]", "[FATAL]", "ERROR:"]),
    ("success", COL_GREEN,  ["[SUCCESS]", "[DISCOVER]"]),
    ("warn",    COL_YELLOW, ["[WARN]"]),
    ("system",  COL_PURPLE, ["[SYSTEM]", "[WIZARD]", "[CONFIG]"]),
    ("info",    COL_BLUE,   ["[INFO]", "INFO:", "Uvicorn", "Started", "Waiting", "Application"]),
]


class QueueStream:
    """
    Minimal text-mode stream that routes all writes into a thread-safe queue.
    Works for both print() calls (str) and binary writes from uvicorn internals (bytes).
    """
    encoding = 'utf-8'
    errors   = 'replace'
    softspace = 0

    def __init__(self, q: queue.Queue):
        self.q = q
        # Some libraries call sys.stdout.buffer — point it back at ourselves
        self.buffer = self

    def write(self, text):
        if not text:
            return 0
        # Handle binary writes (uvicorn internals, logging formatters)
        if isinstance(text, (bytes, bytearray)):
            text = text.decode('utf-8', errors='replace')
        text = str(text)
        for line in text.splitlines():
            if line.strip():
                self.q.put(line)
        return len(text)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):   pass
    def isatty(self):  return False
    def readable(self): return False
    def writable(self): return True
    def seekable(self): return False

    def fileno(self):
        raise OSError(9, 'QueueStream has no real file descriptor')


class QueueLogHandler(logging.Handler):
    """Routes Python logging output into the same queue."""
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record):
        try:
            self.q.put(self.format(record))
        except Exception:
            pass


class AuraControlPanel:
    def __init__(self):
        self.log_q: queue.Queue = queue.Queue()
        self.server_instance = None
        self._status = "starting"   # starting | running | error | stopping
        self._lan_ips: list = []
        self.logs_visible = False

        # Redirect ALL output before any imports that emit logs
        self._redirect_io()

        self._build_window()
        self._start_server()
        self._poll_logs()

    # ── I/O Redirection ────────────────────────────────────────────────────
    def _redirect_io(self):
        stream = QueueStream(self.log_q)
        sys.stdout = stream
        sys.stderr = stream

        # Route Python's logging module into the same queue
        handler = QueueLogHandler(self.log_q)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(handler)

    # ── Window Construction ────────────────────────────────────────────────
    def _build_window(self):
        self.root = tk.Tk()
        self.root.title("Aura - Wyzecam Local Stream by Haistellar")
        self.root.geometry("540x260")
        self.root.minsize(500, 260)
        self.root.configure(bg=BG_DARK)
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Try to set a taskbar icon (requires icon.ico next to exe)
        try:
            ico = os.path.join(current_dir, "aura.ico")
            if os.path.exists(ico):
                self.root.iconbitmap(ico)
        except Exception:
            pass

        self._build_header()
        self._build_controls()
        self._build_log_pane()
        self._build_footer()

    def _build_header(self):
        hdr = tk.Frame(self.root, bg=BG_DEEPEST, height=54)
        hdr.pack(fill=tk.X, side=tk.TOP)
        hdr.pack_propagate(False)

        # Accent top bar
        tk.Frame(hdr, bg=ACCENT, height=2).pack(fill=tk.X, side=tk.TOP)

        inner = tk.Frame(hdr, bg=BG_DEEPEST)
        inner.pack(fill=tk.BOTH, expand=True, padx=20)

        # Logo
        tk.Label(inner, text="●", font=("Segoe UI", 11), fg=ACCENT,
                 bg=BG_DEEPEST).pack(side=tk.LEFT, pady=12)
        tk.Label(inner, text="  AURA", font=("Segoe UI", 14, "bold"),
                 fg=TEXT_WHITE, bg=BG_DEEPEST).pack(side=tk.LEFT, pady=12)

        # Status indicator (right side)
        self.status_dot_lbl = tk.Label(inner, text="●", font=("Segoe UI", 11),
                                       fg=COL_YELLOW, bg=BG_DEEPEST)
        self.status_dot_lbl.pack(side=tk.RIGHT, pady=12, padx=(4, 0))

        self.status_text_lbl = tk.Label(inner, text="STARTING",
                                        font=("Consolas", 9, "bold"),
                                        fg=COL_YELLOW, bg=BG_DEEPEST)
        self.status_text_lbl.pack(side=tk.RIGHT, pady=12)

    def _build_controls(self):
        ctrl = tk.Frame(self.root, bg=BG_DARK, pady=15, padx=20)
        ctrl.pack(fill=tk.X, side=tk.TOP)

        # URL / IP Label Row
        url_frame = tk.Frame(ctrl, bg=BG_DARK)
        url_frame.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(url_frame, text="SERVER URL:", font=("Consolas", 8, "bold"),
                 fg=TEXT_DIM, bg=BG_DARK).pack(side=tk.LEFT, padx=(0, 10))
                 
        self.ip_label = tk.Label(url_frame, text="Starting server…",
                                 font=("Consolas", 9, "underline"), fg=ACCENT,
                                 bg=BG_DARK, cursor="hand2")
        self.ip_label.pack(side=tk.LEFT)
        self.ip_label.bind("<Button-1>", self._open_first_ip)

        # Settings Row
        settings_frame = tk.Frame(ctrl, bg=BG_DARK)
        settings_frame.pack(fill=tk.X)

        tk.Label(settings_frame, text="AUTO RESTART:", font=("Consolas", 8, "bold"),
                 fg=TEXT_DIM, bg=BG_DARK).pack(side=tk.LEFT, padx=(0, 10))

        self.interval_var = tk.StringVar(value="Never")
        interval_val = "0"
        env_path = os.path.join(current_dir, ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("RESTART_INTERVAL="):
                            interval_val = line.split("=", 1)[1].strip().strip("'\"")
            except Exception:
                pass
                
        interval_map_rev = {"1": "1 Hour", "3": "3 Hours", "8": "8 Hours", "24": "1 Day", "72": "3 Days", "0": "Never", "-1": "Never"}
        self.interval_var.set(interval_map_rev.get(interval_val, "Never"))

        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=BG_MID, background=BG_MID, foreground=TEXT_WHITE, borderwidth=0, arrowcolor=TEXT_GRAY)
        
        # Fix the dropdown listbox styling
        self.root.option_add("*TCombobox*Listbox.background", BG_MID)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT_WHITE)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_GLOW)
        self.root.option_add("*TCombobox*Listbox.selectForeground", TEXT_WHITE)

        self.interval_cb = ttk.Combobox(
            settings_frame, textvariable=self.interval_var,
            values=["1 Hour", "3 Hours", "8 Hours", "1 Day", "3 Days", "Never"],
            state="readonly", width=8, font=("Consolas", 8)
        )
        self.interval_cb.pack(side=tk.LEFT)
        self.interval_cb.bind("<<ComboboxSelected>>", self._on_interval_change)

        # Log Toggle
        self.btn_logs = tk.Button(
            settings_frame, text="SHOW LOGS", command=self._toggle_logs,
            font=("Consolas", 8, "bold"), fg=TEXT_GRAY, bg=BG_MID,
            activeforeground=TEXT_WHITE, activebackground=BORDER,
            relief=tk.FLAT, padx=10, pady=4, cursor="hand2", borderwidth=0
        )
        self.btn_logs.pack(side=tk.RIGHT)
        
    def _toggle_logs(self):
        current_width = self.root.winfo_width()
        if current_width < 500:
            current_width = 540
            
        if self.logs_visible:
            self.log_wrapper.pack_forget()
            self.btn_logs.config(text="SHOW LOGS", bg=BG_MID, fg=TEXT_GRAY)
            self.logs_visible = False
            self.root.geometry(f"{current_width}x260")
        else:
            self.log_wrapper.pack(fill=tk.BOTH, expand=True)
            self.btn_logs.config(text="HIDE LOGS", bg=BORDER, fg=TEXT_WHITE)
            self.logs_visible = True
            self.root.geometry(f"{current_width}x560")

    def _on_interval_change(self, event=None):
        val = self.interval_var.get()
        interval_map = {"1 Hour": "1", "3 Hours": "3", "8 Hours": "8", "1 Day": "24", "3 Days": "72", "Never": "0"}
        hours = interval_map.get(val, "3")
        os.environ["RESTART_INTERVAL"] = hours
        
        env_path = os.path.join(current_dir, ".env")
        lines = []
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        
        new_lines = []
        found = False
        for line in lines:
            if line.startswith("RESTART_INTERVAL="):
                new_lines.append(f"RESTART_INTERVAL={hours}\n")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"RESTART_INTERVAL={hours}\n")
            
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            self.log_q.put(f"[CONFIG] Updated auto-restart interval to {val}")
        except Exception as e:
            self.log_q.put(f"[ERROR] Failed to save interval to .env: {e}")

    def _build_log_pane(self):
        self.log_wrapper = tk.Frame(self.root, bg=BG_DARK, padx=14, pady=10)
        # log_wrapper packed later when logs are shown

        # Section label
        tk.Label(self.log_wrapper, text="SYSTEM LOG", font=("Consolas", 8, "bold"),
                 fg=TEXT_DIM, bg=BG_DARK, anchor="w").pack(fill=tk.X, pady=(0, 5))

        # Log text widget + scrollbar
        frame = tk.Frame(self.log_wrapper, bg=BG_DEEPEST, highlightthickness=1,
                         highlightbackground=BORDER)
        frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            frame,
            bg=BG_DEEPEST,
            fg=TEXT_GRAY,
            font=("Consolas", 9),
            wrap=tk.WORD,
            relief=tk.FLAT,
            borderwidth=0,
            insertbackground=ACCENT,
            state=tk.DISABLED,
            selectbackground=ACCENT_GLOW,
            selectforeground=TEXT_WHITE,
            padx=10,
            pady=8,
            cursor="arrow",
        )

        # Configure all log color tags
        for tag, color, _ in LOG_TAGS:
            self.log_text.tag_configure(tag, foreground=color)
        self.log_text.tag_configure("ts", foreground=TEXT_DIM)

        scrollbar = tk.Scrollbar(frame, orient=tk.VERTICAL,
                                 command=self.log_text.yview,
                                 bg=BG_MID, troughcolor=BG_DARK,
                                 relief=tk.FLAT, borderwidth=0)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _build_footer(self):
        footer = tk.Frame(self.root, bg=BG_DEEPEST, height=64)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        footer.pack_propagate(False)

        # Top border
        tk.Frame(footer, bg=BORDER, height=1).pack(fill=tk.X, side=tk.TOP)

        inner = tk.Frame(footer, bg=BG_DEEPEST)
        inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=0)

        # Action buttons (center distributed)
        self.btn_open = self._make_btn(inner, "🌐  OPEN DASHBOARD",
                                       self._open_browser, ACCENT)
        self.btn_open.pack(side=tk.LEFT, pady=14)

        self.btn_restart = self._make_btn(inner, "↺  RESTART STREAMS",
                                          self._restart_streams, TEXT_GRAY)
        self.btn_restart.pack(side=tk.LEFT, padx=10, pady=14)

        self.btn_shutdown = self._make_btn(inner, "⏻  SHUTDOWN",
                                           self._shutdown, COL_RED)
        self.btn_shutdown.pack(side=tk.RIGHT, pady=14)

    def _make_btn(self, parent, text, cmd, fg):
        btn = tk.Button(
            parent, text=text, command=cmd,
            font=("Consolas", 8, "bold"),
            fg=fg, bg=BG_MID,
            activeforeground=fg, activebackground=BORDER,
            relief=tk.FLAT, padx=12, pady=7,
            cursor="hand2", borderwidth=0,
            highlightthickness=1, highlightbackground=BORDER,
        )
        btn.bind("<Enter>", lambda e: btn.config(bg=BORDER))
        btn.bind("<Leave>", lambda e: btn.config(bg=BG_MID))
        return btn

    # ── Server Lifecycle ───────────────────────────────────────────────────
    def _start_server(self):
        def _run():
            try:
                import uvicorn
                from main import app, get_all_lan_ips

                # Quiet the per-request access log — it clutters the GUI pane
                logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

                config = uvicorn.Config(
                    app,
                    host="0.0.0.0",
                    port=8000,
                    log_level="info",
                )
                server = uvicorn.Server(config)
                # On Windows uvicorn skips signal handlers automatically;
                # override anyway so a non-main thread doesn't raise
                server.install_signal_handlers = lambda: None
                self.server_instance = server

                # After a short delay, mark as running and display LAN IPs
                def _mark_running():
                    time.sleep(2.5)
                    if self._status == "starting":
                        self._status = "running"
                        ips = get_all_lan_ips()
                        self._lan_ips = ips
                        self.root.after(0, self._set_status_running)
                        self.root.after(0, self._update_ip_label)

                threading.Thread(target=_mark_running, daemon=True).start()
                server.run()

            except Exception as exc:
                import traceback
                self._status = "error"
                self.log_q.put(f"[FATAL] Server failed to start: {exc}")
                self.log_q.put(traceback.format_exc())
                self.root.after(0, lambda: self._set_status("ERROR", COL_RED))

        threading.Thread(target=_run, daemon=True, name="uvicorn").start()

    # ── Log Polling ────────────────────────────────────────────────────────
    def _poll_logs(self):
        try:
            while True:
                line = self.log_q.get_nowait()
                self._append_log(str(line))
        except queue.Empty:
            pass
        self.root.after(80, self._poll_logs)

    def _append_log(self, text: str):
        # Determine which color tag applies (first match wins)
        tag = None
        for tag_name, _, patterns in LOG_TAGS:
            if any(p in text for p in patterns):
                tag = tag_name
                break

        self.log_text.configure(state=tk.NORMAL)

        # Timestamp prefix
        ts = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] ", "ts")

        if tag:
            self.log_text.insert(tk.END, text + "\n", tag)
        else:
            self.log_text.insert(tk.END, text + "\n")

        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

        # Auto-detect if server is now running (look for uvicorn ready message)
        if "Uvicorn running on" in text and self._status == "starting":
            self._status = "running"
            self.root.after(0, self._set_status_running)

    # ── Status Helpers ─────────────────────────────────────────────────────
    def _set_status_running(self):
        self._set_status("RUNNING", ACCENT)

    def _set_status(self, text: str, color: str):
        self.status_text_lbl.config(text=text, fg=color)
        self.status_dot_lbl.config(fg=color)

    def _update_ip_label(self):
        if not self._lan_ips:
            self.ip_label.config(text="http://localhost:8000", fg=ACCENT)
        else:
            parts = [f"http://{ip}:8000" for ip in self._lan_ips]
            self.ip_label.config(text="  ·  ".join(parts), fg=ACCENT)

    # ── Button Actions ─────────────────────────────────────────────────────
    def _open_browser(self):
        webbrowser.open("http://localhost:8000")

    def _open_first_ip(self, _event=None):
        if self._lan_ips:
            webbrowser.open(f"http://{self._lan_ips[0]}:8000")
        else:
            webbrowser.open("http://localhost:8000")

    def _restart_streams(self):
        self.btn_restart.config(text="↺  RESTARTING…", state=tk.DISABLED)

        def _do():
            try:
                from main import boot_matrix
                boot_matrix()
                self.root.after(0, lambda: self.btn_restart.config(
                    text="↺  RESTART STREAMS", state=tk.NORMAL))
            except Exception as e:
                self.log_q.put(f"[ERROR] Restart failed: {e}")
                self.root.after(0, lambda: self.btn_restart.config(
                    text="↺  RESTART STREAMS", state=tk.NORMAL))

        threading.Thread(target=_do, daemon=True).start()

    def _shutdown(self):
        if not messagebox.askokcancel(
            "Shutdown Aura",
            "This will stop the Aura security server.\n"
            "All active camera feeds will be disconnected.\n\n"
            "Shut down?"
        ):
            return

        self._status = "stopping"
        self._set_status("SHUTTING DOWN…", COL_RED)
        self.btn_shutdown.config(state=tk.DISABLED)
        self.btn_restart.config(state=tk.DISABLED)
        self.btn_open.config(state=tk.DISABLED)

        def _do_shutdown():
            # Stop go2rtc first
            try:
                from main import kill_matrix_workers
                kill_matrix_workers()
            except Exception:
                pass

            # Signal uvicorn to stop
            if self.server_instance:
                self.server_instance.should_exit = True

            time.sleep(1.2)
            self.root.after(0, self.root.destroy)

        threading.Thread(target=_do_shutdown, daemon=True).start()

    def _on_close(self):
        """X button — same as Shutdown."""
        self._shutdown()

    # ── Main Loop ──────────────────────────────────────────────────────────
    def run(self):
        # Open browser automatically (same behavior as before, with delay)
        def _auto_open():
            time.sleep(2.0)
            webbrowser.open("http://localhost:8000")

        threading.Thread(target=_auto_open, daemon=True).start()

        self.root.mainloop()


if __name__ == "__main__":
    panel = AuraControlPanel()
    panel.run()
