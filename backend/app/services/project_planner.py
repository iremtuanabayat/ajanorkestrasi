import logging
import re

from app.llm.ollama_provider import ollama
from app.schemas.project import ProjectPlan

logger = logging.getLogger(__name__)


class ProjectPlanner:
    async def plan(self, message: str, model: str | None = None) -> ProjectPlan:
        prompt = (
            "Create a concise implementation plan as JSON with fields: project_name, project_type, requirements, "
            "selected_agents, technology_stack, execution_steps, expected_files, testing_requirements, "
            "delivery_requirements, frontend_required, backend_required. Do not add a backend unless the user "
            "explicitly requests server-side behavior. For a simple website use a static frontend and include "
            "frontend/index.html, frontend/style.css, frontend/script.js.\n"
            f"User request: {message}"
        )
        try:
            raw = await ollama.chat_json(prompt, "You are a pragmatic project planner. Avoid unnecessary services.", model)
            plan = ProjectPlan.model_validate_json(raw)
        except Exception:
            logger.exception("[PLANNER] planning failed; using static-web plan")
            name = re.sub(r"[^\w -]", "", message[:50], flags=re.UNICODE).strip() or "AI Orchestra Project"
            return ProjectPlan(
                project_name=name,
                project_type="static_web",
                requirements=[message],
                selected_agents=["Frontend Agent", "QA Agent"],
                technology_stack=["HTML", "CSS", "JavaScript"],
                execution_steps=["Generate frontend files", "Run static QA", "Start local preview"],
                expected_files=["frontend/index.html", "frontend/style.css", "frontend/script.js"],
                testing_requirements=["Check required files", "Parse JavaScript", "Fetch preview page"],
                delivery_requirements=["Return preview URL", "List generated files"],
            )
        if plan.backend_required:
            raise RuntimeError("This task requires a backend. The isolated backend runtime is not enabled yet; no server code was executed.")
        plan.frontend_required = True
        if not plan.technology_stack:
            plan.technology_stack = ["HTML", "CSS", "JavaScript"]
        plan.expected_files = ["frontend/index.html", "frontend/style.css", "frontend/script.js"]
        logger.info("[PLANNER] project=%s type=%s", plan.project_name, plan.project_type)
        return plan


planner = ProjectPlanner()
