import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.database.models import Project
from app.services.context_manager import context_manager

TOOL_SPECS = [
    {"type": "function", "function": {"name": "search_project_context", "description": "Search relevant uploaded documents and sources scoped to this conversation or project.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "list_project_files", "description": "List tracked files in the current project workspace.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "read_project_file", "description": "Read a tracked text file from the current project workspace.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
]


class ToolExecutor:
    def __init__(self, db: Session, conversation_id: str | None, project_id: str | None):
        self.db = db
        self.conversation_id = conversation_id
        self.project_id = project_id

    def execute(self, name: str, arguments: dict) -> dict:
        if name == "search_project_context":
            results = context_manager.search_context(self.db, str(arguments.get("query", ""))[:500], self.conversation_id, self.project_id, 5)
            return {"results": [{"source_type": item["source_type"], "source_id": item["source_id"], "metadata": item["metadata"], "content": item["content"]} for item in results]}
        project = self.db.get(Project, self.project_id) if self.project_id else None
        if not project:
            return {"error": "No project is attached to this task."}
        root = Path(project.workspace_path).resolve()
        if name == "list_project_files":
            return {"files": project.generated_files or []}
        if name == "read_project_file":
            relative = str(arguments.get("path", ""))
            if relative not in (project.generated_files or []):
                return {"error": "The requested file is not tracked by this project."}
            try:
                from app.services.execution_engine import file_manager
                target = file_manager._safe_target(root, relative)
                return {"path": relative, "content": target.read_text(encoding="utf-8")[:30000]}
            except (ValueError, OSError, UnicodeError) as exc:
                return {"error": str(exc)}
        return {"error": "Tool is not allowlisted."}


def serialize_tool_result(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False)
