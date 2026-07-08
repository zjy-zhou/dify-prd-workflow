# PRD 到工作流生成详细技术开发步骤

状态：草稿
最后更新：2026-07-07
来源文档：

- `docs/prd-to-workflow-requirements.md`
- `docs/prd-to-workflow-technical-design.md`

## 1. 目标和当前状态

目标是在 Dify 开源版内跑通“Wiki PRD -> LLM 编译 -> Dify workflow draft -> 画布编辑调试 -> 发布 -> 严格格式 package 下载”的闭环。

当前已确认：

- 第一版基于 Dify 二次开发，不单独重建画布和运行时。
- MVP 只支持 Wiki PRD 来源。
- PRD 结构化上下文来自现有 Wiki Tree Context API。
- 后端生成并校验 Dify graph 后直接写入 draft，前端刷新画布。
- MVP 节点类型只支持 Start、LLM、IfElse、Answer/End。
- 发布仍走 Dify 原有 published workflow 逻辑。
- package 只在用户下载时按需生成，不长期保存。
- package 必须严格遵循参考格式，只包含 `package.yaml`、`workflow.yaml`、`skills/`、`schemas/`、`data/`。
- Dify DSL、Dify graph、IR、validation、source metadata 不进入下载 package。
- 右侧自然语言助手使用独立 graph patch prompt，返回预览，用户确认后应用。

## 2. 推荐分期

### 阶段 0：开发准备和代码定位

目标：确认 Dify 当前 graph shape、draft sync 入参、发布流程和前端画布刷新方式。

需要阅读的文件：

- `api/AGENTS.md`
- `web/AGENTS.md`
- `api/controllers/console/app/generator.py`
- `api/services/workflow_generator_service.py`
- `api/core/workflow/generator/`
- `api/controllers/console/app/workflow.py`
- `api/services/workflow_service.py`
- `web/app/components/workflow/index.tsx`
- `web/app/components/workflow/types.ts`
- `web/app/components/workflow/workflow-generator/`
- `web/service/debug.ts`
- `web/service/use-workflow.ts`

开发动作：

1. 找出当前 workflow generator 输出的 graph JSON 结构。
2. 找出 `WorkflowService.sync_draft_workflow` 需要的参数、hash 校验方式和异常形态。
3. 找出 draft 页面刷新 draft 的前端 hook 或 query key。
4. 找出 publish 后读取 published workflow 的方法。
5. 找出 Dify 中 Start、LLM、IfElse、Answer/End 的最小合法 node data。

阶段验收：

- 能手工构造一个最小 Start -> LLM -> Answer graph，并确认可以被 draft sync 接受。
- 记录最小 graph fixture，用于后续单元测试和集成测试。

## 3. 阶段 1：Dify Draft 生成 MVP

### 3.1 增加后端配置和请求模型

目标：为 Wiki PRD 来源、模型配置、覆盖策略定义稳定 API 合同。

建议新增或修改：

- `api/controllers/console/app/prd_workflow_generator.py`
- `api/controllers/console/app/generator.py`
- `api/services/prd_workflow_generator_service.py`
- `api/services/prd_context_service.py`
- `api/core/workflow/prd_compiler/entities.py`

实现要点：

1. 新增阻塞式接口：

   ```http
   POST /console/api/workflow-generate/from-prd
   ```

2. 请求体支持：

   - `app_id`
   - `source.type = wiki_tree_context`
   - `source.doc_id`
   - `source.workspace`
   - `source.tree_type`，默认 `reasoning_action`
   - `source.force_rebuild`，默认 `false`
   - `model_config`
   - `sync_to_draft`
   - `overwrite_policy`
   - 可选 `draft_hash`

3. 使用 Pydantic v2 DTO，`extra="forbid"`。
4. controller 只负责解析、鉴权、调用 service、序列化响应。
5. service 内部保留 tenant/app/workflow 上下文，所有 DB 查询必须按 tenant scope。

测试：

- 请求体缺少 `doc_id` 返回参数错误。
- `source.type` 非 `wiki_tree_context` 返回 MVP 不支持错误。
- `tree_type` 和 `force_rebuild` 默认值正确。

### 3.2 接入 Wiki Tree Context API

