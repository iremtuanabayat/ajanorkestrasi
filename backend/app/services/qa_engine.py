import asyncio
import logging
import re
import shutil
import subprocess
from pathlib import Path

import httpx

from app.services.execution_engine import file_manager

logger = logging.getLogger(__name__)


class QAEngine:
    async def run_static_checks(self, project_id: str, preview_url: str) -> dict:
        project = (file_manager.root / project_id).resolve()
        frontend = (project / "frontend").resolve()
        checks: list[dict] = []
        required = ["index.html", "style.css", "script.js"]
        missing = [name for name in required if not (frontend / name).is_file()]
        checks.append({"name": "required_files", "passed": not missing, "details": f"Missing: {missing}" if missing else "All required files exist"})
        html = (frontend / "index.html").read_text(encoding="utf-8") if (frontend / "index.html").exists() else ""
        refs = re.findall(r"(?:src|href)=[\"']([^\"']+)[\"']", html)
        unresolved = [ref for ref in refs if not ref.startswith(("http://", "https://", "#", "data:")) and not (frontend / ref).is_file()]
        checks.append({"name": "asset_references", "passed": not unresolved, "details": f"Unresolved: {unresolved}" if unresolved else "Local references resolve"})
        node = shutil.which("node")
        script = frontend / "script.js"
        if node and script.is_file():
            result = await asyncio.to_thread(subprocess.run, [node, "--check", str(script)], capture_output=True, text=True, timeout=15, shell=False)
            checks.append({"name": "javascript_syntax", "passed": result.returncode == 0, "details": (result.stderr or "JavaScript syntax is valid")[:1000]})
        else:
            checks.append({"name": "javascript_syntax", "passed": False, "details": "Node.js or script.js is unavailable"})
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(preview_url)
                checks.append({"name": "preview_http", "passed": response.status_code == 200 and "<html" in response.text.lower(), "details": f"HTTP {response.status_code}"})
        except httpx.HTTPError as exc:
            checks.append({"name": "preview_http", "passed": False, "details": type(exc).__name__})
        passed = all(item["passed"] for item in checks)
        logger.info("[QA] project=%s passed=%s checks=%d", project_id, passed, len(checks))
        return {"passed": passed, "checks": checks}


qa_engine = QAEngine()
