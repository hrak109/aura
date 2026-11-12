import os
import sys
import subprocess
import urllib.request
import zipfile
import io
import ssl
import urllib3
import requests
import signal
import time
import threading
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from wyze_sdk import Client

# Dynamic path resolution to support single-file Windows compilation
if getattr(sys, 'frozen', False):
    # Running inside PyInstaller standalone bundle
    bundle_dir = sys._MEIPASS
    current_dir = os.path.dirname(sys.executable)
else:
    # Running inside standard raw python commandline environment
    bundle_dir = os.path.dirname(os.path.abspath(__file__))
    current_dir = bundle_dir

# 1. Zero-dependency .env loader (reads from persistent directory next to exe)
def load_env_file():
    env_path = os.path.join(current_dir, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip("'\"")

load_env_file()

# 2. SSL certification verification bypass monkeypatch
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
original_send = requests.Session.send
requests.Session.send = lambda self, request, **kwargs: original_send(self, request, **{**kwargs, "verify": False})

stream_event_queues = []
boot_lock = None

def get_restart_interval_seconds():
    val_str = os.environ.get("RESTART_INTERVAL", "0")
    try:
        hours = float(val_str)
        return int(hours * 3600)
    except Exception:
        return 0

async def auto_restart_worker():
    slept_for = 0
    while True:
        await asyncio.sleep(10)
        interval = get_restart_interval_seconds()
        
        if interval <= 0:
            slept_for = 0
            continue
            
        slept_for += 10
        if slept_for >= interval:
            slept_for = 0
            while go2rtc_process:
                print("[SYSTEM] Performing scheduled matrix restart...")
                try:
                    if boot_lock:
                        async with boot_lock:
                            await asyncio.to_thread(boot_matrix)
                    else:
                        await asyncio.to_thread(boot_matrix)
                    for q in stream_event_queues:
                        q.put_nowait("restart")
                    break  # Success, exit retry loop
                except Exception as e:
                    print(f"[ERROR] Scheduled restart failed: {e}. Retrying in 10 minutes...")
                    await asyncio.sleep(600)  # Retry in 10 minutes


@asynccontextmanager
async def lifespan(app: FastAPI):
    global boot_lock
    boot_lock = asyncio.Lock()
    boot_matrix()
    task = asyncio.create_task(auto_restart_worker())
    yield
    task.cancel()
    kill_matrix_workers()

app = FastAPI(title="Aura Home Security Matrix", lifespan=lifespan)
templates = Jinja2Templates(directory=os.path.join(bundle_dir, "templates"))

# Global variables to track running go2rtc subprocess and log file descriptor
go2rtc_process = None
go2rtc_log_file = None

# Get environment config with defaults
WYZE_EMAIL = os.environ.get("WYZE_EMAIL", "")
WYZE_PASSWORD = os.environ.get("WYZE_PASSWORD", "")
WYZE_CLIENT_ID = os.environ.get("WYZE_CLIENT_ID", "")
WYZE_API_KEY = os.environ.get("WYZE_API_KEY", "")
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "aura")

def download_go2rtc():
    """
    Downloads and extracts go2rtc.exe if not already present.
    """
    exe_path = os.path.join(current_dir, "go2rtc.exe")
    if os.path.exists(exe_path):
        return exe_path
    
    print("[INFO] Downloading native go2rtc streaming engine...")
    url = "https://github.com/AlexxIT/go2rtc/releases/latest/download/go2rtc_win64.zip"
    try:
        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        # Create unverified context for GitHub download in case local CA certs are missing
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, context=ctx) as response:
            zip_data = response.read()
        
        with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
            z.extractall(current_dir)
        print("[SUCCESS] go2rtc.exe extracted successfully!")
        return exe_path
    except Exception as e:
        print(f"[ERROR] Failed to download go2rtc: {e}")
        return None

