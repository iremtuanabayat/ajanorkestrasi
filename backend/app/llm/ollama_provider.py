import httpx
import json
import logging
from collections.abc import AsyncIterator

from app.core.config import settings

logger = logging.getLogger(__name__)


class OllamaProvider:
    def __init__(self):
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model

    async def health(self):
        try:
            models = await self.list_models()
            return {"status": "ok", "ollama": {"connected": True, "model": self.model}, "models": models}
        except httpx.HTTPError:
            return {"status": "degraded", "ollama": {"connected": False, "model": self.model}, "models": []}

    async def list_models(self):
        async with httpx.AsyncClient(timeout=4) as client:
            logger.info("[OLLAMA] listing installed models base_url=%s", self.base_url)
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            models = [model["name"] for model in response.json().get("models", [])]
            logger.info("[OLLAMA] models received count=%d", len(models))
            return models

    async def chat(self, message: str, system_prompt: str, model: str | None = None):
        selected_model = model or self.model
        logger.info("[OLLAMA] request sent model=%s", selected_model)
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(f"{self.base_url}/api/chat", json={
                "model": selected_model,
                "stream": False,
                "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": message}],
            })
            response.raise_for_status()
            answer = response.json()["message"]["content"]
            logger.info("[OLLAMA] response received model=%s chars=%d", selected_model, len(answer))
            return answer

    async def chat_json(self, message: str, system_prompt: str, model: str | None = None):
        selected_model = model or self.model
        logger.info("[OLLAMA] structured request sent model=%s", selected_model)
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(f"{self.base_url}/api/chat", json={
                "model": selected_model,
                "stream": False,
                "format": "json",
                "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": message}],
            })
            response.raise_for_status()
            content = response.json()["message"]["content"]
            logger.info("[OLLAMA] structured response received model=%s chars=%d", selected_model, len(content))
            return content

    async def chat_stream(self, message: str, system_prompt: str, model: str | None = None) -> AsyncIterator[str]:
        selected_model = model or self.model
        logger.info("[OLLAMA] streaming request sent model=%s", selected_model)
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{self.base_url}/api/chat", json={
                "model": selected_model,
                "stream": True,
                "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": message}],
            }) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    item = json.loads(line)
                    token = item.get("message", {}).get("content", "")
                    if token:
                        yield token
        logger.info("[OLLAMA] stream completed model=%s", selected_model)


ollama = OllamaProvider()