目标：把 Wiki API 响应标准化成 PRD 编译输入。

建议文件：

- `api/services/prd_context_service.py`
- `api/core/workflow/prd_compiler/wiki_context.py`

外部 API：

```http
POST /api/wiki/tree/context
Header: LIGHTRAG-WORKSPACE: <workspace_id>
Body:
{
  "doc_id": "...",
  "tree_type": "reasoning_action",
  "force_rebuild": false
}
```

实现要点：

1. Wiki API base URL 不要在代码里硬编码，应走 Dify config。
2. 出站 HTTP 请求必须设置 timeout。
3. 按接口文档读取 `tree_json`、`outline_md`、`dimension_bundle.markdown`、`raw_bundle.markdown`、`source_name`、`version`、`tree_type`。
4. 对大文档做裁剪策略：
   - 优先保留 `tree_json` 中 action、condition、outcome、rule。
   - `raw_bundle.markdown` 默认不完整送入 LLM，只在必要时抽片段。
   - 记录被裁剪的 warning。
5. 失败时返回明确错误，且不得修改 draft。

测试：

- 正常响应可标准化。
- 缺少 `tree_json` 时失败。
- 外部 API 500、timeout、无权限时，错误可读且 `draft_synced=false`。
- 超大响应会产生 warning。

### 3.3 定义 Workflow IR 和 IR 校验

目标：让 LLM 输出先进入平台无关 IR，而不是直接成为 Dify graph。

建议文件：

- `api/core/workflow/prd_compiler/entities.py`
- `api/core/workflow/prd_compiler/validator.py`

IR 最小字段：

- `id`
- `title`
- `scenario`
- `inputs`
- `outputs`
- `phases`
- `edges`
- `schemas`
- `skills`

MVP 支持的 phase kind：

- `workflow_start`
- `llm_task`
- `condition`
- `workflow_output`

实现要点：

1. 用 Pydantic model 定义 IR。
2. 明确支持节点白名单，不支持的 kind 必须进入 `warnings` 或 `missing_requirements`。
3. 校验 phase id 唯一。
4. 校验 edges 的 source/target 存在。
5. 校验 workflow 至少有一个输入和一个输出。
6. 人工确认语义可以保留在 IR `confirmation` 字段，但 MVP 不强行映射到 Dify graph。

测试：

- 合法 IR 通过。
- 重复 phase id 失败。
- edge 指向不存在 phase 失败。
- 出现 `http_call`、`code_transform` 等第二阶段节点时，MVP 返回 unsupported warning，而不是静默生成错误 graph。

### 3.4 编写 LLM Planner

目标：把 Wiki PRD context 编译成结构化 Workflow IR。

建议文件：

- `api/core/workflow/prd_compiler/planner.py`
- `api/core/workflow/prd_compiler/prompts/prd_to_workflow_ir.md`
- `api/services/prd_workflow_generator_service.py`

实现要点：

1. prompt 明确要求模型只输出 JSON IR。
2. prompt 明确节点限制：Start、LLM、IfElse、Answer/End。
3. prompt 明确不确定内容必须放入 `warnings` 和 `missing_requirements`。
4. prompt 明确不可生成密钥、真实凭证、外部 API Key。
5. LLM 输出必须经过 JSON parse 和 IR 校验。
6. LLM 调用尽量复用 Dify 现有 provider/model 配置能力，不单独绕过 Dify 模型管理。

测试：

- 使用 mock LLM 输出合法 IR。
- LLM 输出非 JSON 时失败并返回可读错误。
- LLM 输出不支持节点类型时不会写 draft。
- LLM 输出缺字段时不会写 draft。

### 3.5 实现 IR 到 Dify Graph 编译器

目标：生成 Dify draft sync 可接受的 graph。

建议文件：

- `api/core/workflow/prd_compiler/dify_compiler.py`
- `api/core/workflow/prd_compiler/validator.py`

实现要点：

1. 优先参考 `api/core/workflow/generator/` 的 graph 输出 shape。
2. 为每个 IR phase 生成稳定 node id。
3. 生成合理坐标，避免所有节点重叠。
4. 生成 Start 节点输入变量。
5. 为 LLM 节点生成 prompt、model、上下游变量 selector。
6. PRD 中有 condition 时生成 IfElse 节点和分支边。
7. 生成 Answer/End 节点，引用上游输出。
8. 生成 viewport。

