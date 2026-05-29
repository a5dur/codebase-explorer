import os
import json
import re
import ast
import subprocess
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

REPO_CACHE: dict = {}
REPO_CACHE_DIR = os.getenv("REPO_CACHE_DIR", "/tmp/codebase_explorer")
LM_STUDIO_URL = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1/chat/completions")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "google/gemma-4-e4b")

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "dist", "build",
    ".next", ".idea", ".vscode", ".mypy_cache", ".pytest_cache",
}
SKIP_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".lock", ".min.js",
    ".map", ".woff", ".woff2", ".ttf", ".eot", ".bin", ".exe",
    ".zip", ".tar", ".gz", ".pyc",
}
MAX_FILE_SIZE = 100 * 1024  # 100 KB
MAX_FILES = 500


@app.get("/")
def root():
    return HTMLResponse(open("index.html").read())


@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            await client.get("http://localhost:1234/v1/models")
        lmstudio_up = True
    except Exception:
        lmstudio_up = False
    return {"status": "ok", "lmstudio": lmstudio_up}


# ── File tree ─────────────────────────────────────────────────────────────────

def build_file_tree(files: list[str]) -> str:
    lines = []
    seen_dirs: set[str] = set()
    for path in sorted(files, key=lambda p: (p.count("/"), p)):
        parts = path.replace("\\", "/").split("/")
        for i in range(len(parts) - 1):
            dir_path = "/".join(parts[: i + 1])
            if dir_path not in seen_dirs:
                lines.append("  " * i + parts[i] + "/")
                seen_dirs.add(dir_path)
        lines.append("  " * (len(parts) - 1) + parts[-1])
    return "\n".join(lines)


# ── Symbol extraction ─────────────────────────────────────────────────────────

def extract_symbols_python(filepath: str, content: str) -> dict[str, str]:
    symbols: dict[str, str] = {}
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols[node.name] = f"{filepath}:{node.lineno}"
    except Exception:
        pass
    return symbols


