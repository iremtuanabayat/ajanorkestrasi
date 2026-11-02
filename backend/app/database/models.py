from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base


def now():
    return datetime.now(timezone.utc)


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="You are a helpful assistant.")
    model_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(240))
    user_input: Mapped[str] = mapped_column(Text)
    execution_mode: Mapped[str] = mapped_column(String(20), default="single")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String(40), default="information")
    current_step: Mapped[str] = mapped_column(String(40), default="pending")
    selected_agents: Mapped[list] = mapped_column(JSON, default=list)
    execution_logs: Mapped[list] = mapped_column(JSON, default=list)
    generated_files: Mapped[list] = mapped_column(JSON, default=list)
    preview_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    test_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    final_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    steps: Mapped[list["TaskStep"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    project_type: Mapped[str] = mapped_column(String(80), default="web")
    status: Mapped[str] = mapped_column(String(30), default="planning")
    workspace_path: Mapped[str] = mapped_column(String(1000))
    technology_stack: Mapped[list] = mapped_column(JSON, default=list)
    generated_files: Mapped[list] = mapped_column(JSON, default=list)
    preview_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    test_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    runtime_pid: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TaskStep(Base):
    __tablename__ = "task_steps"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    input: Mapped[str] = mapped_column(Text)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    task: Mapped[Task] = relationship(back_populates="steps")


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(240))
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")
