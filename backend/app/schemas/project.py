from enum import Enum

from pydantic import BaseModel, Field


class TaskType(str, Enum):
    information = "information"
    code_generation = "code_generation"
    project_creation = "project_creation"
    project_modification = "project_modification"
    data_analysis = "data_analysis"


class TaskClassification(BaseModel):
    task_type: TaskType
    confidence: float = Field(ge=0, le=1, default=0.5)
    needs_clarification: bool = False
    clarification_question: str | None = None


class ProjectPlan(BaseModel):
    task_id: str = ""
    project_name: str = Field(min_length=1, max_length=120)
    project_type: str = "web"
    requirements: list[str] = Field(default_factory=list)
    selected_agents: list[str] = Field(default_factory=list)
    technology_stack: list[str] = Field(default_factory=list)
    execution_steps: list[str] = Field(default_factory=list)
    expected_files: list[str] = Field(default_factory=list)
    testing_requirements: list[str] = Field(default_factory=list)
    delivery_requirements: list[str] = Field(default_factory=list)
    frontend_required: bool = True
    backend_required: bool = False


class GeneratedFile(BaseModel):
    path: str = Field(min_length=1, max_length=240)
    content: str = Field(max_length=1_000_000)


class GeneratedProject(BaseModel):
    files: list[GeneratedFile] = Field(min_length=1, max_length=30)
    summary: str = Field(min_length=1, max_length=2000)


class ProjectDelivery(BaseModel):
    project_id: str
    project_name: str
    project_type: str
    technology_stack: list[str]
    generated_files: list[str]
    status: str
    test_status: str
    preview_url: str | None = None
    workspace_path: str
    test_results: dict
