"""Opt-in live smoke test. Requires a running local Ollama and installed model."""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

temp_dir = tempfile.TemporaryDirectory(prefix="ai-orchestra-smoke-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(temp_dir.name, 'smoke.db').as_posix()}"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm.ollama_provider import ollama
from app.database.connection import engine
from app.main import app


def check(condition: bool, label: str):
    if not condition:
        raise AssertionError(f"FAIL: {label}")
    print(f"PASS: {label}", flush=True)


async def check_ollama():
    models = await ollama.list_models()
    check(bool(models), "Ollama model list")
    check(ollama.model in models, f"Configured model is installed ({ollama.model})")
    response = await ollama.chat("Merhaba, kendini kısaca tanıt.", "Türkçe tek cümleyle yanıtla.")
    check(bool(response.strip()), "Direct Ollama chat")


def check_api():
    with TestClient(app) as client:
        health = client.get("/api/health")
        check(health.status_code == 200 and health.json()["ollama"]["connected"], "FastAPI health and Ollama connection")

        specs = [
            ("Coding Agent", "Python implementation", "Write concise Python code.", ["coding", "python"]),
            ("Research Agent", "Research and requirements", "Research the key requirements.", ["research"]),
            ("Analysis Agent", "Analyze and design", "Analyze the problem and recommend a structure.", ["analysis"]),
            ("Synthesis Agent", "Combine findings", "Synthesize findings into a clear Turkish response.", ["synthesis"]),
        ]
        ids = {}
        for name, description, prompt, capabilities in specs:
            response = client.post("/api/agents", json={
                "name": name, "description": description, "system_prompt": prompt,
                "capabilities": capabilities, "is_active": True,
            })
            check(response.status_code == 201, f"Create {name}")
            ids[name] = response.json()["id"]

        single = client.post("/api/chat", json={
            "message": "Python ile iki sayıyı toplayan fonksiyon yaz.",
            "agent_id": ids["Coding Agent"],
        })
        check(single.status_code == 200 and bool(single.json().get("response", "").strip()), "Single agent API response")

        multi = client.post("/api/orchestrate", json={
            "message": "Python ile veri analizi için basit proje mimarisi oluştur.",
            "execution_mode": "multi",
        })
        check(multi.status_code == 200 and bool(multi.json().get("response", "").strip()), "Supervisor/LangGraph response")
        task_id = multi.json()["task_id"]
        task = client.get(f"/api/tasks/{task_id}").json()
        check(task["status"] == "completed" and len(task["steps"]) >= 2, "Persisted multi-agent task steps")

        stream = client.post("/api/chat?stream=true", json={
            "message": "Selam.", "agent_id": ids["Coding Agent"],
        })
        body = stream.text
        check(stream.status_code == 200 and stream.headers.get("content-type", "").startswith("text/event-stream"), "SSE response headers")
        check("event: token" in body and "event: done" in body, "SSE token and terminal events")


if __name__ == "__main__":
    try:
        asyncio.run(check_ollama())
        check_api()
        print("PASS: live orchestration smoke suite", flush=True)
    finally:
        engine.dispose()
        temp_dir.cleanup()
