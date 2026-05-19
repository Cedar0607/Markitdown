# 多模态 RAG 自动化数据清洗智能体开发设计方案

日期：2026-05-19

## 1. 项目目标

本项目用于构建一个本地化的 Multimodal Ingestion Agent，将本地 Docx 文档自动解析、清洗、图文语义重构，并导出适合导入 Dify 知识库的高质量 Markdown 分块。

核心目标：

- 保持 Docx 原始内容的阅读顺序，避免图文、表格顺序错位。
- 使用 Qwen3-VL 对图片、图表、截图、架构图进行语义补全。
- 使用 GLM-4.7 对融合后的图文表混合内容进行 Markdown 结构化转换与语义切分。
- 输出可校验、可追踪、可重跑的 chunk 数据。
- 将 LLM 作为语义增强组件，而不是不可控的一次性清洗黑盒。

## 2. 总体架构

推荐采用“确定性解析 + 多模态补语义 + 规则粗切 + LLM 精切 + 程序校验”的本地流水线。

```text
Docx 文档
  -> 顺序 XML / run 级解析
  -> 生成 typed nodes
  -> 图片抽取与缓存
  -> Qwen3-VL 图片语义解析
  -> 节点级语义回填
  -> 规则粗切分
  -> GLM-4.7 Markdown 重构与语义精切
  -> JSON Schema 校验
  -> Markdown / JSONL 导出
  -> Dify 知识库导入
```

## 3. 核心设计原则

1. 原文优先：专有名词、技术参数、指标、步骤顺序必须忠实保留。
2. 顺序优先：解析阶段必须保留文档中的图、文、表原始出现顺序。
3. 可追踪：每个节点、图片、表格、chunk 都应有稳定 ID 与来源位置。
4. 可重试：VLM 解析、LLM 切分、JSON 校验失败后均支持局部重跑。
5. 可验证：导出前必须做 schema、长度、连续性、覆盖率等检查。
6. 渐进落地：先覆盖正文段落、表格、内嵌图片，再扩展页眉页脚、文本框、脚注、浮动图等复杂对象。

## 4. 模块设计

### 4.1 Docx 顺序解析模块

职责：

- 打开 Docx 文件。
- 遍历底层 XML body。
- 按原始顺序生成统一的 typed nodes。
- 支持段落、表格、图片、标题、列表、分页符等基础结构识别。

关键要求：

- 不能只按 paragraph 级别判断是否包含图片。
- 段落内需进一步遍历 run，避免“文字 + 图片 + 文字”被错误压缩成单个图片节点。
- 表格内也可能包含段落、图片、列表，MVP 可先将表格整体转为 Markdown / HTML，生产版再递归解析单元格内容。

节点示例：

```json
{
  "node_id": "n_000012",
  "type": "text",
  "source": {
    "file": "example.docx",
    "block_index": 12,
    "run_index": 3
  },
  "style": {
    "paragraph_style": "Heading 2",
    "is_list": false
  },
  "content": "本文介绍系统整体架构。"
}
```

图片节点示例：

```json
{
  "node_id": "n_000023",
  "type": "image",
  "image_id": "img_000004",
  "content": "assets/images/img_000004.png",
  "source": {
    "file": "example.docx",
    "block_index": 18,
    "run_index": 1
  }
}
```

### 4.2 图片抽取与缓存模块

职责：

- 从 Docx relationship 中解析图片资源。
- 保存为本地文件。
- 计算图片 hash，避免重复解析。
- 建立 `image_id -> image_path -> vlm_result` 映射。

建议目录：

```text
doc_pre_chunk/
  assets/
    images/
  cache/
    image_vlm_results.jsonl
  output/
```

缓存字段：

```json
{
  "image_id": "img_000004",
  "image_hash": "sha256:...",
  "image_path": "assets/images/img_000004.png",
  "model": "Qwen3-VL",
  "prompt_version": "vlm_chart_parse_v1",
  "status": "success",
  "content": "...",
  "confidence": "medium",
  "uncertain_points": []
}
```

### 4.3 Qwen3-VL 图像语义重构模块

职责：

- 异步批量处理图片节点。
- 根据图片类型生成图表、流程、架构、截图、实物等语义描述。
- 将图片解析结果回填到原 typed nodes 中。

工程要求：

- 支持并发数配置，避免本地显存打满。
- 支持超时、失败重试、失败占位。
- 对低置信度结果保留 `uncertain_points`，不要让模型强行编造。
- 数值型图表需要尽量保留 OCR 原文和可见数据，避免视觉估算冒充精确值。

回填后的节点建议：

```json
{
  "node_id": "n_000023",
  "type": "image_description",
  "image_id": "img_000004",
  "content": "> 💡 **[图表解析]**\n系统由采集层、处理层、检索层和应用层组成..."
}
```

