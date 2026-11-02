import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.schemas.chat import ChatRequest
from app.services.task_runner import runner

router = APIRouter(tags=["chat"])


async def run_request(payload: ChatRequest, db: Session, multi: bool):
    task_id, conversation_id = runner.start(payload, db, multi)
    try:
        result = await asyncio.wait_for(asyncio.shield(runner.results[task_id]), timeout=300)
        return {**result, "conversation_id": conversation_id}
    except HTTPException:
        raise
    except asyncio.TimeoutError as exc:
        await runner.cancel(task_id)
        raise HTTPException(504, "Task timed out") from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


async def stream_request(payload: ChatRequest, db: Session, multi: bool):
    task_id, _ = runner.start(payload, db, multi)

    async def events():
        queue = runner.queue(task_id)
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=20)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if item["event"] == "close": break
            yield f"event: {item['event']}\ndata: {json.dumps(item['data'], ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/chat")
async def chat(payload: ChatRequest, stream: bool = False, db: Session = Depends(get_db)):
    return await stream_request(payload, db, False) if stream else await run_request(payload, db, False)


@router.post("/orchestrate")
async def orchestrate(payload: ChatRequest, stream: bool = False, db: Session = Depends(get_db)):
    return await stream_request(payload, db, True) if stream else await run_request(payload, db, True)
