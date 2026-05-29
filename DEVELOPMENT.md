# Development Guide

Local setup for contributing to or extending Codebase Explorer.

---

## Requirements

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ | 3.13 tested |
| git | any | must be in PATH |
| LM Studio | latest | [lmstudio.ai](https://lmstudio.ai) |
| Model | `google/gemma-4-e4b` | load in LM Studio before starting |

---

## First-time setup

```bash
git clone https://github.com/a5dur/codebase-explorer
cd codebase-explorer

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment config (optional — defaults work)
cp .env.example .env
```

---

## LM Studio configuration

1. Download and open [LM Studio](https://lmstudio.ai)
2. Search for and download `google/gemma-4-e4b`
3. Load the model
4. Go to **Local Server** tab → Start server
5. In model settings, set **Context Length to 8192 or higher** (default 4096 is too small for large repos)
6. Verify the server is running: `curl http://localhost:1234/v1/models`

---

## Running the app

```bash
source .venv/bin/activate
python main.py
```

App available at [http://localhost:8000](http://localhost:8000).

The server runs with `reload=True` by default — file changes restart it automatically.

---

## Environment variables

Defined in `.env` (copy from `.env.example`):

```bash
LM_STUDIO_URL=http://localhost:1234/v1/chat/completions
LM_STUDIO_MODEL=google/gemma-4-e4b
REPO_CACHE_DIR=/tmp/codebase_explorer
```

| Variable | Default | Description |
|---|---|---|
| `LM_STUDIO_URL` | `http://localhost:1234/v1/chat/completions` | LM Studio API endpoint |
| `LM_STUDIO_MODEL` | `google/gemma-4-e4b` | Must match model ID shown in LM Studio |
| `REPO_CACHE_DIR` | `/tmp/codebase_explorer` | Where repos are cloned on disk |

---

## Running tests

```bash
source .venv/bin/activate
pytest tests/ -v
```

Tests cover pure functions only (no LM Studio required): symbol extraction, file tree building, code search, tool call parsing, and the `/file` endpoint.

```
tests/test_main.py::test_health_lmstudio_down          PASSED
tests/test_main.py::test_build_file_tree_basic         PASSED
tests/test_main.py::test_extract_symbols_python_*      PASSED
tests/test_main.py::test_extract_symbols_js_*          PASSED
tests/test_main.py::test_search_code_*                 PASSED
tests/test_main.py::test_extract_tool_call_*           PASSED
tests/test_main.py::test_file_endpoint_*               PASSED
```

---

## Project structure

```
codebase-explorer/
├── main.py          # All backend logic (FastAPI app, indexer, agentic loop)
├── index.html       # Entire frontend — vanilla JS, no build step
├── requirements.txt # Python dependencies
├── .env.example     # Environment variable template
├── tests/
│   └── test_main.py # Unit tests for pure functions + endpoints
└── DEVELOPMENT.md   # This file
```

`main.py` is intentionally a single file. The key sections, in order:

| Section | What it does |
|---|---|
| App setup | FastAPI, CORS, env vars, `REPO_CACHE` dict |
| `build_file_tree` | Build indented directory string from file paths |
| `extract_symbols_*` | AST-based (Python) and regex-based (JS/TS) symbol extraction |
| `index_repo` | Walk clone, filter files, build file\_index + symbol\_map |
| `/clone` endpoint | git clone + index, store in `REPO_CACHE` |
| `search_code` / `get_file_content` / `lookup_symbol` | Tool implementations |
| `SYSTEM_PROMPT` | Gemma 4 instructions + tool call format |
| `extract_tool_call` | Parse `<tool_call>` XML blocks from model output |
| `call_lmstudio_sync` | Non-streaming LM Studio call (for tool loop) |
| `stream_lmstudio` | Streaming LM Studio call (for final answer) |
| `agentic_chat` | Main agentic loop generator |
| `/chat` endpoint | SSE wrapper around `agentic_chat` |
| `/file` endpoint | Return indexed file content for citation modal |

---

## How the agentic loop works

The loop in `agentic_chat` runs up to 5 iterations:

1. Build message list: system prompt → history → current question (with truncated file tree)
2. Call LM Studio (non-streaming)
3. Parse response for `<tool_call>` block
4. If tool call found: execute tool, append result to messages, repeat
5. If no tool call: call LM Studio again (streaming), pipe tokens as SSE events to client

The final answer is streamed token-by-token using LM Studio's streaming API. Tool call events (`{"type": "tool_call", ...}`) are emitted between loop iterations so the frontend can show live status.

---

## Troubleshooting

**400 Bad Request from LM Studio**

Context window too small. In LM Studio model settings, increase context length to 8192 or higher.

**Empty responses / no tokens streamed**

Gemma 4 with thinking mode enabled places the final answer in `content` and reasoning in `reasoning_content`. The backend handles this automatically. If responses are empty, check LM Studio logs for token limit errors.

**git clone fails**

- Public repos: no token needed, leave PAT field blank
- Private repos: generate a PAT at GitHub → Settings → Developer Settings → Personal Access Tokens → Classic, with `repo` scope
- The PAT is injected into the clone URL and never stored to disk

**Repo too large**

The indexer caps at 500 files (shallowest paths first). For very large repos, the most important files (root-level configs, top-level source dirs) are included; deep nested files may be excluded.

**LM Studio not detected on port 1234**

Check that the local server is started in LM Studio. The `/health` endpoint pings `http://localhost:1234/v1/models` — the banner in the UI reflects the result.

---

## Making changes

The backend (`main.py`) and frontend (`index.html`) can be edited directly — the server reloads on save. After changes:

```bash
pytest tests/ -v          # verify nothing broken
git add -p                # stage selectively
git commit -m "..."
git push
```
