"""Window 25 regression gates for the native Agno 3.1.1 migration."""

from importlib.metadata import version
import inspect
from pathlib import Path

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.google import Gemini
from agno.models.mistral import MistralChat
from agno.tools.mcp import MCPTools, SSEClientParams, StreamableHTTPClientParams

from app.utils.agno_utils import create_model


BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"


def test_exact_agno_runtime_and_native_agent_surface():
    assert version("agno") == "3.1.1"
    params = inspect.signature(Agent).parameters
    assert {"id", "db", "output_schema", "add_history_to_context"} <= set(params)
    assert "agent_id" not in params
    assert "storage" not in params
    assert "response_model" not in params
    assert "add_history_to_messages" not in params
    assert "message" not in inspect.signature(Agent.arun).parameters
    assert "input" in inspect.signature(Agent.arun).parameters


def test_google_vertex_and_mistral_use_native_311_models():
    google = create_model("GOOGLE", "dummy", "gemini-2.5-flash", max_tokens=32)
    vertex = create_model("GOOGLEVERTEX", "dummy", "gemini-2.5-flash", max_tokens=32)
    mistral = create_model("MISTRAL", "dummy", "mistral-small-latest", max_tokens=32)

    assert isinstance(google, Gemini)
    assert isinstance(vertex, Gemini)
    assert vertex.vertexai is True
    assert isinstance(mistral, MistralChat)


def test_mcp_230_native_parameter_surface():
    assert version("mcp") == "2.3.0"
    assert version("fastmcp") == "4.0.11"
    assert "server_params" in inspect.signature(MCPTools).parameters
    sse = SSEClientParams(url="https://example.invalid/sse", timeout=7.0, sse_read_timeout=30.0)
    http = StreamableHTTPClientParams(
        url="https://example.invalid/mcp",
        timeout=7.0,
        sse_read_timeout=30.0,
        terminate_on_close=True,
    )
    assert isinstance(sse.timeout, (int, float))
    assert isinstance(http.timeout, (int, float))


def test_native_postgresdb_session_run_api_is_available_but_not_chat_authority():
    assert hasattr(PostgresDb, "upsert_session")
    assert hasattr(PostgresDb, "get_session")
    assert hasattr(PostgresDb, "upsert_run")
    assert hasattr(PostgresDb, "get_run")

    chat_agent = (APP / "agents" / "chat_agent.py").read_text(encoding="utf-8")
    assert "PostgresDb(" not in chat_agent
    assert "agent_sessions" not in chat_agent
    assert "EncryptedPostgresAgentStorage" not in chat_agent
    assert "get_recent_context_messages" in chat_agent

    chat_model = (APP / "models" / "chat_history.py").read_text(encoding="utf-8")
    assert "message = Column(EncryptedText" in chat_model


def test_agno_1x_security_and_storage_shims_are_retired():
    assert not (APP / "utils" / "agno_eval_guard.py").exists()
    assert not (APP / "utils" / "agno_patches.py").exists()
    assert not (APP / "agents" / "encrypted_storage.py").exists()

    requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
    assert "agno==3.1.1" in requirements
    assert "mcp==2.3.0" in requirements
    assert "fastmcp==4.0.11" in requirements
    assert "mistralai==3.0.0" in requirements
    assert "google-genai==2.28.0" in requirements
