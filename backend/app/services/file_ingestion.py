import hashlib
import mimetypes
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.database.models import UploadedFile
from app.services.context_manager import context_manager
from app.services.document_processor import ALLOWED_EXTENSIONS, extract_document

UPLOAD_ROOT = Path(__file__).resolve().parents[3] / "workspace" / "uploads"
MAX_UPLOAD_BYTES = 20_000_000


def ingest_upload(db: Session, filename: str, data: bytes, conversation_id: str | None = None,
                  project_id: str | None = None) -> tuple[UploadedFile, bool]:
    original = os.path.basename(filename.replace("\\", "/"))[:255]
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("Bu dosya uzantısı kabul edilmiyor")
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Dosya boş veya 20 MB sınırını aşıyor")
    checksum = hashlib.sha256(data).hexdigest()
    duplicate = db.query(UploadedFile).filter(UploadedFile.checksum == checksum,
        UploadedFile.conversation_id == conversation_id).first()
    if duplicate:
        return duplicate, True
    file_id = str(uuid4())
    folder = (UPLOAD_ROOT / (conversation_id or "unassigned")).resolve()
    root = UPLOAD_ROOT.resolve()
    if not folder.is_relative_to(root):
        raise ValueError("Upload workspace path is invalid")
    folder.mkdir(parents=True, exist_ok=True)
    stored = f"{file_id}{suffix}"
    target = folder / stored
    target.write_bytes(data)
    row = UploadedFile(id=file_id, conversation_id=conversation_id, project_id=project_id,
        original_filename=original, stored_filename=stored,
        mime_type=mimetypes.guess_type(original)[0] or "application/octet-stream",
        file_size=len(data), checksum=checksum, storage_path=str(target), processing_status="processing")
    db.add(row)
    db.flush()
    try:
        extracted, metadata = extract_document(original, data)
        row.extracted_text = extracted
        row.processing_status = "ready"
        context_manager.add_document(db, "file", row.id, extracted, conversation_id, project_id,
                                    {"filename": original, **metadata}) if extracted else None
    except Exception:
        row.processing_status = "failed"
        db.commit()
        raise
    db.commit()
    db.refresh(row)
    return row, False
