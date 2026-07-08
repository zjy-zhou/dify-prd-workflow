# PRD 到工作流生成阶段 0 代码定位报告

状态：已完成静态定位，已完成 fixture JSON 语法验证
最后更新：2026-07-07

## 1. 结论摘要

阶段 0 的目标是确认 Dify 当前 workflow graph shape、draft sync 入参、发布流程和前端画布刷新方式。已完成代码定位，并沉淀两个最小 graph fixture：

- `docs/fixtures/prd-to-workflow/minimal-advanced-chat-start-llm-answer.json`
- `docs/fixtures/prd-to-workflow/minimal-workflow-start-llm-end.json`

重要结论：

- Dify graph 顶层结构是 `nodes`、`edges`、`viewport`。
- 每个节点是 ReactFlow node wrapper，真实节点类型在 `node.data.type`。
- 每条边是 ReactFlow edge wrapper，Dify 使用 `type: "custom"`，默认 handle 是 `source` -> `target`。
- `WorkflowService.sync_draft_workflow` 的写入参数是 `graph`、`features`、`unique_hash`、`account`、`environment_variables`、`conversation_variables`。
- HTTP draft sync 接口入参字段名是 `graph`、`features`、`hash`、`environment_variables`、`conversation_variables`。
- `hash` 不匹配时后端抛 `WorkflowHashNotEqualError`，controller 转成 HTTP 409，错误码 `draft_workflow_not_sync`。
- 普通 Workflow 模式终点是 `End` 节点；Advanced Chat/Chatflow 模式终点是 `Answer` 节点。
- 后端 `/workflow-generate` 现有生成器输出就是可直接交给 `/apps/{app_id}/workflows/draft` 的 graph payload。
- 后端直接写入 draft 后，前端应调用 `handleRefreshWorkflowDraft()` 重新拉取 draft 并刷新画布，或者通过 `WORKFLOW_DATA_UPDATE` 事件更新画布。

## 2. 已阅读和定位的文件

后端：

- `api/AGENTS.md`
- `api/controllers/console/app/generator.py`
- `api/services/workflow_generator_service.py`
- `api/core/workflow/generator/__init__.py`
- `api/core/workflow/generator/types.py`
- `api/core/workflow/generator/runner.py`
- `api/core/workflow/generator/prompts/builder_prompts.py`
- `api/controllers/console/app/workflow.py`
- `api/controllers/console/app/error.py`
- `api/services/workflow_service.py`
- `api/services/errors/app.py`

前端：

- `web/AGENTS.md`
- `web/app/components/workflow/index.tsx`
- `web/app/components/workflow/types.ts`
- `web/app/components/workflow/workflow-generator/`
- `web/app/components/workflow/workflow-generator/apply.ts`
- `web/app/components/workflow/hooks/use-workflow-update.ts`
- `web/app/components/workflow/hooks/use-workflow-refresh-draft.ts`
- `web/app/components/workflow/hooks/use-nodes-sync-draft.ts`
- `web/app/components/workflow-app/hooks/use-workflow-refresh-draft.ts`
- `web/app/components/workflow-app/hooks/use-nodes-sync-draft.ts`
- `web/service/debug.ts`
- `web/service/workflow.ts`
- `web/service/use-workflow.ts`
- `web/app/components/workflow/nodes/start/default.ts`
- `web/app/components/workflow/nodes/llm/default.ts`
- `web/app/components/workflow/nodes/if-else/default.ts`
- `web/app/components/workflow/nodes/answer/default.ts`
- `web/app/components/workflow/nodes/end/default.ts`

## 3. 当前 workflow generator 输出的 graph JSON 结构

现有生成链路：

```text
api/controllers/console/app/generator.py
  POST /console/api/workflow-generate
    -> WorkflowGeneratorService.generate_workflow_graph
      -> core.workflow.generator.WorkflowGenerator.generate_workflow_graph
```

关键定义：

- `api/core/workflow/generator/types.py`
  - `GraphDict`
  - `GraphNodeDict`
  - `GraphEdgeDict`
  - `GraphViewportDict`
  - `WorkflowGenerateResultDict`

graph 顶层结构：

```json
{
  "nodes": [],
  "edges": [],
  "viewport": {
    "x": 0,
    "y": 0,
    "zoom": 0.7
  }
}
```

node wrapper 最小结构：

```json
{
  "id": "start",
  "type": "custom",
  "position": { "x": 80, "y": 280 },
  "data": {
    "type": "start",
    "title": "Start",
    "desc": "",
    "selected": false
  }
}
```

