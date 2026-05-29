# Codebase Explorer
<img width="491" height="493" alt="image" src="https://github.com/user-attachments/assets/75267e45-34a5-4844-9b95-b66b5decc175" />

Ask natural language questions about any GitHub repository — public or private. Answers stream back with inline file citations. Everything runs locally. Nothing leaves your machine.

Powered by [Gemma 4](https://ai.google.dev/gemma) running in [LM Studio](https://lmstudio.ai).

![Python](https://img.shields.io/badge/python-3.11+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green) ![License](https://img.shields.io/badge/license-Apache%202.0-blue)

---

## Why local-first matters

In April 2023, Samsung engineers leaked confidential source code to a cloud AI service — three times within 20 days. In one incident, an engineer pasted proprietary semiconductor source code to ask for bug fixes. In another, internal meeting notes were submitted for summarisation. The data was transmitted to external servers and potentially used for model training. Samsung subsequently banned the use of generative AI tools on internal devices. [[Reuters]](https://www.reuters.com/technology/samsung-bans-use-generative-ai-tools-like-chatgpt-after-internal-data-leak-2023-05-02/) [[Bloomberg]](https://www.bloomberg.com/news/articles/2023-05-02/samsung-bans-chatgpt-and-other-generative-ai-use-by-staff-after-leak)

Samsung is not an outlier. Any time you paste code into a cloud AI interface, that code travels to an external server, may be logged, and may be used to improve the model. For proprietary codebases — internal tools, unreleased products, financial systems — that is an unacceptable risk.

**Codebase Explorer eliminates this risk entirely.** The model runs on your hardware. The code never leaves your machine. You get the same AI-assisted code understanding with zero exposure.

---

## What it does

Codebase Explorer is a local-first alternative to tools like Sourcegraph — no cloud, no API keys, no data sent anywhere. You point it at a repo, it indexes the code on your machine, and you chat with it using plain English.

Every answer is grounded in real code. The model doesn't hallucinate file paths — it searches first, reads the files, then responds. Click any `[file.py:42]` citation in the answer to open that exact line in a syntax-highlighted viewer.

---

## How it works

### 1. Clone & Index

When you submit a repo URL, the backend:

- Clones it locally with `git clone --depth=1` (fast, no history)
- Walks the file tree, skipping binaries, lockfiles, and build artifacts
- Reads up to 500 files (prioritising shallower paths)
- Extracts a symbol map: function and class names → `file:line` using Python's `ast` module for `.py` files and regex for `.js`/`.ts`

Everything is stored in memory. No database. Restart = re-clone.

### 2. Agentic Search Loop

When you ask a question, the backend runs an agentic loop — not a single prompt. Gemma 4 is given a set of tools and instructed to use them before answering:

```
┌─────────────────────────────────────────────┐
│  User question                              │
│       ↓                                     │
│  Gemma 4 decides: "I need to search first" │
│       ↓                                     │
│  <tool_call>                                │
│  {"tool": "search_code", "query": "auth"}  │
│  </tool_call>                               │
│       ↓                                     │
│  Backend executes search → returns results  │
│       ↓                                     │
│  Gemma 4 reads results, may call more tools │
│       ↓                                     │
│  Gemma 4 synthesises final answer           │
│  with real [file:line] citations            │
└─────────────────────────────────────────────┘
```

Available tools the model can call:

| Tool | What it does |
|---|---|
| `search_code(query)` | Keyword search across all indexed files |
| `get_file(path)` | Read the full content of a specific file |
| `list_symbols(name)` | Look up where a function or class is defined |
| `get_file_tree()` | Get the full directory structure |

The loop runs up to 5 iterations. Once Gemma stops calling tools, the final answer is streamed token-by-token to the browser.

### 3. Streaming Response

The answer streams via SSE (Server-Sent Events). As Gemma generates tokens, they appear in the UI in real time. Tool call indicators (`🔍 Searching...`, `📄 Reading...`) appear and disappear live so you can see exactly what the model is doing.

---

## Why Gemma 4

Gemma 4 (`google/gemma-4-e4b`) is central to what makes this work well:

**Instruction following.** The agentic loop depends entirely on the model reliably emitting structured `<tool_call>` blocks when it needs more information. Gemma 4 follows this format consistently across many types of questions, without needing fine-tuning or special scaffolding.

**Code understanding.** Gemma 4 was trained on a large corpus of code. It understands function signatures, import chains, class hierarchies, and framework patterns — which means it can reason about search results meaningfully, not just pattern-match keywords.

**Efficiency.** The `e4b` variant (4-bit quantized) runs on consumer hardware. On an M-series Mac with LM Studio, responses typically start within a few seconds, making local interactive use practical.

**Grounded reasoning.** Because we force the model to search before answering, Gemma 4's strength at reading and reasoning over retrieved context — rather than recalling from training — is what produces accurate, citation-backed answers rather than hallucinated summaries.

The combination of a capable instruction-following model + a lightweight agentic loop + local execution is what makes this viable as a privacy-first tool for private codebases.

---

## Prerequisites

- Python 3.11+
- `git` in PATH
- [LM Studio](https://lmstudio.ai) with:
  - `google/gemma-4-e4b` loaded
  - Local server enabled on port `1234`
  - Context length set to **8192+** (recommended)
- GitHub Personal Access Token with `repo` scope (for private repos only)

---

## Setup

```bash
git clone https://github.com/a5dur/codebase-explorer
cd codebase-explorer

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env   # optional — defaults work out of the box
python main.py
```

Open [http://localhost:8000](http://localhost:8000).

---

## Usage

1. **Clone & Index** — paste a repo URL and optional GitHub PAT, click the button
2. **Ask** — type a question, hit Enter or Send
3. **Cite** — click any `[file.py:42]` citation to view the file with the line highlighted

---

## Stack

| Layer | Tech |
|---|---|
| LLM | Gemma 4 (`google/gemma-4-e4b`) via LM Studio |
| Backend | Python 3.11 + FastAPI + uvicorn |
| Frontend | Single `index.html` — vanilla JS, no build step |
| Symbol extraction | Python `ast` module + regex for JS/TS |
| Code search | In-memory keyword search |
| Syntax highlighting | [highlight.js](https://highlightjs.org) (CDN) |

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `LM_STUDIO_URL` | `http://localhost:1234/v1/chat/completions` | LM Studio API endpoint |
| `LM_STUDIO_MODEL` | `google/gemma-4-e4b` | Model ID as shown in LM Studio |
| `REPO_CACHE_DIR` | `/tmp/codebase_explorer` | Where repos are cloned |

---

## Running tests

```bash
pytest tests/ -v
```

---

## Limitations

- No persistence — restart means re-clone
- Caps at 500 files per repo (shallowest paths prioritised)
- No semantic/vector search — keyword matching only
- Single repo at a time
- GitHub PAT stored in browser memory only, never persisted

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
