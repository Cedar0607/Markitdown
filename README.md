# doc_pre_chunk

Docx 文档预处理工具：

1. 用 Docling 将 Docx 转为 Markdown。
2. 将 Markdown 中的图片交给 Qwen3-VL 识别。
3. 把图片/图表解析结果插回图片原位置。
4. 基于 Markdown 标题层级生成 RAG 预分段结果。
5. 输出富化 Markdown、带分隔符的 prechunk Markdown、JSONL chunk 清单。

## 安装

```bash
python -m pip install -r requirements.txt
```

如果使用离线 Docling 模型，把模型路径写入 `config.json`：

```json
{
  "docling": {
    "artifacts_path": "/opt/models/docling_models"
  }
}
```

## 配置

编辑 `config.json`：

```json
{
  "vlm": {
    "endpoint": "http://localhost:8000/v1/chat/completions",
    "api_key": "your_api_key",
    "model": "Qwen3-VL",
    "timeout": 120,
    "retries": 2
  },
  "chunking": {
    "enabled": true,
    "divider": "<<<SECTION_DIVIDER>>>",
    "max_chars": 1800,
    "split_header_depth": 3,
    "inject_breadcrumb": true,
    "breadcrumb_prefix": "上下文",
    "output_jsonl": true
  }
}
```

`chunking` 说明：

- `divider`：写入 `.prechunk.md` 的自定义分段符，导入 Dify 时可指定它作为分隔符。
- `max_chars`：每个 chunk 的目标最大字符数。表格和代码块会尽量作为整体保留，避免被硬切断。
- `split_header_depth`：按 Markdown 标题切分的最大层级，默认处理 `#`、`##`、`###`。
- `inject_breadcrumb`：是否在 chunk 正文前插入标题路径，例如 `[上下文：系统设计 > 存储方案]`。
- `output_jsonl`：是否额外输出 JSONL，便于后续 API 导入或调试。

## 运行

处理单篇文档：

```bash
python doc_pre_chunk.py --input ./demo.docx --output ./result
```

处理目录下所有 `.docx`：

```bash
python doc_pre_chunk.py --input ./docs --output ./result
```

不调用 Qwen3-VL，仅插入占位解析：

```bash
python doc_pre_chunk.py --input ./docs --dry-run
```

临时关闭分段输出：

```bash
python doc_pre_chunk.py --input ./docs --no-chunk
```

临时调整 chunk 目标长度：

```bash
python doc_pre_chunk.py --input ./docs --chunk-max-chars 2400
```

未指定 `--output` 时，自动输出到：

```text
outputs/YYYYMMDD_HHMMSS/
```

输出目录结构示例：

```text
result/
  demo.md
  .chunks/
    demo.prechunk.md
    demo.chunks.jsonl
  .work/
    demo/
      document.md
      artifacts/
```

其中：

- `demo.md`：Docling 转换并回填图片/图表说明后的 Markdown。
- `.chunks/demo.prechunk.md`：适合 Dify 自定义分隔符导入的预分段 Markdown。
- `.chunks/demo.chunks.jsonl`：每行一个 chunk，包含 `chunk_id`、`source`、`title_path`、`breadcrumb`、`text`。