edge wrapper 最小结构：

```json
{
  "id": "start-source-llm-target",
  "source": "start",
  "target": "llm",
  "type": "custom",
  "sourceHandle": "source",
  "targetHandle": "target",
  "data": {
    "sourceType": "start",
    "targetType": "llm",
    "isInIteration": false,
    "isInLoop": false
  }
}
```

后端 generator postprocess 会补齐：

- node `type`
- node `data.title`
- node `data.desc`
- node `data.selected`
- node `position`
- node `positionAbsolute`
- node `width`
- node `height`
- node `sourcePosition`
- node `targetPosition`
- edge `type`
- edge `sourceHandle`
- edge `targetHandle`
- edge `data.sourceType`
- edge `data.targetType`
- container 相关 edge 标记

PRD 编译器如果不是复用 generator postprocess，而是自己输出 graph，建议直接输出补齐后的完整 wrapper，减少画布渲染不确定性。

## 4. Draft Sync 入参、hash 校验和异常形态

后端 HTTP 接口：

```http
GET  /console/api/apps/{app_id}/workflows/draft
POST /console/api/apps/{app_id}/workflows/draft
```

controller：

```text
api/controllers/console/app/workflow.py
  @console_ns.route("/apps/<uuid:app_id>/workflows/draft")
  class DraftWorkflowApi
```

HTTP POST 请求模型：

```python
class SyncDraftWorkflowPayload(BaseModel):
    graph: dict[str, Any]
    features: dict[str, Any]
    hash: str | None = None
    environment_variables: list[dict[str, Any]] = Field(default_factory=list)
    conversation_variables: list[dict[str, Any]] = Field(default_factory=list)
```

service 入参：

```python
WorkflowService.sync_draft_workflow(
    app_model=app_model,
    graph=args["graph"],
    features=args["features"],
    unique_hash=args.get("hash"),
    account=current_user,
    environment_variables=environment_variables,
    conversation_variables=conversation_variables,
)
```

hash 校验逻辑：

```python
workflow = self.get_draft_workflow(app_model=app_model)

if workflow and workflow.unique_hash != unique_hash:
    raise WorkflowHashNotEqualError()
```

异常映射：

- service 抛：`services.errors.app.WorkflowHashNotEqualError`
- controller 转：`controllers.console.app.error.DraftWorkflowNotSync`
- HTTP status：`409`
- error_code：`draft_workflow_not_sync`
- description：`Workflow graph might have been modified, please refresh and resubmit.`

GET draft 响应模型：

```python
class WorkflowResponse(ResponseModel):
    id: str
    graph: dict[str, Any]
    features: dict[str, Any]
    hash: str
    version: str
    marked_name: str
    marked_comment: str
    environment_variables: list[WorkflowEnvironmentVariableResponse]
    conversation_variables: list[WorkflowConversationVariableResponse]
```

POST draft 成功响应：

```json
{
  "result": "success",
  "hash": "<new_unique_hash>",
  "updated_at": "<timestamp>"
}
```

前端保存封装：

- `web/service/workflow.ts`
  - `fetchWorkflowDraft(url)`
  - `syncWorkflowDraft({ url, params })`

前端覆盖当前 app 的现有生成器逻辑：

- `web/app/components/workflow/workflow-generator/apply.ts`
  - `applyToCurrentApp`
  - 先 `fetchWorkflowDraft("apps/{appId}/workflows/draft")` 读取 `hash`
  - 再调用 `syncWorkflowDraft`
  - 保留已有 `features`、`environment_variables`、`conversation_variables`
  - 只替换 `graph`
  - 409 时转成 `WorkflowApplyHashCollisionError`

## 5. 发布流程和发布后读取 published workflow

后端 HTTP 接口：

```http
GET  /console/api/apps/{app_id}/workflows/publish
POST /console/api/apps/{app_id}/workflows/publish
```

controller：

```text
api/controllers/console/app/workflow.py
  @console_ns.route("/apps/<uuid:app_id>/workflows/publish")
  class PublishedWorkflowApi
```

GET 逻辑：

```python
workflow = WorkflowService().get_published_workflow(app_model=app_model)
if workflow is None:
    return None
return dump_response(WorkflowResponse, workflow)
```

POST 逻辑：

```python
workflow = workflow_service.publish_workflow(
    session=session,
    app_model=app_model,
    account=current_user,
    marked_name=args.marked_name or "",
    marked_comment=args.marked_comment or "",
)
app_model_in_session.workflow_id = workflow.id
```

service 发布入口：

