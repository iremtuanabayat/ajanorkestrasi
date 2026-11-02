import asyncio
import json
import logging
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.database.models import Artifact, Project, Task
from app.schemas.project import ProjectPlan
from app.services.execution_engine import FileManager, ProjectCodeGenerator, file_manager, code_generator
from app.services.project_planner import planner
from app.services.qa_engine import qa_engine
from app.services.runtime_manager import runtime_manager
from app.services.artifact_manager import register_project_files

logger = logging.getLogger(__name__)


class ProjectState(TypedDict, total=False):
    task: Task
    db: Session
    prompt: str
    model: str | None
    project: Project
    existing_project: Project | None
    plan: ProjectPlan
    workspace: Path
    generated: Any
    old_files: dict[str, str]
    written_files: list[str]
    preview_url: str
    runtime_pid: int
    test_results: dict
    repair_count: int
    answer: str
    publish: Any
    cancelled: Any


class ProjectExecutor:
    def __init__(self, planner_service=planner, generator: ProjectCodeGenerator = code_generator,
                 files: FileManager = file_manager, qa=qa_engine, runtime=runtime_manager):
        self.planner = planner_service
        self.generator = generator
        self.files = files
        self.qa = qa
        self.runtime = runtime
        graph = StateGraph(ProjectState)
        graph.add_node("planning", self._planning)
        graph.add_node("generate", self._generate)
        graph.add_node("write_files", self._write_files)
        graph.add_node("start_runtime", self._start_runtime)
        graph.add_node("qa", self._qa)
        graph.add_node("repair", self._repair)
        graph.add_node("deliver", self._deliver)
        graph.add_edge(START, "planning")
        graph.add_edge("planning", "generate")
        graph.add_edge("generate", "write_files")
        graph.add_edge("write_files", "start_runtime")
        graph.add_edge("start_runtime", "qa")
        graph.add_conditional_edges("qa", self._qa_route, {"repair": "repair", "deliver": "deliver"})
        graph.add_edge("repair", "start_runtime")
        graph.add_edge("deliver", END)
        self.graph = graph.compile()

    async def _progress(self, state: ProjectState, step: str, label: str):
        task = state["task"]
        task.current_step = step
        task.execution_logs = [*(task.execution_logs or []), {"step": step, "label": label}]
        state["db"].commit()
        await state["publish"]("step", {"status": "started", "label": label, "step": step})
        if state["cancelled"]():
            raise asyncio.CancelledError

    async def _planning(self, state: ProjectState):
        await self._progress(state, "planning", "Proje planı hazırlanıyor")
        if state.get("existing_project"):
            project = state["existing_project"]
            plan = ProjectPlan(project_name=project.name, project_type=project.project_type,
                               technology_stack=project.technology_stack or ["HTML", "CSS", "JavaScript"],
                               expected_files=project.generated_files or ["frontend/index.html", "frontend/style.css", "frontend/script.js"])
            plan.requirements = [state["prompt"]]
        else:
            plan = await self.planner.plan(state["prompt"], state.get("model"))
        if plan.backend_required:
            raise RuntimeError("This task requires a backend. The isolated backend runtime is not enabled yet; no server code was executed.")
        task = state["task"]
        if state.get("existing_project"):
            project = state["existing_project"]
            project.task_id = task.id
            project.status = "planning"
        else:
            project_id = str(uuid4())
            workspace = self.files.create_project(project_id)
            project = Project(id=project_id, task_id=task.id, conversation_id=task.conversation_id,
                              name=plan.project_name, project_type=plan.project_type, status="planning",
                              workspace_path=str(workspace), technology_stack=plan.technology_stack,
                              manifest={"plan": plan.model_dump(mode="json")})
            state["db"].add(project)
        task.project_id = project.id
        task.task_type = "project_modification" if state.get("existing_project") else "project_creation"
        task.selected_agents = plan.selected_agents or ["Planner", "Frontend Agent", "QA Agent"]
        project.manifest = {**(project.manifest or {}), "plan": plan.model_dump(mode="json")}
        state["db"].commit()
        return {"project": project, "plan": plan, "workspace": Path(project.workspace_path), "repair_count": 0}

    def _read_existing(self, state: ProjectState) -> dict[str, str]:
        project = state["project"]
        result = {}
        for relative in project.generated_files or []:
            path = self.files._safe_target(Path(project.workspace_path), relative)
            if path.is_file():
                result[relative] = path.read_text(encoding="utf-8")
        return result

    async def _generate(self, state: ProjectState):
        await self._progress(state, "generation", "Arayüz dosyaları üretiliyor")
        existing = self._read_existing(state) if state.get("existing_project") else {}
        generated = await self.generator.generate(state["prompt"], state["plan"], state.get("model"), existing_files=existing)
        return {"generated": generated, "old_files": existing}

    async def _write_files(self, state: ProjectState):
        await self._progress(state, "writing", "Dosyalar güvenli çalışma alanına yazılıyor")
        paths = self.files.write_files(state["workspace"], [item.model_dump() for item in state["generated"].files], overwrite=bool(state.get("existing_project")))
        project, task = state["project"], state["task"]
        project.generated_files = sorted(set((project.generated_files or []) + paths))
        project.status = "starting"
        task.generated_files = paths
        project.manifest = {**(project.manifest or {}), "technology_stack": project.technology_stack, "generated_files": project.generated_files, "plan": json.loads(state["plan"].model_dump_json())}
        register_project_files(state["db"], project.id, task.id, state["workspace"], paths)
        state["db"].commit()
        return {"written_files": paths}

    async def _start_runtime(self, state: ProjectState):
        await self._progress(state, "runtime", "Yerel statik önizleme başlatılıyor")
        project = state["project"]
        self.runtime.stop(project.id)
        preview_url, pid = await self.runtime.start_static(project.id)
        project.preview_url = preview_url
        project.runtime_pid = pid
        state["task"].preview_url = preview_url
        project.status = "testing"
        state["task"].current_step = "qa"
        state["db"].commit()
        return {"preview_url": preview_url, "runtime_pid": pid}

    async def _qa(self, state: ProjectState):
        await self._progress(state, "qa", "Otomatik kalite kontrolleri çalışıyor")
        result = await self.qa.run_static_checks(state["project"].id, state["preview_url"])
        state["project"].test_results = result
        state["task"].test_results = result
        state["db"].commit()
        await state["publish"]("step", {"status": "completed", "label": "Kalite kontrolü tamamlandı", "passed": result["passed"], "checks": result["checks"]})
        return {"test_results": result}

    @staticmethod
    def _qa_route(state: ProjectState) -> str:
        if not state["test_results"]["passed"] and state.get("repair_count", 0) < 1:
            return "repair"
        return "deliver"

    async def _repair(self, state: ProjectState):
        await self._progress(state, "repair", "QA bulgularına göre bir düzeltme deneniyor")
        feedback = "\n".join(f"{check['name']}: {check['details']}" for check in state["test_results"]["checks"] if not check["passed"])
        generated = await self.generator.generate(state["prompt"], state["plan"], state.get("model"), repair_feedback=feedback, existing_files=state["old_files"])
        paths = self.files.write_files(state["workspace"], [item.model_dump() for item in generated.files], overwrite=True)
        state["project"].generated_files = sorted(set((state["project"].generated_files or []) + paths))
        state["project"].manifest = {**(state["project"].manifest or {}), "generated_files": state["project"].generated_files}
        state["task"].generated_files = paths
        state["test_results"] = {**state["test_results"], "passed": False}
        state["project"].manifest = {**(state["project"].manifest or {}), "plan": json.loads(state["plan"].model_dump_json()), "generated_files": state["project"].generated_files}
        register_project_files(state["db"], state["project"].id, state["task"].id, state["workspace"], paths)
        state["db"].commit()
        return {"generated": generated, "written_files": paths, "repair_count": state.get("repair_count", 0) + 1}

    async def _deliver(self, state: ProjectState):
        await self._progress(state, "delivery", "Proje teslimi hazırlanıyor")
        project, tests = state["project"], state["test_results"]
        project.status = "completed" if tests["passed"] else "completed_with_qa_warnings"
        project.test_results = tests
        project.manifest = {**(project.manifest or {}), "test_results": tests, "status": project.status}
        state["task"].current_step = "completed"
        state["task"].test_results = tests
        state["db"].commit()
        delivery = {"project_id": project.id, "project_name": project.name, "project_type": project.project_type,
                    "technology_stack": project.technology_stack or [], "generated_files": project.generated_files or [],
                    "status": project.status, "test_status": "passed" if tests["passed"] else "warning",
                    "preview_url": project.preview_url, "workspace_path": project.workspace_path, "test_results": tests,
                    "artifacts": [{"artifact_id": row.id, "filename": row.filename, "version": row.version,
                                   "download_url": f"/api/artifacts/{row.id}/download"}
                                  for row in state["db"].query(Artifact).filter(Artifact.project_id == project.id).order_by(Artifact.created_at.desc()).all()]}
        return {"answer": f"{project.name} projesi hazır. Önizleme: {project.preview_url}", "delivery": delivery}

    async def execute(self, task: Task, db: Session, prompt: str, model: str | None, publish, cancelled,
                      existing_project: Project | None = None) -> dict:
        initial: ProjectState = {"task": task, "db": db, "prompt": prompt, "model": model,
                                 "existing_project": existing_project, "publish": publish, "cancelled": cancelled}
        final: ProjectState = initial
        async for update in self.graph.astream(initial, stream_mode="updates"):
            if cancelled():
                raise asyncio.CancelledError
            for delta in update.values():
                final.update(delta)
        return {"response": final["answer"], "project_delivery": final["delivery"]}

    def mark_failed(self, task: Task, db: Session, status: str = "failed"):
        if task.project_id:
            project = db.get(Project, task.project_id)
            if project:
                project.status = status
        db.commit()


project_executor = ProjectExecutor()
