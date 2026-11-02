import hashlib
import difflib
import json
import zipfile
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import ApprovalRequest, Artifact, ContextChunk, Conversation, Project, ProjectMemory, SourceLink, UploadedFile
from app.services.artifact_manager import ARTIFACT_ROOT, resolve_artifact
from app.services.file_ingestion import MAX_UPLOAD_BYTES, ingest_upload
from app.services.source_ingestion import ingest_url
from app.services.task_runner import runner

router = APIRouter(tags=["workspace"])


class ApprovalResolution(BaseModel):
    approved: bool


@router.get("/approvals")
def list_approvals(status: str | None = None, db: Session = Depends(get_db)):
    query = db.query(ApprovalRequest)
    if status:
        query = query.filter(ApprovalRequest.status == status)
    return [{"id": row.id, "task_id": row.task_id, "project_id": row.project_id, "action": row.action,
             "details": row.details, "status": row.status, "created_at": row.created_at.isoformat()}
            for row in query.order_by(ApprovalRequest.created_at.desc()).limit(100).all()]


@router.post("/approvals/{approval_id}/resolve")
async def resolve_approval(approval_id: str, payload: ApprovalResolution, db: Session = Depends(get_db)):
    row = db.get(ApprovalRequest, approval_id)
    if not row or row.status != "pending":
        raise HTTPException(404, "Pending approval not found")
    if not await runner.resolve_approval(row.task_id, payload.approved):
        raise HTTPException(409, "Approval task is not waiting in the current backend process")
    row.status = "approved" if payload.approved else "rejected"
    db.commit()
    return {"id": row.id, "status": row.status}


def _upload(row):
    return {"file_id": row.id, "original_filename": row.original_filename, "mime_type": row.mime_type,
            "file_size": row.file_size, "checksum": row.checksum, "conversation_id": row.conversation_id,
            "project_id": row.project_id, "processing_status": row.processing_status, "created_at": row.created_at.isoformat()}


