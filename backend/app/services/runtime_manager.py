import asyncio
import logging
import socket
import subprocess
import sys
from pathlib import Path

import httpx

from app.services.execution_engine import file_manager

logger = logging.getLogger(__name__)


class RuntimeManager:
    def __init__(self):
        self.processes: dict[str, subprocess.Popen] = {}
        self._ports: dict[str, int] = {}

    def _port(self) -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    async def start_static(self, project_id: str) -> tuple[str, int]:
        project = (file_manager.root / project_id).resolve()
        static_root = (project / "frontend").resolve()
        if not project.is_relative_to(file_manager.root) or not static_root.is_relative_to(project) or not (static_root / "index.html").is_file():
            raise ValueError("Static project workspace is invalid")
        existing = self.processes.get(project_id)
        if existing and existing.poll() is None:
            return f"http://127.0.0.1:{self._ports[project_id]}/", existing.pid
        port = self._port()
        args = [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(static_root)]
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        process = subprocess.Popen(args, cwd=str(static_root), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False, **options)
        self.processes[project_id] = process
        self._ports[project_id] = port
        preview_url = f"http://127.0.0.1:{port}/"
        try:
            async with httpx.AsyncClient(timeout=1) as client:
                for _ in range(20):
                    if process.poll() is not None:
                        raise RuntimeError("Static preview server exited during startup")
                    try:
                        response = await client.get(preview_url)
                        if response.status_code == 200:
                            logger.info("[RUNTIME] preview started project=%s port=%d pid=%d", project_id, port, process.pid)
                            return preview_url, process.pid
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.15)
            raise RuntimeError("Static preview server did not become ready")
        except Exception:
            self.stop(project_id)
            raise

    def stop(self, project_id: str) -> bool:
        process = self.processes.pop(project_id, None)
        if hasattr(self, "_ports"):
            self._ports.pop(project_id, None)
        if not process:
            return False
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        return True


runtime_manager = RuntimeManager()
