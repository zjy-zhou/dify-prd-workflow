"""Validators for PRD compiler intermediate representations and generated graphs."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from core.workflow.prd_compiler.entities import (
    DifyGraphValidationResult,
    WorkflowIR,
    WorkflowIRPhaseKind,
    WorkflowIRValidationResult,
)

SUPPORTED_WORKFLOW_IR_PHASE_KINDS = frozenset(kind.value for kind in WorkflowIRPhaseKind)
SUPPORTED_DIFY_GRAPH_NODE_TYPES = frozenset(
    {
        "start",
        "llm",
        "if-else",
        "answer",
        "end",
        "knowledge-retrieval",
        "http-request",
        "code",
        "tool",
        "human-input",
        "trigger-webhook",
        "trigger-schedule",
        "trigger-plugin",
    }
)
SYSTEM_SELECTOR_ROOTS = frozenset({"sys", "conversation", "env"})
START_NODE_TYPES = frozenset({"start", "trigger-webhook", "trigger-schedule", "trigger-plugin"})
HTTP_REQUEST_OUTPUTS = frozenset({"body", "status_code", "headers", "files"})
TOOL_OUTPUTS = frozenset({"text", "files", "json"})
HUMAN_INPUT_SPECIAL_OUTPUTS = frozenset({"__action_id", "__action_value", "__rendered_content"})


def validate_workflow_ir(ir: WorkflowIR) -> WorkflowIRValidationResult:
    """Validate semantic rules that Pydantic shape checks cannot express.

    Unsupported phase kinds are reported as warnings plus missing requirements.
    They make the result invalid for graph compilation, but they remain distinct
    from structural errors such as duplicate phase ids or broken edges.
    """
    errors: list[str] = []
    warnings = list(ir.warnings)
    missing_requirements = list(ir.missing_requirements)

    _validate_inputs_and_outputs(ir, errors)
    phase_ids = _validate_phase_ids(ir, errors)
    _validate_edges(ir, phase_ids, errors)
    _validate_start_like_phases(ir, errors)
    _validate_phase_kinds(ir, warnings, missing_requirements)
    _validate_supported_phase_configs(ir, warnings, missing_requirements)

    return WorkflowIRValidationResult(
        is_valid=not errors and not missing_requirements,
        errors=errors,
        warnings=warnings,
        missing_requirements=missing_requirements,
    )


def _validate_inputs_and_outputs(ir: WorkflowIR, errors: list[str]) -> None:
    if not ir.inputs:
        errors.append("Workflow IR must define at least one input.")
    if not ir.outputs:
        errors.append("Workflow IR must define at least one output.")
    if not ir.phases:
        errors.append("Workflow IR must define at least one phase.")


def _validate_phase_ids(ir: WorkflowIR, errors: list[str]) -> set[str]:
    phase_ids = [phase.id for phase in ir.phases]
    duplicated_ids = sorted(phase_id for phase_id, count in Counter(phase_ids).items() if count > 1)
    for phase_id in duplicated_ids:
        errors.append(f"Workflow IR phase id '{phase_id}' is duplicated.")
    return set(phase_ids)


def _validate_edges(ir: WorkflowIR, phase_ids: set[str], errors: list[str]) -> None:
    for index, edge in enumerate(ir.edges):
        if edge.source not in phase_ids:
            errors.append(f"Workflow IR edge {index} source '{edge.source}' does not reference an existing phase.")
        if edge.target not in phase_ids:
            errors.append(f"Workflow IR edge {index} target '{edge.target}' does not reference an existing phase.")


def _validate_phase_kinds(
    ir: WorkflowIR,
    warnings: list[str],
    missing_requirements: list[str],
) -> None:
    unsupported_kinds = sorted(
        {
            phase.kind
            for phase in ir.phases
            if phase.kind not in SUPPORTED_WORKFLOW_IR_PHASE_KINDS
        }
    )
    for kind in unsupported_kinds:
        warnings.append(f"Workflow IR phase kind '{kind}' is not supported by the compiler.")
        missing_requirements.append(f"unsupported_phase_kind:{kind}")


def _validate_start_like_phases(ir: WorkflowIR, errors: list[str]) -> None:
    start_like_kinds = {
        WorkflowIRPhaseKind.WORKFLOW_START.value,
        WorkflowIRPhaseKind.TRIGGER.value,
    }
    count = sum(1 for phase in ir.phases if phase.kind in start_like_kinds)
    if count != 1:
        errors.append(f"Workflow IR must contain exactly one workflow_start or trigger phase, found {count}.")


def _validate_supported_phase_configs(
    ir: WorkflowIR,
    warnings: list[str],
    missing_requirements: list[str],
) -> None:
    for phase in ir.phases:
        match phase.kind:
            case WorkflowIRPhaseKind.KNOWLEDGE_RETRIEVAL.value:
                if not _non_empty_string_list(phase.config.get("dataset_ids")):
                    _missing_phase_config(
                        phase.id,
                        "dataset_ids",
                        warnings=warnings,
                        missing_requirements=missing_requirements,
                    )
            case WorkflowIRPhaseKind.HTTP_CALL.value:
                if not _non_empty_string(phase.config.get("url")):
                    _missing_phase_config(
                        phase.id,
                        "url",
                        warnings=warnings,
                        missing_requirements=missing_requirements,
                    )
            case WorkflowIRPhaseKind.CODE_TRANSFORM.value:
                if not _non_empty_string(phase.config.get("code")):
                    _missing_phase_config(
                        phase.id,
                        "code",
                        warnings=warnings,
                        missing_requirements=missing_requirements,
                    )
            case WorkflowIRPhaseKind.TOOL_CALL.value:
                for field in ("provider_id", "provider_type", "tool_name"):
                    if not _non_empty_string(phase.config.get(field)):
                        _missing_phase_config(
                            phase.id,
                            field,
                            warnings=warnings,
                            missing_requirements=missing_requirements,
                        )
            case WorkflowIRPhaseKind.TRIGGER.value:
                trigger_type = str(phase.config.get("trigger_type") or "webhook")
                if trigger_type not in {"webhook", "schedule", "plugin"}:
                    _missing_phase_config(
                        phase.id,
                        "valid_trigger_type",
                        warnings=warnings,
                        missing_requirements=missing_requirements,
                    )
                    continue
                if trigger_type == "webhook" and not _non_empty_string(phase.config.get("webhook_url")):
                    _missing_phase_config(
                        phase.id,
                        "webhook_url",
                        warnings=warnings,
                        missing_requirements=missing_requirements,
                    )
                if trigger_type == "schedule":
                    mode = str(phase.config.get("mode") or "cron")
                    if mode == "cron" and not _non_empty_string(phase.config.get("cron_expression")):
                        _missing_phase_config(
                            phase.id,
                            "cron_expression",
                            warnings=warnings,
                            missing_requirements=missing_requirements,
                        )
                    if mode == "visual" and not _non_empty_string(phase.config.get("frequency")):
                        _missing_phase_config(
                            phase.id,
                            "frequency",
                            warnings=warnings,
                            missing_requirements=missing_requirements,
                        )
                if trigger_type == "plugin":
                    for field in ("subscription_id", "provider_id", "provider_type", "event_name"):
                        if not _non_empty_string(phase.config.get(field)):
                            _missing_phase_config(
                                phase.id,
                                field,
                                warnings=warnings,
                                missing_requirements=missing_requirements,
                            )


def _missing_phase_config(
    phase_id: str,
    field: str,
    *,
    warnings: list[str],
    missing_requirements: list[str],
) -> None:
    warnings.append(f"Workflow IR phase '{phase_id}' is missing required config '{field}'.")
    missing_requirements.append(f"missing_phase_config:{phase_id}:{field}")


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _non_empty_string_list(value: object) -> bool:
    return isinstance(value, list) and any(_non_empty_string(item) for item in value)


def validate_dify_graph(graph: Mapping[str, Any]) -> DifyGraphValidationResult:
    """Validate the generated MVP Dify graph before draft sync.

    Dify's own ``WorkflowService.validate_graph_structure`` is intentionally
    lightweight. This validator enforces the stricter PRD compiler contract so
    graph failures short-circuit before a user draft changes.
    """
    errors: list[str] = []
    warnings: list[str] = []
    nodes = _as_list_of_mappings(graph.get("nodes"))
    edges = _as_list_of_mappings(graph.get("edges"))

    if not nodes:
        errors.append("Dify graph must contain at least one node.")
        return DifyGraphValidationResult(is_valid=False, errors=errors, warnings=warnings)

    node_ids = _validate_graph_node_ids(nodes, errors)
    node_types_by_id = _validate_graph_node_types(nodes, errors)
    _validate_graph_start_and_terminal_nodes(node_types_by_id, errors)
    _validate_graph_edges(edges, node_ids, node_types_by_id, errors)
    known_outputs = _collect_known_graph_outputs(nodes)
    _validate_graph_node_payloads(nodes, known_outputs, errors)
    _validate_if_else_branches(nodes, edges, errors)

    return DifyGraphValidationResult(
        is_valid=not errors,
        errors=errors,
        warnings=warnings,
    )


def _as_list_of_mappings(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _validate_graph_node_ids(nodes: Sequence[Mapping[str, Any]], errors: list[str]) -> set[str]:
    raw_node_ids = [str(node.get("id") or "") for node in nodes]
    for index, node_id in enumerate(raw_node_ids):
        if not node_id:
            errors.append(f"Dify graph node {index} is missing id.")

    duplicated_ids = sorted(node_id for node_id, count in Counter(raw_node_ids).items() if node_id and count > 1)
    for node_id in duplicated_ids:
        errors.append(f"Dify graph node id '{node_id}' is duplicated.")
    return {node_id for node_id in raw_node_ids if node_id}


def _validate_graph_node_types(
    nodes: Sequence[Mapping[str, Any]],
    errors: list[str],
) -> dict[str, str]:
    node_types_by_id: dict[str, str] = {}
    for node in nodes:
        node_id = str(node.get("id") or "")
        data = node.get("data")
        node_type = data.get("type") if isinstance(data, Mapping) else None
        if not node_type:
            errors.append(f"Dify graph node '{node_id}' is missing data.type.")
            continue
        node_type = str(node_type)
        node_types_by_id[node_id] = node_type
        if node_type not in SUPPORTED_DIFY_GRAPH_NODE_TYPES:
            errors.append(f"Dify graph node '{node_id}' type '{node_type}' is not supported by MVP.")
    return node_types_by_id


def _validate_graph_start_and_terminal_nodes(node_types_by_id: Mapping[str, str], errors: list[str]) -> None:
    start_count = sum(1 for node_type in node_types_by_id.values() if node_type in START_NODE_TYPES)
    if start_count != 1:
        errors.append(f"Dify graph must contain exactly one Start or Trigger node, found {start_count}.")

    terminal_count = sum(1 for node_type in node_types_by_id.values() if node_type in {"answer", "end"})
    if terminal_count < 1:
        errors.append("Dify graph must contain at least one Answer or End node.")


def _validate_graph_edges(
    edges: Sequence[Mapping[str, Any]],
    node_ids: set[str],
    node_types_by_id: Mapping[str, str],
    errors: list[str],
) -> None:
    for index, edge in enumerate(edges):
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in node_ids:
            errors.append(f"Dify graph edge {index} source '{source}' does not reference an existing node.")
        if target not in node_ids:
            errors.append(f"Dify graph edge {index} target '{target}' does not reference an existing node.")

        source_type = node_types_by_id.get(source)
        source_handle = str(edge.get("sourceHandle") or "")
        if source_type == "if-else" and not source_handle:
            errors.append(f"Dify graph IfElse edge {index} is missing sourceHandle.")
        if source_type == "human-input" and not source_handle:
            errors.append(f"Dify graph Human Input edge {index} is missing sourceHandle.")
        if source_type not in {"if-else", "human-input"} and source_handle not in {"", "source"}:
            errors.append(f"Dify graph edge {index} has invalid sourceHandle '{source_handle}'.")


def _collect_known_graph_outputs(nodes: Sequence[Mapping[str, Any]]) -> dict[str, set[str]]:
    outputs: dict[str, set[str]] = {}
    for node in nodes:
        node_id = str(node.get("id") or "")
        data = node.get("data")
        if not isinstance(data, Mapping):
            continue

        node_type = data.get("type")
        if node_type == "start":
            variables = data.get("variables") if isinstance(data.get("variables"), list) else []
            outputs[node_id] = {
                str(variable.get("variable"))
                for variable in variables
                if isinstance(variable, Mapping) and variable.get("variable")
            }
        elif node_type == "llm":
            outputs[node_id] = {"text"}
        elif node_type == "if-else":
            outputs[node_id] = {"selected_case_id"}
        elif node_type == "knowledge-retrieval":
            outputs[node_id] = {"result"}
        elif node_type == "http-request":
            outputs[node_id] = set(HTTP_REQUEST_OUTPUTS)
        elif node_type == "code":
            code_outputs = data.get("outputs") if isinstance(data.get("outputs"), Mapping) else {}
            outputs[node_id] = {str(name) for name in code_outputs}
        elif node_type == "tool":
            outputs[node_id] = set(TOOL_OUTPUTS)
        elif node_type == "human-input":
            form_inputs = data.get("inputs") if isinstance(data.get("inputs"), list) else []
            input_outputs = {
                str(form_input.get("output_variable_name"))
                for form_input in form_inputs
                if isinstance(form_input, Mapping) and form_input.get("output_variable_name")
            }
            outputs[node_id] = set(HUMAN_INPUT_SPECIAL_OUTPUTS) | input_outputs
        elif node_type == "trigger-webhook":
            variables = data.get("variables") if isinstance(data.get("variables"), list) else []
            outputs[node_id] = {
                str(variable.get("variable") or variable.get("name"))
                for variable in variables
                if isinstance(variable, Mapping) and (variable.get("variable") or variable.get("name"))
            }
        elif node_type == "trigger-plugin":
            output_schema = data.get("output_schema") if isinstance(data.get("output_schema"), Mapping) else {}
            properties = output_schema.get("properties") if isinstance(output_schema.get("properties"), Mapping) else {}
            outputs[node_id] = {str(name) for name in properties}
        elif node_type == "trigger-schedule":
            outputs[node_id] = set()
        else:
            outputs[node_id] = set()
    return outputs


def _validate_graph_node_payloads(
    nodes: Sequence[Mapping[str, Any]],
    known_outputs: Mapping[str, set[str]],
    errors: list[str],
) -> None:
    for node in nodes:
        node_id = str(node.get("id") or "")
        data = node.get("data")
        if not isinstance(data, Mapping):
            errors.append(f"Dify graph node '{node_id}' data must be an object.")
            continue

        node_type = data.get("type")
        if node_type == "llm":
            _validate_llm_node_payload(node_id, data, known_outputs, errors)
        elif node_type == "if-else":
            _validate_if_else_node_payload(node_id, data, known_outputs, errors)
        elif node_type == "end":
            _validate_end_node_payload(node_id, data, known_outputs, errors)
        elif node_type == "answer":
            _validate_answer_node_payload(node_id, data, known_outputs, errors)
        elif node_type == "knowledge-retrieval":
            _validate_knowledge_retrieval_node_payload(node_id, data, known_outputs, errors)
        elif node_type == "http-request":
            _validate_http_request_node_payload(node_id, data, known_outputs, errors)
        elif node_type == "code":
            _validate_code_node_payload(node_id, data, known_outputs, errors)
        elif node_type == "tool":
            _validate_tool_node_payload(node_id, data, errors)
        elif node_type == "human-input":
            _validate_human_input_node_payload(node_id, data, known_outputs, errors)
        elif node_type == "trigger-webhook":
            _validate_webhook_trigger_node_payload(node_id, data, errors)
        elif node_type == "trigger-schedule":
            _validate_schedule_trigger_node_payload(node_id, data, errors)
        elif node_type == "trigger-plugin":
            _validate_plugin_trigger_node_payload(node_id, data, errors)


def _validate_llm_node_payload(
    node_id: str,
    data: Mapping[str, Any],
    known_outputs: Mapping[str, set[str]],
    errors: list[str],
) -> None:
    model = data.get("model")
    if not isinstance(model, Mapping):
        errors.append(f"Dify graph LLM node '{node_id}' is missing model.")
    else:
        for field in ("provider", "name", "mode"):
            if not model.get(field):
                errors.append(f"Dify graph LLM node '{node_id}' model.{field} is required.")

    prompt_template = data.get("prompt_template")
    if not isinstance(prompt_template, list) or not prompt_template:
        errors.append(f"Dify graph LLM node '{node_id}' prompt_template is required.")

    variables = data.get("variables") if isinstance(data.get("variables"), list) else []
    for variable in variables:
        if isinstance(variable, Mapping):
            _validate_variable_selector(
                node_id=node_id,
                selector=variable.get("value_selector"),
                known_outputs=known_outputs,
                errors=errors,
            )


def _validate_if_else_node_payload(
    node_id: str,
    data: Mapping[str, Any],
    known_outputs: Mapping[str, set[str]],
    errors: list[str],
) -> None:
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append(f"Dify graph IfElse node '{node_id}' must define at least one case.")
        return

    for case in cases:
        if not isinstance(case, Mapping):
            continue
        conditions = case.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            errors.append(f"Dify graph IfElse node '{node_id}' case is missing conditions.")
            continue
        for condition in conditions:
            if isinstance(condition, Mapping):
                _validate_variable_selector(
                    node_id=node_id,
                    selector=condition.get("variable_selector"),
                    known_outputs=known_outputs,
                    errors=errors,
                )


def _validate_end_node_payload(
    node_id: str,
    data: Mapping[str, Any],
    known_outputs: Mapping[str, set[str]],
    errors: list[str],
) -> None:
    outputs = data.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        errors.append(f"Dify graph End node '{node_id}' must define at least one output.")
        return

    for output in outputs:
        if isinstance(output, Mapping):
            _validate_variable_selector(
                node_id=node_id,
                selector=output.get("value_selector"),
                known_outputs=known_outputs,
                errors=errors,
            )


def _validate_answer_node_payload(
    node_id: str,
    data: Mapping[str, Any],
    known_outputs: Mapping[str, set[str]],
    errors: list[str],
) -> None:
    answer = data.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        errors.append(f"Dify graph Answer node '{node_id}' answer is required.")
        return

    for selector in re.findall(r"\{\{#([^#]+)#}}", answer):
        _validate_variable_selector(
            node_id=node_id,
            selector=selector.split("."),
            known_outputs=known_outputs,
            errors=errors,
        )


def _validate_knowledge_retrieval_node_payload(
    node_id: str,
    data: Mapping[str, Any],
    known_outputs: Mapping[str, set[str]],
    errors: list[str],
) -> None:
    dataset_ids = data.get("dataset_ids")
    if not _non_empty_string_list(dataset_ids):
        errors.append(f"Dify graph Knowledge Retrieval node '{node_id}' must define dataset_ids.")
    _validate_variable_selector(
        node_id=node_id,
        selector=data.get("query_variable_selector"),
        known_outputs=known_outputs,
        errors=errors,
    )


def _validate_http_request_node_payload(
    node_id: str,
    data: Mapping[str, Any],
    known_outputs: Mapping[str, set[str]],
    errors: list[str],
) -> None:
    if not _non_empty_string(data.get("url")):
        errors.append(f"Dify graph HTTP Request node '{node_id}' url is required.")
    if str(data.get("method") or "").lower() not in {"get", "post", "head", "patch", "put", "delete"}:
        errors.append(f"Dify graph HTTP Request node '{node_id}' method is invalid.")

    variables = data.get("variables") if isinstance(data.get("variables"), list) else []
    for variable in variables:
        if isinstance(variable, Mapping):
            _validate_variable_selector(
                node_id=node_id,
                selector=variable.get("value_selector"),
                known_outputs=known_outputs,
                errors=errors,
            )


def _validate_code_node_payload(
    node_id: str,
    data: Mapping[str, Any],
    known_outputs: Mapping[str, set[str]],
    errors: list[str],
) -> None:
    if not _non_empty_string(data.get("code")):
        errors.append(f"Dify graph Code node '{node_id}' code is required.")
    outputs = data.get("outputs")
    if not isinstance(outputs, Mapping) or not outputs:
        errors.append(f"Dify graph Code node '{node_id}' must define outputs.")

    variables = data.get("variables") if isinstance(data.get("variables"), list) else []
    for variable in variables:
        if isinstance(variable, Mapping):
            _validate_variable_selector(
                node_id=node_id,
                selector=variable.get("value_selector"),
                known_outputs=known_outputs,
                errors=errors,
            )


def _validate_tool_node_payload(node_id: str, data: Mapping[str, Any], errors: list[str]) -> None:
    for field in ("provider_id", "provider_type", "tool_name"):
        if not _non_empty_string(data.get(field)):
            errors.append(f"Dify graph Tool node '{node_id}' {field} is required.")


def _validate_human_input_node_payload(
    node_id: str,
    data: Mapping[str, Any],
    known_outputs: Mapping[str, set[str]],
    errors: list[str],
) -> None:
    delivery_methods = data.get("delivery_methods")
    if not isinstance(delivery_methods, list) or not delivery_methods:
        errors.append(f"Dify graph Human Input node '{node_id}' must define at least one delivery method.")

    actions = data.get("user_actions")
    if not isinstance(actions, list) or not actions:
        errors.append(f"Dify graph Human Input node '{node_id}' must define at least one user action.")

    form_inputs = data.get("inputs") if isinstance(data.get("inputs"), list) else []
    for form_input in form_inputs:
        if not isinstance(form_input, Mapping):
            continue
        if not _non_empty_string(form_input.get("output_variable_name")):
            errors.append(f"Dify graph Human Input node '{node_id}' has an input without output_variable_name.")
        default = form_input.get("default")
        if isinstance(default, Mapping) and default.get("type") == "variable":
            _validate_variable_selector(
                node_id=node_id,
                selector=default.get("selector"),
                known_outputs=known_outputs,
                errors=errors,
            )


def _validate_webhook_trigger_node_payload(node_id: str, data: Mapping[str, Any], errors: list[str]) -> None:
    if not _non_empty_string(data.get("webhook_url")):
        errors.append(f"Dify graph Webhook Trigger node '{node_id}' webhook_url is required.")
    if str(data.get("method") or "").upper() not in {"GET", "POST", "HEAD", "PATCH", "PUT", "DELETE"}:
        errors.append(f"Dify graph Webhook Trigger node '{node_id}' method is invalid.")
    if not _non_empty_string(data.get("content_type")):
        errors.append(f"Dify graph Webhook Trigger node '{node_id}' content_type is required.")
    variables = data.get("variables")
    if not isinstance(variables, list) or not variables:
        errors.append(f"Dify graph Webhook Trigger node '{node_id}' must define variables.")


def _validate_schedule_trigger_node_payload(node_id: str, data: Mapping[str, Any], errors: list[str]) -> None:
    mode = str(data.get("mode") or "")
    if mode not in {"cron", "visual"}:
        errors.append(f"Dify graph Schedule Trigger node '{node_id}' mode is invalid.")
        return
    if mode == "cron" and not _non_empty_string(data.get("cron_expression")):
        errors.append(f"Dify graph Schedule Trigger node '{node_id}' cron_expression is required.")
    if mode == "visual" and not _non_empty_string(data.get("frequency")):
        errors.append(f"Dify graph Schedule Trigger node '{node_id}' frequency is required.")


def _validate_plugin_trigger_node_payload(node_id: str, data: Mapping[str, Any], errors: list[str]) -> None:
    for field in ("subscription_id", "provider_id", "provider_type", "event_name"):
        if not _non_empty_string(data.get(field)):
            errors.append(f"Dify graph Plugin Trigger node '{node_id}' {field} is required.")


def _validate_variable_selector(
    *,
    node_id: str,
    selector: object,
    known_outputs: Mapping[str, set[str]],
    errors: list[str],
) -> None:
    if not isinstance(selector, list) or len(selector) < 2:
        errors.append(f"Dify graph node '{node_id}' has invalid variable selector {selector!r}.")
        return

    selector_parts = [str(part) for part in selector]
    source_node_id = selector_parts[0]
    variable_name = selector_parts[1]
    if source_node_id in SYSTEM_SELECTOR_ROOTS:
        return

    if source_node_id not in known_outputs:
        errors.append(f"Dify graph node '{node_id}' selector source '{source_node_id}' does not exist.")
        return

    if variable_name not in known_outputs[source_node_id]:
        errors.append(
            f"Dify graph node '{node_id}' selector '{source_node_id}.{variable_name}' "
            "does not reference a known upstream output."
        )


def _validate_if_else_branches(
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    errors: list[str],
) -> None:
    outgoing_handles_by_node_id: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        source = edge.get("source")
        source_handle = edge.get("sourceHandle")
        if source and source_handle:
            outgoing_handles_by_node_id[str(source)].add(str(source_handle))

    for node in nodes:
        node_id = str(node.get("id") or "")
        data = node.get("data")
        if not isinstance(data, Mapping) or data.get("type") != "if-else":
            continue

        cases = data.get("cases") if isinstance(data.get("cases"), list) else []
        case_ids = {
            str(case.get("case_id"))
            for case in cases
            if isinstance(case, Mapping) and case.get("case_id")
        }
        required_handles = case_ids | {"false"}
        missing_handles = sorted(required_handles - outgoing_handles_by_node_id.get(node_id, set()))
        for handle in missing_handles:
            errors.append(f"Dify graph IfElse node '{node_id}' is missing outgoing branch '{handle}'.")

    _validate_human_input_branches(nodes, edges, errors)


def _validate_human_input_branches(
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    errors: list[str],
) -> None:
    outgoing_handles_by_node_id: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        source = edge.get("source")
        source_handle = edge.get("sourceHandle")
        if source and source_handle:
            outgoing_handles_by_node_id[str(source)].add(str(source_handle))

    for node in nodes:
        node_id = str(node.get("id") or "")
        data = node.get("data")
        if not isinstance(data, Mapping) or data.get("type") != "human-input":
            continue

        actions = data.get("user_actions") if isinstance(data.get("user_actions"), list) else []
        allowed_handles = {
            str(action.get("id"))
            for action in actions
            if isinstance(action, Mapping) and action.get("id")
        } | {"timeout"}
        invalid_handles = sorted(outgoing_handles_by_node_id.get(node_id, set()) - allowed_handles)
        for handle in invalid_handles:
            errors.append(f"Dify graph Human Input node '{node_id}' has unknown outgoing branch '{handle}'.")
