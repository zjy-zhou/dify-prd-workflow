"""Compile platform-neutral Workflow IR into Dify workflow graph JSON.

This module is the Dify adapter boundary for the PRD compiler. It deliberately
returns plain graph dictionaries because Dify stores and syncs workflow graphs
as ReactFlow-shaped JSON. Keep this file free of Flask, database, and service
dependencies so it can later move into a standalone compiler package.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any

from core.workflow.prd_compiler.entities import (
    PrdWorkflowModelConfig,
    WorkflowIR,
    WorkflowIREdge,
    WorkflowIRPhase,
    WorkflowIRPhaseKind,
    WorkflowIRVariable,
)
from models.model import AppMode

NODE_WIDTH = 244
NODE_HEIGHT = 100
START_X = 80
START_Y = 280
NODE_X_GAP = 320
BRANCH_Y_GAP = 140
START_PHASE_KINDS = frozenset({WorkflowIRPhaseKind.WORKFLOW_START.value, WorkflowIRPhaseKind.TRIGGER.value})
DEFAULT_HTTP_TIMEOUT = {
    "max_connect_timeout": 0,
    "max_read_timeout": 0,
    "max_write_timeout": 0,
}


class DifyGraphCompileError(ValueError):
    """Raised when valid-looking IR cannot be mapped to MVP Dify graph nodes."""


def compile_workflow_ir_to_dify_graph(
    *,
    ir: WorkflowIR,
    app_mode: AppMode,
    model_config: PrdWorkflowModelConfig,
) -> dict[str, Any]:
    """Compile Workflow IR into Dify graph JSON accepted by draft sync.

    The terminal type is inferred from the target app mode: advanced-chat uses
    Answer, workflow uses End.
    """
    phase_by_id = {phase.id: phase for phase in ir.phases}
    start_phases = [phase for phase in ir.phases if phase.kind in START_PHASE_KINDS]
    if len(start_phases) != 1:
        raise DifyGraphCompileError("Workflow IR must contain exactly one workflow_start or trigger phase.")

    node_id_by_phase_id = _build_node_id_mapping(ir.phases)
    selector_resolver = _SelectorResolver(
        ir=ir,
        node_id_by_phase_id=node_id_by_phase_id,
        start_phase_id=start_phases[0].id,
    )
    positions = _calculate_positions(ir=ir, node_id_by_phase_id=node_id_by_phase_id)

    nodes = [
        _compile_node(
            ir=ir,
            phase=phase,
            node_id=node_id_by_phase_id[phase.id],
            position=positions[node_id_by_phase_id[phase.id]],
            app_mode=app_mode,
            model_config=model_config,
            selector_resolver=selector_resolver,
        )
        for phase in ir.phases
    ]
    edges = _compile_edges(
        ir=ir,
        node_id_by_phase_id=node_id_by_phase_id,
        phase_by_id=phase_by_id,
        app_mode=app_mode,
    )

    return {
        "nodes": nodes,
        "edges": edges,
        "viewport": {
            "x": 0,
            "y": 0,
            "zoom": 0.7,
        },
    }


def _build_node_id_mapping(phases: list[WorkflowIRPhase]) -> dict[str, str]:
    seen: set[str] = set()
    mapping: dict[str, str] = {}
    for phase in phases:
        base = _slugify_id(phase.id)
        node_id = base
        index = 2
        while node_id in seen:
            node_id = f"{base}-{index}"
            index += 1
        seen.add(node_id)
        mapping[phase.id] = node_id
    return mapping


def _slugify_id(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip())
    value = re.sub(r"-+", "-", value).strip("-_")
    return value or "node"


def _calculate_positions(
    *,
    ir: WorkflowIR,
    node_id_by_phase_id: dict[str, str],
) -> dict[str, dict[str, int]]:
    levels = _calculate_phase_levels(ir)
    positions: dict[str, dict[str, int]] = {}
    level_counts: dict[int, int] = defaultdict(int)

    condition_outgoing: dict[str, list[WorkflowIREdge]] = defaultdict(list)
    for edge in ir.edges:
        condition_outgoing[edge.source].append(edge)

    for phase in ir.phases:
        level = levels.get(phase.id, 0)
        row = level_counts[level]
        level_counts[level] += 1
        y = START_Y + row * BRANCH_Y_GAP

        incoming = [edge for edge in ir.edges if edge.target == phase.id]
        if incoming:
            parent_edge = incoming[0]
            parent_phase = next((candidate for candidate in ir.phases if candidate.id == parent_edge.source), None)
            if parent_phase and parent_phase.kind == WorkflowIRPhaseKind.CONDITION.value:
                handle = _condition_edge_handle(
                    edge=parent_edge,
                    sibling_edges=condition_outgoing[parent_phase.id],
                )
                y = START_Y - BRANCH_Y_GAP if handle == "true" else START_Y + BRANCH_Y_GAP

        positions[node_id_by_phase_id[phase.id]] = {
            "x": START_X + level * NODE_X_GAP,
            "y": y,
        }

    return positions


def _calculate_phase_levels(ir: WorkflowIR) -> dict[str, int]:
    phase_ids = {phase.id for phase in ir.phases}
    incoming_count = {phase_id: 0 for phase_id in phase_ids}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in ir.edges:
        outgoing[edge.source].append(edge.target)
        incoming_count[edge.target] = incoming_count.get(edge.target, 0) + 1

    queue = deque([phase.id for phase in ir.phases if incoming_count.get(phase.id, 0) == 0])
    levels = {phase_id: 0 for phase_id in queue}
    while queue:
        phase_id = queue.popleft()
        for target in outgoing.get(phase_id, []):
            levels[target] = max(levels.get(target, 0), levels.get(phase_id, 0) + 1)
            incoming_count[target] -= 1
            if incoming_count[target] == 0:
                queue.append(target)

    return levels


def _compile_node(
    *,
    ir: WorkflowIR,
    phase: WorkflowIRPhase,
    node_id: str,
    position: dict[str, int],
    app_mode: AppMode,
    model_config: PrdWorkflowModelConfig,
    selector_resolver: _SelectorResolver,
) -> dict[str, Any]:
    data = _compile_node_data(
        ir=ir,
        phase=phase,
        node_id=node_id,
        app_mode=app_mode,
        model_config=model_config,
        selector_resolver=selector_resolver,
    )
    return {
        "id": node_id,
        "type": "custom",
        "position": position,
        "positionAbsolute": dict(position),
        "width": NODE_WIDTH,
        "height": NODE_HEIGHT,
        "sourcePosition": "right",
        "targetPosition": "left",
        "data": data,
    }


def _compile_node_data(
    *,
    ir: WorkflowIR,
    phase: WorkflowIRPhase,
    node_id: str,
    app_mode: AppMode,
    model_config: PrdWorkflowModelConfig,
    selector_resolver: _SelectorResolver,
) -> dict[str, Any]:
    match phase.kind:
        case WorkflowIRPhaseKind.WORKFLOW_START.value:
            return _compile_start_data(ir.inputs, phase)
        case WorkflowIRPhaseKind.LLM_TASK.value:
            return _compile_llm_data(
                ir=ir,
                phase=phase,
                model_config=model_config,
                selector_resolver=selector_resolver,
            )
        case WorkflowIRPhaseKind.CONDITION.value:
            return _compile_if_else_data(phase=phase, selector_resolver=selector_resolver)
        case WorkflowIRPhaseKind.WORKFLOW_OUTPUT.value:
            return _compile_terminal_data(
                ir=ir,
                phase=phase,
                node_id=node_id,
                app_mode=app_mode,
                selector_resolver=selector_resolver,
            )
        case WorkflowIRPhaseKind.KNOWLEDGE_RETRIEVAL.value:
            return _compile_knowledge_retrieval_data(phase=phase, selector_resolver=selector_resolver)
        case WorkflowIRPhaseKind.HTTP_CALL.value:
            return _compile_http_request_data(phase=phase, selector_resolver=selector_resolver)
        case WorkflowIRPhaseKind.CODE_TRANSFORM.value:
            return _compile_code_data(phase=phase, selector_resolver=selector_resolver)
        case WorkflowIRPhaseKind.TOOL_CALL.value:
            return _compile_tool_data(phase=phase, selector_resolver=selector_resolver)
        case WorkflowIRPhaseKind.HUMAN_INPUT.value:
            return _compile_human_input_data(phase=phase, selector_resolver=selector_resolver)
        case WorkflowIRPhaseKind.TRIGGER.value:
            return _compile_trigger_data(ir=ir, phase=phase)
        case _:
            raise DifyGraphCompileError(f"Unsupported Workflow IR phase kind: {phase.kind}")


def _compile_start_data(inputs: list[WorkflowIRVariable], phase: WorkflowIRPhase) -> dict[str, Any]:
    return {
        "type": "start",
        "title": phase.title or "Start",
        "desc": phase.goal,
        "selected": False,
        "variables": [_compile_start_variable(variable) for variable in inputs],
    }


def _compile_start_variable(variable: WorkflowIRVariable) -> dict[str, Any]:
    variable_type = _to_dify_start_variable_type(variable.type)
    return {
        "variable": variable.name,
        "label": variable.description or variable.name,
        "type": variable_type,
        "required": variable.required,
        "max_length": 4096 if variable_type == "paragraph" else 256,
        "options": [],
    }


def _to_dify_start_variable_type(variable_type: str) -> str:
    match variable_type:
        case "number" | "integer":
            return "number"
        case "boolean" | "bool":
            return "checkbox"
        case "string":
            return "paragraph"
        case _:
            return "paragraph"


def _compile_llm_data(
    *,
    ir: WorkflowIR,
    phase: WorkflowIRPhase,
    model_config: PrdWorkflowModelConfig,
    selector_resolver: _SelectorResolver,
) -> dict[str, Any]:
    selectors = selector_resolver.resolve_inputs(phase.inputs or [variable.name for variable in ir.inputs])
    return {
        "type": "llm",
        "title": phase.title,
        "desc": phase.goal,
        "selected": False,
        "model": {
            "provider": model_config.provider,
            "name": model_config.name,
            "mode": str(model_config.mode),
            "completion_params": dict(model_config.completion_params or {}),
        },
        "prompt_template": [
            {
                "role": "system",
                "text": "You are a careful workflow step executor. Follow the task instructions exactly.",
            },
            {
                "role": "user",
                "text": _build_llm_user_prompt(phase=phase, selectors=selectors),
            },
        ],
        "variables": [
            {
                "variable": variable_name,
                "value_selector": selector,
            }
            for variable_name, selector in selectors.items()
        ],
        "context": {
            "enabled": False,
            "variable_selector": [],
        },
        "vision": {
            "enabled": False,
        },
    }


def _build_llm_user_prompt(*, phase: WorkflowIRPhase, selectors: dict[str, list[str]]) -> str:
    context_lines = [f"- {name}: {{{{#{'.'.join(selector)}#}}}}" for name, selector in selectors.items()]
    context = "\n".join(context_lines) if context_lines else "- No explicit upstream inputs."
    task = phase.instruction or phase.goal or phase.title
    return f"Workflow context:\n{context}\n\nTask:\n{task}\n\nReturn the result as clear text."


def _compile_if_else_data(
    *,
    phase: WorkflowIRPhase,
    selector_resolver: _SelectorResolver,
) -> dict[str, Any]:
    condition_payloads = phase.config.get("conditions")
    if isinstance(condition_payloads, list) and condition_payloads:
        conditions = [
            _compile_condition_payload(
                payload=payload,
                phase=phase,
                index=index,
                selector_resolver=selector_resolver,
            )
            for index, payload in enumerate(condition_payloads, start=1)
            if isinstance(payload, dict)
        ]
    else:
        conditions = [_compile_default_condition(phase=phase, selector_resolver=selector_resolver)]

    return {
        "type": "if-else",
        "title": phase.title or "IF/ELSE",
        "desc": phase.goal,
        "selected": False,
        "cases": [
            {
                "case_id": "true",
                "logical_operator": "and",
                "conditions": conditions,
            }
        ],
    }


def _compile_condition_payload(
    *,
    payload: dict[str, Any],
    phase: WorkflowIRPhase,
    index: int,
    selector_resolver: _SelectorResolver,
) -> dict[str, Any]:
    variable_name = str(payload.get("variable") or payload.get("input") or _first_or_default(phase.inputs, "query"))
    operator = str(payload.get("comparison_operator") or payload.get("operator") or "not empty")
    value = payload.get("value", "")
    return {
        "id": str(payload.get("id") or f"{phase.id}-condition-{index}"),
        "varType": _to_dify_var_type(str(payload.get("type") or "string")),
        "variable_selector": selector_resolver.resolve_variable(variable_name),
        "comparison_operator": operator,
        "value": value,
    }


def _compile_default_condition(
    *,
    phase: WorkflowIRPhase,
    selector_resolver: _SelectorResolver,
) -> dict[str, Any]:
    variable_name = _first_or_default(phase.inputs, "query")
    return {
        "id": f"{phase.id}-condition-1",
        "varType": "string",
        "variable_selector": selector_resolver.resolve_variable(variable_name),
        "comparison_operator": "not empty",
        "value": "",
    }


def _to_dify_var_type(variable_type: str) -> str:
    match variable_type:
        case "number" | "integer":
            return "number"
        case "boolean" | "bool":
            return "boolean"
        case "array":
            return "array[string]"
        case _:
            return "string"


def _compile_terminal_data(
    *,
    ir: WorkflowIR,
    phase: WorkflowIRPhase,
    node_id: str,
    app_mode: AppMode,
    selector_resolver: _SelectorResolver,
) -> dict[str, Any]:
    selectors = selector_resolver.resolve_inputs(phase.inputs or [output.name for output in ir.outputs])
    output_selector = next(iter(selectors.values()), selector_resolver.fallback_selector())
    if app_mode == AppMode.ADVANCED_CHAT:
        return {
            "type": "answer",
            "title": phase.title or "Answer",
            "desc": phase.goal,
            "selected": False,
            "variables": [],
            "answer": f"{{{{#{'.'.join(output_selector)}#}}}}",
        }

    output_name = ir.outputs[0].name if ir.outputs else "answer"
    return {
        "type": "end",
        "title": phase.title or "End",
        "desc": phase.goal,
        "selected": False,
        "outputs": [
            {
                "variable": output_name,
                "value_selector": output_selector,
            }
        ],
    }


def _compile_knowledge_retrieval_data(
    *,
    phase: WorkflowIRPhase,
    selector_resolver: _SelectorResolver,
) -> dict[str, Any]:
    query_variable = str(phase.config.get("query_variable") or _first_or_default(phase.inputs, "query"))
    dataset_ids = [
        str(dataset_id)
        for dataset_id in phase.config.get("dataset_ids", [])
        if str(dataset_id).strip()
    ]
    return {
        "type": "knowledge-retrieval",
        "title": phase.title,
        "desc": phase.goal,
        "selected": False,
        "query_variable_selector": selector_resolver.resolve_variable(query_variable),
        "query_attachment_selector": [],
        "dataset_ids": dataset_ids,
        "retrieval_mode": str(phase.config.get("retrieval_mode") or "multiple"),
        "multiple_retrieval_config": phase.config.get(
            "multiple_retrieval_config",
            {
                "top_k": 4,
                "score_threshold": None,
                "reranking_enable": False,
            },
        ),
    }


def _compile_http_request_data(
    *,
    phase: WorkflowIRPhase,
    selector_resolver: _SelectorResolver,
) -> dict[str, Any]:
    selectors = selector_resolver.resolve_inputs(phase.inputs)
    body = phase.config.get("body")
    if not isinstance(body, dict):
        body = {"type": "none", "data": []}

    authorization = phase.config.get("authorization")
    if not isinstance(authorization, dict):
        authorization = {"type": "no-auth", "config": None}

    return {
        "type": "http-request",
        "title": phase.title,
        "desc": phase.goal,
        "selected": False,
        "variables": [
            {
                "variable": variable_name,
                "value_selector": selector,
            }
            for variable_name, selector in selectors.items()
        ],
        "method": str(phase.config.get("method") or "get").lower(),
        "url": str(phase.config.get("url") or ""),
        "authorization": authorization,
        "headers": str(phase.config.get("headers") or ""),
        "params": str(phase.config.get("params") or ""),
        "body": body,
        "ssl_verify": bool(phase.config.get("ssl_verify", True)),
        "timeout": phase.config.get("timeout") if isinstance(phase.config.get("timeout"), dict) else DEFAULT_HTTP_TIMEOUT,
        "retry_config": phase.config.get(
            "retry_config",
            {
                "retry_enabled": True,
                "max_retries": 3,
                "retry_interval": 100,
            },
        ),
    }


def _compile_code_data(
    *,
    phase: WorkflowIRPhase,
    selector_resolver: _SelectorResolver,
) -> dict[str, Any]:
    selectors = selector_resolver.resolve_inputs(phase.inputs)
    output_names = phase.outputs or ["result"]
    return {
        "type": "code",
        "title": phase.title,
        "desc": phase.goal,
        "selected": False,
        "variables": [
            {
                "variable": variable_name,
                "value_selector": selector,
            }
            for variable_name, selector in selectors.items()
        ],
        "code_language": str(phase.config.get("code_language") or "python3"),
        "code": str(phase.config.get("code") or ""),
        "outputs": {
            output_name: {
                "type": str(phase.config.get("output_type") or "string"),
                "children": None,
            }
            for output_name in output_names
        },
    }


def _compile_tool_data(
    *,
    phase: WorkflowIRPhase,
    selector_resolver: _SelectorResolver,
) -> dict[str, Any]:
    selectors = selector_resolver.resolve_inputs(phase.inputs)
    tool_parameters = phase.config.get("tool_parameters")
    if not isinstance(tool_parameters, dict):
        tool_parameters = {
            variable_name: {
                "type": "variable",
                "value": selector,
            }
            for variable_name, selector in selectors.items()
        }

    return {
        "type": "tool",
        "title": phase.title,
        "desc": phase.goal,
        "selected": False,
        "provider_id": str(phase.config.get("provider_id") or ""),
        "provider_type": str(phase.config.get("provider_type") or ""),
        "provider_name": str(phase.config.get("provider_name") or phase.config.get("provider_id") or ""),
        "tool_name": str(phase.config.get("tool_name") or ""),
        "tool_label": str(phase.config.get("tool_label") or phase.config.get("tool_name") or phase.title),
        "tool_parameters": tool_parameters,
        "tool_configurations": phase.config.get("tool_configurations")
        if isinstance(phase.config.get("tool_configurations"), dict)
        else {},
        "tool_node_version": "2",
    }


def _compile_human_input_data(
    *,
    phase: WorkflowIRPhase,
    selector_resolver: _SelectorResolver,
) -> dict[str, Any]:
    form_content = str(
        phase.config.get("form_content")
        or (phase.confirmation.prompt if phase.confirmation else "")
        or phase.instruction
        or phase.goal
        or "Please review and choose an action."
    )
    delivery_methods = phase.config.get("delivery_methods")
    if not isinstance(delivery_methods, list) or not delivery_methods:
        delivery_methods = [{"id": "webapp", "type": "webapp", "enabled": True}]

    user_actions = phase.config.get("user_actions")
    if not isinstance(user_actions, list) or not user_actions:
        user_actions = [
            {"id": "approve", "title": "Approve", "button_style": "primary"},
            {"id": "reject", "title": "Reject", "button_style": "default"},
        ]

    input_names = phase.config.get("form_inputs")
    if isinstance(input_names, list):
        output_names = [str(name) for name in input_names if str(name).strip()]
    else:
        output_names = [name for name in phase.outputs if name not in {"__action_id", "__action_value"}]

    return {
        "type": "human-input",
        "title": phase.title,
        "desc": phase.goal,
        "selected": False,
        "delivery_methods": delivery_methods,
        "form_content": form_content,
        "inputs": [
            {
                "type": "paragraph",
                "output_variable_name": output_name,
                "default": {
                    "type": "constant",
                    "selector": [],
                    "value": "",
                },
            }
            for output_name in output_names
        ],
        "user_actions": user_actions,
        "timeout": int(phase.config.get("timeout") or 3),
        "timeout_unit": str(phase.config.get("timeout_unit") or "day"),
    }


def _compile_trigger_data(*, ir: WorkflowIR, phase: WorkflowIRPhase) -> dict[str, Any]:
    trigger_type = str(phase.config.get("trigger_type") or "webhook")
    if trigger_type == "schedule":
        return _compile_schedule_trigger_data(phase)
    if trigger_type == "plugin":
        return _compile_plugin_trigger_data(phase)
    return _compile_webhook_trigger_data(ir=ir, phase=phase)


def _compile_webhook_trigger_data(*, ir: WorkflowIR, phase: WorkflowIRPhase) -> dict[str, Any]:
    variables = phase.config.get("variables")
    if not isinstance(variables, list) or not variables:
        variables_by_name: dict[str, dict[str, Any]] = {
            "_webhook_raw": {
                "variable": "_webhook_raw",
                "label": "raw",
                "value_type": "object",
                "value_selector": [],
                "required": True,
            }
        }
        for variable in ir.inputs:
            variables_by_name.setdefault(variable.name, _compile_trigger_variable(variable))
        for output_name in phase.outputs:
            variables_by_name.setdefault(output_name, _compile_named_trigger_variable(output_name))
        variables = list(variables_by_name.values())
    return {
        "type": "trigger-webhook",
        "title": phase.title or "Webhook Trigger",
        "desc": phase.goal,
        "selected": False,
        "webhook_url": str(phase.config.get("webhook_url") or ""),
        "method": str(phase.config.get("method") or "POST").upper(),
        "content_type": str(phase.config.get("content_type") or "application/json"),
        "headers": phase.config.get("headers") if isinstance(phase.config.get("headers"), list) else [],
        "params": phase.config.get("params") if isinstance(phase.config.get("params"), list) else [],
        "body": phase.config.get("body") if isinstance(phase.config.get("body"), list) else [],
        "async_mode": bool(phase.config.get("async_mode", True)),
        "status_code": int(phase.config.get("status_code") or 200),
        "response_body": str(phase.config.get("response_body") or ""),
        "variables": variables,
    }


def _compile_trigger_variable(variable: WorkflowIRVariable) -> dict[str, Any]:
    return {
        "variable": variable.name,
        "label": variable.description or variable.name,
        "value_type": _to_dify_var_type(variable.type),
        "value_selector": [],
        "required": variable.required,
    }


def _compile_named_trigger_variable(variable_name: str) -> dict[str, Any]:
    return {
        "variable": variable_name,
        "label": variable_name,
        "value_type": "string",
        "value_selector": [],
        "required": False,
    }


def _compile_schedule_trigger_data(phase: WorkflowIRPhase) -> dict[str, Any]:
    return {
        "type": "trigger-schedule",
        "title": phase.title or "Schedule Trigger",
        "desc": phase.goal,
        "selected": False,
        "mode": str(phase.config.get("mode") or "cron"),
        "frequency": phase.config.get("frequency"),
        "cron_expression": str(phase.config.get("cron_expression") or "0 9 * * *"),
        "visual_config": phase.config.get("visual_config") if isinstance(phase.config.get("visual_config"), dict) else None,
        "timezone": str(phase.config.get("timezone") or "UTC"),
    }


def _compile_plugin_trigger_data(phase: WorkflowIRPhase) -> dict[str, Any]:
    output_schema = phase.config.get("output_schema")
    if not isinstance(output_schema, dict) or not output_schema:
        output_schema = {
            "type": "object",
            "properties": {
                output_name: {"type": "string"}
                for output_name in phase.outputs
            },
        }
    return {
        "type": "trigger-plugin",
        "title": phase.title or "Plugin Trigger",
        "desc": phase.goal,
        "selected": False,
        "subscription_id": str(phase.config.get("subscription_id") or ""),
        "provider_id": str(phase.config.get("provider_id") or ""),
        "provider_type": str(phase.config.get("provider_type") or ""),
        "provider_name": str(phase.config.get("provider_name") or phase.config.get("provider_id") or ""),
        "event_name": str(phase.config.get("event_name") or ""),
        "event_label": str(phase.config.get("event_label") or phase.config.get("event_name") or phase.title),
        "event_parameters": phase.config.get("event_parameters")
        if isinstance(phase.config.get("event_parameters"), dict)
        else {},
        "event_configurations": phase.config.get("event_configurations")
        if isinstance(phase.config.get("event_configurations"), dict)
        else {},
        "output_schema": output_schema,
        "plugin_id": str(phase.config.get("plugin_id") or ""),
        "plugin_unique_identifier": str(phase.config.get("plugin_unique_identifier") or ""),
        "event_node_version": str(phase.config.get("event_node_version") or "1"),
        "config": phase.config.get("config") if isinstance(phase.config.get("config"), dict) else {},
    }


def _compile_edges(
    *,
    ir: WorkflowIR,
    node_id_by_phase_id: dict[str, str],
    phase_by_id: dict[str, WorkflowIRPhase],
    app_mode: AppMode,
) -> list[dict[str, Any]]:
    outgoing_by_phase_id: dict[str, list[WorkflowIREdge]] = defaultdict(list)
    for edge in ir.edges:
        outgoing_by_phase_id[edge.source].append(edge)

    edges: list[dict[str, Any]] = []
    for edge in ir.edges:
        source_id = node_id_by_phase_id[edge.source]
        target_id = node_id_by_phase_id[edge.target]
        source_phase = phase_by_id[edge.source]
        target_phase = phase_by_id[edge.target]
        source_handle = _edge_source_handle(
            edge=edge,
            source_phase=source_phase,
            sibling_edges=outgoing_by_phase_id[edge.source],
        )
        edges.append(
            {
                "id": f"{source_id}-{source_handle}-{target_id}-target",
                "source": source_id,
                "target": target_id,
                "type": "custom",
                "sourceHandle": source_handle,
                "targetHandle": "target",
                "data": {
                    "sourceType": _node_type_for_phase(source_phase, app_mode=app_mode),
                    "targetType": _node_type_for_phase(target_phase, app_mode=app_mode),
                    "isInIteration": False,
                    "isInLoop": False,
                },
            }
        )

    return edges


def _condition_edge_handle(*, edge: WorkflowIREdge, sibling_edges: list[WorkflowIREdge]) -> str:
    condition = (edge.condition or "").strip().lower()
    if condition in {"false", "else", "otherwise", "default", "no"}:
        return "false"
    if condition in {"true", "if", "yes"}:
        return "true"

    try:
        index = sibling_edges.index(edge)
    except ValueError:
        index = 0
    return "true" if index == 0 else "false"


def _edge_source_handle(
    *,
    edge: WorkflowIREdge,
    source_phase: WorkflowIRPhase,
    sibling_edges: list[WorkflowIREdge],
) -> str:
    if source_phase.kind == WorkflowIRPhaseKind.CONDITION.value:
        return _condition_edge_handle(edge=edge, sibling_edges=sibling_edges)
    if source_phase.kind == WorkflowIRPhaseKind.HUMAN_INPUT.value:
        return _human_input_edge_handle(edge=edge, source_phase=source_phase, sibling_edges=sibling_edges)
    return "source"


def _human_input_edge_handle(
    *,
    edge: WorkflowIREdge,
    source_phase: WorkflowIRPhase,
    sibling_edges: list[WorkflowIREdge],
) -> str:
    condition = (edge.condition or "").strip()
    if condition:
        return _slugify_id(condition).replace("-", "_")

    user_actions = source_phase.config.get("user_actions")
    if isinstance(user_actions, list):
        action_ids = [
            str(action.get("id"))
            for action in user_actions
            if isinstance(action, dict) and action.get("id")
        ]
    else:
        action_ids = []
    if not action_ids:
        action_ids = ["approve", "reject"]

    try:
        index = sibling_edges.index(edge)
    except ValueError:
        index = 0
    return action_ids[min(index, len(action_ids) - 1)]


def _node_type_for_phase(phase: WorkflowIRPhase, *, app_mode: AppMode) -> str:
    match phase.kind:
        case WorkflowIRPhaseKind.WORKFLOW_START.value:
            return "start"
        case WorkflowIRPhaseKind.LLM_TASK.value:
            return "llm"
        case WorkflowIRPhaseKind.CONDITION.value:
            return "if-else"
        case WorkflowIRPhaseKind.WORKFLOW_OUTPUT.value:
            return "answer" if app_mode == AppMode.ADVANCED_CHAT else "end"
        case WorkflowIRPhaseKind.KNOWLEDGE_RETRIEVAL.value:
            return "knowledge-retrieval"
        case WorkflowIRPhaseKind.HTTP_CALL.value:
            return "http-request"
        case WorkflowIRPhaseKind.CODE_TRANSFORM.value:
            return "code"
        case WorkflowIRPhaseKind.TOOL_CALL.value:
            return "tool"
        case WorkflowIRPhaseKind.HUMAN_INPUT.value:
            return "human-input"
        case WorkflowIRPhaseKind.TRIGGER.value:
            trigger_type = str(phase.config.get("trigger_type") or "webhook")
            if trigger_type == "schedule":
                return "trigger-schedule"
            if trigger_type == "plugin":
                return "trigger-plugin"
            return "trigger-webhook"
        case _:
            return phase.kind


def _first_or_default(values: list[str], default: str) -> str:
    return values[0] if values else default


class _SelectorResolver:
    """Resolve IR variable names to Dify variable selectors for generated nodes."""

    _workflow_inputs: set[str]
    _phase_output_to_node_selector: dict[str, list[str]]
    _first_llm_selector: list[str] | None
    _start_node_id: str

    def __init__(self, *, ir: WorkflowIR, node_id_by_phase_id: dict[str, str], start_phase_id: str) -> None:
        self._workflow_inputs = {variable.name for variable in ir.inputs}
        self._phase_output_to_node_selector = {}
        self._first_llm_selector = None
        self._start_node_id = node_id_by_phase_id[start_phase_id]

        for phase in ir.phases:
            node_id = node_id_by_phase_id[phase.id]
            output_selector = self._default_output_selector_for_phase(phase=phase, node_id=node_id)
            if output_selector is None:
                continue
            if self._first_llm_selector is None and phase.kind == WorkflowIRPhaseKind.LLM_TASK.value:
                self._first_llm_selector = output_selector
            for output in phase.outputs or [phase.id]:
                self._phase_output_to_node_selector[output] = self._output_selector_for_name(
                    phase=phase,
                    node_id=node_id,
                    output_name=output,
                    fallback=output_selector,
                )

    def resolve_inputs(self, variable_names: list[str]) -> dict[str, list[str]]:
        selectors: dict[str, list[str]] = {}
        for variable_name in variable_names:
            selectors[variable_name] = self.resolve_variable(variable_name)
        return selectors

    def resolve_variable(self, variable_name: str) -> list[str]:
        if variable_name.startswith(("sys.", "conversation.", "env.")):
            return variable_name.split(".")
        if variable_name in self._phase_output_to_node_selector:
            return self._phase_output_to_node_selector[variable_name]
        if variable_name in self._workflow_inputs:
            return [self._start_node_id, variable_name]
        return self.fallback_selector()

    def fallback_selector(self) -> list[str]:
        if self._first_llm_selector is not None:
            return self._first_llm_selector
        if self._workflow_inputs:
            return [self._start_node_id, sorted(self._workflow_inputs)[0]]
        return [self._start_node_id, "query"]

    @staticmethod
    def _default_output_selector_for_phase(*, phase: WorkflowIRPhase, node_id: str) -> list[str] | None:
        match phase.kind:
            case WorkflowIRPhaseKind.LLM_TASK.value:
                return [node_id, "text"]
            case WorkflowIRPhaseKind.CONDITION.value:
                return [node_id, "selected_case_id"]
            case WorkflowIRPhaseKind.KNOWLEDGE_RETRIEVAL.value:
                return [node_id, "result"]
            case WorkflowIRPhaseKind.HTTP_CALL.value:
                return [node_id, "body"]
            case WorkflowIRPhaseKind.CODE_TRANSFORM.value:
                return [node_id, _first_or_default(phase.outputs, "result")]
            case WorkflowIRPhaseKind.TOOL_CALL.value:
                return [node_id, "text"]
            case WorkflowIRPhaseKind.HUMAN_INPUT.value:
                return [node_id, "__action_value"]
            case WorkflowIRPhaseKind.TRIGGER.value:
                trigger_type = str(phase.config.get("trigger_type") or "webhook")
                if trigger_type == "plugin":
                    return [node_id, _first_or_default(phase.outputs, "event")]
                if trigger_type == "schedule":
                    return None
                return [node_id, "_webhook_raw"]
            case _:
                return None

    @staticmethod
    def _output_selector_for_name(
        *,
        phase: WorkflowIRPhase,
        node_id: str,
        output_name: str,
        fallback: list[str],
    ) -> list[str]:
        match phase.kind:
            case WorkflowIRPhaseKind.HTTP_CALL.value:
                if output_name in {"body", "status_code", "headers", "files"}:
                    return [node_id, output_name]
                return fallback
            case WorkflowIRPhaseKind.TOOL_CALL.value:
                if output_name in {"text", "files", "json"}:
                    return [node_id, output_name]
                return fallback
            case WorkflowIRPhaseKind.HUMAN_INPUT.value | WorkflowIRPhaseKind.CODE_TRANSFORM.value:
                return [node_id, output_name]
            case WorkflowIRPhaseKind.TRIGGER.value:
                if str(phase.config.get("trigger_type") or "webhook") in {"webhook", "plugin"}:
                    return [node_id, output_name]
                return fallback
            case _:
                return fallback