```text
api/services/workflow_service.py
  WorkflowService.publish_workflow(...)
```

发布前会做：

- 读取 draft workflow。
- 校验 workflow credentials。
- 调用 `validate_graph_structure(graph=draft_workflow.graph_dict)`。
- 校验 agent nodes。
- 生成新的 published workflow 版本。
- controller 同事务更新 `apps.workflow_id` 指向新发布版本。

前端读取 published workflow：

- `web/service/use-workflow.ts`
  - `useAppWorkflow(appID)`
  - queryKey：`['workflow', 'publish', appID]`
  - queryFn：`GET /apps/{appID}/workflows/publish`
- `useInvalidateAppWorkflow(appID)` 可失效这个 query。

前端发布：

- `web/service/use-workflow.ts`
  - `usePublishWorkflow()`
  - mutation key：`['workflow', 'publish']`
  - POST body：`marked_name`、`marked_comment`

## 6. 前端画布刷新方式

当前有两种刷新方式。

### 方式 A：重新拉取 draft 并更新画布

外层实际实现：

- `web/app/components/workflow-app/hooks/use-workflow-refresh-draft.ts`

调用：

```ts
handleRefreshWorkflowDraft()
```

内部动作：

1. `fetchWorkflowDraft("/apps/{appId}/workflows/draft")`
2. `getWorkflowDraftGraphForCanvas(response.graph)`
3. `handleUpdateWorkflowCanvas(...)`
4. `setSyncWorkflowDraftHash(response.hash)`
5. 更新 environment variables。
6. 更新 conversation variables。

workflow 内部 hook：

- `web/app/components/workflow/hooks/use-workflow-refresh-draft.ts`

只是从 hooks store 取 `handleRefreshWorkflowDraft`。

### 方式 B：发送 WORKFLOW_DATA_UPDATE 事件

实现：

- `web/app/components/workflow/hooks/use-workflow-update.ts`

调用：

```ts
handleUpdateWorkflowCanvas({
  nodes,
  edges,
  viewport,
})
```

它会 emit：

```ts
{
  type: WORKFLOW_DATA_UPDATE,
  payload: {
    nodes: initialNodes(nodes, edges),
    edges: initialEdges(edges, nodes),
  }
}
```

接收：

- `web/app/components/workflow/index.tsx`

接收后会：

- `setNodes(payload.nodes)`
- `store.getState().setNodes(payload.nodes)`
- `setEdges(payload.edges)`
- 如果有 `viewport`，调用 `reactflow.setViewport(payload.viewport)`
- 如果有 `hash`，调用 `setSyncWorkflowDraftHash(payload.hash)`

PRD 后端直接写 draft 的推荐前端动作：

1. 调用 PRD 生成 API。
2. 后端成功写入 draft 并返回新 `hash`。
3. 前端调用 `handleRefreshWorkflowDraft()` 拉取后端最新 draft。

如果 PRD 生成 API 直接返回 graph，也可以先用 `handleUpdateWorkflowCanvas` 做乐观更新，但最终仍建议以 `handleRefreshWorkflowDraft()` 的后端数据为准。

## 7. MVP 节点最小合法 data

### Start

来源：

- `web/app/components/workflow/nodes/start/default.ts`
- `api/core/workflow/generator/prompts/builder_prompts.py`

最小 data：

```json
{
  "type": "start",
  "title": "Start",
  "desc": "",
  "selected": false,
  "variables": []
}
```

带用户输入变量时：

```json
{
  "variables": [
    {
      "variable": "query",
      "label": "Query",
      "type": "paragraph",
      "required": true,
      "max_length": 4096,
      "options": []
    }
  ]
}
```

### LLM

来源：

- `web/app/components/workflow/nodes/llm/default.ts`
- `api/core/workflow/generator/prompts/builder_prompts.py`

最小 data：

```json
{
  "type": "llm",
  "title": "LLM",
  "desc": "",
  "selected": false,
  "model": {
    "provider": "__PROVIDER__",
    "name": "__MODEL__",
    "mode": "chat",
    "completion_params": {
      "temperature": 0.7
    }
  },
  "prompt_template": [
    {
      "role": "system",
      "text": "You are a helpful assistant."
    },
    {
      "role": "user",
      "text": "Answer the user query:\n\n{{#start.query#}}"
    }
  ],
  "context": {
    "enabled": false,
    "variable_selector": []
  },
  "vision": {
    "enabled": false
  }
}
```

注意：

