from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.workflow.prd_compiler.entities import PrdWorkflowGeneratePayload, WorkflowIRPlanningResult
from core.workflow.prd_compiler.planner import PrdWorkflowPlannerError
from core.workflow.prd_compiler.wiki_context import PrdWikiContext
from services.errors.app import WorkflowHashNotEqualError
from services.prd_context_service import PrdContextServiceError
from services.prd_workflow_generator_service import (
    PrdWorkflowGeneratorService,
    UnsupportedPrdWorkflowSourceError,
)


def _payload(**overrides) -> PrdWorkflowGeneratePayload:
    raw = {
        "app_id": "app-1",
        "source": {
            "type": "wiki_tree_context",
            "doc_id": "wiki-doc-1",
            "workspace": "workspace-1",
        },
        "model_config": {
            "provider": "langgenius/tongyi/tongyi",
            "name": "qwen-plus",
            "mode": "chat",
            "completion_params": {},
        },
    }
    raw.update(overrides)
    return PrdWorkflowGeneratePayload.model_validate(raw)


def _context(**overrides) -> PrdWikiContext:
    raw = {
        "doc_id": "wiki-doc-1",
        "workspace": "workspace-1",
        "source_name": "Opportunity PRD",
        "version": 3,
        "tree_type": "reasoning_action",
        "tree_json": {"id": "root", "kind": "root", "title": "Opportunity PRD", "children": []},
        "warnings": [],
    }
    raw.update(overrides)
    return PrdWikiContext.model_validate(raw)


def _planning_result(**validation_overrides) -> WorkflowIRPlanningResult:
    raw = {
        "ir": {
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
        },
        "validation": {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "missing_requirements": [],
        },
    }
    raw["validation"].update(validation_overrides)
    return WorkflowIRPlanningResult.model_validate(raw)


def test_generate_from_prd_uses_tenant_scoped_app_query(monkeypatch: pytest.MonkeyPatch) -> None:
    app_model = SimpleNamespace(id="app-1", tenant_id="tenant-1", mode="workflow")
    draft = SimpleNamespace(
        id="workflow-1",
        unique_hash="hash-1",
        normalized_features_dict={},
        environment_variables=[],
        conversation_variables=[],
    )
    workflow_service = SimpleNamespace(
        get_draft_workflow=lambda **_kwargs: draft,
        sync_draft_workflow=lambda **_kwargs: SimpleNamespace(id="workflow-1", unique_hash="hash-2"),
    )
    session = MagicMock()
    session.scalar.return_value = app_model

    monkeypatch.setattr(
        "services.prd_workflow_generator_service.WorkflowService",
        lambda: workflow_service,
    )
    monkeypatch.setattr(
        PrdWorkflowGeneratorService,
        "_resolve_planner_model_context",
        staticmethod(lambda **_kwargs: (SimpleNamespace(), {})),
    )

    response = PrdWorkflowGeneratorService.generate_from_prd(
        session=session,
        tenant_id="tenant-1",
        payload=_payload(),
        account=SimpleNamespace(id="account-1"),
        context_service=SimpleNamespace(fetch_wiki_tree_context=lambda _source: _context()),
        planner=SimpleNamespace(plan=lambda **_kwargs: _planning_result()),
    )

    stmt = session.scalar.call_args.args[0]
    compiled = stmt.compile()
    statement = str(compiled)
    assert "apps.id" in statement
    assert "apps.tenant_id" in statement
    assert "apps.status" in statement
    assert "apps.mode" in statement
    assert "app-1" in compiled.params.values()
    assert "tenant-1" in compiled.params.values()
    assert response.draft_synced is True
    assert response.workflow.id == "workflow-1"
    assert response.workflow.hash == "hash-2"
    assert response.graph == {
        "node_count": 3,
        "edge_count": 2,
        "node_types": ["start", "llm", "end"],
    }


def test_generate_from_prd_returns_failed_response_when_wiki_context_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_model = SimpleNamespace(id="app-1", tenant_id="tenant-1", mode="workflow")
    draft = SimpleNamespace(id="workflow-1", unique_hash="hash-1")
    session = MagicMock()
    session.scalar.return_value = app_model

    monkeypatch.setattr(
        "services.prd_workflow_generator_service.WorkflowService",
        lambda: SimpleNamespace(get_draft_workflow=lambda **_kwargs: draft),
    )

    def _raise(_source):
        raise PrdContextServiceError(
            "Wiki Tree Context API returned HTTP 500: failed",
            code="wiki_context_server_error",
        )

    response = PrdWorkflowGeneratorService.generate_from_prd(
        session=session,
        tenant_id="tenant-1",
        payload=_payload(),
        context_service=SimpleNamespace(fetch_wiki_tree_context=_raise),
    )

    assert response.result == "failed"
    assert response.draft_synced is False
    assert response.workflow.hash == "hash-1"
    assert response.missing_requirements == ["wiki_context_server_error"]
    assert "HTTP 500" in response.warnings[0]


