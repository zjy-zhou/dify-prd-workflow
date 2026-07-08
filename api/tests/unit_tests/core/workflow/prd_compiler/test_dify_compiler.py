from __future__ import annotations

from copy import deepcopy

from core.workflow.prd_compiler.dify_compiler import compile_workflow_ir_to_dify_graph
from core.workflow.prd_compiler.entities import PrdWorkflowModelConfig, WorkflowIR
from core.workflow.prd_compiler.validator import validate_dify_graph
from models.model import AppMode


def _model_config() -> PrdWorkflowModelConfig:
    return PrdWorkflowModelConfig.model_validate(
        {
            "provider": "langgenius/tongyi/tongyi",
            "name": "qwen-plus",
            "mode": "chat",
            "completion_params": {"temperature": 0.2},
        }
    )


def _single_path_ir() -> WorkflowIR:
    return WorkflowIR.model_validate(
        {
            "id": "opportunity-discovery",
            "title": "Opportunity Discovery",
            "scenario": "Discover opportunities from PRD input.",
            "inputs": [{"name": "prd_context", "type": "object"}],
            "outputs": [{"name": "answer", "type": "string"}],
            "phases": [
                {"id": "start", "kind": "workflow_start", "title": "Start"},
                {
                    "id": "analyze",
                    "kind": "llm_task",
                    "title": "Analyze PRD",
                    "instruction": "Analyze the PRD and produce opportunities.",
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
                {"source": "start", "target": "analyze"},
                {"source": "analyze", "target": "answer"},
            ],
        }
    )


def _conditional_ir() -> WorkflowIR:
    return WorkflowIR.model_validate(
        {
            "id": "conditional-opportunity-discovery",
            "title": "Conditional Opportunity Discovery",
            "scenario": "Branch based on PRD completeness.",
            "inputs": [{"name": "prd_context", "type": "object"}],
            "outputs": [{"name": "answer", "type": "string"}],
            "phases": [
                {"id": "start", "kind": "workflow_start", "title": "Start"},
                {
                    "id": "check-prd",
                    "kind": "condition",
                    "title": "Check PRD",
                    "inputs": ["prd_context"],
                    "config": {
                        "conditions": [
                            {
                                "variable": "prd_context",
                                "operator": "not empty",
                                "value": "",
                            }
                        ]
                    },
                },
                {
                    "id": "analyze",
                    "kind": "llm_task",
                    "title": "Analyze PRD",
                    "inputs": ["prd_context"],
                    "outputs": ["analysis"],
                },
                {
                    "id": "missing-context",
                    "kind": "workflow_output",
                    "title": "Missing Context",
                    "inputs": ["prd_context"],
                },
                {
                    "id": "answer",
                    "kind": "workflow_output",
                    "title": "Answer",
                    "inputs": ["analysis"],
                },
            ],
            "edges": [
                {"source": "start", "target": "check-prd"},
                {"source": "check-prd", "target": "analyze", "condition": "true"},
                {"source": "check-prd", "target": "missing-context", "condition": "false"},
                {"source": "analyze", "target": "answer"},
            ],
        }
    )


def _human_input_ir() -> WorkflowIR:
    return WorkflowIR.model_validate(
        {
            "id": "human-review",
            "title": "Human Review",
            "scenario": "Ask a human to approve the compiled plan.",
            "inputs": [{"name": "draft_plan", "type": "string"}],
            "outputs": [{"name": "answer", "type": "string"}],
            "phases": [
                {"id": "start", "kind": "workflow_start", "title": "Start"},
                {
                    "id": "review",
                    "kind": "human_input",
                    "title": "Review Plan",
                    "goal": "Confirm whether the plan can be used.",
                    "inputs": ["draft_plan"],
                    "outputs": ["approval"],
                },
                {"id": "answer", "kind": "workflow_output", "title": "Answer", "inputs": ["approval"]},
            ],
            "edges": [
                {"source": "start", "target": "review"},
                {"source": "review", "target": "answer", "condition": "approve"},
            ],
        }
    )


def _http_code_ir() -> WorkflowIR:
    return WorkflowIR.model_validate(
        {
            "id": "http-code",
            "title": "HTTP And Code",
            "scenario": "Call an approved API and transform its response.",
            "inputs": [{"name": "query", "type": "string"}],
            "outputs": [{"name": "answer", "type": "string"}],
            "phases": [
                {"id": "start", "kind": "workflow_start", "title": "Start"},
                {
                    "id": "call-api",
                    "kind": "http_call",
                    "title": "Call API",
                    "inputs": ["query"],
                    "outputs": ["body"],
                    "config": {
                        "method": "post",
                        "url": "https://example.com/internal/search",
                    },
                },
                {
                    "id": "transform",
                    "kind": "code_transform",
                    "title": "Transform Response",
                    "inputs": ["body"],
                    "outputs": ["summary"],
                    "config": {
                        "code": "def main(body: str) -> dict:\n    return {\"summary\": body}",
                    },
                },
                {"id": "answer", "kind": "workflow_output", "title": "Answer", "inputs": ["summary"]},
            ],
            "edges": [
                {"source": "start", "target": "call-api"},
                {"source": "call-api", "target": "transform"},
                {"source": "transform", "target": "answer"},
            ],
        }
    )


def _knowledge_tool_ir() -> WorkflowIR:
    return WorkflowIR.model_validate(
        {
            "id": "knowledge-tool",
            "title": "Knowledge And Tool",
            "scenario": "Retrieve context and call an approved tool.",
            "inputs": [{"name": "query", "type": "string"}],
            "outputs": [{"name": "answer", "type": "string"}],
            "phases": [
                {"id": "start", "kind": "workflow_start", "title": "Start"},
                {
                    "id": "retrieve",
                    "kind": "knowledge_retrieval",
                    "title": "Retrieve Knowledge",
                    "inputs": ["query"],
                    "outputs": ["documents"],
                    "config": {
                        "dataset_ids": ["dataset-1"],
                    },
                },
                {
                    "id": "tool",
                    "kind": "tool_call",
                    "title": "Call Tool",
                    "inputs": ["documents"],
                    "outputs": ["text"],
                    "config": {
                        "provider_id": "provider-1",
                        "provider_type": "builtin",
                        "tool_name": "summarize",
                    },
                },
                {"id": "answer", "kind": "workflow_output", "title": "Answer", "inputs": ["text"]},
            ],
            "edges": [
                {"source": "start", "target": "retrieve"},
                {"source": "retrieve", "target": "tool"},
                {"source": "tool", "target": "answer"},
            ],
        }
    )


def _webhook_trigger_ir() -> WorkflowIR:
    return WorkflowIR.model_validate(
        {
            "id": "webhook-trigger",
            "title": "Webhook Trigger",
            "scenario": "Run when an approved webhook receives a payload.",
            "inputs": [{"name": "query", "type": "string"}],
            "outputs": [{"name": "answer", "type": "string"}],
            "phases": [
                {
                    "id": "webhook",
                    "kind": "trigger",
                    "title": "Webhook",
                    "outputs": ["query"],
                    "config": {
                        "trigger_type": "webhook",
                        "webhook_url": "https://example.com/webhook/run",
                    },
                },
                {
                    "id": "analyze",
                    "kind": "llm_task",
                    "title": "Analyze",
                    "inputs": ["query"],
                    "outputs": ["analysis"],
                },
                {"id": "answer", "kind": "workflow_output", "title": "Answer", "inputs": ["analysis"]},
            ],
            "edges": [
                {"source": "webhook", "target": "analyze"},
                {"source": "analyze", "target": "answer"},
            ],
        }
    )


def _schedule_trigger_ir() -> WorkflowIR:
    return WorkflowIR.model_validate(
        {
            "id": "schedule-trigger",
            "title": "Schedule Trigger",
            "scenario": "Run every morning.",
            "inputs": [{"name": "schedule_tick", "type": "string"}],
            "outputs": [{"name": "answer", "type": "string"}],
            "phases": [
                {
                    "id": "schedule",
                    "kind": "trigger",
                    "title": "Schedule",
                    "config": {
                        "trigger_type": "schedule",
                        "mode": "cron",
                        "cron_expression": "0 9 * * *",
                    },
                },
                {
                    "id": "analyze",
                    "kind": "llm_task",
                    "title": "Analyze",
                    "inputs": ["sys.time"],
                    "outputs": ["analysis"],
                },
                {"id": "answer", "kind": "workflow_output", "title": "Answer", "inputs": ["analysis"]},
            ],
            "edges": [
                {"source": "schedule", "target": "analyze"},
                {"source": "analyze", "target": "answer"},
            ],
        }
    )


def _plugin_trigger_ir() -> WorkflowIR:
    return WorkflowIR.model_validate(
        {
            "id": "plugin-trigger",
            "title": "Plugin Trigger",
            "scenario": "Run when an approved plugin event arrives.",
            "inputs": [{"name": "event", "type": "object"}],
            "outputs": [{"name": "answer", "type": "string"}],
            "phases": [
                {
                    "id": "plugin",
                    "kind": "trigger",
                    "title": "Plugin",
                    "outputs": ["event"],
                    "config": {
                        "trigger_type": "plugin",
                        "subscription_id": "subscription-1",
                        "provider_id": "provider-1",
                        "provider_type": "builtin",
                        "event_name": "created",
                    },
                },
                {
                    "id": "analyze",
                    "kind": "llm_task",
                    "title": "Analyze",
                    "inputs": ["event"],
                    "outputs": ["analysis"],
                },
                {"id": "answer", "kind": "workflow_output", "title": "Answer", "inputs": ["analysis"]},
            ],
            "edges": [
                {"source": "plugin", "target": "analyze"},
                {"source": "analyze", "target": "answer"},
            ],
        }
    )


def test_compile_single_path_ir_to_workflow_graph() -> None:
    graph = compile_workflow_ir_to_dify_graph(
        ir=_single_path_ir(),
        app_mode=AppMode.WORKFLOW,
        model_config=_model_config(),
    )

    node_types = [node["data"]["type"] for node in graph["nodes"]]
    assert node_types == ["start", "llm", "end"]
    assert graph["edges"][0]["source"] == "start"
    assert graph["edges"][1]["target"] == "answer"
    assert validate_dify_graph(graph).is_valid is True


def test_compile_conditional_ir_to_advanced_chat_graph() -> None:
    graph = compile_workflow_ir_to_dify_graph(
        ir=_conditional_ir(),
        app_mode=AppMode.ADVANCED_CHAT,
        model_config=_model_config(),
    )

    node_types = [node["data"]["type"] for node in graph["nodes"]]
    source_handles = {edge["sourceHandle"] for edge in graph["edges"] if edge["source"] == "check-prd"}
    assert "if-else" in node_types
    assert "answer" in node_types
    assert source_handles == {"true", "false"}
    assert validate_dify_graph(graph).is_valid is True


def test_validate_dify_graph_rejects_missing_terminal_node() -> None:
    graph = compile_workflow_ir_to_dify_graph(
        ir=_single_path_ir(),
        app_mode=AppMode.WORKFLOW,
        model_config=_model_config(),
    )
    graph["nodes"] = [node for node in graph["nodes"] if node["data"]["type"] != "end"]

    result = validate_dify_graph(graph)

    assert result.is_valid is False
    assert any("at least one Answer or End" in error for error in result.errors)


def test_validate_dify_graph_rejects_edge_to_missing_node() -> None:
    graph = compile_workflow_ir_to_dify_graph(
        ir=_single_path_ir(),
        app_mode=AppMode.WORKFLOW,
        model_config=_model_config(),
    )
    broken_graph = deepcopy(graph)
    broken_graph["edges"][0]["target"] = "missing"

    result = validate_dify_graph(broken_graph)

    assert result.is_valid is False
    assert any("target 'missing'" in error for error in result.errors)


def test_compile_human_input_ir_to_valid_workflow_graph() -> None:
    graph = compile_workflow_ir_to_dify_graph(
        ir=_human_input_ir(),
        app_mode=AppMode.WORKFLOW,
        model_config=_model_config(),
    )

    node_types = [node["data"]["type"] for node in graph["nodes"]]
    review_edges = [edge for edge in graph["edges"] if edge["source"] == "review"]
    assert "human-input" in node_types
    assert review_edges[0]["sourceHandle"] == "approve"
    assert validate_dify_graph(graph).is_valid is True


def test_compile_http_and_code_ir_to_valid_workflow_graph() -> None:
    graph = compile_workflow_ir_to_dify_graph(
        ir=_http_code_ir(),
        app_mode=AppMode.WORKFLOW,
        model_config=_model_config(),
    )

    node_types = [node["data"]["type"] for node in graph["nodes"]]
    assert "http-request" in node_types
    assert "code" in node_types
    assert validate_dify_graph(graph).is_valid is True


def test_compile_knowledge_and_tool_ir_to_valid_workflow_graph() -> None:
    graph = compile_workflow_ir_to_dify_graph(
        ir=_knowledge_tool_ir(),
        app_mode=AppMode.WORKFLOW,
        model_config=_model_config(),
    )

    node_types = [node["data"]["type"] for node in graph["nodes"]]
    assert "knowledge-retrieval" in node_types
    assert "tool" in node_types
    assert validate_dify_graph(graph).is_valid is True


def test_compile_webhook_trigger_ir_to_valid_workflow_graph() -> None:
    graph = compile_workflow_ir_to_dify_graph(
        ir=_webhook_trigger_ir(),
        app_mode=AppMode.WORKFLOW,
        model_config=_model_config(),
    )

    first_node = graph["nodes"][0]
    assert first_node["data"]["type"] == "trigger-webhook"
    assert {variable["variable"] for variable in first_node["data"]["variables"]} == {"_webhook_raw", "query"}
    assert validate_dify_graph(graph).is_valid is True


def test_compile_schedule_trigger_ir_to_valid_workflow_graph() -> None:
    graph = compile_workflow_ir_to_dify_graph(
        ir=_schedule_trigger_ir(),
        app_mode=AppMode.WORKFLOW,
        model_config=_model_config(),
    )

    first_node = graph["nodes"][0]
    llm_node = graph["nodes"][1]
    assert first_node["data"]["type"] == "trigger-schedule"
    assert llm_node["data"]["variables"][0]["value_selector"] == ["sys", "time"]
    assert validate_dify_graph(graph).is_valid is True


def test_compile_plugin_trigger_ir_to_valid_workflow_graph() -> None:
    graph = compile_workflow_ir_to_dify_graph(
        ir=_plugin_trigger_ir(),
        app_mode=AppMode.WORKFLOW,
        model_config=_model_config(),
    )

    first_node = graph["nodes"][0]
    assert first_node["data"]["type"] == "trigger-plugin"
    assert first_node["data"]["subscription_id"] == "subscription-1"
    assert validate_dify_graph(graph).is_valid is True