- `__PROVIDER__` 和 `__MODEL__` 是 fixture 占位符。
- 真正运行 debug 前必须替换为租户已配置模型，例如 Qwen/GPT 对应 provider/name。
- LLM 默认输出变量是 `text`，下游可引用 `["llm", "text"]` 或 `{{#llm.text#}}`。

### IfElse

来源：

- `web/app/components/workflow/nodes/if-else/default.ts`
- `api/core/workflow/generator/prompts/builder_prompts.py`

最小 data：

```json
{
  "type": "if-else",
  "title": "If/Else",
  "desc": "",
  "selected": false,
  "_targetBranches": [
    { "id": "true", "name": "IF" },
    { "id": "false", "name": "ELSE" }
  ],
  "logical_operator": "and",
  "cases": [
    {
      "case_id": "true",
      "logical_operator": "and",
      "conditions": [
        {
          "id": "c1",
          "variable_selector": ["llm", "text"],
          "comparison_operator": "contains",
          "value": "yes"
        }
      ]
    }
  ]
}
```

注意：

- 从 IfElse 出边时，`sourceHandle` 应使用 branch id，例如 `true` 或 `false`。
- 默认普通边的 `sourceHandle` 是 `source`，但 IfElse 不是。

### Answer

来源：

- `web/app/components/workflow/nodes/answer/default.ts`
- `api/core/workflow/generator/prompts/builder_prompts.py`

用于 Advanced Chat/Chatflow。

最小 data：

```json
{
  "type": "answer",
  "title": "Answer",
  "desc": "",
  "selected": false,
  "variables": [],
  "answer": "{{#llm.text#}}"
}
```

### End

来源：

- `web/app/components/workflow/nodes/end/default.ts`
- `api/core/workflow/generator/prompts/builder_prompts.py`

用于普通 Workflow。

最小 data：

```json
{
  "type": "end",
  "title": "End",
  "desc": "",
  "selected": false,
  "outputs": [
    {
      "variable": "answer",
      "value_selector": ["llm", "text"]
    }
  ]
}
```

## 8. 最小 graph fixture

已记录两个 fixture：

```text
docs/fixtures/prd-to-workflow/minimal-advanced-chat-start-llm-answer.json
docs/fixtures/prd-to-workflow/minimal-workflow-start-llm-end.json
```

使用方式：

- Chatflow/Advanced Chat 验证：使用 `minimal-advanced-chat-start-llm-answer.json`。
- Workflow 验证：使用 `minimal-workflow-start-llm-end.json`。

`Start -> LLM -> Answer` 只适用于 Advanced Chat/Chatflow。普通 Workflow 模式必须使用 `Start -> LLM -> End`，否则现有 generator structural validator 会报缺少 `end` 终点。

已验证：

- 两个 fixture 均通过 `python -m json.tool` JSON 语法校验。

未完成的自动结构校验：

- 尝试用系统 Python 导入 `core.workflow.generator.runner.WorkflowGenerator` 时缺少 `json_repair`。
- 尝试按仓库约定执行 `uv run --project api ...` 时，本机 PATH 中没有 `uv`。
- 尝试使用 Docker Compose API 容器时，Docker Desktop daemon 未运行。
- 因此暂未执行 `WorkflowGenerator._validate_structure(...)` 和真实 `POST /workflows/draft`。

## 9. 阶段 0 验收状态

已完成：

- 找出当前 workflow generator 输出的 graph JSON 结构。
- 找出 `WorkflowService.sync_draft_workflow` 需要的参数、hash 校验方式和异常形态。
- 找出 draft 页面刷新 draft 的前端 hook 和事件方式。
- 找出 publish 后读取 published workflow 的方法。
- 找出 Start、LLM、IfElse、Answer/End 的最小合法 node data。
- 手工构造最小 graph fixture。

待后续在有真实 app/account/session 的环境中验证：

- 用 `uv run --project api` 或 API Docker 容器执行 `WorkflowGenerator._validate_structure(...)`。
- 用 fixture 调用 `POST /console/api/apps/{app_id}/workflows/draft`，确认真实数据库 draft sync 成功。
- 用真实模型 provider/name 替换 fixture 占位符，执行一次 draft debug。

阶段 1 开发建议：

- PRD 编译器初版可直接以这两个 fixture 的 node wrapper 和 edge wrapper 为模板。
- 后端直接写 draft 时应复用 `WorkflowService.sync_draft_workflow`，不要绕过 hash 和 graph/features 校验。
- 前端生成成功后优先调用 `handleRefreshWorkflowDraft()`，以服务器 draft 为准刷新画布。
