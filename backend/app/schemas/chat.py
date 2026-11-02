from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    user_input: str | None = None
    agent_id: str | None = None
    execution_mode: str = "single"
    model: str | None = None
    conversation_id: str | None = None
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)
    source_ids: list[str] = Field(default_factory=list, max_length=20)


class ChatResponse(BaseModel):
    response: str
    task_id: str
    status: str = "completed"
