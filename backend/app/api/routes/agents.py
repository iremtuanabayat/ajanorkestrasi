from datetime import timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Agent
from app.schemas.agent import AgentCreate, AgentRead, AgentUpdate

router = APIRouter(prefix="/agents", tags=["agents"])


def serialize(agent: Agent):
    return {"id": agent.id, "name": agent.name, "description": agent.description,
            "system_prompt": agent.system_prompt, "model_name": agent.model_name,
            "capabilities": agent.capabilities, "is_active": agent.is_active,
            "created_at": agent.created_at.replace(tzinfo=timezone.utc).isoformat()}


@router.get("", response_model=list[AgentRead])
def list_agents(db: Session = Depends(get_db)):
    return [serialize(agent) for agent in db.query(Agent).order_by(Agent.created_at.desc()).all()]


@router.post("", response_model=AgentRead, status_code=201)
def create_agent(payload: AgentCreate, db: Session = Depends(get_db)):
    agent = Agent(id=str(uuid4()), **payload.model_dump())
    db.add(agent); db.commit(); db.refresh(agent)
    return serialize(agent)


@router.get("/{agent_id}", response_model=AgentRead)
def get_agent(agent_id: str, db: Session = Depends(get_db)):
    agent = db.get(Agent, agent_id)
    if not agent: raise HTTPException(404, "Agent not found")
    return serialize(agent)


@router.put("/{agent_id}", response_model=AgentRead)
def update_agent(agent_id: str, payload: AgentUpdate, db: Session = Depends(get_db)):
    agent = db.get(Agent, agent_id)
    if not agent: raise HTTPException(404, "Agent not found")
    for key, value in payload.model_dump().items(): setattr(agent, key, value)
    db.commit(); db.refresh(agent)
    return serialize(agent)


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: str, db: Session = Depends(get_db)):
    agent = db.get(Agent, agent_id)
    if not agent: raise HTTPException(404, "Agent not found")
    db.delete(agent); db.commit()
    return Response(status_code=204)
