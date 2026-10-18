#!/usr/bin/env python3
"""
Headless High-Speed Minecraft Name Sniper (24/7 Cloud Edition)
Runs continuously in the cloud even when your personal PC is powered off.
Supports: Linux VPS (Ubuntu/Debian), Windows VPS, Docker, Railway, Render, Oracle Cloud Free Tier, AWS EC2.
"""

import os
import sys
import time
import json
import threading
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

TARGET_IGN = "lineage"
INTERVAL_MS = 20           # Interval between attempts in milliseconds
THREADS = 2                # Staggered concurrent worker threads
USE_PROXIES = True
PROXIES_FILE = "proxies.txt"
TOKEN_FILE = "bearer.txt"
WEBHOOK_FILE = "webhook.txt"

# Thread-safe states
running = True
sniper_attempts = 0
sniper_success = 0
last_log_time = 0
lock = threading.Lock()
rate_limited_until = 0.0

def log(msg, color="white"):
    now_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    colors = {
        "green": "\033[92m",
        "red": "\033[91m",
        "yellow": "\033[93m",
        "cyan": "\033[96m",
        "white": "\033[0m"
    }
    col = colors.get(color, "\033[0m")
    print(f"{col}[{now_str}] {msg}\033[0m", flush=True)

def load_file_content(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""

def send_discord_webhook(webhook_url, target, content_msg):
    if not webhook_url or not webhook_url.startswith("http"):
        return
    payload = {
        "content": f"🎯 **[NAME SNIPER ALERT]** {content_msg}",
        "embeds": [{
            "title": "Minecraft IGN Sniped!",
            "description": f"Successfully claimed: **`{target}`**",
            "color": 3066993, # Emerald green
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }]
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(webhook_url, data=data, headers={
            "Content-Type": "application/json",
            "User-Agent": "HeadlessSniper/1.0"
        })
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        log(f"Webhook delivery failed: {e}", "red")

def fetch_free_proxies():
    log("Fetching public rotating proxies for sniper...", "cyan")
    proxies = []
    urls = [
        "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=3500&country=all&ssl=yes&anonymity=elite",
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
            if proxies:
                break
        except Exception:
            continue
    if proxies:
        with open(PROXIES_FILE, "w", encoding="utf-8") as f:
            for p in proxies:
                f.write(p + "\n")
        log(f"Successfully loaded {len(proxies)} rotating proxies into {PROXIES_FILE}!", "green")
    return proxies

def load_proxies():
    if not os.path.exists(PROXIES_FILE) or os.path.getsize(PROXIES_FILE) == 0:
        return fetch_free_proxies()
    proxies = []
    with open(PROXIES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            clean = line.strip()
            if clean and not clean.startswith("#") and ":" in clean:
                proxies.append(clean)
    return proxies

def sniper_worker(thread_id, target, token, interval_ms, webhook_url, proxies):
    global running, sniper_attempts, sniper_success, last_log_time, rate_limited_until
    
    url = f"https://api.minecraftservices.com/minecraft/profile/name/{target}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Connection": "keep-alive"
    }

    proxy_idx = thread_id

    while running:
        # Rate-limit barrier check
        now_ts = time.time()
        if rate_limited_until > now_ts:
            time.sleep(min(rate_limited_until - now_ts, 0.1))
            continue

        loop_start = time.perf_counter()

        current_proxy = None
        if USE_PROXIES and proxies:
            current_proxy = proxies[proxy_idx % len(proxies)]
            proxy_idx += 1

        req = urllib.request.Request(url, method="PUT", headers=headers)
        if current_proxy:
            proxy_clean = current_proxy if "://" in current_proxy else f"http://{current_proxy}"
            req.set_proxy(proxy_clean.replace("http://", "").replace("https://", ""), "http")

        status_code = 0
        resp_body = ""
        try:
            with urllib.request.urlopen(req, timeout=1.2) as resp:
                status_code = resp.status
                resp_body = resp.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:
            status_code = e.code
            try:
                resp_body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
        except Exception:
            # Network/Proxy timeout: rapid failover to next proxy
            time.sleep(0.01)
            continue

        with lock:
            sniper_attempts += 1
            cur_attempts = sniper_attempts

        now_sec = time.time()

        # 1. Success! (HTTP 200)
        if status_code == 200:
            with lock:
                sniper_success += 1
                running = False
            log("*" * 65, "green")
            log(f"[SNIPED SUCCESS!] IGN '{target}' successfully claimed! (HTTP 200)", "green")
            log(f"Response: {resp_body}", "green")
            log("*" * 65, "green")
            send_discord_webhook(webhook_url, target, f"Claimed **`{target}`** on attempt #{cur_attempts}!")
            break

        # 2. Token Expired / Invalid (HTTP 401)
        if status_code == 401:
            log(f"[ERROR] Invalid or expired Minecraft Bearer Token (HTTP 401). Stopping sniper.", "red")
            send_discord_webhook(webhook_url, target, "Sniper stopped: Bearer Token is invalid or expired (HTTP 401).")
            running = False
            break

        # 3. Rate Limited (HTTP 429)
        if status_code == 429:
            if current_proxy:
                # Individual proxy rate limited: failover immediately to next proxy
                time.sleep(0.01)
                continue
            else:
                # Direct IP rate limited: pause 3s
                with lock:
                    rate_limited_until = time.time() + 3.0
                log("[RATE LIMIT] Direct IP rate-limited (HTTP 429). Pausing 3s...", "yellow")
                time.sleep(0.2)
                continue

        # 4. Normal attempt: Not available yet (HTTP 403, HTTP 400) - Non-fatal!
        with lock:
            if now_sec - last_log_time >= 1.0:
                log(f"[ATTEMPT #{cur_attempts}] Forcefully sent change-name to '{target}' -> HTTP {status_code} (Not dropped yet)", "white")
                last_log_time = now_sec

        # Microsecond interval pacing
        elapsed_ms = (time.perf_counter() - loop_start) * 1000.0
        if interval_ms > elapsed_ms:
            time.sleep((interval_ms - elapsed_ms) / 1000.0)

def main():
    target = os.getenv("SNIPER_TARGET", TARGET_IGN).strip()
    interval = int(os.getenv("SNIPER_INTERVAL_MS", str(INTERVAL_MS)))
    token = os.getenv("MINECRAFT_BEARER_TOKEN", load_file_content(TOKEN_FILE)).strip()
    webhook = os.getenv("DISCORD_WEBHOOK_URL", load_file_content(WEBHOOK_FILE)).strip()

    if not token:
        log("ERROR: Minecraft Bearer Token not found! Paste your token into 'bearer.txt' or set MINECRAFT_BEARER_TOKEN env var.", "red")
        sys.exit(1)

    proxies = load_proxies() if USE_PROXIES else []
    route_info = f"Routing via {len(proxies)} Rotating Proxies" if proxies else "Direct Connection"

    log("=" * 65, "cyan")
    log(f"  HEADLESS MINECRAFT NAME SNIPER (24/7 CLOUD DAEMON)", "cyan")
    log(f"  Target IGN     : {target}", "cyan")
    log(f"  Interval       : {interval}ms ({THREADS} Staggered Threads)", "cyan")
    log(f"  Network Mode   : {route_info}", "cyan")
    log(f"  Webhook Alerts : {'CONFIGURED' if webhook else 'DISABLED'}", "cyan")
    log("=" * 65, "cyan")

    threads = []
    for i in range(THREADS):
        t = threading.Thread(target=sniper_worker, args=(i, target, token, interval, webhook, proxies), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(interval / (THREADS * 1000.0))

    try:
        while running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        log("Stopping sniper by user request...", "yellow")

if __name__ == "__main__":
    main()
