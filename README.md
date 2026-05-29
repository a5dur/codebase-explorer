# Codebase Explorer

Ask natural language questions about any private GitHub repository. Answers come with inline file citations. Everything runs locally — nothing leaves your machine.

Powered by [Gemma 4](https://ai.google.dev/gemma) running in [LM Studio](https://lmstudio.ai).

![Python](https://img.shields.io/badge/python-3.11+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green) ![License](https://img.shields.io/badge/license-MIT-blue)

---

## How it works

1. Paste a GitHub repo URL (private repos need a PAT)
2. The backend clones it locally, walks the file tree, and builds a symbol index
3. Ask a question — an agentic loop searches the codebase using tools (`search_code`, `get_file`, `list_symbols`)
4. Answer streams back token-by-token with clickable `[file:line]` citations

All inference runs on-device via LM Studio's local OpenAI-compatible API.

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
2. **Ask** — type a question about the codebase, hit Enter or Send
3. **Cite** — click any `[file.py:42]` citation to view the file with the relevant line highlighted

---

## Stack

| Layer | Tech |
|---|---|
| LLM | Gemma 4 (`google/gemma-4-e4b`) via LM Studio |
| Backend | Python 3.11 + FastAPI + uvicorn |
| Frontend | Single `index.html` — vanilla JS, no build step |
| Code search | Python `ast` (symbols) + in-memory keyword search |
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
- No semantic search — keyword matching only
- Single repo at a time
- GitHub PAT stored in browser memory only (never sent to any server except GitHub's clone URL)

---

## License

MIT
