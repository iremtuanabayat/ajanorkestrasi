from fastapi import APIRouter

from app.llm.ollama_provider import ollama

router = APIRouter(prefix="/models", tags=["models"])


@router.get("")
async def list_models():
    return {"models": await ollama.list_models()}
