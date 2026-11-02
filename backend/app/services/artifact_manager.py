import hashlib
import os
import shutil
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.database.models import Artifact

ARTIFACT_ROOT = Path(__file__).resolve().parents[3] / "workspace" / "artifacts"


def register_project_files(db: Session, project_id: str, task_id: str, workspace: Path, paths: list[str]) -> list[Artifact]:
    rows = []
    for relative in paths:
        source = (workspace / Path(*relative.split("/"))).resolve()
        if not source.is_relative_to(workspace.resolve()) or not source.is_file():
            raise ValueError("Artifact path is outside the project workspace")
        content = source.read_bytes()
        checksum = hashlib.sha256(content).hexdigest()
        previous = db.query(Artifact).filter(Artifact.project_id == project_id, Artifact.filename == relative).order_by(Artifact.version.desc()).first()
        if previous and previous.checksum == checksum:
            rows.append(previous)
            continue
        artifact_id = str(uuid4())
        version = (previous.version + 1) if previous else 1
        folder = (ARTIFACT_ROOT / artifact_id).resolve()
        if not folder.is_relative_to(ARTIFACT_ROOT.resolve()):
            raise ValueError("Artifact path is invalid")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / Path(relative).name
        target.write_bytes(content)
        artifact = Artifact(id=artifact_id, project_id=project_id, task_id=task_id,
                            filename=relative, file_type=source.suffix.lower(), storage_path=str(target),
                            source_agent="Frontend Agent", version=version, checksum=checksum)
        db.add(artifact)
        rows.append(artifact)
    db.flush()
    return rows


def resolve_artifact(row: Artifact) -> Path:
    root = ARTIFACT_ROOT.resolve()
    path = Path(row.storage_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise FileNotFoundError("Artifact unavailable")
    return path