### 4.4 语义融合模块

职责：

- 将 text、table、image_description 按节点顺序拼接为全局富语义文本流。
- 保留 node_id、image_id、table_id 等引用信息。
- 为后续粗切和 GLM 精切提供稳定输入。

建议中间格式：

```markdown
<!-- node_id: n_000012; type: text -->
本文介绍系统整体架构。

<!-- node_id: n_000023; type: image_description; image_id: img_000004 -->
> 💡 **[图表解析]**
> 系统由采集层、处理层、检索层和应用层组成...
```

### 4.5 规则粗切模块

职责：

- 在调用 GLM-4.7 前进行确定性的粗粒度分段。
- 降低一次性长上下文输出 JSON 截断、字段缺失、结构坍塌的风险。

推荐粗切规则：

- 一级标题可作为强边界。
- 二级标题通常作为边界。
- 表格、代码块、图片解析结果不得从中间切开。
- 单个 batch 建议控制在 20k 至 30k 中文字以内，具体阈值按本地模型吞吐实测调整。
- 若一个章节过长，可按三级标题或自然段进行进一步分段。

粗切输出示例：

```json
{
  "batch_id": "batch_0003",
  "title_hint": "第二章 > 系统架构",
  "node_ids": ["n_000120", "n_000121", "n_000122"],
  "mixed_markdown": "..."
}
```

### 4.6 GLM-4.7 Markdown 重构与语义精切模块

职责：

- 将粗切 batch 转换为规范 Markdown。
- 根据语义完整性生成高质量 chunks。
- 补全 `title_path`。
- 保留图表解析内容和关键上下文。

说明：

- 当前已有 GLM-4.7 prompt 方案可继续沿用，本设计文档不再改写 prompt。
- 建议开启 Thinking 能力用于语义边界判断。
- 建议使用 JSON object / schema 风格的结构化输出。
- 仍需对输出做程序级校验，不能完全信任模型格式。

目标输出结构：

```json
{
  "chunks": [
    {
      "chunk_index": 0,
      "title_path": "第一章 > 核心架构 > 信号检测",
      "markdown_content": "# 信号检测\n本文档主要阐述...",
      "split_reason": "初始化介绍完毕，后续转入具体参数配置，语义发生切换。"
    }
  ]
}
```

### 4.7 校验与修复模块

职责：

- 校验 GLM 输出是否符合结构要求。
- 检查 chunk 内容是否完整、稳定、可导入。
- 对失败 batch 触发重试或降级处理。

建议校验项：

- JSON 可解析。
- `chunks` 为数组且非空。
- `chunk_index` 连续。
- `title_path` 非空。
- `markdown_content` 非空。
- 单个 chunk 长度在预期范围内。
- 表格没有被截断。
- 代码块围栏成对出现。
- 图片解析块没有丢失。
- 关键 node_id 覆盖率达到阈值。

降级策略：

- 第一次失败：使用相同输入重试。
- 第二次失败：降低 batch 大小后重试。
- 第三次失败：跳过 GLM 精切，按规则粗切结果直接导出，并标记 `needs_review: true`。

### 4.8 导出模块

推荐同时导出两类产物：

1. 面向人工检查的 Markdown 文件。
2. 面向 Dify 导入或后续脚本处理的 JSONL 文件。

JSONL chunk 示例：

```json
{
  "chunk_id": "doc_sha256:000012",
  "source_file": "example.docx",
  "title_path": "第一章 > 核心架构 > 信号检测",
  "markdown_content": "...",
  "image_refs": ["img_000004"],
  "table_refs": ["tbl_000002"],
  "node_refs": ["n_000120", "n_000121"],
  "token_count": 812,
  "content_hash": "sha256:...",
  "split_reason": "...",
  "needs_review": false
}
```

## 5. 推荐项目结构

```text
doc_pre_chunk/
  README.md
  multimodal_ingestion_agent_design.md
  configs/
    pipeline.yaml
    prompts/
      vlm_image_parse.txt
      glm_chunking.txt
  src/
    doc_pre_chunk/
      __init__.py
      parser/
        docx_ordered_parser.py
        table_converter.py
        image_extractor.py
      vlm/
        qwen3_vl_client.py
        image_pipeline.py
      fusion/
        node_fusion.py
      chunking/
        rule_segmenter.py
        glm_chunker.py
        schema.py
      validation/
        chunk_validator.py
      export/
        markdown_exporter.py
        jsonl_exporter.py
      pipeline.py
  assets/
    images/
  cache/
  output/
  tests/
    fixtures/
    test_docx_ordered_parser.py
    test_rule_segmenter.py
    test_chunk_validator.py
```

## 6. MVP 范围

第一阶段建议只实现可闭环能力：

