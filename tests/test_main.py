import pytest
from fastapi.testclient import TestClient


# ── Health ────────────────────────────────────────────────────────────────────

def test_health_lmstudio_down():
    from main import app
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "lmstudio" in data
    assert isinstance(data["lmstudio"], bool)


# ── build_file_tree ───────────────────────────────────────────────────────────

def test_build_file_tree_basic():
    from main import build_file_tree
    files = ["README.md", "src/main.py", "src/utils.py", "tests/test_main.py"]
    tree = build_file_tree(files)
    assert "README.md" in tree
    assert "src/" in tree
    assert "main.py" in tree
    assert "tests/" in tree


def test_build_file_tree_depth_indent():
    from main import build_file_tree
    files = ["a/b/c.py"]
    tree = build_file_tree(files)
    lines = tree.split("\n")
    c_line = [l for l in lines if "c.py" in l][0]
    a_line = [l for l in lines if "a/" in l][0]
    assert len(c_line) - len(c_line.lstrip()) > len(a_line) - len(a_line.lstrip())


# ── Symbol extraction ─────────────────────────────────────────────────────────

def test_extract_symbols_python_finds_functions_and_classes():
    from main import extract_symbols_python
    content = """
class AuthMiddleware:
    def verify(self, token):
        pass

def login(username, password):
    return True

async def logout():
    pass
"""
    symbols = extract_symbols_python("src/auth.py", content)
    assert "AuthMiddleware" in symbols
    assert symbols["AuthMiddleware"] == "src/auth.py:2"
    assert "login" in symbols
    assert "logout" in symbols
    assert "verify" in symbols


def test_extract_symbols_python_invalid_syntax():
    from main import extract_symbols_python
    result = extract_symbols_python("bad.py", "def :()")
    assert result == {}


def test_extract_symbols_js_finds_functions_and_classes():
    from main import extract_symbols_js
    content = """function handleAuth(req, res) {}
const getUser = async (id) => {};
class TokenService {}
export default function renderPage() {}
"""
    symbols = extract_symbols_js("src/auth.js", content)
    assert "handleAuth" in symbols
    assert "getUser" in symbols
    assert "TokenService" in symbols
    assert "renderPage" in symbols


# ── Search tools ──────────────────────────────────────────────────────────────

def _setup_test_repo():
    import main
    main.REPO_CACHE["testrepo"] = {
        "file_index": {
            "src/auth.py": "def login():\n    token = jwt.encode(payload)\n    return token\n",
            "src/main.py": "from auth import login\napp = FastAPI()\n",
        },
        "symbol_map": {
            "AuthMiddleware": "src/auth.py:5",
            "login": "src/auth.py:12",
        },
        "file_tree": "",
        "clone_path": "/tmp/test",
    }


def test_search_code_finds_matches():
    import main
    _setup_test_repo()
    results = main.search_code("testrepo", "token")
    assert len(results) > 0
    assert results[0]["file"] == "src/auth.py"
    assert results[0]["line_number"] == 2
    assert "token" in results[0]["line_content"].lower()
    assert "context" in results[0]


def test_search_code_case_insensitive():
    import main
    _setup_test_repo()
    results = main.search_code("testrepo", "LOGIN")
    assert any(r["file"] == "src/auth.py" for r in results)


def test_search_code_max_results():
    import main
    _setup_test_repo()
    main.REPO_CACHE["testrepo"]["file_index"]["src/big.py"] = "\n".join(
        [f"var_a_{i} = {i}" for i in range(20)]
    )
    results = main.search_code("testrepo", "var_a", max_results=5)
    assert len(results) <= 5


def test_lookup_symbol_partial_match():
    import main
    _setup_test_repo()
    result = main.lookup_symbol("testrepo", "auth")
    assert "AuthMiddleware" in result


def test_get_file_content_found():
    import main
    _setup_test_repo()
    content = main.get_file_content("testrepo", "src/auth.py")
    assert content is not None
    assert "login" in content


def test_get_file_content_not_found():
    import main
    _setup_test_repo()
    content = main.get_file_content("testrepo", "nonexistent.py")
    assert content is None


# ── extract_tool_call ─────────────────────────────────────────────────────────

def test_extract_tool_call_valid():
    from main import extract_tool_call
    content = 'Let me search.\n<tool_call>\n{"tool": "search_code", "query": "JWT"}\n</tool_call>\n'
    result = extract_tool_call(content)
    assert result is not None
    assert result["tool"] == "search_code"
    assert result["query"] == "JWT"


def test_extract_tool_call_none_when_absent():
    from main import extract_tool_call
    result = extract_tool_call("Here is my answer without any tool call.")
    assert result is None


def test_extract_tool_call_malformed_json():
    from main import extract_tool_call
    result = extract_tool_call("<tool_call>\nnot valid json\n</tool_call>")
    assert result is None


# ── /file endpoint ────────────────────────────────────────────────────────────

def test_file_endpoint_found():
    import main
    main.REPO_CACHE["testrepo"] = {
        "file_index": {"src/auth.py": "def login(): pass"},
        "symbol_map": {},
        "file_tree": "",
        "clone_path": "/tmp/test",
    }
    client = TestClient(main.app)
    response = client.get("/file?repo_name=testrepo&path=src/auth.py")
    assert response.status_code == 200
    data = response.json()
    assert data["language"] == "python"
    assert "login" in data["content"]


def test_file_endpoint_not_found():
    import main
    client = TestClient(main.app)
    response = client.get("/file?repo_name=testrepo&path=does_not_exist.py")
    assert response.status_code == 404
