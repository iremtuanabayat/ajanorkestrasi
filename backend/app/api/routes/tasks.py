import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Task
from app.services.task_runner import runner

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("")
def list_tasks(db: Session = Depends(get_db)):
    return [{"id": task.id, "title": task.title, "status": task.status, "execution_mode": task.execution_mode, "task_type": task.task_type, "current_step": task.current_step, "project_id": task.project_id,
             "created_at": task.created_at.isoformat(), "final_result": task.final_result}
            for task in db.query(Task).order_by(Task.created_at.desc()).limit(100).all()]


@router.get("/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task: raise HTTPException(404, "Task not found")
    return {"id": task.id, "title": task.title, "status": task.status, "conversation_id": task.conversation_id,
            "execution_mode": task.execution_mode, "final_result": task.final_result,
            "task_type": task.task_type, "current_step": task.current_step, "project_id": task.project_id,
            "selected_agents": task.selected_agents or [], "execution_logs": task.execution_logs or [],
            "generated_files": task.generated_files or [], "preview_url": task.preview_url, "test_results": task.test_results,
            "steps": [{"id": step.id, "agent_id": step.agent_id, "status": step.status, "output": step.output} for step in task.steps]}


@router.get("/{task_id}/events")
async def task_events(task_id: str, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task: raise HTTPException(404, "Task not found")
    async def events():
        if task_id not in runner.events:
            yield f"event: snapshot\ndata: {json.dumps({'task_id': task.id, 'status': task.status, 'final_result': task.final_result}, ensure_ascii=False)}\n\n"
            return
        queue = runner.queue(task_id)
        while True:
            try: item = await asyncio.wait_for(queue.get(), timeout=20)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"; continue
            if item["event"] == "close": break
            yield f"event: {item['event']}\ndata: {json.dumps(item['data'], ensure_ascii=False)}\n\n"
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task: raise HTTPException(404, "Task not found")
    if task.status in ("queued", "running"):
        task.cancel_requested = True; db.commit()
        if task_id in runner.jobs:
            await runner.cancel(task_id)
        else:
            task.status = "cancelled"
            task.completed_at = datetime.now(timezone.utc)
            db.commit()
    return {"id": task.id, "status": task.status}
