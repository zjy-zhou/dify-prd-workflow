"""Request and response contracts for the PRD-to-workflow compiler.

These entities are intentionally platform-facing but side-effect free. The
console controller validates HTTP payloads with them, and services may pass the
same objects through later Wiki, LLM, IR, and Dify graph compiler stages.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.app.app_config.entities import ModelConfig
from fields.base import ResponseModel


class PrdWorkflowSourceType(StrEnum):
    WIKI_TREE_CONTEXT = "wiki_tree_context"


class PrdWorkflowOverwritePolicy(StrEnum):
    REQUIRE_CONFIRMATION = "require_confirmation"
    FORCE = "force"


class WorkflowIRPhaseKind(StrEnum):
    WORKFLOW_START = "workflow_start"
    LLM_TASK = "llm_task"
    CONDITION = "condition"
    WORKFLOW_OUTPUT = "workflow_output"
    KNOWLEDGE_RETRIEVAL = "knowledge_retrieval"
    HTTP_CALL = "http_call"
    CODE_TRANSFORM = "code_transform"
    TOOL_CALL = "tool_call"
    HUMAN_INPUT = "human_input"
    TRIGGER = "trigger"


class PrdWorkflowModelConfig(ModelConfig):
    """Strict model config wrapper for PRD compiler requests."""

    model_config = ConfigDict(extra="forbid")


class WikiTreeContextSource(BaseModel):
    """Wiki Tree Context API source descriptor.

    MVP only supports this source type. ``tree_type`` and ``force_rebuild`` keep
    the defaults from the existing Wiki API contract.
    """

    type: str = Field(description="PRD source type")
    doc_id: str = Field(min_length=1, description="Wiki document id")
    workspace: str = Field(min_length=1, description="LIGHTRAG workspace id")
    tree_type: str = Field(default="reasoning_action", min_length=1, description="Wiki tree type")
    force_rebuild: bool = Field(default=False, description="Whether to force Wiki context rebuild")

    model_config = ConfigDict(extra="forbid")


class PrdWorkflowGeneratePayload(BaseModel):
    """HTTP payload for creating a Dify workflow draft from a PRD source.

    This stage defines a stable API contract only. Later compiler stages will
    consume the same payload to fetch Wiki context, call the planner, compile
    graph JSON, and optionally sync the draft.
    """

    app_id: str = Field(min_length=1, description="Target Dify app id")
    source: WikiTreeContextSource = Field(description="PRD source descriptor")
    model_config_data: PrdWorkflowModelConfig = Field(
        ...,
        alias="model_config",
        description="Model configuration used by the compiler planner",
    )
    sync_to_draft: bool = Field(default=True, description="Whether to sync generated graph to draft")
    overwrite_policy: PrdWorkflowOverwritePolicy = Field(
        default=PrdWorkflowOverwritePolicy.REQUIRE_CONFIRMATION,
        description="Draft overwrite policy",
    )
    draft_hash: str | None = Field(default=None, description="Optional current draft hash for conflict protection")

    model_config = ConfigDict(extra="forbid")


class PrdWorkflowSourceResponse(ResponseModel):
    type: str
    doc_id: str
    workspace: str
    tree_type: str
    force_rebuild: bool


class PrdWorkflowDraftResponse(ResponseModel):
    id: str | None = None
    hash: str | None = None


class PrdWorkflowGenerateResponse(ResponseModel):
    """Response envelope for PRD workflow generation.

    ``draft_synced`` is false for this contract-only stage. Later stages may set
    it true after graph validation and draft sync succeed.
    """

    result: str
    draft_synced: bool
    workflow: PrdWorkflowDraftResponse
    source: PrdWorkflowSourceResponse
    warnings: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    graph: dict[str, Any] | None = None


class WorkflowIRVariable(BaseModel):
    """A platform-neutral workflow input or output variable."""

    name: str = Field(min_length=1)
    type: str = Field(default="string", min_length=1)
    description: str = ""
    required: bool = True

    model_config = ConfigDict(extra="forbid")


class WorkflowIRConfirmation(BaseModel):
    """Human confirmation semantics preserved for later package/HITL support."""

    required: bool = False
    prompt: str = ""

    model_config = ConfigDict(extra="forbid")


class WorkflowIRPhase(BaseModel):
    """A platform-neutral step before it is compiled to Dify graph nodes."""

    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    title: str = Field(min_length=1)
    goal: str = ""
    instruction: str = ""
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    confirmation: WorkflowIRConfirmation | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class WorkflowIREdge(BaseModel):
    """Directed dependency between two IR phases."""

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    condition: str | None = None

    model_config = ConfigDict(extra="forbid")


class WorkflowIRSchema(BaseModel):
    """Named JSON schema emitted by the compiler."""

    name: str = Field(min_length=1)
    schema: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class WorkflowIRSkill(BaseModel):
    """Skill metadata preserved for package generation."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class WorkflowIR(BaseModel):
    """Platform-neutral workflow representation generated from a PRD."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    scenario: str = ""
    inputs: list[WorkflowIRVariable]
    outputs: list[WorkflowIRVariable]
    phases: list[WorkflowIRPhase]
    edges: list[WorkflowIREdge]
    schemas: list[WorkflowIRSchema] = Field(default_factory=list)
    skills: list[WorkflowIRSkill] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class WorkflowIRValidationResult(BaseModel):
    """Result of semantic IR validation before graph compilation."""

    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class WorkflowIRPlanningResult(BaseModel):
    """Planner output after parsing and validating the LLM-generated IR."""

    ir: WorkflowIR
    validation: WorkflowIRValidationResult

    model_config = ConfigDict(extra="forbid")


class DifyGraphValidationResult(BaseModel):
    """Result of validating generated Dify graph JSON before draft sync."""

    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")