def start_go2rtc(cameras):
    """
    Generates go2rtc.yaml and spawns the background go2rtc process.
    """
    global go2rtc_process, go2rtc_log_file
    
    # 0. Clean up any existing tracked go2rtc process to prevent port conflicts
    if go2rtc_process:
        try:
            go2rtc_process.kill()
            go2rtc_process.wait(timeout=3)
        except Exception:
            pass
        go2rtc_process = None
        
    if go2rtc_log_file:
        try:
            go2rtc_log_file.close()
        except Exception:
            pass
        go2rtc_log_file = None
        
    config_path = os.path.join(current_dir, "go2rtc.yaml")
    
    # OS-level cleanup for any stray processes
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/IM", "go2rtc.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["killall", "-9", "go2rtc"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["killall", "-9", "go2rtc.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[INFO] Cleaned up any existing go2rtc background instances.")
    except Exception as e:
        print(f"[WARN] Error cleaning up old go2rtc processes: {e}")
        
    # 1. Generate YAML contents
    # Binds to ":1984" to support both IPv4 and IPv6 loopback (resolving 'localhost' issues)
    yaml_lines = [
        "log:",
        "  level: trace",
        "",
        "api:",
        "  listen: \":1984\"",
        "  origin: \"*\"",
        "",
        "webrtc:",
        "  listen: \":8555\"",
        "  timeout: 45",
        "",
        "rtsp:",
        "  timeout: 15",
        "",
        "wyze:",
        f"  {WYZE_EMAIL}:",
        f"    api_id: \"{WYZE_CLIENT_ID}\"",
        f"    api_key: \"{WYZE_API_KEY}\"",
        f"    password: \"{WYZE_PASSWORD}\"",
        "",
        "streams:"
    ]
    for cam in cameras:
        safe_name = cam["safe_name"]
        ip = cam["ip"]
        uid = cam["uid"]
        enr = cam["enr"]
        mac = cam["mac"]
        model = cam["model"]
        
        # 1. Fallback stream (tries HD first, then falls back to SD, with and without DTLS)
        yaml_lines.append(f"  {safe_name}:")
        yaml_lines.append(f"    - \"wyze://{ip}?uid={uid}&enr={enr}&mac={mac}&model={model}&dtls=true&subtype=hd#timeout=7\"")
        yaml_lines.append(f"    - \"wyze://{ip}?uid={uid}&enr={enr}&mac={mac}&model={model}&dtls=false&subtype=hd#timeout=7\"")
        yaml_lines.append(f"    - \"wyze://{mac}?dtls=true&subtype=hd#timeout=7\"")
        yaml_lines.append(f"    - \"wyze://{mac}?dtls=false&subtype=hd#timeout=7\"")
        yaml_lines.append(f"    - \"wyze://{ip}?uid={uid}&enr={enr}&mac={mac}&model={model}&dtls=true&subtype=sd#timeout=7\"")
        yaml_lines.append(f"    - \"wyze://{ip}?uid={uid}&enr={enr}&mac={mac}&model={model}&dtls=false&subtype=sd#timeout=7\"")
        yaml_lines.append(f"    - \"wyze://{mac}?dtls=true&subtype=sd#timeout=7\"")
        yaml_lines.append(f"    - \"wyze://{mac}?dtls=false&subtype=sd#timeout=7\"")
        
        # 2. Explicit HD stream (with DTLS fallback)
        yaml_lines.append(f"  {safe_name}_hd:")
        yaml_lines.append(f"    - \"wyze://{ip}?uid={uid}&enr={enr}&mac={mac}&model={model}&dtls=true&subtype=hd#timeout=7\"")
        yaml_lines.append(f"    - \"wyze://{ip}?uid={uid}&enr={enr}&mac={mac}&model={model}&dtls=false&subtype=hd#timeout=7\"")
        yaml_lines.append(f"    - \"wyze://{mac}?dtls=true&subtype=hd#timeout=7\"")
        yaml_lines.append(f"    - \"wyze://{mac}?dtls=false&subtype=hd#timeout=7\"")
        
        # 3. Explicit SD (Smooth) stream (with DTLS fallback)
        yaml_lines.append(f"  {safe_name}_sd:")
        yaml_lines.append(f"    - \"wyze://{ip}?uid={uid}&enr={enr}&mac={mac}&model={model}&dtls=true&subtype=sd#timeout=7\"")
        yaml_lines.append(f"    - \"wyze://{ip}?uid={uid}&enr={enr}&mac={mac}&model={model}&dtls=false&subtype=sd#timeout=7\"")
        yaml_lines.append(f"    - \"wyze://{mac}?dtls=true&subtype=sd#timeout=7\"")
        yaml_lines.append(f"    - \"wyze://{mac}?dtls=false&subtype=sd#timeout=7\"")
    
    # Write to go2rtc.yaml
    with open(config_path, "w", encoding="utf-8") as f:
        f.write("\n".join(yaml_lines))
        
    print(f"[CONFIG] go2rtc.yaml written. Configured {len(cameras)} cameras.")
    
    # 2. Download and run go2rtc.exe
    exe_path = download_go2rtc()
    if not exe_path:
        print("[ERROR] Cannot run go2rtc: executable missing.")
        return
        
    try:
        # Launch go2rtc background process cleanly and log to file to avoid Errno 9
        go2rtc_log_file = open(os.path.join(current_dir, "go2rtc.log"), "w", encoding="utf-8")
        go2rtc_process = subprocess.Popen(
            [exe_path], 
            cwd=current_dir,
            stdout=go2rtc_log_file,
            stderr=go2rtc_log_file,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        print("[INFO] Native go2rtc streaming engine started in background (port 1984)")
    except Exception as e:
        print(f"[ERROR] Failed to run go2rtc: {e}")

# Security: Cookie authentication helper
def is_authenticated(request: Request) -> bool:
    return request.cookies.get("matrix_auth") == "authorized"

def boot_matrix():
    """Discover your 8 cameras and hook them straight into bare-metal pipelines."""
    print("Initializing Aura Bare-Metal Matrix Core by Haistellar...")
    
    if not all([WYZE_EMAIL, WYZE_PASSWORD, WYZE_CLIENT_ID, WYZE_API_KEY]):
        print("[ERROR] Missing credentials in .env file! Please check configurations.")
        app.state.camera_manifest = []
        return
        
    client = Client(email=WYZE_EMAIL, password=WYZE_PASSWORD, api_key=WYZE_API_KEY, key_id=WYZE_CLIENT_ID)
    
    try:
        # Fetch raw list of devices from Wyze API with retry logic
        raw_devices = None
        
        # Load custom IPs if they exist
        custom_ips = {}
        custom_ips_path = os.path.join(current_dir, "custom_ips.json")
        if os.path.exists(custom_ips_path):
            try:
                import json
                with open(custom_ips_path, "r") as f:
                    custom_ips = json.load(f)
                print(f"[CONFIG] Loaded {len(custom_ips)} custom IP overrides from custom_ips.json")
            except Exception as e:
                pass

        for attempt in range(3):
            try:
                raw_devices = client._api_client().get_object_list()["data"]["device_list"]
                break
            except Exception as api_err:
                if attempt < 2:
                    print(f"[WARN] Wyze API fetch failed (attempt {attempt + 1}/3): {api_err}. Retrying in {5 * (attempt + 1)}s...")
                    time.sleep(5 * (attempt + 1))
                else:
                    raise Exception(f"Failed to fetch camera list after 3 attempts: {api_err}")
                    
        cameras = [d for d in raw_devices if d.get("product_type") == "Camera"]
        
        # Build memory-optimized camera list
        new_manifest = []
        go2rtc_cameras = []
        
        for cam in cameras:
            mac = cam.get("mac", "")
            nickname = cam.get("nickname", "Unnamed Camera")
            safe_name = nickname.lower().replace(" ", "_").replace("-", "_")
            
            # Extract parameters safely
            params = cam.get("device_params", {})
            ip = params.get("ip", "")
            
            # Apply custom IP override if provided
            override_ip = custom_ips.get(nickname)
            if override_ip and override_ip.strip():
                ip = override_ip.strip()
                print(f"[CUSTOM IP] Overriding IP for {nickname} to {ip}")
                
            uid = params.get("p2p_id", "")
            enr = cam.get("enr", "")
            model = cam.get("product_model", "")
            
            if ip and uid and enr:
                camera_info = {
                    "name": nickname,
                    "safe_name": safe_name,
                    "mac": mac,
                    "ip": ip,
                    "uid": uid,
                    "enr": enr,
                    "model": model
                }
                new_manifest.append(camera_info)
                go2rtc_cameras.append(camera_info)
                print(f"[DISCOVER] Found camera: {nickname} -> {ip} ({model})")
            else:
                print(f"[WARN] Skipping camera {nickname} (missing P2P info: ip={ip}, uid={uid}, enr={enr})")
        
        # Atomically update global state
        app.state.camera_manifest = new_manifest
                
        # Boot up go2rtc in background with discovered cameras
        if go2rtc_cameras:
            start_go2rtc(go2rtc_cameras)
        else:
            print("[WARN] No cameras with complete P2P info found to stream.")
            
    except Exception as e:
        print(f"[ERROR] Initialization failure: {e}")
        if not hasattr(app.state, 'camera_manifest') or not app.state.camera_manifest:
            app.state.camera_manifest = []
        raise e

def get_lan_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def is_virtual_or_loopback_ip(ip: str) -> bool:
    """
    Returns True for IPs that belong to virtual adapters and should be excluded
    from the LAN access list shown to the user:
      - 127.x.x.x    — loopback
      - 172.16–31.x  — WSL2, Docker, Hyper-V virtual switches (RFC 1918 /12 block)
      - 169.254.x.x  — APIPA / link-local (no DHCP / cable unplugged)
      - 100.64–127.x — Tailscale, CGN, OpenVPN tun adapters (RFC 6598 /10 block)
    """
    parts = ip.split(".")
    if len(parts) != 4:
        return True
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return True

    if a == 127:
        return True                       # loopback
    if a == 169 and b == 254:
        return True                       # APIPA / link-local
    if a == 172 and 16 <= b <= 31:
        return True                       # WSL2 / Docker / Hyper-V virtual switches
    if a == 100 and 64 <= b <= 127:
        return True                       # Tailscale / CGN / VPN tun (RFC 6598)
    return False

def get_all_lan_ips():
    import socket
    ips = []
    try:
        hostname = socket.gethostname()
        _, _, ip_list = socket.gethostbyname_ex(hostname)
        for ip in ip_list:
            if not is_virtual_or_loopback_ip(ip):
                ips.append(ip)
    except Exception:
        pass
    
    default_ip = get_lan_ip()
    if default_ip not in ips and not is_virtual_or_loopback_ip(default_ip):
        ips.append(default_ip)
        
    if not ips:
        ips.append("127.0.0.1")
        
    return list(sorted(set(ips)))


# Interceptor Helper
def is_setup_required() -> bool:
    return not all([WYZE_EMAIL, WYZE_PASSWORD, WYZE_CLIENT_ID, WYZE_API_KEY])

# Routes
@app.get("/", response_class=HTMLResponse)
async def render_dashboard(request: Request):
    """Renders the high-performance grid layout if authorized."""
    if is_setup_required():
        return RedirectResponse(url="/setup", status_code=status.HTTP_303_SEE_OTHER)
        
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        
    lan_ip = get_lan_ip()
    lan_ips = get_all_lan_ips()
    is_host = request.client.host in ("127.0.0.1", "::1", "localhost")
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"cameras": app.state.camera_manifest, "lan_ip": lan_ip, "lan_ips": lan_ips, "is_host": is_host}
    )

