import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import urllib.request
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("launcher")


def start_webapp_server(port: int = 8080) -> subprocess.Popen:
    logger.info("Starting WebApp server on port %d...", port)
    env = os.environ.copy()
    env["WEBAPP_PORT"] = str(port)
    proc = subprocess.Popen(
        [sys.executable, "-m", "webapp.server"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    return proc


def start_tunnel(port: int = 8080) -> subprocess.Popen:
    logger.info("Starting ngrok tunnel on port %d...", port)
    proc = subprocess.Popen(
        ["ngrok", "http", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    return proc


async def get_tunnel_url(max_retries: int = 15) -> Optional[str]:
    for _ in range(max_retries):
        await asyncio.sleep(1)
        try:
            req = urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2)
            data = json.loads(req.read().decode())
            tunnels = data.get("tunnels", [])
            for t in tunnels:
                url = t.get("public_url", "")
                if url.startswith("https://"):
                    return f"{url}?ngrok-skip-browser-warning=1"
        except Exception:
            continue
    return None


def update_env_webapp_url(url: str) -> None:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    updated = False
    new_lines = []
    for line in lines:
        if line.startswith("WEBAPP_URL="):
            new_lines.append(f"WEBAPP_URL={url}\n")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"WEBAPP_URL={url}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    os.environ["WEBAPP_URL"] = url
    logger.info("Updated .env with WEBAPP_URL: %s", url)


async def main() -> None:
    parser = argparse.ArgumentParser(description="PrivateRoom All-in-One Launcher")
    parser.add_argument("--mode", choices=["admin", "worker", "webapp-only"], default="worker", help="Run mode")
    parser.add_argument("--token", help="Worker bot token")
    args = parser.parse_args()

    webapp_proc = start_webapp_server(8080)
    tunnel_proc = start_tunnel(8080)

    try:
        url = await get_tunnel_url()
        if url:
            logger.info("Active WebApp URL: %s", url)
            update_env_webapp_url(url)
        else:
            logger.warning("Could not automatically retrieve tunnel URL.")

        if args.mode == "worker":
            token = args.token or os.environ.get("ADMIN_BOT_TOKEN")
            if not token:
                logger.error("Please provide --token <BOT_TOKEN>")
                return
            from worker_bot.core import run_worker
            await run_worker(token)
        elif args.mode == "admin":
            from admin_bot.main import main as admin_main
            await admin_main()
        elif args.mode == "webapp-only":
            logger.info("Running in WebApp-only mode. Press Ctrl+C to stop.")
            while True:
                await asyncio.sleep(3600)
    finally:
        logger.info("Stopping processes...")
        webapp_proc.terminate()
        tunnel_proc.terminate()


if __name__ == "__main__":
    asyncio.run(main())
