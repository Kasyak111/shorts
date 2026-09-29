"""
Tunnel Manager for Telegram Mini Apps.
Automatically spins up an instant Cloudflare Quick Tunnel (free, no sign-up needed)
to give a public HTTPS domain required by Telegram Mini Apps.
"""

import os
import sys
import re
import asyncio
import subprocess
import logging
from typing import Optional

logger = logging.getLogger("tunnel_manager")

class TunnelManager:
    def __init__(self, port: int = 8080, bin_path: str = "cloudflared.exe"):
        self.port = port
        self.bin_path = bin_path
        self.process: Optional[asyncio.subprocess.Process] = None
        self.public_url: Optional[str] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> Optional[str]:
        """Starts cloudflared tunnel and captures public HTTPS URL."""
        if not os.path.exists(self.bin_path):
            logger.warning(f"cloudflared binary not found at '{self.bin_path}'. Tunnel not started.")
            return None

        cmd = [
            self.bin_path,
            "tunnel",
            "--url", f"http://127.0.0.1:{self.port}"
        ]

        logger.info(f"🚀 Запуск Cloudflare Quick Tunnel на порту {self.port}...")
        try:
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )

            # Read stream until URL is caught or timeout (15s)
            url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
            
            for _ in range(60):
                if self.process.returncode is not None:
                    break
                try:
                    line_bytes = await asyncio.wait_for(self.process.stdout.readline(), timeout=0.5)
                    if not line_bytes:
                        break
                    line = line_bytes.decode("utf-8", errors="replace").strip()
                    m = url_pattern.search(line)
                    if m:
                        self.public_url = m.group(0)
                        logger.info(f"✅ Cloudflare Tunnel активен! Публичный HTTPS URL: {self.public_url}")
                        # Launch background task to keep reading stdout so pipe does not fill up
                        asyncio.create_task(self._drain_stdout())
                        return self.public_url
                except asyncio.TimeoutError:
                    continue

        except Exception as e:
            logger.error(f"Ошибка запуска cloudflared: {e}")

        return self.public_url

    async def _drain_stdout(self):
        """Continuously reads stdout until process terminates."""
        try:
            while self.process and self.process.returncode is None:
                line = await self.process.stdout.readline()
                if not line:
                    break
        except Exception:
            pass

    async def stop(self):
        """Stops the tunnel process gracefully."""
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=3.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
            logger.info("🛑 Cloudflare Tunnel остановлен.")

if __name__ == "__main__":
    async def _test():
        tm = TunnelManager(8080)
        url = await tm.start()
        print("Tunnel URL:", url)
        if url:
            await asyncio.sleep(5)
            await tm.stop()

    asyncio.run(_test())
