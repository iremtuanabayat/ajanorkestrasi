from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Conversation, Message

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
def list_conversations(db: Session = Depends(get_db)):
    return [{"id": row.id, "title": row.title, "created_at": row.created_at.isoformat(), "message_count": len(row.messages)}
            for row in db.query(Conversation).order_by(Conversation.created_at.desc()).limit(100).all()]


@router.post("")
def create_conversation(payload: dict, db: Session = Depends(get_db)):
    title = str(payload.get("title", "Yeni sohbet"))[:240]
    row = Conversation(id=str(uuid4()), title=title); db.add(row); db.commit()
    return {"id": row.id, "title": row.title, "created_at": row.created_at.isoformat()}


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str, db: Session = Depends(get_db)):
    row = db.get(Conversation, conversation_id)
    if not row: raise HTTPException(404, "Conversation not found")
    return {"id": row.id, "title": row.title, "created_at": row.created_at.isoformat(),
            "messages": [{"id": item.id, "role": item.role, "content": item.content, "agent_id": item.agent_id, "created_at": item.created_at.isoformat()} for item in row.messages]}
