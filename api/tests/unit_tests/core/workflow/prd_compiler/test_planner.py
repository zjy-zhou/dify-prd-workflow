from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.workflow.prd_compiler.planner import PrdWorkflowPlanner, PrdWorkflowPlannerError
from core.workflow.prd_compiler.wiki_context import PrdWikiContext


class _FakeModelInstance:
    outputs: list[str]

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs

    def invoke_llm(self, **_kwargs):
        text = self.outputs.pop(0)
        return SimpleNamespace(message=SimpleNamespace(get_text_content=lambda: text))


def _context() -> PrdWikiContext:
    return PrdWikiContext.model_validate(
        {
            "doc_id": "wiki-doc-1",
            "workspace": "workspace-1",
            "source_name": "Opportunity PRD",
            "tree_type": "reasoning_action",
            "tree_json": {"id": "root", "kind": "root", "title": "Opportunity PRD", "children": []},
        }
    )


def _ir_payload(**overrides) -> dict:
    raw = {
        "id": "opportunity-discovery",
        "title": "Opportunity Discovery",
        "scenario": "Discover opportunities from a PRD.",
        "inputs": [{"name": "prd_context", "type": "object"}],
        "outputs": [{"name": "answer", "type": "string"}],
        "phases": [
            {"id": "start", "kind": "workflow_start", "title": "Start"},
            {"id": "plan", "kind": "llm_task", "title": "Plan"},
            {"id": "answer", "kind": "workflow_output", "title": "Answer"},
        ],
        "edges": [
            {"source": "start", "target": "plan"},
            {"source": "plan", "target": "answer"},
        ],
        "schemas": [],
        "skills": [],
    }
    raw.update(overrides)
    return raw


def test_prd_workflow_planner_returns_validated_ir() -> None:
    model = _FakeModelInstance([json.dumps(_ir_payload())])

    result = PrdWorkflowPlanner.plan(model_instance=model, model_parameters={}, prd_context=_context())

    assert result.ir.id == "opportunity-discovery"
    assert result.validation.is_valid is True
    assert result.validation.errors == []


def test_prd_workflow_planner_retries_once_and_fails_on_non_json() -> None:
    model = _FakeModelInstance(["not json", "still not json"])

    with pytest.raises(PrdWorkflowPlannerError) as exc_info:
        PrdWorkflowPlanner.plan(model_instance=model, model_parameters={}, prd_context=_context())

    assert exc_info.value.code == "workflow_ir_invalid_json"


def test_prd_workflow_planner_fails_on_invalid_ir_shape() -> None:
    model = _FakeModelInstance([json.dumps({"id": "missing-required-fields"})])

    with pytest.raises(PrdWorkflowPlannerError) as exc_info:
        PrdWorkflowPlanner.plan(model_instance=model, model_parameters={}, prd_context=_context())

    assert exc_info.value.code == "workflow_ir_invalid_shape"


def test_prd_workflow_planner_preserves_unsupported_phase_as_validation_requirement() -> None:
    payload = _ir_payload(
        phases=[
            {"id": "start", "kind": "workflow_start", "title": "Start"},
            {"id": "http", "kind": "http_call", "title": "Call API"},
            {"id": "answer", "kind": "workflow_output", "title": "Answer"},
        ],
        edges=[
            {"source": "start", "target": "http"},
            {"source": "http", "target": "answer"},
        ],
    )
    model = _FakeModelInstance([json.dumps(payload)])

    result = PrdWorkflowPlanner.plan(model_instance=model, model_parameters={}, prd_context=_context())

    assert result.validation.is_valid is False
    assert result.validation.missing_requirements == ["unsupported_phase_kind:http_call"]
