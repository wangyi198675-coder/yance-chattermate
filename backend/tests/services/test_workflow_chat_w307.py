"""W307 focused workflow ordering: real service methods, isolated dependencies."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.services.workflow_chat import WorkflowChatService, WORKFLOW_RATING_COPY
from app.agents.chat_agent import ChatResponse


def workflow_result(*, transfer=False, end=False, rating=False, intermediate=None):
    return SimpleNamespace(
        message="Workflow final reply",
        transfer_to_human=transfer, transfer_reason=None,
        transfer_description="Handoff", transfer_group_id="group-123",
        end_chat=end, request_rating=rating,
        intermediate_messages=intermediate or [],
        form_data=None, next_node_id=None,
    )


def session_data():
    return {"agent_id": "agent-123",
            "ai_config": SimpleNamespace(encrypted_api_key="k",
                                         model_name="m", model_type="openai",
                                         settings={})}


async def generate(service, result):
    return await service._handle_successful_workflow(
        result, SimpleNamespace(workflow_id="wf-123"),
        "session-123", "org-123", "customer-123",
        session_data(), AsyncMock(), "/widget", 42, "42:user:revision")


@pytest.mark.asyncio
async def test_f01_transfer_message_is_intent_before_control_and_once():
    service = WorkflowChatService(Mock())
    result = workflow_result(transfer=True)
    availability = ChatResponse(message="Real generated availability", transfer_to_human=True,
                                transfer_reason=None, transfer_description=None,
                                end_chat=False, request_rating=False, create_ticket=False)
    with patch.object(service, "_store_workflow_response") as store, \
         patch.object(service, "_handle_workflow_transfer",
                      new_callable=AsyncMock, return_value=availability) as control:
        response = await generate(service, result)
        store.assert_called_once()
        assert response.message == "Real generated availability"
        assert control.await_count == 1
        assert control.await_args.kwargs["prepare_only"] is True
        assert response._workflow_transfer_pending["transfer_group_id"] == "group-123"
        # Widget calls completion only after deliver_to_customer has returned ok.
        await service.complete_transfer_after_delivery(
            response._workflow_transfer_pending, "session-123",
            "org-123", session_data(), "customer-123")
        assert control.await_count == 2
        assert control.await_args.kwargs["control_only"] is True
        assert control.await_args.args[0].transfer_group_id == "group-123"


@pytest.mark.asyncio
async def test_f01_transfer_handoff_does_not_create_second_bot_history():
    service = WorkflowChatService(Mock())
    result = workflow_result(transfer=True)
    chat_agent = Mock()
    chat_agent.handle_workflow_transfer = AsyncMock(
        return_value=SimpleNamespace(message="availability", transfer_to_human=True))
    chat_agent.safe_cleanup_mcp_tools = AsyncMock()
    with patch("app.services.workflow_chat.decrypt_api_key", return_value="k"), \
         patch("app.services.workflow_chat.ChatAgent.create_async",
               new_callable=AsyncMock, return_value=chat_agent), \
         patch.object(service.session_repo, "update_session_status") as fallback:
        await service._handle_workflow_transfer(
            result, "session-123", "org-123", session_data(),
            "customer-123", Mock(), prepare_only=True)
        assert chat_agent.handle_workflow_transfer.await_count == 1
        assert chat_agent.handle_workflow_transfer.await_args.kwargs["persist_response"] is False
        assert chat_agent.handle_workflow_transfer.await_args.kwargs["defer_control"] is True
        assert chat_agent.handle_workflow_transfer.await_args.kwargs["control_only"] is False
        fallback.assert_not_called()
        chat_agent.safe_cleanup_mcp_tools.assert_awaited_once()


@pytest.mark.asyncio
async def test_f02_end_chat_generates_final_intent_without_premature_close():
    service = WorkflowChatService(Mock())
    result = workflow_result(end=True, rating=True)
    with patch.object(service, "_store_workflow_response") as store, \
         patch.object(service, "_handle_workflow_end_chat",
                      new_callable=AsyncMock) as premature_close:
        response = await generate(service, result)
        assert response.end_chat is True
        assert response.message.endswith(WORKFLOW_RATING_COPY)
        store.assert_called_once()
        assert store.call_args.args[0] is response
        premature_close.assert_not_awaited()


@pytest.mark.asyncio
async def test_f03_unacked_intermediate_creates_no_final_intent():
    service = WorkflowChatService(Mock())
    result = workflow_result(end=True, intermediate=["Step 1"])
    with patch.object(service, "_handle_intermediate_messages",
                      new_callable=AsyncMock, return_value=("42:user:revision", False)), \
         patch.object(service, "_store_workflow_response") as final_intent, \
         patch.object(service, "_handle_workflow_end_chat",
                      new_callable=AsyncMock) as premature_close:
        response = await generate(service, result)
        assert response is None
        final_intent.assert_not_called()
        premature_close.assert_not_awaited()