最低 graph 校验：

- 有且只有一个 Start。
- 至少一个 Answer/End。
- node id 唯一。
- edge source/target 都存在。
- 节点类型在 MVP 白名单内。
- LLM 节点必填字段完整。
- variable selector 引用上游存在输出。
- IfElse 分支连线完整。

测试：

- 单链路 PRD：Start -> LLM -> Answer。
- 条件 PRD：Start -> LLM -> IfElse -> LLM/Answer。
- 缺少 Answer 时校验失败。
- edge 指向不存在 node 时校验失败。

### 3.6 接入 Draft Sync

目标：后端校验通过后直接写入 Dify draft，前端刷新画布。

建议文件：

- `api/services/prd_workflow_generator_service.py`
- `api/services/workflow_service.py`
- `api/controllers/console/app/prd_workflow_generator.py`

实现要点：

1. 生成前读取 app 和 draft workflow，并做 tenant/app 权限检查。
2. 如果传入 `draft_hash` 且和当前 draft 不一致，返回冲突错误。
3. graph 校验通过后调用 `WorkflowService.sync_draft_workflow`。
4. 任何 Wiki、LLM、IR、graph 错误都不得写入 draft。
5. 响应中返回：
   - `result`
   - `draft_synced`
   - `workflow.id`
   - `workflow.hash`
   - `warnings`
   - `missing_requirements`
   - 可选 graph 摘要

测试：

- 成功生成并写入 draft。
- draft hash 冲突不写入。
- graph 校验失败不写入。
- service 异常不会产生半写入状态。

### 3.7 前端 PRD 生成入口

目标：在工作流编辑页提供 Wiki PRD 生成入口，生成成功后刷新现有画布。

建议文件：

- `web/app/components/workflow/index.tsx`
- `web/app/components/workflow/workflow-generator/`
- `web/service/debug.ts`
- `web/service/use-workflow.ts`
- `web/i18n/en-US/`
- 其他 locale 文件

实现要点：

1. 优先复用现有 workflow generator 入口和交互模式。
2. 表单字段：
   - Wiki workspace
   - Wiki doc id
   - tree type，默认 `reasoning_action`
   - force rebuild 开关，默认关闭
   - 模型配置，优先复用现有模型选择方式
3. 生成前检查当前 draft 是否有未保存变更。
4. 覆盖 draft 前必须二次确认。
5. 展示生成进度：
   - 获取 PRD 上下文
   - 编译 workflow plan
   - 生成 graph
   - 校验 graph
   - 写入 draft
6. 成功后 invalidate/refetch draft query，让现有画布渲染新 graph。
7. 错误要展示明确原因，不要只展示“生成失败”。
8. 所有用户可见文案走 i18n。

测试：

- 表单必填校验。
- 生成按钮 loading 和禁用状态。
- 成功后刷新 draft。
- API 错误展示。
- 用户取消覆盖时不调用生成接口。

阶段 1 验收：

- 给定合法 Wiki `doc_id`，能生成 Dify workflow draft。
- 生成后的 draft 能在画布正常打开。
- 支持节点能完成一次基础 debug 运行。
- 外部 API、LLM、graph 校验失败时 draft 不被修改。

## 4. 阶段 2：Package 下载和更多节点

建议先实现 package 下载，再扩展节点。原因是 package 格式已经强约束，且是发布闭环的必要输出。

### 4.1 实现严格格式 Package Builder

目标：基于 published workflow 或内部生成上下文，按参考目录生成 zip。

建议文件：

- `api/services/workflow_package_service.py`
- `api/core/workflow/prd_compiler/package_builder.py`

允许的顶层结构：

```text
package.yaml
workflow.yaml
skills/
schemas/
data/
```

禁止进入 package：

- `dify/`
- `compile/`
- `manifest.lock`
- `README.md`
- `workflow.dsl.yaml`
- `graph.json`
- Dify DSL
- Dify graph
- IR
- validation
- source metadata
- 完整原始 PRD
- 完整 LLM prompt

