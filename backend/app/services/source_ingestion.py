import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session

from app.database.models import SourceLink
from app.services.context_manager import context_manager
from app.services.document_processor import extract_document

MAX_SOURCE_BYTES = 2_000_000


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._in_title = False
        self._blocked = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self._blocked += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self._blocked:
            self._blocked -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        value = " ".join(data.split())
        if not value:
            return
        if self._in_title:
            self.title += value + " "
        if not self._blocked:
            self.parts.append(value)


def _validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Yalnızca kullanıcı bilgisi içermeyen HTTP(S) bağlantıları desteklenir")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Yerel veya özel ağ adreslerine erişim engellendi")
    try:
        addresses = {ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))}
    except (OSError, ValueError) as exc:
        raise ValueError("Alan adı çözümlenemedi") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Özel veya yerel IP adresine çözümlenen URL engellendi")
    return url


async def ingest_url(db: Session, url: str, conversation_id: str | None = None,
                     project_id: str | None = None) -> SourceLink:
    safe_url = _validate_public_url(url)
    async with httpx.AsyncClient(timeout=12, follow_redirects=False, headers={"User-Agent": "AIOrchestraLocal/1.0"}) as client:
        async with client.stream("GET", safe_url) as response:
            if response.is_redirect:
                raise ValueError("Yönlendirmeli bağlantılar güvenlik nedeniyle kabul edilmiyor")
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type not in {"text/html", "text/plain", "application/xhtml+xml", "application/pdf"}:
                raise ValueError(f"Bu kaynak türü henüz çözümlenemiyor: {content_type or 'bilinmiyor'}")
            chunks = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_SOURCE_BYTES:
                    raise ValueError("Kaynak 2 MB sınırını aşıyor")
                chunks.append(chunk)
    raw = b"".join(chunks)
    title = ""
    if content_type == "application/pdf":
        text, _ = extract_document("source.pdf", raw)
    else:
        text = raw.decode("utf-8", errors="replace")
    if content_type in {"text/html", "application/xhtml+xml"}:
        parser = TextExtractor()
        parser.feed(text)
        text, title = "\n".join(parser.parts), parser.title.strip()
    row = SourceLink(id=str(uuid4()), conversation_id=conversation_id, project_id=project_id,
                     url=safe_url, title=title[:500], content_type=content_type,
                     extracted_text=text[:2_000_000], processing_status="ready")
    db.add(row)
    db.flush()
    context_manager.add_document(db, "url", row.id, row.extracted_text, conversation_id, project_id,
                                 {"url": safe_url, "title": row.title})
    db.commit()
    db.refresh(row)
    return row