def test_generate_from_prd_returns_failed_response_when_planner_returns_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_model = SimpleNamespace(id="app-1", tenant_id="tenant-1", mode="workflow")
    draft = SimpleNamespace(id="workflow-1", unique_hash="hash-1")
    session = MagicMock()
    session.scalar.return_value = app_model

    monkeypatch.setattr(
        "services.prd_workflow_generator_service.WorkflowService",
        lambda: SimpleNamespace(get_draft_workflow=lambda **_kwargs: draft),
    )
    monkeypatch.setattr(
        PrdWorkflowGeneratorService,
        "_resolve_planner_model_context",
        staticmethod(lambda **_kwargs: (SimpleNamespace(), {})),
    )

    def _raise(**_kwargs):
        raise PrdWorkflowPlannerError("LLM planner returned non-JSON Workflow IR", code="workflow_ir_invalid_json")

    response = PrdWorkflowGeneratorService.generate_from_prd(
        session=session,
        tenant_id="tenant-1",
        payload=_payload(),
        context_service=SimpleNamespace(fetch_wiki_tree_context=lambda _source: _context()),
        planner=SimpleNamespace(plan=_raise),
    )

    assert response.result == "failed"
    assert response.draft_synced is False
    assert response.missing_requirements == ["workflow_ir_invalid_json"]
    assert "non-JSON" in response.warnings[0]


def test_generate_from_prd_returns_failed_response_when_ir_validation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_model = SimpleNamespace(id="app-1", tenant_id="tenant-1", mode="workflow")
    draft = SimpleNamespace(id="workflow-1", unique_hash="hash-1")
    session = MagicMock()
    session.scalar.return_value = app_model

    monkeypatch.setattr(
        "services.prd_workflow_generator_service.WorkflowService",
        lambda: SimpleNamespace(get_draft_workflow=lambda **_kwargs: draft),
    )
    monkeypatch.setattr(
        PrdWorkflowGeneratorService,
        "_resolve_planner_model_context",
        staticmethod(lambda **_kwargs: (SimpleNamespace(), {})),
    )

    response = PrdWorkflowGeneratorService.generate_from_prd(
        session=session,
        tenant_id="tenant-1",
        payload=_payload(),
        context_service=SimpleNamespace(fetch_wiki_tree_context=lambda _source: _context()),
        planner=SimpleNamespace(
            plan=lambda **_kwargs: _planning_result(
                is_valid=False,
                warnings=["Workflow IR phase kind 'http_call' is planned for a later node expansion stage."],
                missing_requirements=["unsupported_phase_kind:http_call"],
            )
        ),
    )

    assert response.result == "failed"
    assert response.draft_synced is False
    assert response.missing_requirements == ["unsupported_phase_kind:http_call"]
    assert "http_call" in response.warnings[0]


def test_generate_from_prd_rejects_stale_draft_hash_before_external_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_model = SimpleNamespace(id="app-1", tenant_id="tenant-1", mode="workflow")
    draft = SimpleNamespace(id="workflow-1", unique_hash="current-hash")
    context_service = SimpleNamespace(fetch_wiki_tree_context=MagicMock())
    session = MagicMock()
    session.scalar.return_value = app_model

    monkeypatch.setattr(
        "services.prd_workflow_generator_service.WorkflowService",
        lambda: SimpleNamespace(get_draft_workflow=lambda **_kwargs: draft),
    )

    with pytest.raises(WorkflowHashNotEqualError):
        PrdWorkflowGeneratorService.generate_from_prd(
            session=session,
            tenant_id="tenant-1",
            payload=_payload(draft_hash="stale-hash"),
            context_service=context_service,
        )

    context_service.fetch_wiki_tree_context.assert_not_called()


def test_generate_from_prd_rejects_non_wiki_source_without_db_query() -> None:
    payload = _payload()
    payload.source.type = "text"  # type: ignore[assignment]
    session = MagicMock()

    with pytest.raises(UnsupportedPrdWorkflowSourceError):
        PrdWorkflowGeneratorService.generate_from_prd(
            session=session,
            tenant_id="tenant-1",
            payload=payload,
        )

    session.scalar.assert_not_called()
