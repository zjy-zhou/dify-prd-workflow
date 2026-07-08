from __future__ import annotations

from core.workflow.prd_compiler.entities import WorkflowIR
from core.workflow.prd_compiler.validator import validate_workflow_ir


def _valid_ir(**overrides) -> WorkflowIR:
    raw = {
        "id": "opportunity-discovery",
        "title": "Opportunity Discovery",
        "scenario": "Discover product opportunities from PRD inputs.",
        "inputs": [
            {
                "name": "prd_context",
                "type": "object",
                "description": "Normalized PRD context",
                "required": True,
            }
        ],
        "outputs": [
            {
                "name": "answer",
                "type": "string",
                "description": "Workflow answer",
                "required": True,
            }
        ],
        "phases": [
            {
                "id": "start",
                "kind": "workflow_start",
                "title": "Start",
                "outputs": ["prd_context"],
            },
            {
                "id": "plan",
                "kind": "llm_task",
                "title": "Analyze PRD",
                "goal": "Generate opportunity analysis",
                "inputs": ["prd_context"],
                "outputs": ["analysis"],
            },
            {
                "id": "answer",
                "kind": "workflow_output",
                "title": "Answer",
                "inputs": ["analysis"],
            },
        ],
        "edges": [
            {"source": "start", "target": "plan"},
            {"source": "plan", "target": "answer"},
        ],
        "schemas": [],
        "skills": [],
    }
    raw.update(overrides)
    return WorkflowIR.model_validate(raw)


def test_validate_workflow_ir_accepts_valid_ir() -> None:
    result = validate_workflow_ir(_valid_ir())

    assert result.is_valid is True
    assert result.errors == []
    assert result.warnings == []
    assert result.missing_requirements == []


def test_validate_workflow_ir_rejects_duplicate_phase_id() -> None:
    ir = _valid_ir(
        phases=[
            {"id": "start", "kind": "workflow_start", "title": "Start"},
            {"id": "start", "kind": "llm_task", "title": "Duplicate"},
        ],
        edges=[],
    )

    result = validate_workflow_ir(ir)

    assert result.is_valid is False
    assert "duplicated" in result.errors[0]


def test_validate_workflow_ir_rejects_edge_to_missing_phase() -> None:
    ir = _valid_ir(edges=[{"source": "start", "target": "missing"}])

    result = validate_workflow_ir(ir)

    assert result.is_valid is False
    assert "target 'missing'" in result.errors[0]


def test_validate_workflow_ir_requires_second_stage_node_config() -> None:
    ir = _valid_ir(
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

    result = validate_workflow_ir(ir)

    assert result.is_valid is False
    assert result.errors == []
    assert result.missing_requirements == ["missing_phase_config:http:url"]
    assert "missing required config 'url'" in result.warnings[0]


def test_validate_workflow_ir_accepts_human_input_phase() -> None:
    ir = _valid_ir(
        phases=[
            {"id": "start", "kind": "workflow_start", "title": "Start"},
            {
                "id": "review",
                "kind": "human_input",
                "title": "Review",
                "outputs": ["approval"],
            },
            {"id": "answer", "kind": "workflow_output", "title": "Answer", "inputs": ["approval"]},
        ],
        edges=[
            {"source": "start", "target": "review"},
            {"source": "review", "target": "answer", "condition": "approve"},
        ],
    )

    result = validate_workflow_ir(ir)

    assert result.is_valid is True
    assert result.errors == []
    assert result.missing_requirements == []


def test_validate_workflow_ir_requires_plugin_trigger_config() -> None:
    ir = _valid_ir(
        phases=[
            {
                "id": "plugin-trigger",
                "kind": "trigger",
                "title": "Plugin Trigger",
                "config": {"trigger_type": "plugin"},
            },
            {"id": "answer", "kind": "workflow_output", "title": "Answer"},
        ],
        edges=[{"source": "plugin-trigger", "target": "answer"}],
    )

    result = validate_workflow_ir(ir)

    assert result.is_valid is False
    assert result.errors == []
    assert result.missing_requirements == [
        "missing_phase_config:plugin-trigger:subscription_id",
        "missing_phase_config:plugin-trigger:provider_id",
        "missing_phase_config:plugin-trigger:provider_type",
        "missing_phase_config:plugin-trigger:event_name",
    ]


def test_validate_workflow_ir_requires_input_and_output() -> None:
    ir = _valid_ir(inputs=[], outputs=[])

    result = validate_workflow_ir(ir)

    assert result.is_valid is False
    assert "at least one input" in result.errors[0]
    assert "at least one output" in result.errors[1]