@router.post("/uploads")
async def upload_file(file: UploadFile = File(...), conversation_id: str | None = Query(None), project_id: str | None = Query(None), db: Session = Depends(get_db)):
    if conversation_id and not db.get(Conversation, conversation_id):
        raise HTTPException(404, "Conversation not found")
    if project_id and not db.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        row, duplicate = ingest_upload(db, file.filename or "upload", data, conversation_id, project_id)
    except (ValueError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise HTTPException(400, str(exc)) from exc
    notice = "Yerel vision modeli yapılandırılmadığı için görsel analiz edilmedi." if row.mime_type.startswith("image/") else None
    return {**_upload(row), "duplicate": duplicate, "preview": row.extracted_text[:600] or None, "notice": notice}


@router.get("/uploads")
def list_uploads(conversation_id: str | None = None, db: Session = Depends(get_db)):
    query = db.query(UploadedFile)
    if conversation_id:
        query = query.filter(UploadedFile.conversation_id == conversation_id)
    return [_upload(row) for row in query.order_by(UploadedFile.created_at.desc()).limit(100).all()]


@router.delete("/uploads/{file_id}")
def delete_upload(file_id: str, db: Session = Depends(get_db)):
    row = db.get(UploadedFile, file_id)
    if not row:
        raise HTTPException(404, "Upload not found")
    Path(row.storage_path).unlink(missing_ok=True)
    chunk_ids = [item[0] for item in db.query(ContextChunk.id).filter(ContextChunk.source_type == "file", ContextChunk.source_id == row.id).all()]
    if chunk_ids:
        db.query(ContextChunk).filter(ContextChunk.id.in_(chunk_ids)).delete(synchronize_session=False)
        if db.bind and db.bind.dialect.name == "sqlite":
            for chunk_id in chunk_ids:
                db.execute(text("DELETE FROM context_chunks_fts WHERE chunk_id = :id"), {"id": chunk_id})
    db.delete(row)
    db.commit()
    return {"deleted": True}


class SourceRequest(BaseModel):
    url: str
    conversation_id: str | None = None
    project_id: str | None = None


@router.post("/sources")
async def add_source(payload: SourceRequest, db: Session = Depends(get_db)):
    if payload.conversation_id and not db.get(Conversation, payload.conversation_id):
        raise HTTPException(404, "Conversation not found")
    if payload.project_id and not db.get(Project, payload.project_id):
        raise HTTPException(404, "Project not found")
    try:
        row = await ingest_url(db, payload.url, payload.conversation_id, payload.project_id)
    except (ValueError, OSError, httpx.HTTPError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"source_id": row.id, "url": row.url, "title": row.title, "content_type": row.content_type,
            "processing_status": row.processing_status, "preview": row.extracted_text[:600]}


@router.get("/sources")
def list_sources(conversation_id: str | None = None, db: Session = Depends(get_db)):
    query = db.query(SourceLink)
    if conversation_id:
        query = query.filter(SourceLink.conversation_id == conversation_id)
    return [{"source_id": row.id, "url": row.url, "title": row.title, "content_type": row.content_type,
             "processing_status": row.processing_status, "created_at": row.created_at.isoformat()}
            for row in query.order_by(SourceLink.created_at.desc()).limit(100).all()]


@router.delete("/sources/{source_id}")
def delete_source(source_id: str, db: Session = Depends(get_db)):
    row = db.get(SourceLink, source_id)
    if not row:
        raise HTTPException(404, "Source not found")
    chunk_ids = [item[0] for item in db.query(ContextChunk.id).filter(ContextChunk.source_type == "url", ContextChunk.source_id == row.id).all()]
    if chunk_ids:
        db.query(ContextChunk).filter(ContextChunk.id.in_(chunk_ids)).delete(synchronize_session=False)
        if db.bind and db.bind.dialect.name == "sqlite":
            for chunk_id in chunk_ids:
                db.execute(text("DELETE FROM context_chunks_fts WHERE chunk_id = :id"), {"id": chunk_id})
    db.delete(row)
    db.commit()
    return {"deleted": True}


@router.get("/artifacts")
def list_artifacts(project_id: str | None = None, db: Session = Depends(get_db)):
    query = db.query(Artifact)
    if project_id:
        query = query.filter(Artifact.project_id == project_id)
    return [{"artifact_id": row.id, "project_id": row.project_id, "filename": row.filename, "file_type": row.file_type,
             "source_agent": row.source_agent, "version": row.version, "checksum": row.checksum,
             "created_at": row.created_at.isoformat(), "download_url": f"/api/artifacts/{row.id}/download"}
            for row in query.order_by(Artifact.created_at.desc()).limit(500).all()]


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str, db: Session = Depends(get_db)):
    row = db.get(Artifact, artifact_id)
    if not row:
        raise HTTPException(404, "Artifact not found")
    try:
        path = resolve_artifact(row)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(path, filename=Path(row.filename).name, media_type="application/octet-stream")


@router.get("/artifacts/{artifact_id}/versions")
def artifact_versions(artifact_id: str, db: Session = Depends(get_db)):
    row = db.get(Artifact, artifact_id)
    if not row:
        raise HTTPException(404, "Artifact not found")
    query = db.query(Artifact).filter(Artifact.filename == row.filename)
    if row.project_id:
        query = query.filter(Artifact.project_id == row.project_id)
    versions = query.order_by(Artifact.version.asc()).all()
    return [{"artifact_id": item.id, "version": item.version, "checksum": item.checksum,
             "created_at": item.created_at.isoformat(), "download_url": f"/api/artifacts/{item.id}/download"} for item in versions]


