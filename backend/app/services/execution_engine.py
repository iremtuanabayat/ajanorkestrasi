import json
import logging
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from app.llm.ollama_provider import ollama
from app.schemas.project import GeneratedProject, ProjectPlan

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3] / "workspace" / "projects"
ALLOWED_EXTENSIONS = {".html", ".css", ".js", ".json", ".md", ".svg", ".txt"}
MAX_FILE_BYTES = 1_000_000
MAX_PROJECT_BYTES = 5_000_000


class FileManager:
    def __init__(self, root: Path = PROJECT_ROOT):
        self.root = root.resolve()

    def create_project(self, project_id: str) -> Path:
        project = (self.root / project_id).resolve()
        if not project.is_relative_to(self.root) or project.exists():
            raise ValueError("Project workspace path is invalid or already exists")
        self.root.mkdir(parents=True, exist_ok=True)
        (project / "frontend").mkdir(parents=True)
        return project

    def _safe_target(self, project: Path, relative: str) -> Path:
        pure = PurePosixPath(relative.replace("\\", "/"))
        if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
            raise ValueError("Generated file path is not allowed")
        if pure.parts[0] not in {"frontend", "backend"}:
            raise ValueError("Generated files must be inside a project component folder")
        if Path(pure.name).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise ValueError("Generated file extension is not allowed")
        target = (project / Path(*pure.parts)).resolve()
        if not target.is_relative_to(project.resolve()):
            raise ValueError("Generated file escaped its project workspace")
        return target

    def write_files(self, project: Path, files: list[dict], overwrite: bool = False) -> list[str]:
        total = 0
        seen: set[str] = set()
        paths: list[str] = []
        validated: list[tuple[Path, str, str]] = []
        for item in files:
            relative = item["path"]
            target = self._safe_target(project, relative)
            normalized = target.relative_to(project.resolve()).as_posix()
            if normalized in seen:
                raise ValueError("Duplicate generated file path")
            seen.add(normalized)
            content = item["content"]
            encoded_size = len(content.encode("utf-8"))
            if encoded_size > MAX_FILE_BYTES:
                raise ValueError("Generated file exceeds the per-file size limit")
            total += encoded_size
            validated.append((target, normalized, content))
        if total > MAX_PROJECT_BYTES:
            raise ValueError("Generated project exceeds the total size limit")
        for target, normalized, content in validated:
            if target.exists() and not overwrite:
                raise FileExistsError(f"Refusing to overwrite an existing file: {normalized}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
            paths.append(normalized)
        return paths

    def write_metadata(self, project: Path, filename: str, content: dict):
        target = (project / filename).resolve()
        if not target.is_relative_to(project.resolve()) or target.exists():
            raise ValueError("Project metadata path is invalid")
        target.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


class ProjectCodeGenerator:
    async def generate(self, message: str, plan: ProjectPlan, model: str | None = None, repair_feedback: str | None = None, existing_files: dict[str, str] | None = None) -> GeneratedProject:
        prompt = (
            "Create a complete, polished, responsive static web project. Return JSON exactly as "
            "{\"files\":[{\"path\":\"frontend/index.html\",\"content\":\"...\"},...],\"summary\":\"...\"}. "
            "Include frontend/index.html, frontend/style.css, frontend/script.js. HTML must link the CSS and JS. "
            "Do not include markdown fences, backend code, package installation, or other file paths. "
            f"Project name: {plan.project_name}. Requirements: {json.dumps(plan.requirements, ensure_ascii=False)}. "
            f"Repair feedback: {repair_feedback or 'None'}. Existing project files to preserve/update: {json.dumps(existing_files or {}, ensure_ascii=False)}. "
            f"Original user request: {message}"
        )
        system = "You are the Frontend Agent. Output only valid JSON matching the requested file structure. Escape JSON strings correctly."
        last_error = "unknown output error"
        for attempt in range(2):
            try:
                raw = await ollama.chat_json(prompt if attempt == 0 else f"{prompt}\nPrevious output validation failed: {last_error}. Return corrected valid JSON.", system, model)
                result = GeneratedProject.model_validate_json(raw)
                paths = {item.path for item in result.files}
                required = {"frontend/index.html", "frontend/style.css", "frontend/script.js"}
                if not required.issubset(paths):
                    raise ValueError("Generated output omitted one or more required frontend files")
                if any(not item.path.startswith("frontend/") for item in result.files):
                    raise ValueError("Static web generation may only write frontend files")
                logger.info("[EXECUTION] structured files validated count=%d", len(result.files))
                return result
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)
                logger.warning("[EXECUTION] output validation failed attempt=%d reason=%s", attempt + 1, last_error)
        raise RuntimeError(f"Code agent did not return valid project files: {last_error}")


file_manager = FileManager()
code_generator = ProjectCodeGenerator()