实现要点：

1. package 只在请求生命周期内生成 zip stream。
2. 不落库，不写对象存储。
3. `package.yaml` 字段对齐参考 package：
   - `id`
   - `version`
   - `title`
   - `scenario`
   - `entry_workflow`
4. `workflow.yaml` 字段对齐参考 package：
   - `id`
   - `entry_phase`
   - `phases`
   - phase 中包含 `id`、`title`、`skill`、`goal`、`confirmation`
5. 每个 phase 生成 `skills/<skill-id>/skill.md`。
6. 每个 phase 输出 schema 生成到 `schemas/*.schema.json`。
7. `data/` 可以为空目录或放脱敏样例数据，但不得放密钥和完整 PRD 原文。
8. 所有文件使用 UTF-8。

测试：

- zip 顶层文件严格等于允许列表。
- 不包含 Dify DSL/graph/IR。
- YAML 可被解析。
- skill front matter 可被解析。
- schema 是合法 JSON Schema。
- package 不包含疑似 secret 明文。

### 4.2 新增 Package Export API

目标：用户在发布后可以下载 package。

建议接口：

```http
POST /console/api/apps/{app_id}/workflows/{workflow_id}/package/export
```

建议文件：

- `api/controllers/console/app/workflow.py`
- `api/controllers/console/app/prd_workflow_generator.py`
- `api/services/workflow_package_service.py`

实现要点：

1. 只允许对当前 app 下的 published workflow 导出。
2. 读取 published workflow，不改变 Dify 原有发布流程。
3. 直接返回 zip archive stream。
4. 设置合理文件名，例如 `<package-id>-<version>.zip`。
5. 导出失败不影响 published workflow。

测试：

- 已发布 workflow 可导出。
- 非当前 app workflow 不能导出。
- draft workflow 不应作为正式 package 来源，除非后续产品明确允许。
- zip 文件名和 content type 正确。

### 4.3 前端增加 Package 下载入口

目标：发布后提供 package 下载按钮。

建议文件：

- `web/service/use-workflow.ts`
- workflow 发布成功区域或 workflow 操作菜单相关组件
- `web/i18n/en-US/`

实现要点：

1. 只在存在 published workflow 时展示下载入口。
2. 点击后调用 package export API。
3. 处理文件流下载。
4. 失败时展示错误原因。
5. 文案走 i18n。

测试：

- 有 published workflow 时按钮可见。
- 无 published workflow 时按钮不可用或不展示。
- 下载失败有错误提示。

### 4.4 扩展第二阶段节点映射

目标：在 Dify 路径稳定后支持更多节点。

新增节点：

- Knowledge Retrieval
- HTTP Request
- Code
- Tool
- Human Input
- Trigger

开发顺序建议：

1. Knowledge Retrieval：依赖 Dify 知识库配置，先做已有知识库引用。
2. HTTP Request：重点是脱敏和 secret placeholder。
3. Code：重点是安全沙箱和输入输出 schema。
4. Tool：重点是工具权限和依赖声明。
5. Human Input：承接第一版 IR/package 的 `confirmation` 语义。
6. Trigger：涉及运行入口，最后做。

每增加一种节点，都要同步修改：

- IR kind 白名单。
- LLM prompt。
- IR validator。
- Dify graph compiler。
- Graph validator。
- Package builder。
- 前端展示和错误提示。
- 单元测试 fixture。

阶段 2 验收：

- 发布后能下载严格格式 package。
- package 不包含任何 Dify 内部编译产物。
- 第二阶段节点至少逐项通过 graph sync 和基础 debug。

## 5. 阶段 3：右侧自然语言编辑器

### 5.1 后端 Graph Patch 能力

目标：把自然语言修改转成可预览、可校验的 graph patch。

建议文件：

- `api/services/workflow_graph_edit_service.py`
- `api/core/workflow/prd_compiler/graph_patch.py`
- `api/core/workflow/prd_compiler/prompts/graph_patch.md`

建议接口：

```http
POST /console/api/apps/{app_id}/workflows/draft/nl-edit
```

实现要点：

