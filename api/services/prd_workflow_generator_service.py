"""Application service for generating Dify workflow drafts from PRD sources.

The service owns the tenant-scoped orchestration for Wiki context resolution,
LLM planning, Dify graph compilation, graph validation, and optional draft sync.
Every failure before graph validation returns without mutating the user's draft.
"""

import logging
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.model_manager import ModelManager
from core.workflow.prd_compiler.dify_compiler import DifyGraphCompileError, compile_workflow_ir_to_dify_graph
from core.workflow.prd_compiler.entities import (
    PrdWorkflowGeneratePayload,
    PrdWorkflowGenerateResponse,
    WorkflowIRPlanningResult,
    PrdWorkflowSourceResponse,
    PrdWorkflowSourceType,
    PrdWorkflowDraftResponse,
)
from core.workflow.prd_compiler.planner import PrdWorkflowPlanner, PrdWorkflowPlannerError
from core.workflow.prd_compiler.validator import validate_dify_graph
from core.workflow.prd_compiler.wiki_context import PrdWikiContext
from graphon.model_runtime.entities.model_entities import ModelType
from models import Account, App
from models.model import AppMode
from services.errors.app import WorkflowHashNotEqualError
from services.prd_context_service import PrdContextService, PrdContextServiceError
from services.workflow_service import WorkflowService

logger = logging.getLogger(__name__)


class UnsupportedPrdWorkflowSourceError(ValueError):
    """Raised when a request uses a source outside the MVP support set."""


class PrdWorkflowAppNotFoundError(ValueError):
    """Raised when the tenant has no normal workflow app matching the request."""


class PrdWorkflowPlannerProtocol(Protocol):
    def plan(
        self,
        *,
        model_instance: Any,
        model_parameters: dict[str, Any],
        prd_context: PrdWikiContext,
    ) -> WorkflowIRPlanningResult: ...


