import re
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.models import ContextChunk

CHUNK_SIZE = 1400
CHUNK_OVERLAP = 180


class ContextManager:
    def add_document(self, db: Session, source_type: str, source_id: str, content: str,
                     conversation_id: str | None = None, project_id: str | None = None,
                     metadata: dict | None = None) -> int:
        clean = content.strip()
        pieces = []
        start = 0
        while start < len(clean):
            end = min(len(clean), start + CHUNK_SIZE)
            if end < len(clean):
                boundary = clean.rfind("\n", start + CHUNK_SIZE // 2, end)
                if boundary > start:
                    end = boundary
            pieces.append(clean[start:end].strip())
            if end >= len(clean):
                break
            start = max(start + 1, end - CHUNK_OVERLAP)
        for index, piece in enumerate(filter(None, pieces)):
            chunk_id = str(uuid4())
            db.add(ContextChunk(id=chunk_id, source_type=source_type, source_id=source_id,
                                conversation_id=conversation_id, project_id=project_id, ordinal=index,
                                content=piece, metadata_json=metadata or {}))
            if db.bind and db.bind.dialect.name == "sqlite":
                db.execute(text("INSERT INTO context_chunks_fts(chunk_id, content) VALUES (:id, :content)"), {"id": chunk_id, "content": piece})
        db.flush()
        return len(pieces)

    def search_context(self, db: Session, query: str, conversation_id: str | None = None,
                       project_id: str | None = None, limit: int = 5) -> list[dict]:
        terms = re.findall(r"[\w-]{2,}", query, flags=re.UNICODE)[:12]
        if not terms:
            return []
        rows = []
        if db.bind and db.bind.dialect.name == "sqlite":
            expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
            scope_sql = " AND (conversation_id = :conversation_id OR project_id = :project_id)" if conversation_id or project_id else ""
            rows = db.execute(text(f"""SELECT c.id, c.source_type, c.source_id, c.conversation_id, c.project_id,
                c.ordinal, c.content, c.metadata_json, bm25(context_chunks_fts) AS score
                FROM context_chunks_fts JOIN document_chunks c ON c.id=context_chunks_fts.chunk_id
                WHERE context_chunks_fts MATCH :query{scope_sql} ORDER BY score LIMIT :limit"""),
                {"query": expression, "conversation_id": conversation_id, "project_id": project_id, "limit": limit}).mappings().all()
        if not rows:
            from sqlalchemy import or_
            query_filter = or_(*(ContextChunk.content.ilike(f"%{term}%") for term in terms))
            scoped = []
            if conversation_id:
                scoped.append(ContextChunk.conversation_id == conversation_id)
            if project_id:
                scoped.append(ContextChunk.project_id == project_id)
            q = db.query(ContextChunk).filter(query_filter)
            if scoped:
                q = q.filter(or_(*scoped))
            rows = q.limit(limit).all()
        results = []
        for row in rows:
            def value(key):
                return row[key] if isinstance(row, dict) or hasattr(row, "keys") else getattr(row, key)
            results.append({"source_type": value("source_type"), "source_id": value("source_id"),
                            "conversation_id": value("conversation_id"), "project_id": value("project_id"),
                            "ordinal": value("ordinal"), "content": value("content"), "metadata": value("metadata_json")})
        return results


context_manager = ContextManager()
