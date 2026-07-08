from __future__ import annotations

from copy import deepcopy

from core.workflow.prd_compiler.graph_patch import WorkflowGraphPatch, apply_graph_patch
from core.workflow.prd_compiler.validator import validate_dify_graph


def _graph() -> dict:
    return {
        "nodes": [
            {
                "id": "start",
                "data": {
                    "type": "start",
                    "title": "Start",
                    "variables": [{"variable": "query", "type": "paragraph"}],
                },
            },
            {
                "id": "llm",
                "data": {
                    "type": "llm",
                    "title": "Analyze",
                    "desc": "Analyze input.",
                    "model": {"provider": "provider", "name": "qwen-plus", "mode": "chat"},
                    "prompt_template": [{"role": "user", "text": "Analyze {{#start.query#}}"}],
                    "variables": [{"variable": "query", "value_selector": ["start", "query"]}],
                },
            },
            {
                "id": "answer",
                "data": {
                    "type": "answer",
                    "title": "Answer",
                    "answer": "{{#llm.text#}}",
                },
            },
        ],
        "edges": [
            {"id": "start-source-llm-target", "source": "start", "target": "llm", "sourceHandle": "source"},
            {"id": "llm-source-answer-target", "source": "llm", "target": "answer", "sourceHandle": "source"},
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 0.7},
    }


def test_apply_graph_patch_updates_node_data_without_mutating_source_graph() -> None:
    graph = _graph()
    patch = WorkflowGraphPatch.model_validate(
        {
            "summary": "Rename the LLM node.",
            "operations": [
                {
                    "op": "update_node",
                    "node_id": "llm",
                    "updates": {"data": {"title": "Review PRD", "desc": "Review the PRD."}},
                }
            ],
        }
    )

    preview = apply_graph_patch(graph, patch)

    assert preview["nodes"][1]["data"]["title"] == "Review PRD"
    assert preview["nodes"][1]["data"]["desc"] == "Review the PRD."
    assert graph["nodes"][1]["data"]["title"] == "Analyze"
    assert validate_dify_graph(preview).is_valid is True


def test_apply_graph_patch_removes_connected_edges_and_validator_catches_missing_terminal() -> None:
    patch = WorkflowGraphPatch.model_validate(
        {
            "summary": "Remove answer.",
            "operations": [{"op": "remove_node", "node_id": "answer"}],
        }
    )

    preview = apply_graph_patch(_graph(), patch)
    result = validate_dify_graph(preview)

    assert preview["edges"] == [{"id": "start-source-llm-target", "source": "start", "target": "llm", "sourceHandle": "source"}]
    assert result.is_valid is False
    assert any("at least one Answer or End" in error for error in result.errors)


def test_apply_graph_patch_adds_node_and_edge() -> None:
    graph = _graph()
    graph["edges"] = [graph["edges"][0]]
    patch = WorkflowGraphPatch.model_validate(
        {
            "summary": "Add answer path.",
            "operations": [
                {
                    "op": "add_node",
                    "node": deepcopy(_graph()["nodes"][2]),
                },
                {
                    "op": "add_edge",
                    "edge": {
                        "id": "llm-source-answer-target",
                        "source": "llm",
                        "target": "answer",
                        "sourceHandle": "source",
                    },
                },
            ],
        }
    )
    graph["nodes"] = graph["nodes"][:2]

    preview = apply_graph_patch(graph, patch)

    assert [node["id"] for node in preview["nodes"]] == ["start", "llm", "answer"]
    assert preview["edges"][1]["target"] == "answer"
    assert validate_dify_graph(preview).is_valid is True