class PrdWorkflowGeneratorService:
    """Coordinates PRD source validation, compilation, and optional draft sync."""

    @classmethod
    def generate_from_prd(
        cls,
        *,
        session: Session,
        tenant_id: str,
        payload: PrdWorkflowGeneratePayload,
        account: Account | None = None,
        context_service: PrdContextService | None = None,
        planner: PrdWorkflowPlannerProtocol | None = None,
        workflow_service: WorkflowService | None = None,
    ) -> PrdWorkflowGenerateResponse:
        """Generate a workflow graph from PRD context and optionally sync the draft.

        The app lookup is scoped by ``tenant_id`` and limited to normal workflow
        apps. Draft writes happen only after Wiki context, LLM planning, IR
        validation, graph compilation, and graph validation have all succeeded.
        """
        if payload.source.type != PrdWorkflowSourceType.WIKI_TREE_CONTEXT.value:
            raise UnsupportedPrdWorkflowSourceError("MVP only supports wiki_tree_context source.")

        app_model = cls._get_workflow_app(session=session, tenant_id=tenant_id, app_id=payload.app_id)
        workflow_service = workflow_service or WorkflowService()
        draft_workflow = workflow_service.get_draft_workflow(app_model=app_model, session=session)
        if payload.draft_hash and draft_workflow and str(draft_workflow.unique_hash) != payload.draft_hash:
            raise WorkflowHashNotEqualError()

        workflow_response = PrdWorkflowDraftResponse(
            id=str(draft_workflow.id) if draft_workflow else None,
            hash=str(draft_workflow.unique_hash) if draft_workflow else None,
        )
        source_response = PrdWorkflowSourceResponse(
            type=payload.source.type,
            doc_id=payload.source.doc_id,
            workspace=payload.source.workspace,
            tree_type=payload.source.tree_type,
            force_rebuild=payload.source.force_rebuild,
        )

        context_service = context_service or PrdContextService()
        try:
            prd_context = context_service.fetch_wiki_tree_context(payload.source)
        except PrdContextServiceError as exc:
            logger.warning(
                "Failed to resolve Wiki PRD context for tenant=%s app=%s doc_id=%s: %s",
                tenant_id,
                payload.app_id,
                payload.source.doc_id,
                exc,
            )
            return PrdWorkflowGenerateResponse(
                result="failed",
                draft_synced=False,
                workflow=workflow_response,
                source=source_response,
                warnings=[str(exc)],
                missing_requirements=[exc.code],
                graph=None,
            )

        planner = planner or PrdWorkflowPlanner()
        try:
            model_instance, model_parameters = cls._resolve_planner_model_context(
                tenant_id=tenant_id,
                payload=payload,
            )
            planning_result = planner.plan(
                model_instance=model_instance,
                model_parameters=model_parameters,
                prd_context=prd_context,
            )
        except PrdWorkflowPlannerError as exc:
            logger.warning(
                "Failed to plan Workflow IR for tenant=%s app=%s doc_id=%s: %s",
                tenant_id,
                payload.app_id,
                payload.source.doc_id,
                exc,
            )
            return PrdWorkflowGenerateResponse(
                result="failed",
                draft_synced=False,
                workflow=workflow_response,
                source=source_response,
                warnings=[*prd_context.warnings, str(exc)],
                missing_requirements=[exc.code],
                graph=None,
            )

        validation = planning_result.validation
        if not validation.is_valid:
            return PrdWorkflowGenerateResponse(
                result="failed",
                draft_synced=False,
                workflow=workflow_response,
                source=source_response,
                warnings=[*prd_context.warnings, *validation.errors, *validation.warnings],
                missing_requirements=validation.missing_requirements or ["invalid_workflow_ir"],
                graph=None,
            )

        try:
            app_mode = AppMode.value_of(str(app_model.mode))
            graph = compile_workflow_ir_to_dify_graph(
                ir=planning_result.ir,
                app_mode=app_mode,
                model_config=payload.model_config_data,
            )
        except DifyGraphCompileError as exc:
            logger.warning(
                "Failed to compile Dify graph for tenant=%s app=%s doc_id=%s: %s",
                tenant_id,
                payload.app_id,
                payload.source.doc_id,
                exc,
            )
            return PrdWorkflowGenerateResponse(
                result="failed",
                draft_synced=False,
                workflow=workflow_response,
                source=source_response,
                warnings=[*prd_context.warnings, str(exc)],
                missing_requirements=["dify_graph_compile_failed"],
                graph=None,
            )

        graph_validation = validate_dify_graph(graph)
        if not graph_validation.is_valid:
            return PrdWorkflowGenerateResponse(
                result="failed",
                draft_synced=False,
                workflow=workflow_response,
                source=source_response,
                warnings=[*prd_context.warnings, *graph_validation.errors, *graph_validation.warnings],
                missing_requirements=["invalid_dify_graph"],
                graph=cls._graph_summary(graph),
            )

        if not payload.sync_to_draft:
            return PrdWorkflowGenerateResponse(
                result="success",
                draft_synced=False,
                workflow=workflow_response,
                source=source_response,
                warnings=[*prd_context.warnings, *graph_validation.warnings],
                missing_requirements=[],
                graph=cls._graph_summary(graph),
            )

        if account is None:
            return PrdWorkflowGenerateResponse(
                result="failed",
                draft_synced=False,
                workflow=workflow_response,
                source=source_response,
                warnings=[*prd_context.warnings, "Current account is required to sync the generated draft."],
                missing_requirements=["account_required_for_draft_sync"],
                graph=cls._graph_summary(graph),
            )

        try:
            synced_workflow = workflow_service.sync_draft_workflow(
                app_model=app_model,
                graph=graph,
                features=cls._draft_features(draft_workflow),
                unique_hash=payload.draft_hash or (str(draft_workflow.unique_hash) if draft_workflow else None),
                account=account,
                environment_variables=cls._draft_environment_variables(draft_workflow),
                conversation_variables=cls._draft_conversation_variables(draft_workflow),
            )
        except WorkflowHashNotEqualError:
            raise
        except Exception as exc:
            logger.warning(
                "Failed to sync generated PRD workflow draft for tenant=%s app=%s doc_id=%s: %s",
                tenant_id,
                payload.app_id,
                payload.source.doc_id,
                exc,
            )
            return PrdWorkflowGenerateResponse(
                result="failed",
                draft_synced=False,
                workflow=workflow_response,
                source=source_response,
                warnings=[*prd_context.warnings, f"Draft sync failed: {exc}"],
                missing_requirements=["draft_sync_failed"],
                graph=cls._graph_summary(graph),
            )

        return PrdWorkflowGenerateResponse(
            result="success",
            draft_synced=True,
            workflow=PrdWorkflowDraftResponse(
                id=str(synced_workflow.id),
                hash=str(synced_workflow.unique_hash),
            ),
            source=source_response,
            warnings=[*prd_context.warnings, *graph_validation.warnings],
            missing_requirements=[],
            graph=cls._graph_summary(graph),
        )

    @staticmethod
    def _get_workflow_app(*, session: Session, tenant_id: str, app_id: str) -> App:
        app_model = session.scalar(
            select(App)
            .where(
                App.id == app_id,
                App.tenant_id == tenant_id,
                App.status == "normal",
                App.mode.in_([AppMode.WORKFLOW, AppMode.ADVANCED_CHAT]),
            )
            .limit(1)
        )
        if app_model is None:
            raise PrdWorkflowAppNotFoundError(f"App {app_id} not found.")
        return app_model

    @staticmethod
    def _resolve_planner_model_context(
        *,
        tenant_id: str,
        payload: PrdWorkflowGeneratePayload,
    ) -> tuple[Any, dict[str, Any]]:
        model_config = payload.model_config_data
        model_manager = ModelManager.for_tenant(tenant_id=tenant_id)
        model_instance = model_manager.get_model_instance(
            tenant_id=tenant_id,
            model_type=ModelType.LLM,
            provider=model_config.provider,
            model=model_config.name,
        )
        model_parameters = dict(model_config.completion_params or {})
        return model_instance, model_parameters

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