1. 输入当前 draft graph、用户 instruction、选中节点 id、scope。
2. 使用独立 graph patch prompt，不复用从零生成 workflow 的 prompt。
3. LLM 输出类型化 patch：
   - `add_node`
   - `update_node`
   - `remove_node`
   - `add_edge`
   - `remove_edge`
4. 先在内存中应用 patch，生成 preview graph。
5. 对 preview graph 运行同一套 graph validator。
6. `dry_run=true` 时只返回预览，不写 draft。
7. 用户确认后再 apply，并再次校验。

测试：

- 修改节点 prompt。
- 增加节点和连线。
- 删除节点时阻止产生断边。
- 无效 patch 返回错误，不写 draft。

### 5.2 前端右侧助手面板

目标：在 workflow 编辑页右侧提供自然语言修改入口。

建议文件：

- `web/app/components/workflow/index.tsx`
- `web/app/components/workflow/panel/`
- 可新增 `web/app/components/workflow/nl-edit-assistant/`
- `web/i18n/en-US/`

实现要点：

1. 面板不永久遮挡现有节点配置面板。
2. 支持读取当前选中节点。
3. 支持输入修改指令。
4. 展示 proposed changes 和 warnings。
5. 用户可应用或拒绝。
6. 应用后走 draft sync 或后端 apply 接口。
7. 应用成功后刷新画布。

测试：

- 选中节点上下文传入正确。
- 预览状态展示。
- 拒绝不修改画布。
- 应用成功刷新 draft。

阶段 3 验收：

- 用户能用自然语言修改已有节点配置。
- 用户能预览变更。
- 未确认前不会修改 draft。
- 无效 patch 不会写入 draft。

## 6. 阶段 4：编译器抽离准备

目标：当 Dify 内闭环稳定后，把 PRD 编译器从 Dify 业务代码中逐步解耦。

当前阶段先不单独建新工程，但编码时要保留边界：

- `prd_compiler` 不直接依赖 Flask controller。
- IR、validator、package builder 保持纯函数或低副作用。
- Dify graph 生成放在 Dify adapter 层。
- Wiki context 获取和 LLM 调用通过接口封装，便于替换。

未来可抽离为：

```text
prd-compiler-service/
  core/
    ir/
    planner/
    validators/
    package_builder/
  adapters/
    dify/
    coze/
  providers/
    wiki_context/
    llm/
```

阶段 4 验收：

- PRD compiler 的单元测试不需要启动 Flask。
- Dify adapter 可以单独测试 IR -> Dify graph。
- package builder 可以单独测试 IR/package model -> zip。

## 7. 数据、权限和安全要求

开发时必须贯穿以下要求：

- 所有 app、workflow、draft、published workflow 操作都要校验 tenant/app 权限。
- 不允许任意 URL 拉取，MVP 只接入固定 Wiki Tree Context API。
- package 不导出密钥、凭证、完整原始 PRD、完整 LLM prompt。
- 日志默认只记元数据，不记敏感 PRD 正文。
- 外部 API timeout、LLM 失败、graph 校验失败都必须短路，不写 draft。
- 覆盖 draft 前必须有用户确认或 hash 保护。

## 8. 推荐测试矩阵

后端单元测试：

- Wiki context 标准化。
- IR parse 和校验。
- LLM 输出解析失败。
- IR -> Dify graph 编译。
- Graph validator。
- Draft sync 成功和失败。
- Package builder 严格目录结构。
- Graph patch 应用和校验。

后端 controller 测试：

- `/workflow-generate/from-prd` 成功。
- Wiki API 失败。
- LLM 失败。
- Graph 校验失败。
- Draft hash 冲突。
- `/package/export` 成功和权限失败。
- `/workflows/draft/nl-edit` dry run 和 apply。

前端测试：

- PRD 生成面板表单校验。
- 生成进度和错误展示。
- 覆盖确认。
- 成功后刷新 draft。
- package 下载按钮状态。
- 自然语言编辑预览、应用、拒绝。

人工验收：

1. 输入合法 Wiki workspace 和 doc id。
2. 生成 workflow draft。
3. 打开画布检查 Start、LLM、IfElse、Answer/End。
4. 修改一个节点配置。
5. 执行 draft debug。
6. 发布 workflow。
7. 使用 Dify 原有 API/WebApp/触发器运行 published workflow。
8. 下载 package。
9. 解压检查顶层只包含 `package.yaml`、`workflow.yaml`、`skills/`、`schemas/`、`data/`。
10. 检查 package 中没有 Dify DSL、graph、IR、validation、source metadata、完整 PRD 原文和密钥。