@app.get("/login", response_class=HTMLResponse)
async def get_login(request: Request):
    """Renders the cyber login gate."""
    if is_setup_required():
        return RedirectResponse(url="/setup", status_code=status.HTTP_303_SEE_OTHER)
        
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": None}
    )

@app.post("/login", response_class=HTMLResponse)
async def post_login(request: Request, password: str = Form(...)):
    """Verifies portal access credentials and issues cookie."""
    if is_setup_required():
        return RedirectResponse(url="/setup", status_code=status.HTTP_303_SEE_OTHER)
        
    if password == WEB_PASSWORD:
        response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="matrix_auth", value="authorized", max_age=86400 * 30, httponly=True)
        return response
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "INCORRECT ACCESS CODE"}
    )

@app.get("/setup", response_class=HTMLResponse)
async def get_setup(request: Request):
    """Renders the step-by-step security wizard install gate."""
    if not is_setup_required():
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request=request,
        name="setup.html",
        context={"error": None}
    )

@app.post("/setup", response_class=HTMLResponse)
async def post_setup(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    client_id: str = Form(...),
    api_key: str = Form(...),
    web_password: str = Form(...)
):
    """Dynamically writes setup values to persistence base and registers device discover pipelines."""
    global WYZE_EMAIL, WYZE_PASSWORD, WYZE_CLIENT_ID, WYZE_API_KEY, WEB_PASSWORD
    
    email = email.strip()
    password = password.strip()
    client_id = client_id.strip()
    api_key = api_key.strip()
    web_password = web_password.strip()
    
    if not all([email, password, client_id, api_key, web_password]):
        return templates.TemplateResponse(
            request=request,
            name="setup.html",
            context={"error": "All fields are required."}
        )
        
    current_interval = os.environ.get("RESTART_INTERVAL", "0")
    
    # Write Dynamic configurations to .env next to running runner
    env_path = os.path.join(current_dir, ".env")
    env_lines = [
        "# Wyze Account Credentials",
        f"WYZE_EMAIL={email}",
        f"WYZE_PASSWORD={password}",
        "",
        "# Wyze Developer API Keys",
        f"WYZE_CLIENT_ID={client_id}",
        f"WYZE_API_KEY={api_key}",
        "",
        "# Web Portal Access Settings",
        f"WEB_PASSWORD={web_password}",
        "",
        "# Advanced Options",
        f"RESTART_INTERVAL={current_interval}"
    ]
    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(env_lines))
    except Exception as e:
        return templates.TemplateResponse(
            request=request,
            name="setup.html",
            context={"error": f"Failed to save configurations: {e}"}
        )
        
    # Hot re-apply configurations
    WYZE_EMAIL = email
    WYZE_PASSWORD = password
    WYZE_CLIENT_ID = client_id
    WYZE_API_KEY = api_key
    WEB_PASSWORD = web_password
    
    print("[WIZARD] Hot-rebooting camera discovery matrix dynamically...")
    try:
        if boot_lock:
            async with boot_lock:
                await asyncio.to_thread(boot_matrix)
        else:
            boot_matrix()
    except Exception as e:
        return templates.TemplateResponse(
            request=request,
            name="setup.html",
            context={"error": f"Wyze Verification Failure: {e}"}
        )
        
    # Connect user directly by baking auth cookie
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key="matrix_auth", value="authorized", max_age=86400 * 30, httponly=True)
    return response

