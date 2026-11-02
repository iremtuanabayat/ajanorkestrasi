from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    system_prompt: str = Field(default="You are a helpful assistant.", max_length=12000)
    model_name: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    is_active: bool = True


class AgentUpdate(AgentCreate):
    pass


class AgentRead(AgentCreate):
    id: str
    created_at: str

    class Config:
        from_attributes = True
