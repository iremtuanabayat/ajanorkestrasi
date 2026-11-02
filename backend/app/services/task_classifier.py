import json
import logging
import re

from pydantic import ValidationError

from app.llm.ollama_provider import ollama
from app.schemas.project import TaskClassification, TaskType

logger = logging.getLogger(__name__)


class TaskClassifier:
    async def classify(self, message: str, model: str | None = None) -> TaskClassification:
        prompt = (
            "Classify the user request. Return JSON only with task_type (information, code_generation, "
            "project_creation, project_modification, data_analysis), confidence, needs_clarification, "
            "clarification_question. A request to build a website/app/project is project_creation; "
            "change an existing project is project_modification; asking for a code snippet is code_generation.\n"
            f"Request: {message}"
        )
        try:
            raw = await ollama.chat_json(prompt, "You classify software tasks precisely.", model)
            result = TaskClassification.model_validate_json(raw)
            logger.info("[CLASSIFIER] type=%s confidence=%.2f", result.task_type.value, result.confidence)
            return result
        except (ValidationError, ValueError, TypeError):
            logger.exception("[CLASSIFIER] invalid structured response; using conservative fallback")
        except Exception:
            logger.exception("[CLASSIFIER] model classification failed; using conservative fallback")
        text = message.lower()
        if re.search(r"(mevcut|var olan).{0,40}(proje|site|uygulama).{0,60}(ekle|değiştir|düzelt|refactor|tema)", text):
            task_type = TaskType.project_modification
        elif re.search(r"(oluştur|yap|geliştir|build|create).{0,60}(site|web|uygulama|proje|app)", text):
            task_type = TaskType.project_creation
        elif re.search(r"(fonksiyon|function|kod|code).{0,50}(yaz|oluştur|üret)", text):
            task_type = TaskType.code_generation
        elif re.search(r"(veri|dataset).{0,50}(analiz|temizle|model)", text):
            task_type = TaskType.data_analysis
        else:
            task_type = TaskType.information
        logger.warning("[CLASSIFIER] fallback type=%s", task_type.value)
        return TaskClassification(task_type=task_type, confidence=0.35)


classifier = TaskClassifier()