- 支持 `.docx` 正文段落顺序解析。
- 支持段落内 run 级图片识别。
- 支持普通表格转换为 Markdown。
- 支持图片抽取、hash 缓存、Qwen3-VL 解析。
- 支持节点顺序融合。
- 支持规则粗切。
- 支持 GLM-4.7 输出 JSON chunks。
- 支持 JSON Schema 校验。
- 支持导出 Markdown 与 JSONL。

MVP 暂不强制支持：

- 页眉页脚。
- 脚注尾注。
- 批注。
- 文本框。
- SmartArt。
- 复杂浮动图定位。
- 嵌套表格的完美还原。

## 7. 开发里程碑

### Milestone 1：Docx 顺序解析闭环

交付内容：

- `parse_docx_in_order(docx_path) -> list[Node]`
- 段落、标题、表格、图片节点基础识别。
- 图片保存到 `assets/images/`。
- 输出中间 `nodes.jsonl`。

验收标准：

- 图、文、表顺序与 Word 阅读顺序基本一致。
- 段落内“文字 + 图片 + 文字”不会丢失文字。
- 表格不会被拆散到多个不连续节点。

### Milestone 2：VLM 图片解析与缓存

交付内容：

- Qwen3-VL 本地推理 API 客户端。
- 异步图片处理队列。
- 图片 hash 缓存。
- 失败重试与失败占位。

验收标准：

- 重复运行时已解析图片不重复调用模型。
- 单张图片失败不影响整篇文档处理。
- 输出可回填到原节点位置。

### Milestone 3：融合与规则粗切

交付内容：

- typed nodes 到 mixed markdown 的融合器。
- 基于标题、长度、表格边界、图片边界的粗切器。
- 输出 `batches.jsonl`。

验收标准：

- 每个 batch 语义上尽量完整。
- 表格和图片解析块不会被截断。
- batch 长度可配置。

### Milestone 4：GLM 精切与结构化输出

交付内容：

- GLM-4.7 本地推理 API 客户端。
- prompt 配置加载。
- JSON 输出解析。
- chunk schema 定义。

验收标准：

- 输出 chunks 可解析。
- `title_path`、`markdown_content`、`split_reason` 字段完整。
- 图表解析内容保留在相关上下文中。

### Milestone 5：校验、导出与 Dify 准备

交付内容：

- chunk validator。
- Markdown 导出。
- JSONL 导出。
- 处理报告 `report.json`。

验收标准：

- 导出文件可稳定重跑。
- 异常 batch 有明确错误信息。
- chunk 粒度适合导入 Dify。

## 8. 关键配置项

```yaml
pipeline:
  max_batch_chars: 30000
  target_chunk_chars_min: 500
  target_chunk_chars_max: 1200
  preserve_node_comments: true

vlm:
  model: Qwen3-VL
  concurrency: 2
  timeout_seconds: 120
  max_retries: 2
  cache_enabled: true

glm:
  model: GLM-4.7
  enable_thinking: true
  response_format: json_object
  timeout_seconds: 300
  max_retries: 2

export:
  formats:
    - markdown
    - jsonl
  include_metadata: true
```

## 9. 风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| Docx 复杂对象导致顺序错乱 | 检索上下文错误 | MVP 明确支持边界，逐步扩展文本框、页眉页脚、浮动图 |
| VLM 图表数值幻觉 | 错误知识入库 | 保留置信度与不确定点，关键图表人工抽检 |
| GLM 长输出 JSON 截断 | 导出失败 | 规则粗切、schema 校验、失败重试、缩小 batch |
| LLM 改写过度 | 原文事实被污染 | 校验关键术语覆盖率，保留 node_refs，必要时人工抽样 |
| Dify chunk 粒度不合适 | 召回质量下降 | 通过 chunk 长度、标题路径、metadata 调优 |
| 本地推理吞吐不足 | 处理耗时过长 | 图片缓存、批处理、并发限制、断点续跑 |

## 10. 测试策略

建议准备以下测试文档：

- 纯文本长文档。
- 含标题层级的技术文档。
- 段落中插入图片的文档。
- 表格前后有解释文字的文档。
- 表格内含图片的文档。
- 架构图、流程图、折线图、截图混合文档。
- 超长章节文档。

核心测试用例：

- 顺序解析结果是否符合预期。
- 图片是否保存并建立 image_id。
- VLM 失败是否能降级。
- 表格是否完整保留。
- GLM 输出 JSON 是否通过 schema。
- chunk 是否保留图表解析。
- 导出 JSONL 是否可被下游读取。

## 11. 落地结论

该方案具备明确可落地性。工程上不建议做成“LLM 一次性全自动清洗器”，而应做成可观测、可重试、可校验的本地数据处理流水线。

推荐优先完成 MVP，验证 10 至 20 份真实 Docx 文档的解析顺序、图片解析质量、chunk 粒度和 Dify 召回效果，再进入生产增强阶段。
