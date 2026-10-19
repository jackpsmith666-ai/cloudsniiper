#!/usr/bin/env python3
"""
Headless Ultra-Fast Minecraft Name Sniper (24/7 Cloud Edition)
Precision Drop-Timing Engine with Render Keep-Alive Server
Target IGN: lineage | Drop Time: 10/19/2026 8:24:35 AM
"""

import os
import sys
import time
import json
import threading
import urllib.request
import urllib.error
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta

# =====================================================================
# CONFIGURATION
# =====================================================================
TARGET_IGN = "lineage"

# Target Drop Timestamp: 10/19/2026 08:24:35 AM Local Time (UTC+1 / 07:24:35 UTC)
# UNIX Timestamp: 1792394675.0
DEFAULT_DROP_TIMESTAMP = 1792394675.0

# Pre-Drop Monitoring Mode
MONITOR_INTERVAL_SEC = 10.0   # Gentle heartbeat to keep connections warm and detect early release

# Hyper-Burst Snipe Mode (Activates at T - 5 seconds)
BURST_LEAD_TIME_SEC = 5.0     # Start hyper-burst 5 seconds before drop
BURST_WINDOW_SEC = 45.0       # Maintain hyper-burst for 45 seconds through and after drop
BURST_INTERVAL_MS = 5         # Hyper-burst interval per thread in milliseconds
BURST_THREADS = 4             # Staggered concurrent worker threads (Effective 1.25ms interval!)

USE_PROXIES = True
PROXIES_FILE = "proxies.txt"
TOKEN_FILE = "bearer.txt"
WEBHOOK_FILE = "webhook.txt"

# Thread-safe State
running = True
sniped_success = False
sniper_attempts = 0
last_http_code = 0
last_attempt_time = 0.0
rate_limited_until = 0.0
lock = threading.Lock()
start_time = time.time()
active_proxies = []

# =====================================================================
# LOGGING & NOTIFICATIONS
# =====================================================================
def log(msg, color="white"):
    now_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    colors = {
        "green": "\033[92m",
        "red": "\033[91m",
        "yellow": "\033[93m",
        "cyan": "\033[96m",
        "magenta": "\033[95m",
        "white": "\033[0m"
    }
    col = colors.get(color, "\033[0m")
    print(f"{col}[{now_str}] {msg}\033[0m", flush=True)

