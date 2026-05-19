在 Linux 上不要保留 Windows 路径，建议放成类似：

/opt/models/docling_models
# 或
/home/your_user/models/docling_models
然后设置 Docling 的模型路径：

export DOCLING_ARTIFACTS_PATH=/opt/models/docling_models
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
官方文档里，Docling 支持用 DOCLING_ARTIFACTS_PATH 指向本地预下载模型，也支持 CLI 的 --artifacts-path。参考：
Docling advanced options
。

推荐测试步骤：

cd /path/to/doc_pre_chunk

python3 -m venv .venv
source .venv/bin/activate

pip install -U pip
pip install -e ".[docling]"

export DOCLING_ARTIFACTS_PATH=/opt/models/docling_models
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

python -m doc_pre_chunk /path/to/test.docx --output output --dry-run
如果公司内网不能访问 PyPI，你还需要提前准备 docling 及其依赖的 wheel 包，在内网用：

pip install --no-index --find-links /path/to/wheelhouse -e ".[docling]"
跑通后重点看这些文件：

output/
  docling/
    document.md
    artifacts/
  enriched.md
  chunks.md
  chunks.jsonl
  report.json
注意几点：

你的 D:\docling\docling_models 传到 Linux 后，目录结构要保持原样，不要只拷里面某几个权重文件。
对纯 DOCX 转 Markdown 来说，Docling 可能不一定需要所有 PDF/OCR/layout 模型，但设置本地 artifacts path 更稳，避免运行时尝试联网下载。
当前工程代码还没有显式参数 --docling-artifacts-path，所以先用环境变量 DOCLING_ARTIFACTS_PATH。
先用 --dry-run 测 Docling 转换、图片 referenced 输出、chunk 导出；确认这条链路正常后，再接 Qwen3-VL：
python -m doc_pre_chunk /path/to/test.docx \
  --output output \
  --vlm-endpoint http://your-qwen3-vl-server/v1/chat/completions
所以答案是：是的，可以开始测试。只要 Linux 环境里 docling 安装成功、模型目录路径正确、环境变量设置好，当前工程就能先跑 dry-run。
