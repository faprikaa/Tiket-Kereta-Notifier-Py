"""Cloudflare Tunnel integration.

Starts a quick tunnel via `cloudflared` and extracts the
generated public URL for use as a Telegram webhook endpoint.

Auto-downloads the cloudflared binary if not already installed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import stat
import sys

logger = logging.getLogger(__name__)

# Where to store the downloaded binary
_BINARY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bin")


def _get_cloudflared_path() -> str:
    """Get the path to the cloudflared binary, downloading if needed."""
    # Check if already on PATH
    import shutil

    system_binary = shutil.which("cloudflared")
    if system_binary:
        logger.debug("Using system cloudflared: %s", system_binary)
        return system_binary

    # Check local download
    binary_name = "cloudflared.exe" if sys.platform == "win32" else "cloudflared"
    local_path = os.path.join(_BINARY_DIR, binary_name)

    if os.path.isfile(local_path):
        logger.debug("Using local cloudflared: %s", local_path)
        return local_path

    # Download it
    logger.info("cloudflared not found, downloading automatically...")
    _download_cloudflared(local_path)
    return local_path


def _download_cloudflared(target_path: str) -> None:
    """Download the cloudflared binary from GitHub releases."""
    import urllib.request

    system = platform.system().lower()
    machine = platform.machine().lower()

    # Map to cloudflared release names
    if system == "linux":
        if machine in ("x86_64", "amd64"):
            filename = "cloudflared-linux-amd64"
        elif machine in ("aarch64", "arm64"):
            filename = "cloudflared-linux-arm64"
        elif machine.startswith("arm"):
            filename = "cloudflared-linux-arm"
        else:
            raise RuntimeError(f"Unsupported Linux architecture: {machine}")
    elif system == "darwin":
        if machine in ("arm64", "aarch64"):
            filename = "cloudflared-darwin-amd64.tgz"  # universal binary
        else:
            filename = "cloudflared-darwin-amd64.tgz"
    elif system == "windows":
        if machine in ("amd64", "x86_64"):
            filename = "cloudflared-windows-amd64.exe"
        else:
            filename = "cloudflared-windows-386.exe"
    else:
        raise RuntimeError(f"Unsupported OS: {system}")

    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/{filename}"

    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    logger.info("Downloading cloudflared from %s", url)
    urllib.request.urlretrieve(url, target_path)

    # Make executable on Unix
    if system != "windows":
        st = os.stat(target_path)
        os.chmod(target_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    logger.info("cloudflared downloaded to %s", target_path)


class CloudflaredTunnel:
    """Manages a cloudflared quick tunnel subprocess."""

    def __init__(self, local_port: int) -> None:
        self._local_port = local_port
        self._process: asyncio.subprocess.Process | None = None
        self._url: str | None = None

    @property
    def url(self) -> str | None:
        """The public tunnel URL (e.g. https://xxx.trycloudflare.com)."""
        return self._url

    async def start(self, timeout: float = 30.0) -> str:
        """Start cloudflared quick tunnel and return the public URL.

        Auto-downloads the binary if not installed.

        Args:
            timeout: Max seconds to wait for the tunnel URL.

        Returns:
            The public HTTPS URL.

        Raises:
            RuntimeError: If cloudflared fails to start or URL not found.
        """
        binary = _get_cloudflared_path()

        cmd = [
            binary, "tunnel",
            "--url", f"http://localhost:{self._local_port}",
            "--no-autoupdate",
        ]

        logger.info(
            "Starting cloudflared tunnel → http://localhost:%d", self._local_port
        )

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to start cloudflared: {e}")

        # cloudflared prints the URL to stderr
        url = await self._wait_for_url(timeout)
        if not url:
            await self.stop()
            raise RuntimeError(
                f"Failed to get tunnel URL within {timeout}s. "
                "Check cloudflared output."
            )

        self._url = url
        logger.info("Cloudflared tunnel ready: %s", url)
        return url

    async def _wait_for_url(self, timeout: float) -> str | None:
        """Read stderr line by line looking for the tunnel URL."""
        url_pattern = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")

        async def _read_lines() -> str | None:
            while True:
                if self._process is None or self._process.stderr is None:
                    return None

                line = await self._process.stderr.readline()
                if not line:
                    break

                decoded = line.decode("utf-8", errors="replace").strip()
                if decoded:
                    logger.debug("cloudflared: %s", decoded)

                match = url_pattern.search(decoded)
                if match:
                    return match.group(0)
            return None

        try:
            return await asyncio.wait_for(_read_lines(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def stop(self) -> None:
        """Stop the cloudflared tunnel."""
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass
            self._process = None
            logger.info("Cloudflared tunnel stopped")
