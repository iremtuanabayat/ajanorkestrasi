from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import agents, chat, conversations, models, projects, settings as settings_routes, tasks
from app.core.config import settings
from app.database.connection import create_tables

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    yield


app = FastAPI(title="AI Orchestra API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:8443", "http://127.0.0.1:8443"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(agents.router, prefix="/api")
app.include_router(models.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(settings_routes.router, prefix="/api")


@app.get("/api/health")
async def health():
    from app.llm.ollama_provider import ollama

    return await ollama.health()