def shutdown_worker():
    """Background thread worker to shut down server cleanly after short delay."""
    time.sleep(1.0)
    print("[SYSTEM] Shutting down Aura Core cleanly...")
    global go2rtc_process
    if go2rtc_process:
        try:
            go2rtc_process.kill()
        except:
            pass
        go2rtc_process = None
    # Send SIGINT to own process to shut down uvicorn cleanly
    os.kill(os.getpid(), signal.SIGINT)

@app.post("/api/system/shutdown")
async def shutdown_system(request: Request):
    """Safely shuts down the background server and go2rtc process."""
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if request.client.host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Forbidden: System operations only allowed on the host machine.")
    threading.Thread(target=shutdown_worker).start()
    return {"status": "success", "message": "Server shutting down..."}

@app.post("/api/system/restart_streams")
async def restart_streams(request: Request):
    """Refreshes camera feeds and hot-reboots go2rtc configuration pipelines."""
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if request.client.host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Forbidden: System operations only allowed on the host machine.")
    print("[SYSTEM] Hot-rebooting camera pipeline...")
    try:
        if boot_lock:
            async with boot_lock:
                await asyncio.to_thread(boot_matrix)
        else:
            await asyncio.to_thread(boot_matrix)
        for q in stream_event_queues:
            q.put_nowait("restart")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "success", "message": "Streaming restarted successfully."}

