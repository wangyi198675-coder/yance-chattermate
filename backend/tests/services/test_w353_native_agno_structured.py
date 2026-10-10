"""Native Agno Reply Brain output schema, scoped to W353 contract."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest

from app.services import yance_reply_runtime as reply


@pytest.mark.asyncio
async def test_w353_native_agno_uses_structured_schema_and_canonical_context(monkeypatch):
    calls = []
    monkeypatch.setattr(reply, "check_inbound", lambda *args, **kwargs: calls.append("inbound"))
    monkeypatch.setattr(reply, "check_output", lambda text, **kwargs: (text, None))
    response = reply._AgnoReplyEnvelope(
        state="ready",
        why="Natural answer",
        candidates=[reply._AgnoReplyChoice(text="Hallo, das klingt schön.", human_likeness="pass")],
    )
    native = NS(output_schema=None, structured_outputs=False,
                arun=AsyncMock(return_value=NS(content=response)))
    chat = NS(agent=native, _guardrail_ctx=None,
              _canonical_agent_input=lambda *args, **kwargs: ["stored chat", "request"])
    output = await reply._generate_native_agno_envelope(chat, "session-test")
    assert native.output_schema is reply._AgnoReplyEnvelope
    assert native.structured_outputs is True
    assert native.arun.await_args.kwargs["session_id"] == "session-test"
    assert native.arun.await_args.args[0] == ["stored chat", "request"]
    assert output["candidates"][0]["text"] == "Hallo, das klingt schön."
    assert calls == ["inbound"]


@pytest.mark.asyncio
async def test_w353_native_agno_rejects_non_envelope(monkeypatch):
    monkeypatch.setattr(reply, "check_inbound", lambda *args, **kwargs: None)
    native = NS(output_schema=None, structured_outputs=False,
                arun=AsyncMock(return_value=NS(content="Hello, I have sent your reply")))
    chat = NS(agent=native, _guardrail_ctx=None,
              _canonical_agent_input=lambda *args, **kwargs: [])
    with pytest.raises(RuntimeError, match="reply_candidate_envelope_invalid"):
        await reply._generate_native_agno_envelope(chat, "session-test")


@pytest.mark.asyncio
async def test_w353_guardrail_blocks_altered_native_candidate(monkeypatch):
    monkeypatch.setattr(reply, "check_inbound", lambda *args, **kwargs: None)
    monkeypatch.setattr(reply, "check_output",
                        lambda text, **kwargs: ("Cannot share that.", "block"))
    native = NS(output_schema=None, structured_outputs=False,
                arun=AsyncMock(return_value=NS(content=reply._AgnoReplyEnvelope(
                    state="ready", candidates=[reply._AgnoReplyChoice(
                        text="Some unsafe output", human_likeness="pass"
                    )],
                ))))
    chat = NS(agent=native, _guardrail_ctx=None,
              _canonical_agent_input=lambda *args, **kwargs: [])
    output = await reply._generate_native_agno_envelope(chat, "session-test")
    assert output["candidates"][0]["text"] == "Cannot share that."
    assert output["candidates"][0]["human_likeness"] == "blocked"
