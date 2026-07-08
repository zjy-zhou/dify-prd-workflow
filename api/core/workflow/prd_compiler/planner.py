"""LLM planner that turns normalized PRD context into Workflow IR."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import json_repair
from pydantic import ValidationError

from core.workflow.prd_compiler.entities import WorkflowIR, WorkflowIRPlanningResult
from core.workflow.prd_compiler.validator import validate_workflow_ir
from core.workflow.prd_compiler.wiki_context import PrdWikiContext
from graphon.model_runtime.entities.message_entities import SystemPromptMessage, UserPromptMessage

_PROMPT_PATH = Path(__file__).parent / "prompts" / "prd_to_workflow_ir.md"
_JSON_RETRY_HINT = "Return only a valid JSON object matching the Workflow IR schema. No Markdown or prose."


class PrdWorkflowPlannerError(RuntimeError):
    """Raised when the LLM planner cannot produce parseable Workflow IR."""

    code: str

    def __init__(self, message: str, *, code: str = "prd_workflow_planner_error") -> None:
        super().__init__(message)
        self.code = code


class PrdWorkflowPlanner:
    """Pure domain planner for PRD context to Workflow IR."""

    @classmethod
    def plan(
        cls,
        *,
        model_instance: Any,
        model_parameters: dict[str, Any],
        prd_context: PrdWikiContext,
    ) -> WorkflowIRPlanningResult:
        """Invoke the model, parse Workflow IR, and run semantic validation."""
        payload = cls._invoke_and_parse_json(
            model_instance=model_instance,
            model_parameters=model_parameters,
            prd_context=prd_context,
        )
        try:
            workflow_ir = WorkflowIR.model_validate(payload)
        except ValidationError as exc:
            raise PrdWorkflowPlannerError(
                f"LLM planner returned invalid Workflow IR fields: {exc.errors()}",
                code="workflow_ir_invalid_shape",
            ) from exc

        validation = validate_workflow_ir(workflow_ir)
        return WorkflowIRPlanningResult(ir=workflow_ir, validation=validation)

    @classmethod
    def _invoke_and_parse_json(
        cls,
        *,
        model_instance: Any,
        model_parameters: dict[str, Any],
        prd_context: PrdWikiContext,
    ) -> dict[str, Any]:
        messages = cls._messages(prd_context)
        last_error = ""
        for attempt in range(2):
            attempt_messages = messages if attempt == 0 else [*messages, UserPromptMessage(content=_JSON_RETRY_HINT)]
            response = model_instance.invoke_llm(
                prompt_messages=attempt_messages,
                model_parameters=model_parameters,
                stream=False,
            )
            text = response.message.get_text_content() or ""
            try:
                parsed = json_repair.loads(text)
            except Exception as exc:
                last_error = str(exc)
                continue
            if isinstance(parsed, dict):
                return parsed
            last_error = f"LLM planner returned {type(parsed).__name__}, expected JSON object."

        raise PrdWorkflowPlannerError(
            f"LLM planner returned non-JSON Workflow IR: {last_error or 'JSON parse failed'}",
            code="workflow_ir_invalid_json",
        )

    @classmethod
    def _messages(cls, prd_context: PrdWikiContext) -> list[Any]:
        user_payload = {
            "doc_id": prd_context.doc_id,
            "source_name": prd_context.source_name,
            "tree_type": prd_context.tree_type,
            "tree_json": prd_context.tree_json,
            "outline_md": prd_context.outline_md,
            "dimension_markdown": prd_context.dimension_markdown,
            "raw_markdown_excerpt": prd_context.raw_markdown_excerpt,
            "context_warnings": prd_context.warnings,
        }
        user_prompt = (
            "Compile this normalized PRD context into Workflow IR JSON:\n"
            f"{json.dumps(user_payload, ensure_ascii=False, separators=(',', ':'))}"
        )
        return [
            SystemPromptMessage(content=_PROMPT_PATH.read_text(encoding="utf-8")),
            UserPromptMessage(content=user_prompt),
        ]