async def event_generator(request: Request):
    q = asyncio.Queue()
    stream_event_queues.append(q)
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(q.get(), timeout=15.0)
                yield f"data: {msg}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        if q in stream_event_queues:
            stream_event_queues.remove(q)

@app.get("/api/system/events")
async def system_events(request: Request):
    """SSE endpoint to notify connected clients of system events (e.g., stream restart)."""
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return StreamingResponse(event_generator(request), media_type="text/event-stream")

@app.get("/logout")
async def logout():
    """Clears credential session and redirects to gateway."""
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("matrix_auth")
    return response

def kill_matrix_workers():
    """Clean up background go2rtc process on server shutdown."""
    global go2rtc_process, go2rtc_log_file
    if go2rtc_process:
        print("Terminating native go2rtc streaming engine cleanly...")
        try:
            go2rtc_process.kill()
            go2rtc_process.wait(timeout=2)
        except:
            pass
        go2rtc_process = None
        
    if go2rtc_log_file:
        try:
            go2rtc_log_file.close()
        except:
            pass
        go2rtc_log_file = None

if __name__ == "__main__":
    import uvicorn
    # Bind to 0.0.0.0 so other devices on the network can connect
    print("Starting Aura Home Security Matrix portal on local network...")
    if getattr(sys, 'frozen', False):
        import threading
        import webbrowser
        def open_browser():
            time.sleep(1.5)
            try:
                webbrowser.open("http://localhost:8000")
            except:
                pass
        threading.Thread(target=open_browser, daemon=True).start()
        uvicorn.run(app, host="0.0.0.0", port=8000)
    else:
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)