def load_file_content(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""

def send_discord_webhook(webhook_url, target, content_msg, color_int=3066993):
    if not webhook_url or not webhook_url.startswith("http"):
        return
    payload = {
        "content": f"ðŸŽ¯ **[NAME SNIPER ALERT]** {content_msg}",
        "embeds": [{
            "title": f"Minecraft Name Sniper: {target}",
            "description": content_msg,
            "color": color_int,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }]
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(webhook_url, data=data, headers={
            "Content-Type": "application/json",
            "User-Agent": "HeadlessSniper/2.0"
        })
        urllib.request.urlopen(req, timeout=4)
    except Exception as e:
        log(f"Webhook delivery notice: {e}", "yellow")

# =====================================================================
# PROXY MANAGEMENT
# =====================================================================
def fetch_fresh_proxies():
    global active_proxies
    log("Refreshing rotating proxy pool...", "cyan")
    proxies = []
    urls = [
        "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=3000&country=all&ssl=yes&anonymity=elite",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"
    ]
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                text = resp.read().decode("utf-8", errors="ignore")
                for line in text.splitlines():
                    clean = line.strip()
                    if clean and not clean.startswith("#") and ":" in clean:
                        proxies.append(clean)
                        if len(proxies) >= 150:
                            break
            if len(proxies) >= 50:
                break
        except Exception:
            continue
    
    if proxies:
        with lock:
            active_proxies = proxies
        try:
            with open(PROXIES_FILE, "w", encoding="utf-8") as f:
                for p in proxies:
                    f.write(p + "\n")
        except Exception:
            pass
        log(f"Proxy pool updated: {len(proxies)} live rotating proxies loaded!", "green")
    return proxies

def load_proxies():
    global active_proxies
    if os.path.exists(PROXIES_FILE) and os.path.getsize(PROXIES_FILE) > 0:
        proxies = []
        with open(PROXIES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                clean = line.strip()
                if clean and not clean.startswith("#") and ":" in clean:
                    proxies.append(clean)
        if proxies:
            active_proxies = proxies
            return proxies
    return fetch_fresh_proxies()

# =====================================================================
# RENDER KEEP-ALIVE & STATUS HTTP SERVER
# =====================================================================
class SniperStatusHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress noisy HTTP access logs in stdout
        return

    def do_GET(self):
        global sniper_attempts, last_http_code, sniped_success
        now = time.time()
        drop_time = get_drop_timestamp()
        time_left = drop_time - now
        
        status_text = "SNIPED SUCCESSFULLY!" if sniped_success else (
            "HYPER-BURST ACTIVE!" if -BURST_WINDOW_SEC <= time_left <= BURST_LEAD_TIME_SEC else "ARMED & STANDING BY"
        )

        hours = int(max(0, time_left) // 3600)
        minutes = int((max(0, time_left) % 3600) // 60)
        seconds = int(max(0, time_left) % 60)
        countdown_str = f"{hours:02d}h {minutes:02d}m {seconds:02d}s"

        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = json.dumps({
                "status": "ok",
                "target": TARGET_IGN,
                "state": status_text,
                "seconds_to_drop": round(time_left, 2),
                "attempts": sniper_attempts,
                "last_http_code": last_http_code,
                "sniped": sniped_success
            })
            self.wfile.write(resp.encode("utf-8"))
            return

        # HTML Live Dashboard
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Minecraft Cloud Sniper - {TARGET_IGN}</title>
    <meta http-equiv="refresh" content="3">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 40px; }}
        .card {{ background: #1e293b; max-width: 650px; margin: 0 auto; border-radius: 12px; padding: 30px; box-shadow: 0 8px 24px rgba(0,0,0,0.4); border: 1px solid #334155; }}
        h1 {{ color: #38bdf8; margin-top: 0; font-size: 28px; }}
        .target {{ font-size: 36px; font-weight: bold; color: #4ade80; letter-spacing: 2px; }}
        .badge {{ display: inline-block; padding: 6px 14px; border-radius: 20px; font-size: 14px; font-weight: bold; background: #0284c7; color: white; margin-top: 10px; }}
        .countdown {{ font-size: 32px; font-family: monospace; color: #facc15; margin: 20px 0; }}
        .stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-top: 25px; }}
        .stat-box {{ background: #0f172a; padding: 15px; border-radius: 8px; border: 1px solid #334155; }}
        .stat-label {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; }}
        .stat-val {{ font-size: 22px; font-weight: bold; margin-top: 5px; color: #f8fafc; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>ðŸŽ¯ 24/7 Cloud Name Sniper</h1>
        <div class="target">{TARGET_IGN}</div>
        <div class="badge">{status_text}</div>
        <div class="countdown">â³ Drop in: {countdown_str}</div>
        <p style="color: #94a3b8;">Scheduled Drop: 10/19/2026 &bull; 8:24:35 AM</p>
        <div class="stats">
            <div class="stat-box">
                <div class="stat-label">Total Attempts</div>
                <div class="stat-val">{sniper_attempts:,}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Last API Response</div>
                <div class="stat-val">HTTP {last_http_code}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Active Proxies</div>
                <div class="stat-val">{len(active_proxies)}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Hyper-Burst Speed</div>
                <div class="stat-val">5ms (4 Threads)</div>
            </div>
        </div>
    </div>
</body>
</html>"""
        self.wfile.write(html.encode("utf-8"))

def start_http_server(port):
    try:
        server = HTTPServer(("0.0.0.0", port), SniperStatusHandler)
        log(f"Render Keep-Alive Server listening on 0.0.0.0:{port} (Prevents timeouts & sleep)", "green")
        server.serve_forever()
    except Exception as e:
        log(f"HTTP Server warning: {e}", "yellow")

def self_ping_worker(port):
    """Periodically ping local HTTP server to satisfy Render activity requirements"""
    time.sleep(10)
    while running:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
            with urllib.request.urlopen(req, timeout=3) as resp:
                resp.read()
        except Exception:
            pass
        time.sleep(300) # Ping every 5 minutes

# =====================================================================
# CORE SNIPING LOGIC
# =====================================================================
def get_drop_timestamp():
    val = os.getenv("DROP_TIMESTAMP")
    if val:
        try:
            return float(val)
        except ValueError:
            pass
    return DEFAULT_DROP_TIMESTAMP

def single_snipe_attempt(target, token, current_proxy):
    global sniper_attempts, last_http_code, sniped_success, running, rate_limited_until

    url = f"https://api.minecraftservices.com/minecraft/profile/name/{target}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Connection": "keep-alive"
    }

    req = urllib.request.Request(url, method="PUT", headers=headers)
    if current_proxy:
        p_clean = current_proxy if "://" in current_proxy else f"http://{current_proxy}"
        req.set_proxy(p_clean.replace("http://", "").replace("https://", ""), "http")

    status_code = 0
    resp_body = ""
    try:
        with urllib.request.urlopen(req, timeout=1.1) as resp:
            status_code = resp.status
            resp_body = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        status_code = e.code
        try:
            resp_body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
    except Exception:
        # Network / proxy timeout
        return 0, ""

    with lock:
        sniper_attempts += 1
        last_http_code = status_code

    return status_code, resp_body

def burst_worker(thread_id, target, token, webhook_url, drop_time):
    global running, sniped_success, active_proxies, rate_limited_until

    proxy_idx = thread_id
    burst_end_time = drop_time + BURST_WINDOW_SEC

    while running and time.time() < burst_end_time:
        now_ts = time.time()
        if now_ts < rate_limited_until:
            time.sleep(0.05)
            continue

        loop_start = time.perf_counter()

        current_proxy = None
        if active_proxies:
            with lock:
                current_proxy = active_proxies[proxy_idx % len(active_proxies)]
                proxy_idx += 1

        code, body = single_snipe_attempt(target, token, current_proxy)

        # 1. SUCCESS! Claimed!
        if code == 200:
            with lock:
                sniped_success = True
                running = False
            log("*" * 65, "green")
            log(f"ðŸŽ‰ [SNIPED SUCCESS!] IGN '{target}' successfully claimed! (HTTP 200)", "green")
            log(f"Response: {body}", "green")
            log("*" * 65, "green")
            send_discord_webhook(webhook_url, target, f"ðŸ† **Successfully sniped `{target}`!** Account updated.")
            break

        # 2. Token expired (Fatal)
        if code == 401:
            log(f"[FATAL] Bearer Token expired or invalid (HTTP 401).", "red")
            send_discord_webhook(webhook_url, target, "âš ï¸ Sniper halted: Minecraft token expired.", color_int=15158332)
            running = False
            break

        # 3. Rate limited on proxy
        if code == 429:
            time.sleep(0.01)
            continue

        # Micro-interval pacing for hyper-burst
        elapsed_ms = (time.perf_counter() - loop_start) * 1000.0
        if BURST_INTERVAL_MS > elapsed_ms:
            time.sleep((BURST_INTERVAL_MS - elapsed_ms) / 1000.0)

# =====================================================================
# MAIN LIFECYCLE CONTROLLER
# =====================================================================
def main():
    global running, sniped_success, active_proxies

    target = os.getenv("SNIPER_TARGET", TARGET_IGN).strip()
    token = os.getenv("MINECRAFT_BEARER_TOKEN", load_file_content(TOKEN_FILE)).strip()
    webhook = os.getenv("DISCORD_WEBHOOK_URL", load_file_content(WEBHOOK_FILE)).strip()
    port = int(os.getenv("PORT", "10000"))
    drop_time = get_drop_timestamp()

    if not token:
        log("ERROR: Minecraft Bearer Token not found! Paste into 'bearer.txt' or set MINECRAFT_BEARER_TOKEN.", "red")
        sys.exit(1)

    load_proxies()

    # Start Render Keep-Alive Server
    http_thread = threading.Thread(target=start_http_server, args=(port,), daemon=True)
    http_thread.start()

    # Start self-ping daemon to guarantee 0% idle spin-down on Render
    ping_thread = threading.Thread(target=self_ping_worker, args=(port,), daemon=True)
    ping_thread.start()

    drop_utc = datetime.fromtimestamp(drop_time, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    now_ts = time.time()
    time_to_drop = drop_time - now_ts

    log("=" * 65, "cyan")
    log("  HEADLESS MINECRAFT NAME SNIPER (PRECISION DROP EDITION)", "cyan")
    log(f"  Target IGN       : {target}", "cyan")
    log(f"  Scheduled Drop   : 10/19/2026 8:24:35 AM ({drop_utc})", "cyan")
    log(f"  Time Remaining   : {round(time_to_drop / 3600, 2)} hours ({int(time_to_drop)}s)", "cyan")
    log(f"  Render KeepAlive : Listening on port {port} (0% Idle Sleep)", "cyan")
    log(f"  Burst Speed      : {BURST_INTERVAL_MS}ms across {BURST_THREADS} Staggered Threads (1.25ms rate)", "cyan")
    log(f"  Webhook Alerts   : {'CONFIGURED' if webhook else 'DISABLED'}", "cyan")
    log("=" * 65, "cyan")

    send_discord_webhook(
        webhook, target,
        f"ðŸš€ **Sniper Armed in Cloud!**\nTarget: `{target}`\nDrop Time: `10/19/2026 8:24:35 AM`\nBurst Rate: `5ms / 4 threads`\nKeep-Alive Server: Active on port {port}"
    )

    alert_3m_sent = False
    alert_1m_sent = False
    proxies_refreshed = False

    # -------------------------------------------------------------
    # STAGE 1: Pre-Drop Monitoring & Standby
    # -------------------------------------------------------------
    proxy_cursor = 0
    while running and (drop_time - time.time()) > BURST_LEAD_TIME_SEC:
        now = time.time()
        remaining = drop_time - now

        # Refresh proxies 3 minutes before drop to ensure pristine, fast connections
        if remaining <= 180 and not proxies_refreshed:
            log("âš¡ T-3 Minutes! Fetching fresh proxy pool for drop...", "yellow")
            fetch_fresh_proxies()
            proxies_refreshed = True
            if not alert_3m_sent:
                send_discord_webhook(webhook, target, "âš¡ **3 MINUTES TO DROP!** Fresh proxy pool loaded. Getting into position...")
                alert_3m_sent = True

        if remaining <= 60 and not alert_1m_sent:
            send_discord_webhook(webhook, target, "ðŸš¨ **60 SECONDS TO DROP!** Hyper-burst engine primed and standing by!")
            alert_1m_sent = True

        # Gentle monitor ping every 10 seconds to detect early drop and keep sockets warm
        current_proxy = None
        if active_proxies:
            current_proxy = active_proxies[proxy_cursor % len(active_proxies)]
            proxy_cursor += 1

        code, body = single_snipe_attempt(target, token, current_proxy)

        if code == 200:
            sniped_success = True
            running = False
            log("*" * 65, "green")
            log(f"ðŸŽ‰ [EARLY DROP SNIPED!] IGN '{target}' claimed ahead of schedule!", "green")
            log("*" * 65, "green")
            send_discord_webhook(webhook, target, f"ðŸ† **EARLY DROP! Successfully claimed `{target}`!**")
            break

        if code == 401:
            log("[FATAL] Bearer Token is invalid or expired (HTTP 401).", "red")
            send_discord_webhook(webhook, target, "âš ï¸ Sniper stopped: Minecraft bearer token is invalid (HTTP 401).")
            running = False
            break

        # Log countdown progress once a minute
        hrs = int(remaining // 3600)
        mins = int((remaining % 3600) // 60)
        secs = int(remaining % 60)
        log(f"[COUNTDOWN] {hrs:02d}h {mins:02d}m {secs:02d}s until drop | Check: HTTP {code} | Proxies: {len(active_proxies)}", "white")

        # Sleep up to MONITOR_INTERVAL_SEC or until T - BURST_LEAD_TIME_SEC
        sleep_dur = min(MONITOR_INTERVAL_SEC, max(0.5, remaining - BURST_LEAD_TIME_SEC))
        time.sleep(sleep_dur)

    # -------------------------------------------------------------
    # STAGE 2: Hyper-Burst Snipe Window
    # -------------------------------------------------------------
    if running and not sniped_success:
        log("!" * 65, "magenta")
        log(f"ðŸ”¥ [HYPER-BURST ENGAGED] Unleashing {BURST_THREADS} threads @ {BURST_INTERVAL_MS}ms interval!", "magenta")
        log("!" * 65, "magenta")

        threads = []
        for i in range(BURST_THREADS):
            t = threading.Thread(target=burst_worker, args=(i, target, token, webhook, drop_time), daemon=True)
            t.start()
            threads.append(t)
            time.sleep(BURST_INTERVAL_MS / (BURST_THREADS * 1000.0))

        for t in threads:
            t.join()

    log("=" * 65, "cyan")
    log("  SNIPER OPERATION COMPLETED", "cyan")
    log(f"  Final Status   : {'CLAIMED! ðŸŽ‰' if sniped_success else 'COMPLETED'}", "cyan")
    log(f"  Total Attempts : {sniper_attempts:,}", "cyan")
    log("=" * 65, "cyan")

    # Keep server alive for log inspection
    while running and not sniped_success:
        time.sleep(1)

if __name__ == "__main__":
    main()
