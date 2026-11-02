from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Setting
from app.llm.ollama_provider import ollama

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    ollama_base_url: str | None = Field(default=None, max_length=500)
    ollama_model: str | None = Field(default=None, max_length=160)
    default_agent_id: str | None = None


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    values = {row.key: row.value for row in db.query(Setting).all()}
    return {"ollama_base_url": values.get("ollama_base_url", ollama.base_url),
            "ollama_model": values.get("ollama_model", ollama.model),
            "default_agent_id": values.get("default_agent_id")}


@router.put("")
def put_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    for key, value in payload.model_dump(exclude_none=True).items():
        row = db.get(Setting, key)
        if row is None: row = Setting(key=key, value=str(value)); db.add(row)
        else: row.value = str(value)
    db.commit()
    if payload.ollama_base_url:
        ollama.base_url = payload.ollama_base_url.rstrip("/")
    if payload.ollama_model:
        ollama.model = payload.ollama_model
    return get_settings(db)
