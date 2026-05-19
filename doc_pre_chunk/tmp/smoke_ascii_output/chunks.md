<!-- chunk_id: smoke_ascii:000000; title_path: System Architecture -->

---

<!-- node_id: n_000000; type: heading -->

# System Architecture

<!-- node_id: n_000001; type: text -->

This document describes a multimodal RAG pre-processing pipeline.

<!-- node_id: n_000002; type: table; table_id: tbl_000000 -->

| Module | Responsibility |
| --- | --- |
| Parser | Parse Docx in order |

<!-- node_id: n_000003; type: heading -->

## Processing Flow

<!-- node_id: n_000004; type: text -->

The parser is followed by rule segmentation and model chunking.
