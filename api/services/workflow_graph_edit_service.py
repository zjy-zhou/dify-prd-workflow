"""Application service for natural-language workflow graph edits.

The service keeps all database and draft-sync side effects outside the graph
patch core. It reads the tenant-scoped draft workflow, plans or receives a
typed patch, validates the preview graph, and writes the draft only when the
caller explicitly applies the patch.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from core.model_manager import ModelManager
from core.workflow.prd_compiler.entities import PrdWorkflowDraftResponse
from core.workflow.prd_compiler.graph_patch import (
    WorkflowGraphEditPayload,
    WorkflowGraphEditResponse,
    WorkflowGraphPatch,
    WorkflowGraphPatchError,
    WorkflowGraphPatchPlanner,
    apply_graph_patch,
)
from core.workflow.prd_compiler.validator import validate_dify_graph
from graphon.model_runtime.entities.model_entities import ModelType
from models import Account, App
from services.errors.app import WorkflowHashNotEqualError
from services.workflow_service import WorkflowService

logger = logging.getLogger(__name__)


class WorkflowGraphPatchPlannerProtocol(Protocol):
    def plan(
        self,
        *,
        model_instance: Any,
        model_parameters: dict[str, Any],
        graph: dict[str, Any],
        instruction: str,
        selected_node_id: str | None,
        scope: str,
    ) -> WorkflowGraphPatch: ...


class WorkflowGraphEditService:
    """Preview and apply validated typed patches to Dify workflow drafts."""

    @classmethod
    def edit_draft_workflow_graph(
        cls,
        *,
        app_model: App,
        payload: WorkflowGraphEditPayload,
        account: Account | None = None,
        workflow_service: WorkflowService | None = None,
        planner: WorkflowGraphPatchPlannerProtocol | None = None,
    ) -> WorkflowGraphEditResponse:
        workflow_service = workflow_service or WorkflowService()
        draft_workflow = workflow_service.get_draft_workflow(app_model=app_model)
        if draft_workflow is None:
            return cls._failed_response(
                workflow=PrdWorkflowDraftResponse(),
                warnings=["Draft workflow does not exist."],
                missing_requirements=["draft_workflow_not_found"],
            )

        workflow_response = PrdWorkflowDraftResponse(
            id=str(draft_workflow.id),
            hash=str(draft_workflow.unique_hash),
        )
        if payload.draft_hash and str(draft_workflow.unique_hash) != payload.draft_hash:
            raise WorkflowHashNotEqualError()

        patch = payload.patch
        if patch is None:
            try:
                patch = cls._plan_patch(app_model=app_model, payload=payload, graph=draft_workflow.graph_dict, planner=planner)
            except WorkflowGraphPatchError as exc:
                logger.warning(
                    "Failed to plan workflow graph patch for tenant=%s app=%s: %s",
                    app_model.tenant_id,
                    app_model.id,
                    exc,
                )
                return cls._failed_response(
                    workflow=workflow_response,
                    warnings=[str(exc)],
                    missing_requirements=[exc.code],
                )

        try:
            preview_graph = apply_graph_patch(draft_workflow.graph_dict, patch)
        except WorkflowGraphPatchError as exc:
            return cls._failed_response(
                workflow=workflow_response,
                warnings=[str(exc)],
                missing_requirements=[exc.code],
                patch=patch,
            )

        graph_validation = validate_dify_graph(preview_graph)
        if not graph_validation.is_valid:
            return cls._failed_response(
                workflow=workflow_response,
                warnings=[*patch.warnings, *graph_validation.errors, *graph_validation.warnings],
                missing_requirements=["invalid_dify_graph"],
                patch=patch,
                graph=preview_graph,
            )

        if payload.dry_run:
            return WorkflowGraphEditResponse(
                result="success",
                draft_synced=False,
                workflow=workflow_response,
                summary=patch.summary,
                warnings=[*patch.warnings, *graph_validation.warnings],
                missing_requirements=[],
                patch=patch,
                graph=preview_graph,
                graph_summary=cls._graph_summary(preview_graph),
            )

        if account is None:
            return cls._failed_response(
                workflow=workflow_response,
                warnings=["Current account is required to apply the graph patch."],
                missing_requirements=["account_required_for_graph_patch"],
                patch=patch,
                graph=preview_graph,
            )

        try:
            synced_workflow = workflow_service.sync_draft_workflow(
                app_model=app_model,
                graph=preview_graph,
                features=cls._draft_features(draft_workflow),
                unique_hash=payload.draft_hash or str(draft_workflow.unique_hash),
                account=account,
                environment_variables=cls._draft_environment_variables(draft_workflow),
                conversation_variables=cls._draft_conversation_variables(draft_workflow),
            )
        except WorkflowHashNotEqualError:
            raise
        except Exception as exc:
            logger.warning(
                "Failed to apply workflow graph patch for tenant=%s app=%s: %s",
                app_model.tenant_id,
                app_model.id,
                exc,
            )
            return cls._failed_response(
                workflow=workflow_response,
                warnings=[f"Draft sync failed: {exc}"],
                missing_requirements=["draft_sync_failed"],
                patch=patch,
                graph=preview_graph,
            )

        return WorkflowGraphEditResponse(
            result="success",
            draft_synced=True,
            workflow=PrdWorkflowDraftResponse(
                id=str(synced_workflow.id),
                hash=str(synced_workflow.unique_hash),
            ),
            summary=patch.summary,
            warnings=[*patch.warnings, *graph_validation.warnings],
            missing_requirements=[],
            patch=patch,
            graph=preview_graph,
            graph_summary=cls._graph_summary(preview_graph),
        )

    @classmethod
    def _plan_patch(
        cls,
        *,
        app_model: App,
        payload: WorkflowGraphEditPayload,
        graph: dict[str, Any],
        planner: WorkflowGraphPatchPlannerProtocol | None,
    ) -> WorkflowGraphPatch:
        planner = planner or WorkflowGraphPatchPlanner()
        model_instance, model_parameters = cls._resolve_model_context(
            tenant_id=app_model.tenant_id,
            payload=payload,
        )
        return planner.plan(
            model_instance=model_instance,
            model_parameters=model_parameters,
            graph=graph,
            instruction=payload.instruction,
            selected_node_id=payload.selected_node_id,
            scope=payload.scope,
        )

    @staticmethod
    def _resolve_model_context(
        *,
        tenant_id: str,
        payload: WorkflowGraphEditPayload,
    ) -> tuple[Any, dict[str, Any]]:
        model_config = payload.model_config_data
        model_manager = ModelManager.for_tenant(tenant_id=tenant_id)
        model_instance = model_manager.get_model_instance(
            tenant_id=tenant_id,
            model_type=ModelType.LLM,
            provider=model_config.provider,
            model=model_config.name,
        )
        return model_instance, dict(model_config.completion_params or {})

    @staticmethod
    def _failed_response(
        *,
        workflow: PrdWorkflowDraftResponse,
        warnings: list[str],
        missing_requirements: list[str],
        patch: WorkflowGraphPatch | None = None,
        graph: dict[str, Any] | None = None,
    ) -> WorkflowGraphEditResponse:
        return WorkflowGraphEditResponse(
            result="failed",
            draft_synced=False,
            workflow=workflow,
            warnings=warnings,
            missing_requirements=missing_requirements,
            patch=patch,
            graph=graph,
            graph_summary=WorkflowGraphEditService._graph_summary(graph) if graph else None,
        )

    @staticmethod
    def _graph_summary(graph: dict[str, Any]) -> dict[str, Any]:
        nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
        edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
        node_types = [
            node.get("data", {}).get("type")
            for node in nodes
            if isinstance(node, dict) and isinstance(node.get("data"), dict)
        ]
        return {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "node_types": node_types,
        }

    @staticmethod
    def _draft_features(draft_workflow: Any | None) -> dict[str, Any]:
        if draft_workflow is None:
            return {}
        features = getattr(draft_workflow, "normalized_features_dict", None)
        if isinstance(features, dict):
            return dict(features)
        features = getattr(draft_workflow, "features_dict", None)
        return dict(features) if isinstance(features, dict) else {}

    @staticmethod
    def _draft_environment_variables(draft_workflow: Any | None) -> list[Any]:
        if draft_workflow is None:
            return []
        variables = getattr(draft_workflow, "environment_variables", None)
        return list(variables or [])

    @staticmethod
    def _draft_conversation_variables(draft_workflow: Any | None) -> list[Any]:
        if draft_workflow is None:
            return []
        variables = getattr(draft_workflow, "conversation_variables", None)
        return list(variables or [])