def extract_symbols_js(filepath: str, content: str) -> dict[str, str]:
    patterns = [
        r"(?:export\s+(?:default\s+)?function\s+)(\w+)",
        r"(?:function\s+)(\w+)\s*\(",
        r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(",
        r"class\s+(\w+)",
    ]
    symbols: dict[str, str] = {}
    for i, line in enumerate(content.splitlines(), 1):
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                name = match.group(1)
                if name not in symbols:
                    symbols[name] = f"{filepath}:{i}"
                break
    return symbols


# ── Indexer ───────────────────────────────────────────────────────────────────

def index_repo(clone_path: str) -> tuple[dict, dict, str]:
    all_files: list[str] = []

    for root, dirs, files in os.walk(clone_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext in SKIP_EXTS:
                continue
            abs_path = os.path.join(root, fname)
            try:
                if os.path.getsize(abs_path) > MAX_FILE_SIZE:
                    continue
            except OSError:
                continue
            rel_path = os.path.relpath(abs_path, clone_path)
            all_files.append(rel_path)

    all_files.sort(key=lambda p: (p.count(os.sep), p))
    all_files = all_files[:MAX_FILES]

    file_index: dict[str, str] = {}
    symbol_map: dict[str, str] = {}

    for rel_path in all_files:
        abs_path = os.path.join(clone_path, rel_path)
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue
        file_index[rel_path] = content
        ext = os.path.splitext(rel_path)[1].lower()
        if ext == ".py":
            symbol_map.update(extract_symbols_python(rel_path, content))
        elif ext in {".js", ".ts", ".jsx", ".tsx"}:
            symbol_map.update(extract_symbols_js(rel_path, content))

    return file_index, symbol_map, build_file_tree(list(file_index.keys()))


# ── Clone endpoint ────────────────────────────────────────────────────────────

class CloneRequest(BaseModel):
    repo_url: str
    github_token: str = ""


@app.post("/clone")
async def clone_repo(req: CloneRequest):
    repo_name = req.repo_url.rstrip("/").split("/")[-1].replace(".git", "")

    if req.github_token:
        url_with_token = req.repo_url.replace("https://", f"https://{req.github_token}@")
    else:
        url_with_token = req.repo_url

    clone_path = os.path.join(REPO_CACHE_DIR, repo_name)
    os.makedirs(REPO_CACHE_DIR, exist_ok=True)

    if os.path.exists(clone_path):
        subprocess.run(["rm", "-rf", clone_path], check=True)

    result = subprocess.run(
        ["git", "clone", "--depth=1", url_with_token, clone_path],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        return {"status": "error", "message": f"git clone failed: {result.stderr}"}

    file_index, symbol_map, file_tree = index_repo(clone_path)
    file_count = len(file_index)
    truncated = file_count == MAX_FILES

    REPO_CACHE[repo_name] = {
        "file_index": file_index,
        "symbol_map": symbol_map,
        "file_tree": file_tree,
        "clone_path": clone_path,
    }

    return {
        "status": "ok",
        "repo_name": repo_name,
        "file_count": file_count,
        "symbol_count": len(symbol_map),
        "file_tree": file_tree,
        "truncated": truncated,
    }


# ── Search tools ──────────────────────────────────────────────────────────────

def search_code(repo_name: str, query: str, max_results: int = 5) -> list[dict]:
    results: list[dict] = []
    file_index = REPO_CACHE[repo_name]["file_index"]
    query_lower = query.lower()

    for filepath, content in file_index.items():
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if query_lower in line.lower():
                results.append({
                    "file": filepath,
                    "line_number": i + 1,
                    "line_content": line.strip(),
                    "context": "\n".join(lines[max(0, i - 2): i + 3]),
                })
                if len(results) >= max_results:
                    return results
    return results


def get_file_content(repo_name: str, path: str) -> str | None:
    return REPO_CACHE[repo_name]["file_index"].get(path)


def lookup_symbol(repo_name: str, name: str) -> dict[str, str]:
    symbol_map = REPO_CACHE[repo_name]["symbol_map"]
    name_lower = name.lower()
    return {sym: loc for sym, loc in symbol_map.items() if name_lower in sym.lower()}


# ── Agentic loop ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert software engineer helping a user understand a codebase.

You have access to the following tools. Use them to find relevant code before answering.

TOOLS:
1. search_code(query) — Search all files for a string or keyword. Returns matching lines with file paths and line numbers.
2. get_file(path) — Read the full content of a specific file.
3. list_symbols(name) — Look up where a function/class is defined.
4. get_file_tree() — Get the full directory structure.

RULES:
- ALWAYS use tools to find relevant code before answering. Do not guess.
- When you reference code in your answer, ALWAYS include a citation in this exact format: [filepath:line_number]
- Citations must be real file paths from the codebase, not made up.
- After using 1-3 tool calls, synthesize your findings into a clear, concise answer.
- If you cannot find something after 3 searches, say so honestly.

TOOL CALL FORMAT (use exactly this — no variation):
<tool_call>
{"tool": "search_code", "query": "authentication"}
</tool_call>

Other examples:
<tool_call>
{"tool": "get_file", "path": "src/auth.py"}
</tool_call>
<tool_call>
{"tool": "list_symbols", "name": "AuthMiddleware"}
</tool_call>
<tool_call>
{"tool": "get_file_tree"}
</tool_call>"""


def extract_tool_call(content: str) -> dict | None:
    match = re.search(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", content, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


async def call_lmstudio_sync(messages: list[dict]) -> str:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            LM_STUDIO_URL,
            json={
                "model": LM_STUDIO_MODEL,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 1500,
                "stream": False,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


async def stream_lmstudio(messages: list[dict]):
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            LM_STUDIO_URL,
            json={
                "model": LM_STUDIO_MODEL,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 1500,
                "stream": True,
            },
        ) as r:
            async for line in r.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                try:
                    chunk = json.loads(line[6:])
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


async def agentic_chat(repo_name: str, question: str, history: list[dict]):
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    for turn in history:
        messages.append(turn)

    file_tree = REPO_CACHE[repo_name]["file_tree"]
    messages.append({
        "role": "user",
        "content": f"FILE TREE:\n{file_tree}\n\nQUESTION: {question}",
    })

    for _ in range(5):
        try:
            content = await call_lmstudio_sync(messages)
        except httpx.TimeoutException:
            yield f"data: {json.dumps({'type': 'error', 'message': 'LM Studio timed out'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        tool_call = extract_tool_call(content)

        if tool_call:
            tool_name = tool_call.get("tool", "")
            query_hint = (
                tool_call.get("query")
                or tool_call.get("path")
                or tool_call.get("name")
                or ""
            )
            yield f"data: {json.dumps({'type': 'tool_call', 'tool': tool_name, 'query': query_hint})}\n\n"

            if tool_name == "search_code":
                result = search_code(repo_name, tool_call.get("query", ""))
            elif tool_name == "get_file":
                result = get_file_content(repo_name, tool_call.get("path", "")) or "File not found in index"
            elif tool_name == "list_symbols":
                result = lookup_symbol(repo_name, tool_call.get("name", ""))
            elif tool_name == "get_file_tree":
                result = REPO_CACHE[repo_name]["file_tree"]
            else:
                result = f"Unknown tool: {tool_name}"

            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": f"TOOL RESULT:\n{json.dumps(result, indent=2)}"})

        else:
            try:
                async for delta in stream_lmstudio(messages):
                    yield f"data: {json.dumps({'type': 'token', 'content': delta})}\n\n"
            except httpx.TimeoutException:
                yield f"data: {json.dumps({'type': 'error', 'message': 'LM Studio timed out during streaming'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

    yield f"data: {json.dumps({'type': 'error', 'message': 'Reached max tool call iterations'})}\n\n"
    yield f"data: {json.dumps({'type': 'done'})}\n\n"


# ── Chat endpoint ─────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    repo_name: str
    question: str
    history: list[dict] = []


@app.post("/chat")
async def chat(req: ChatRequest):
    if req.repo_name not in REPO_CACHE:
        async def err():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Repo not indexed. Clone it first.'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")

    return StreamingResponse(
        agentic_chat(req.repo_name, req.question, req.history),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── File endpoint ─────────────────────────────────────────────────────────────

EXT_TO_LANG = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "javascript", ".tsx": "typescript", ".go": "go",
    ".rs": "rust", ".java": "java", ".cpp": "cpp", ".c": "c",
    ".h": "c", ".cs": "csharp", ".rb": "ruby", ".php": "php",
    ".html": "html", ".css": "css", ".scss": "css",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".md": "markdown", ".sh": "bash", ".bash": "bash",
    ".sql": "sql", ".xml": "xml", ".toml": "toml",
}


@app.get("/file")
async def get_file(repo_name: str, path: str):
    if repo_name not in REPO_CACHE:
        raise HTTPException(status_code=404, detail=f"Repo '{repo_name}' not indexed")
    content = get_file_content(repo_name, path)
    if content is None:
        raise HTTPException(status_code=404, detail=f"File '{path}' not found in index")
    ext = os.path.splitext(path)[1].lower()
    return {"path": path, "content": content, "language": EXT_TO_LANG.get(ext, "plaintext")}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