@router.get("/artifacts/{artifact_id}/compare/{version}")
def compare_artifact_version(artifact_id: str, version: int, db: Session = Depends(get_db)):
    current = db.get(Artifact, artifact_id)
    if not current:
        raise HTTPException(404, "Artifact not found")
    query = db.query(Artifact).filter(Artifact.filename == current.filename, Artifact.version == version)
    if current.project_id:
        query = query.filter(Artifact.project_id == current.project_id)
    previous = query.first()
    if not previous:
        raise HTTPException(404, "Artifact version not found")
    try:
        old_text = resolve_artifact(previous).read_text(encoding="utf-8").splitlines()
        new_text = resolve_artifact(current).read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, UnicodeError) as exc:
        raise HTTPException(400, "Binary or unavailable artifacts cannot be compared as text") from exc
    return {"filename": current.filename, "from_version": version, "to_version": current.version,
            "diff": list(difflib.unified_diff(old_text, new_text, fromfile=f"v{version}", tofile=f"v{current.version}", lineterm=""))}


@router.post("/projects/{project_id}/package")
def package_project(project_id: str, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    workspace = Path(project.workspace_path).resolve()
    generated_root = Path(__file__).resolve().parents[4] / "workspace" / "projects"
    if not workspace.is_relative_to(generated_root.resolve()):
        raise HTTPException(400, "Project path is outside generated workspace")
    artifact_id = str(uuid4())
    folder = (ARTIFACT_ROOT / artifact_id).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    archive_path = folder / f"{project.id}.zip"
    try:
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for relative in project.generated_files or []:
                source = (workspace / Path(*relative.split("/"))).resolve()
                if not source.is_relative_to(workspace) or not source.is_file():
                    raise ValueError("Project contains an invalid generated file path")
                archive.write(source, relative)
    except Exception as exc:
        archive_path.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc
    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    row = Artifact(id=artifact_id, project_id=project.id, task_id=project.task_id, filename=f"{project.name}.zip",
                   file_type=".zip", storage_path=str(archive_path), source_agent="Delivery Manager", version=1, checksum=checksum)
    db.add(row)
    db.commit()
    return {"artifact_id": row.id, "filename": row.filename, "download_url": f"/api/artifacts/{row.id}/download", "checksum": checksum}


@router.get("/projects/{project_id}/memory")
def get_memory(project_id: str, db: Session = Depends(get_db)):
    if not db.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    return [{"id": row.id, "category": row.category, "content": row.content, "approved": row.approved,
             "created_at": row.created_at.isoformat()}
            for row in db.query(ProjectMemory).filter(ProjectMemory.project_id == project_id).order_by(ProjectMemory.created_at.asc()).all()]


class MemoryRequest(BaseModel):
    category: str = "note"
    content: str
    approved: bool = False


@router.post("/projects/{project_id}/memory")
def add_memory(project_id: str, payload: MemoryRequest, db: Session = Depends(get_db)):
    if not db.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    row = ProjectMemory(id=str(uuid4()), project_id=project_id, category=payload.category[:50], content=payload.content[:10000], approved=payload.approved)
    db.add(row)
    db.commit()
    return {"id": row.id, "category": row.category, "content": row.content, "approved": row.approved}


@router.delete("/projects/{project_id}/memory/{memory_id}")
def delete_memory(project_id: str, memory_id: str, db: Session = Depends(get_db)):
    row = db.query(ProjectMemory).filter(ProjectMemory.project_id == project_id, ProjectMemory.id == memory_id).first()
    if not row:
        raise HTTPException(404, "Memory entry not found")
    db.delete(row)
    db.commit()
    return {"deleted": True}


@router.patch("/projects/{project_id}/memory/{memory_id}")
def edit_memory(project_id: str, memory_id: str, payload: MemoryRequest, db: Session = Depends(get_db)):
    row = db.query(ProjectMemory).filter(ProjectMemory.project_id == project_id, ProjectMemory.id == memory_id).first()
    if not row:
        raise HTTPException(404, "Memory entry not found")
    row.category = payload.category[:50]
    row.content = payload.content[:10000]
    row.approved = payload.approved
    db.commit()
    return {"id": row.id, "category": row.category, "content": row.content, "approved": row.approved}
