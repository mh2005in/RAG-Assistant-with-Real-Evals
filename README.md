# RAG Assistant with Real Evals - In Progress

A Retrieval-Augmented Generation (RAG) assistant built with a rigorous, evaluation-driven approach. This project explores the full RAG pipeline — from document ingestion through chunking, embedding, and retrieval — and measures each stage with real evaluations rather than vibes.

## Pipeline Overview

The system is organized into the following stages:

### 1. Document Extraction

Extract text, images, and structured data from source documents:

- **PyMuPDF** — text extraction
- **Tesseract OCR** — text and image extraction
- **Docling** — text, image, and tabular data extraction

### 2. Web Scraping

Collect content from the web:

- **Firecrawl**
- **Pyppeteer**
- **Beautiful Soup**

### 3. Chunking

Split extracted content into retrievable units. Strategies under evaluation:

- **Fixed** chunking
- **Semantic** chunking
- **Structural** chunking
- **Recursive** chunking
- **LLM-based** chunking

### 4. Embedding

Convert chunks into vector representations for similarity search via
**sentence-transformers**. The model (default `all-mpnet-base-v2`, 768-dim) and
the compute device (default `cpu`) are configurable. See the comparative
baseline in [`evals/results/embedding.json`](evals/results/embedding.json)
(regenerate with `uv run python -m evals.embedding_eval`).

### 5. Storage

Persist embeddings and metadata for retrieval:

- **PostgreSQL** with the **pgvector** extension

### 6. Validation

Validate structured inputs and outputs:

- **Pydantic** schema validation
- **LLM-based** validation

## Status

Early development — architecture and tooling are still being finalized.
