# doc_pre_chunk

本项目是一个极简 Docling-first 多模态 RAG 文档预处理工具。

当前范围只保留 MVP 主链路：

1. 用 Docling 将 Docx 转为 Markdown，图片采用 referenced 文件形式。
2. 扫描 Markdown 图片引用。
3. 用 Qwen3-VL 为图片生成图表解析，dry-run 模式下生成占位解析。
4. 在图片后追加图表解析。
5. 按标题和长度规则切块。
6. 导出 Markdown / JSONL / report。

## 快速运行

```powershell
cd doc_pre_chunk
python -m pip install -e ".[docling]"
python -m doc_pre_chunk path\to\input.docx --output output --dry-run
```

真实调用 Qwen3-VL：

```powershell
python -m doc_pre_chunk path\to\input.docx --output output --vlm-endpoint http://localhost:8000/v1/chat/completions
```

## 主要输出

```text
output/
  docling/
    document.md
    artifacts/
  enriched.md
  chunks.jsonl
  chunks.md
  report.json
```

## 开发状态

第一版故意保持简单，不包含 Dify 导入、XML fallback、hybrid parser、GLM 精切或复杂校验。
