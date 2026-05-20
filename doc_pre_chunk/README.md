# doc_pre_chunk

单文件 Docx 预处理工具：

1. 用 Docling 将 Docx 转为 Markdown。
2. 将 Markdown 中的图片交给 Qwen3-VL 识别。
3. 把图片解析结果插回图片原位置。
4. 输出处理后的 Markdown。

不做 chunk 切分、不做 JSONL、不做 Dify 导入。

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
  }
}
```

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

未指定 `--output` 时，自动输出到：

```text
outputs/YYYYMMDD_HHMMSS/
```

输出目录中会包含处理后的 Markdown，以及用于保存 Docling 图片文件的 `.work/` 目录。
