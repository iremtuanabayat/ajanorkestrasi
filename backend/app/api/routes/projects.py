from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Project
from app.services.execution_engine import FileManager
from app.services.runtime_manager import runtime_manager

router = APIRouter(prefix="/projects", tags=["projects"])
file_manager = FileManager()


def serialize(project: Project):
    return {"id": project.id, "task_id": project.task_id, "conversation_id": project.conversation_id,
            "name": project.name, "project_type": project.project_type, "status": project.status,
            "workspace_path": project.workspace_path, "technology_stack": project.technology_stack or [],
            "generated_files": project.generated_files or [], "preview_url": project.preview_url,
            "test_results": project.test_results, "created_at": project.created_at.isoformat()}


@router.get("")
def list_projects(db: Session = Depends(get_db)):
    return [serialize(project) for project in db.query(Project).order_by(Project.created_at.desc()).limit(100).all()]


@router.get("/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return serialize(project)


@router.get("/{project_id}/files")
def get_project_files(project_id: str, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    result = []
    root = Path(project.workspace_path).resolve()
    for relative in project.generated_files or []:
        try:
            target = file_manager._safe_target(root, relative)
            if target.is_file():
                result.append({"path": relative, "content": target.read_text(encoding="utf-8")})
        except (ValueError, OSError):
            continue
    return result


@router.post("/{project_id}/runtime/stop")
def stop_project_runtime(project_id: str, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    stopped = runtime_manager.stop(project_id)
    if stopped:
        project.preview_url = None
        project.runtime_pid = None
        db.commit()
    return {"project_id": project_id, "stopped": stopped}
