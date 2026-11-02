import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.database.connection import SessionLocal
from app.database.models import Agent, Conversation, Message, Project, Setting, Task, TaskStep
from app.llm.ollama_provider import ollama
from app.orchestration.workflow import OrchestraState, build_workflow, select_agents
from app.schemas.chat import ChatRequest
from app.services.project_executor import project_executor
from app.services.task_classifier import classifier

logger = logging.getLogger(__name__)


class TaskRunner:
    def __init__(self):
        self.events: dict[str, asyncio.Queue] = {}
        self.cancel_events: dict[str, asyncio.Event] = {}
        self.jobs: dict[str, asyncio.Task] = {}
        self.results: dict[str, asyncio.Future] = {}

    def queue(self, task_id: str):
        return self.events.setdefault(task_id, asyncio.Queue())

    async def publish(self, task_id: str, event: str, data: dict):
        await self.queue(task_id).put({"event": event, "data": data})

    def start(self, payload: ChatRequest, db: Session, multi: bool):
        prompt = payload.user_input or payload.message
        task_id = str(uuid4())
        logger.info("[ORCHESTRATOR] task accepted task_id=%s mode=%s", task_id, "multi" if multi else "single")
        task = Task(id=task_id, title=prompt[:100], user_input=prompt, execution_mode="multi" if multi else "single", status="queued")
        db.add(task)
        db.flush()
        if payload.conversation_id:
            conversation = db.get(Conversation, payload.conversation_id)
            if conversation is None:
                raise HTTPException(404, "Conversation not found")
        else:
            conversation = Conversation(id=str(uuid4()), title=prompt[:100])
            db.add(conversation)
        db.add(Message(id=str(uuid4()), conversation_id=conversation.id, role="user", content=prompt))
        default_agent = db.get(Setting, "default_agent_id")
        if not payload.agent_id and default_agent and default_agent.value:
            payload.agent_id = default_agent.value
        task.conversation_id = conversation.id
        db.commit()
        self.cancel_events[task_id] = asyncio.Event()
        future = asyncio.get_running_loop().create_future()
        future.add_done_callback(lambda item: item.exception() if not item.cancelled() else None)
        self.results[task_id] = future
        self.queue(task_id)
        job = asyncio.create_task(self._run(task_id, payload, conversation.id, multi))
        self.jobs[task_id] = job
        return task_id, conversation.id

    async def _run(self, task_id: str, payload: ChatRequest, conversation_id: str, multi: bool):
        db = SessionLocal()
        task = db.get(Task, task_id)
        try:
            task.status = "running"; task.cancel_requested = False; db.commit()
            logger.info("[ORCHESTRATOR] workflow started task_id=%s mode=%s", task_id, "multi" if multi else "single")
            await self.publish(task_id, "task", {"task_id": task_id, "conversation_id": conversation_id, "status": "running", "execution_mode": task.execution_mode})
            prompt = payload.user_input or payload.message
            classification = await classifier.classify(prompt, payload.model)
            task.task_type = classification.task_type.value
            task.current_step = "classification"
            task.execution_logs = [{"step": "classification", "task_type": task.task_type, "confidence": classification.confidence}]
            db.commit()
            await self.publish(task_id, "step", {"status": "completed", "label": "Görev sınıflandırıldı", "task_type": task.task_type})
            if task.task_type in ("project_creation", "project_modification"):
                existing_project = None
                if task.task_type == "project_modification":
                    existing_project = db.query(Project).filter(Project.conversation_id == conversation_id).order_by(Project.created_at.desc()).first()
                    if existing_project is None:
                        raise ValueError("Bu sohbette değiştirilecek kayıtlı proje bulunamadı. Önce yeni bir proje oluşturun.")
                project_result = await project_executor.execute(task, db, prompt, payload.model, lambda event, data: self.publish(task_id, event, data), self.cancel_events[task_id].is_set, existing_project)
                answer = project_result["response"]
                task.status = "completed"; task.final_result = answer; task.completed_at = datetime.now(timezone.utc)
                db.add(Message(id=str(uuid4()), conversation_id=conversation_id, role="assistant", content=answer))
                db.commit()
                result = {"response": answer, "task_id": task_id, "conversation_id": conversation_id, "status": "completed", "project_delivery": project_result["project_delivery"]}
                await self.publish(task_id, "done", result)
                logger.info("[ORCHESTRATOR] project workflow completed task_id=%s project_id=%s", task_id, task.project_id)
                if not self.results[task_id].done(): self.results[task_id].set_result(result)
                return
            if multi:
                agents = db.query(Agent).filter(Agent.is_active.is_(True)).order_by(Agent.created_at.asc()).limit(8).all()
                if not agents: raise HTTPException(400, "Create at least one active agent before using multi-agent mode")
                if payload.agent_id:
                    chosen = next((agent for agent in agents if agent.id == payload.agent_id), None)
                    if chosen is None: raise HTTPException(404, "Active agent not found")
                    agents = [chosen]
                else:
                    agents = await select_agents(prompt, agents, payload.model)
                if not agents:
                    raise HTTPException(422, "Supervisor could not select an active agent")
                logger.info("[ROUTER] task_id=%s selected=%s", task_id, [agent.name for agent in agents])
                await self.publish(task_id, "step", {"status": "started", "label": "Ajanlar seçiliyor", "agent_count": len(agents)})
                workflow = build_workflow(agents)
                initial: OrchestraState = {"task_id": task_id, "user_input": prompt, "selected_agents": [{"id": a.id, "name": a.name, "system_prompt": a.system_prompt, "model_name": a.model_name} for a in agents], "agent_outputs": [], "execution_steps": [], "task_status": "running", "errors": [], "model": payload.model}
                state = initial
                async for update in workflow.astream(initial, stream_mode="updates"):
                    if self.cancel_events[task_id].is_set(): raise asyncio.CancelledError
                    for node_name, delta in update.items():
                        state.update(delta)
                        if node_name.startswith("agent_"):
                            output = delta.get("agent_outputs", [])[-1]
                            state["agent_outputs"] = [*state.get("agent_outputs", []), output]
                            await self.publish(task_id, "step", {"status": "completed", **output})
                            db.add(TaskStep(id=str(uuid4()), task_id=task_id, agent_id=output["agent_id"], input=prompt, output=output["output"], status="completed", started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc)))
                        elif node_name == "synthesis":
                            state["final_result"] = delta.get("final_result", state.get("final_result", ""))
                            await self.publish(task_id, "step", {"status": "completed", "agent_name": "Synthesis", "output": state.get("final_result", "")})
                            synthesis_agent = next((agent for agent in agents if "synthesis" in agent.name.lower()), None)
                            db.add(TaskStep(id=str(uuid4()), task_id=task_id, agent_id=synthesis_agent.id if synthesis_agent else None, input=prompt, output=state.get("final_result", ""), status="completed", started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc)))
                answer = state.get("final_result") or "\n\n".join(f"### {x['agent_name']}\n{x['output']}" for x in state.get("agent_outputs", []))
            else:
                agent = db.get(Agent, payload.agent_id) if payload.agent_id else None
                if payload.agent_id and (agent is None or not agent.is_active): raise HTTPException(404, "Active agent not found")
                await self.publish(task_id, "step", {"status": "started", "agent_id": agent.id if agent else None, "agent_name": agent.name if agent else "Orchestra"})
                tokens = []
                async for token in ollama.chat_stream(prompt, agent.system_prompt if agent else "You are the AI Orchestra supervisor. Give a useful, clear answer.", payload.model or (agent.model_name if agent else None)):
                    if self.cancel_events[task_id].is_set(): raise asyncio.CancelledError
                    tokens.append(token)
                    await self.publish(task_id, "token", {"text": token})
                answer = "".join(tokens)
                db.add(TaskStep(id=str(uuid4()), task_id=task_id, agent_id=agent.id if agent else None, input=prompt, output=answer, status="completed", started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc)))
            if self.cancel_events[task_id].is_set(): raise asyncio.CancelledError
            if not answer or not answer.strip():
                raise RuntimeError("Workflow completed without a final answer")
            task.status = "completed"; task.final_result = answer; task.completed_at = datetime.now(timezone.utc)
            db.add(Message(id=str(uuid4()), conversation_id=conversation_id, role="assistant", content=answer))
            db.commit()
            result = {"response": answer, "task_id": task_id, "conversation_id": conversation_id, "status": "completed"}
            await self.publish(task_id, "done", result)
            logger.info("[ORCHESTRATOR] workflow completed task_id=%s chars=%d", task_id, len(answer))
            if not self.results[task_id].done(): self.results[task_id].set_result(result)
        except asyncio.CancelledError:
            task.status = "cancelled"; task.completed_at = datetime.now(timezone.utc); db.commit()
            project_executor.mark_failed(task, db, "cancelled")
            await self.publish(task_id, "cancelled", {"task_id": task_id, "status": "cancelled"})
            if not self.results[task_id].done(): self.results[task_id].set_exception(HTTPException(409, "Task cancelled"))
        except Exception as exc:
            logger.exception("[ORCHESTRATOR] task failed task_id=%s error_type=%s", task_id, type(exc).__name__)
            task.status = "failed"; task.final_result = str(exc); task.completed_at = datetime.now(timezone.utc); db.commit()
            project_executor.mark_failed(task, db)
            await self.publish(task_id, "error", {"task_id": task_id, "message": str(exc)})
            if not self.results[task_id].done(): self.results[task_id].set_exception(exc)
        finally:
            await self.publish(task_id, "close", {})
            db.close()

    async def cancel(self, task_id: str):
        if task_id not in self.jobs or self.jobs[task_id].done(): return False
        self.cancel_events[task_id].set()
        return True


runner = TaskRunner()