## 9. 风险和处理策略

| 风险 | 处理策略 |
|---|---|
| Dify graph shape 理解不准 | 先用现有 generator fixture 和 draft sync 跑通最小 graph，再扩展 |
| Wiki PRD tree 太大 | 裁剪 action/condition/outcome/rule，raw markdown 默认不完整送入 LLM |
| LLM 输出不稳定 | 强 JSON schema、IR validator、失败不写 draft |
| 覆盖用户 draft | draft hash + 覆盖确认 + 前端未保存变更检查 |
| package 格式漂移 | builder 测试断言顶层结构严格等于允许列表 |
| package 泄露敏感内容 | secret scanner + 禁止完整 PRD/prompt 入包 |
| 自然语言 patch 破坏 graph | patch 后统一走 graph validator，dry run 默认预览 |
| 第二阶段节点依赖复杂 | 每次只扩一种节点，补齐 IR/prompt/compiler/validator/package/test |

## 10. 优先级清单

P0：

- 确认最小 Dify graph fixture。
- 实现 Wiki context service。
- 实现 IR model 和 validator。
- 实现 mock LLM planner。
- 实现 IR -> Dify graph compiler。
- 实现 graph validator。
- 实现 `from-prd` API。
- 后端写入 draft。
- 前端 PRD 生成入口和刷新画布。

P1：

- 接入真实 Qwen/GPT 模型调用。
- 完善错误展示和 warnings。
- 增加 package builder。
- 增加 package export API。
- 前端 package 下载入口。

P2：

- 右侧自然语言 graph patch 助手。
- Knowledge Retrieval、HTTP Request、Code、Tool、Human Input、Trigger 节点扩展。
- 生成日志和更完整观测。

P3：

- PRD compiler 独立包/服务化。
- Coze adapter 或其他目标平台 adapter。

## 11. 建议第一周执行计划

第 1 天：

- 阅读 Dify generator、workflow draft sync、workflow graph type。
- 记录 Start、LLM、IfElse、Answer/End 最小合法 graph fixture。

第 2 天：

- 新建 `api/core/workflow/prd_compiler/`。
- 完成 IR model、IR validator、graph validator 初版。
- 写单元测试。

第 3 天：

- 完成 Wiki context service。
- 用 mock Wiki 响应跑通 PRD context 标准化。
- 完成 mock planner，先不用真实 LLM。

第 4 天：

- 完成 IR -> Dify graph compiler。
- 后端接入 draft sync。
- API 用 mock planner 跑通 draft 写入。

第 5 天：

- 前端增加 PRD 生成入口。
- 调通端到端：输入 Wiki doc id -> draft 画布刷新。
- 补齐失败态和覆盖确认。

第 6 天：

- 接入真实 Qwen/GPT。
- 调整 prompt 和 IR 校验。
- 准备 3 到 5 个 Wiki PRD 测试样例。

第 7 天：

- 完成第一轮人工验收。
- 记录 graph shape 问题、prompt 问题、package 字段缺口。
- 决定是否进入 package export 开发。

## 12. 交接给开发时的关键信息

必须遵守的边界：

- 不重建 Dify 画布。
- 不重建 Dify runtime。
- 不绕过 Dify 发布。
- 不把 Dify DSL 放进 package。
- 不把内部 IR/graph/validation 放进 package。
- 不长期保存 package artifact。
- 不把完整 PRD 原文和完整 LLM prompt 默认保存或导出。

最容易踩坑的点：

- Dify graph 的节点 data 字段必须完全匹配当前版本，否则画布或 draft sync 会失败。
- IfElse 的 variable selector 和分支 edge 很容易不完整。
- package 是业务自定义制品，不是 Dify published workflow 本身。
- 人工确认第一版只进入 IR/package，不进入 Dify graph；第二阶段 Human Input 支持后再映射。
- 自然语言编辑必须先预览，不能让 LLM 直接静默改 graph。
