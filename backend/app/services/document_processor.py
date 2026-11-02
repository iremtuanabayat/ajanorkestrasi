import csv
import io
import json
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".json", ".py", ".js", ".ts", ".html", ".css", ".zip", ".png", ".jpg", ".jpeg", ".webp"}
MAX_TEXT_CHARS = 2_000_000
MAX_ARCHIVE_FILES = 500
MAX_ARCHIVE_EXPANDED = 20_000_000


def _xml_text(data: bytes) -> str:
    root = ElementTree.fromstring(data)
    return " ".join(part.strip() for part in root.itertext() if part.strip())


def _archive_members(data: bytes):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ARCHIVE_FILES or sum(item.file_size for item in entries) > MAX_ARCHIVE_EXPANDED:
            raise ValueError("Archive exceeds processing limits")
        safe = []
        for item in entries:
            path = PurePosixPath(item.filename.replace("\\", "/"))
            if path.is_absolute() or any(part in {"..", ""} for part in path.parts) or (path.parts and ":" in path.parts[0]):
                raise ValueError("Archive contains an unsafe path")
            safe.append((item, path.as_posix()))
        return safe


def extract_document(filename: str, data: bytes) -> tuple[str, dict]:
    from pathlib import PurePosixPath
    import os
    extension = PurePosixPath(os.path.basename(filename)).suffix.lower()
    if extension in {".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json"}:
        text = data.decode("utf-8-sig")
        if extension == ".json":
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        return text[:MAX_TEXT_CHARS], {"format": extension[1:]}
    if extension == ".csv":
        text = data.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        return "\n".join(" | ".join(row) for row in rows[:5000])[:MAX_TEXT_CHARS], {"rows": min(len(rows), 5000)}
    if extension == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("PDF metin çıkarımı için pypdf kurulu değil") from exc
        reader = PdfReader(io.BytesIO(data), strict=False)
        pages = [f"[Sayfa {index + 1}]\n{page.extract_text() or ''}" for index, page in enumerate(reader.pages[:500])]
        return "\n\n".join(pages)[:MAX_TEXT_CHARS], {"pages": len(pages)}
    if extension == ".docx":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if len(archive.infolist()) > MAX_ARCHIVE_FILES or sum(item.file_size for item in archive.infolist()) > MAX_ARCHIVE_EXPANDED:
                raise ValueError("DOCX expanded content exceeds processing limits")
            document = _xml_text(archive.read("word/document.xml"))
            return document[:MAX_TEXT_CHARS], {"format": "docx"}
    if extension == ".xlsx":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if len(archive.infolist()) > MAX_ARCHIVE_FILES or sum(item.file_size for item in archive.infolist()) > MAX_ARCHIVE_EXPANDED:
                raise ValueError("XLSX expanded content exceeds processing limits")
            shared = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                shared = ["".join(node.itertext()) for node in root]
            blocks = []
            sheets = sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
            for sheet_index, sheet_name in enumerate(sheets[:30]):
                root = ElementTree.fromstring(archive.read(sheet_name))
                rows = []
                for row in root.iter():
                    if row.tag.endswith("}row"):
                        cells = []
                        for cell in row:
                            if not cell.tag.endswith("}c"):
                                continue
                            value = next((child.text for child in cell if child.tag.endswith("}v")), "")
                            if cell.attrib.get("t") == "s" and value:
                                value = shared[int(value)]
                            cells.append(value or "")
                        rows.append(" | ".join(cells))
                        if len(rows) >= 3000:
                            break
                blocks.append(f"[Sayfa {sheet_index + 1}]\n" + "\n".join(rows))
            return "\n\n".join(blocks)[:MAX_TEXT_CHARS], {"sheets": len(sheets)}
    if extension == ".zip":
        safe_entries = _archive_members(data)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            blocks = [f"[ZIP içeriği: {name}]\n{archive.read(item).decode('utf-8', 'replace')[:30000]}"
                      for item, name in safe_entries if not item.is_dir() and PurePosixPath(name).suffix.lower() in {".txt", ".md", ".json", ".py", ".js", ".ts", ".html", ".css"}]
        return "\n\n".join(blocks)[:MAX_TEXT_CHARS], {"members": len(safe_entries), "text_members": len(blocks)}
    if extension in {".png", ".jpg", ".jpeg", ".webp"}:
        return "", {"vision_available": False, "notice": "Yerel vision modeli yapılandırılmamış; görsel analiz edilmedi."}
    raise ValueError("Dosya türü desteklenmiyor")
