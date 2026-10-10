"""
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from app.models.schemas.chat import (
    ChatOverviewResponse,
    ChatDetailResponse,
    ChatMessagePageResponse,
    ConversationStateResponse,
    ConversationStateUpdate,
)
from app.core.auth import get_current_user, require_permissions, get_unified_chat_auth
from app.services.shopify_session import require_shopify_or_jwt_auth
from app.models.user import User
from app.database import get_db
from app.repositories.chat import ChatRepository
from app.repositories.session_to_agent import SessionToAgentRepository
from app.core.logger import get_logger
from uuid import UUID

from fastapi import status


router = APIRouter()
logger = get_logger(__name__)




@router.get("/")
async def get_chat_history():
    return {"message": "Chat history endpoint"}


@router.get("/recent/shopify", response_model=List[ChatOverviewResponse])
@router.get("/recent", response_model=List[ChatOverviewResponse])
async def get_recent_chats(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    agent_id: Optional[str] = None,
    status: Optional[str] = Query(None, description="Filter by status: 'open', 'closed', or 'transferred'"),
    user_name: Optional[str] = Query(None, description="Filter by user name"),
    user_id: Optional[str] = Query(None, description="Filter by specific user ID"),
    customer_email: Optional[str] = Query(None, description="Filter by customer email"),
    date_from: Optional[datetime] = Query(None, description="Filter conversations from this date"),
    date_to: Optional[datetime] = Query(None, description="Filter conversations to this date"),
    inbox_filter: Optional[str] = Query(None, pattern="^(all|unread|followed|favourite|archived)$"),
    auth_info: dict = Depends(get_unified_chat_auth),
    db: Session = Depends(get_db)
):
    """Get recent chats - supports both JWT and Shopify session token auth"""
    try:
        chat_repo = ChatRepository(db)
        organization_id = auth_info['organization_id']
        inbox_filter_kw = {'inbox_filter': inbox_filter} if inbox_filter else {}
        
        # For Shopify session token auth, we don't have user permissions, so show all chats for the organization
        if auth_info['auth_type'] == 'shopify_session' or auth_info['auth_type'] == 'shopify':
            return chat_repo.get_recent_chats(
                skip=skip,
                limit=limit,
                agent_id=agent_id,
                status=status,
                organization_id=organization_id,
                user_name=user_name,
                filter_user_id=user_id,
                customer_email=customer_email,
                date_from=date_from,
                date_to=date_to,
                **inbox_filter_kw
            )
        
        # For JWT auth, use permissions from auth_info
        current_user = auth_info['current_user']
        can_view_all = auth_info.get('can_view_all', False)
        can_view_assigned = auth_info.get('can_view_assigned', False)
        can_view_unassigned = auth_info.get('can_view_unassigned', False)

        # Get user's group IDs
        user_group_ids = [str(group.id) for group in current_user.groups]
        logger.debug(f"User groups: {user_group_ids}")
        logger.debug(f"current_user.user_id: {current_user.id}")

        # Scoped inbox: own sessions + group queue (view_assigned_chats) and/or
        # the unclaimed AI queue (view_unassigned_chats)
        if not can_view_all:
            if not (can_view_assigned or can_view_unassigned):
                # Without inbox permissions, an empty visibility condition must
                # never fall through to an unscoped organization-wide query.
                return []
            return chat_repo.get_recent_chats(
                skip=skip,
                limit=limit,
                agent_id=agent_id,
                status=status,
                user_id=current_user.id if can_view_assigned else None,
                user_groups=user_group_ids if can_view_assigned else None,
                include_unassigned=can_view_unassigned,
                organization_id=organization_id,
                user_name=user_name,
                filter_user_id=user_id,  # New parameter for filtering by specific user
                customer_email=customer_email,
                date_from=date_from,
                date_to=date_to,
                **inbox_filter_kw
            )

        # For users with view_all_chats permission
        return chat_repo.get_recent_chats(
            skip=skip,
            limit=limit,
            agent_id=agent_id,
            status=status,
            organization_id=organization_id,
            user_name=user_name,
            filter_user_id=user_id,  # New parameter for filtering by specific user
            customer_email=customer_email,
            date_from=date_from,
            date_to=date_to,
            **inbox_filter_kw
        )
    except ValueError as e:
        logger.error(f"Invalid UUID format: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail="Invalid UUID format"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting recent chats: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch recent chats"
        )

@router.patch("/{session_id}/inbox-state", response_model=ConversationStateResponse)
async def update_conversation_inbox_state(
    session_id: str,
    payload: ConversationStateUpdate,
    auth_info: dict = Depends(get_unified_chat_auth),
    db: Session = Depends(get_db),
):
    """Persist S07 state on the canonical ChatterMate SessionToAgent row."""
    if auth_info['auth_type'] in {'shopify_session', 'shopify'}:
        raise HTTPException(status_code=403, detail="Inbox state requires an authenticated user")

    try:
        session_id_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    chat_repo = ChatRepository(db)
    current_user = auth_info['current_user']
    can_view_all = auth_info.get('can_view_all', False)
    if not can_view_all:
        can_view_assigned = auth_info.get('can_view_assigned', False)
        can_view_unassigned = auth_info.get('can_view_unassigned', False)
        has_access = await chat_repo.check_session_access(
            session_id=session_id_uuid,
            user_id=current_user.id if can_view_assigned else None,
            user_groups=[str(group.id) for group in current_user.groups] if can_view_assigned else [],
            include_unassigned=can_view_unassigned,
        )
        if not has_access:
            raise HTTPException(status_code=404, detail="Chat session not found")

    session = SessionToAgentRepository(db).update_inbox_state(
        session_id=session_id_uuid,
        organization_id=auth_info['organization_id'],
        followed=payload.followed,
        favourite=payload.favourite,
        archived=payload.archived,
        mark_read=payload.mark_read,
    )
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    return {
        "followed": session.is_followed,
        "favourite": session.is_favourite,
        "archived": session.is_archived,
        "last_read_message_id": session.last_read_message_id,
    }


@router.get("/{session_id}/messages", response_model=ChatMessagePageResponse)
async def get_chat_messages(
    session_id: str,
    direction: str = Query(..., pattern="^(older|newer)$"),
    cursor_created_at: datetime = Query(...),
    cursor_id: int = Query(..., ge=0),
    limit: int = Query(50, ge=1, le=200),
    auth_info: dict = Depends(get_unified_chat_auth),
    db: Session = Depends(get_db),
):
    """Fetch one strict keyset page from the canonical ChatHistory owner."""
    try:
        session_id_uuid = UUID(session_id)
        chat_repo = ChatRepository(db)
        organization_id = auth_info['organization_id']

        if auth_info['auth_type'] not in {'shopify_session', 'shopify'}:
            current_user = auth_info['current_user']
            can_view_all = auth_info.get('can_view_all', False)
            if not can_view_all:
                can_view_assigned = auth_info.get('can_view_assigned', False)
                can_view_unassigned = auth_info.get('can_view_unassigned', False)
                user_group_ids = [str(group.id) for group in current_user.groups]
                has_access = await chat_repo.check_session_access(
                    session_id=session_id_uuid,
                    user_id=current_user.id if can_view_assigned else None,
                    user_groups=user_group_ids if can_view_assigned else [],
                    include_unassigned=can_view_unassigned,
                )
                if not has_access:
                    raise HTTPException(status_code=404, detail="Chat session not found")

        # A guessed session UUID must never cross organization boundaries.
        if not chat_repo.session_belongs_to_organization(session_id_uuid, organization_id):
            raise HTTPException(status_code=404, detail="Chat session not found")

        page = await chat_repo.get_session_history_page(
            session_id_uuid,
            limit=limit,
            direction=direction,
            cursor_created_at=cursor_created_at,
            cursor_id=cursor_id,
        )
        return {
            'messages': [
                chat_repo._project_history_message(message)
                for message in page['messages']
            ],
            'has_more': page['has_more'],
            'next_cursor': page['next_cursor'],
        }
    except ValueError as e:
        logger.error(f"Invalid history page request: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid history page request")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting chat message page: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch chat messages")


@router.get("/{session_id}/export")
async def export_chat_history(
    session_id: str,
    auth_info: dict = Depends(get_unified_chat_auth),
    db: Session = Depends(get_db),
):
    """Export canonical ChatHistory rows and their FileAttachment metadata only."""
    try:
        session_id_uuid = UUID(session_id)
        chat_repo = ChatRepository(db)
        organization_id = auth_info['organization_id']

        if auth_info['auth_type'] not in {'shopify_session', 'shopify'}:
            current_user = auth_info['current_user']
            can_view_all = auth_info.get('can_view_all', False)
            if not can_view_all:
                can_view_assigned = auth_info.get('can_view_assigned', False)
                can_view_unassigned = auth_info.get('can_view_unassigned', False)
                user_group_ids = [str(group.id) for group in current_user.groups]
                has_access = await chat_repo.check_session_access(
                    session_id=session_id_uuid,
                    user_id=current_user.id if can_view_assigned else None,
                    user_groups=user_group_ids if can_view_assigned else [],
                    include_unassigned=can_view_unassigned,
                )
                if not has_access:
                    raise HTTPException(status_code=404, detail="Chat session not found")

        if not chat_repo.session_belongs_to_organization(session_id_uuid, organization_id):
            raise HTTPException(status_code=404, detail="Chat session not found")

        history = await chat_repo.get_session_history(session_id_uuid)
        payload = {
            "schema": "yance.conversation-export.v1",
            "session_id": str(session_id_uuid),
            "messages": [
                {
                    "id": row.id,
                    "organization_id": row.organization_id,
                    "user_id": row.user_id,
                    "customer_id": row.customer_id,
                    "agent_id": row.agent_id,
                    "session_id": row.session_id,
                    "client_send_intent_id": row.client_send_intent_id,
                    "message": row.message,
                    "message_type": row.message_type,
                    "provider_channel": row.provider_channel,
                    "external_account_id": row.external_account_id,
                    "external_message_id": row.external_message_id,
                    "attributes": row.attributes,
                    "sentiment_label": row.sentiment_label,
                    "sentiment_score": row.sentiment_score,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                    "attachments": [
                        {
                            "id": attachment.id,
                            "filename": attachment.filename,
                            "content_type": attachment.content_type,
                            "file_size": attachment.file_size,
                            "chat_history_id": attachment.chat_history_id,
                            "organization_id": attachment.organization_id,
                            "uploaded_by_user_id": attachment.uploaded_by_user_id,
                            "uploaded_by_customer_id": attachment.uploaded_by_customer_id,
                            "created_at": attachment.created_at,
                            "updated_at": attachment.updated_at,
                        }
                        for attachment in (row.attachments or [])
                    ],
                }
                for row in history
            ],
        }
        return JSONResponse(
            content=jsonable_encoder(payload),
            headers={
                "Content-Disposition": (
                    f'attachment; filename="conversation-{session_id_uuid}.json"'
                )
            },
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting chat history: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to export chat history")


@router.get("/{session_id}/shopify", response_model=ChatDetailResponse)
@router.get("/{session_id}", response_model=ChatDetailResponse)
async def get_chat_detail(
    session_id: str,
    auth_info: dict = Depends(get_unified_chat_auth),
    db: Session = Depends(get_db)
):
    """Get detailed chat history for a session - supports both JWT and Shopify session token auth"""
    logger.info(f"Getting chat detail for session {session_id}")
    
    try:
        # Convert session_id to UUID
        session_id_uuid = UUID(session_id)
        chat_repo = ChatRepository(db)
        organization_id = auth_info['organization_id']
        
        # For Shopify session token auth, we don't have user permissions, so allow access to all org chats
        if auth_info['auth_type'] == 'shopify_session' or auth_info['auth_type'] == 'shopify':
            # Get chat detail
            chat_detail = await chat_repo.get_chat_detail(
                session_id=session_id_uuid,
                org_id=organization_id
            )
        else:
            # For JWT auth, use permissions from auth_info
            current_user = auth_info['current_user']
            can_view_all = auth_info.get('can_view_all', False)
            can_view_assigned = auth_info.get('can_view_assigned', False)
            can_view_unassigned = auth_info.get('can_view_unassigned', False)

            # Get user's group IDs
            user_group_ids = [str(group.id) for group in current_user.groups]

            # Scoped readers must own the session, share its group, or — with
            # view_unassigned_chats — find it unclaimed
            if not can_view_all:
                has_access = await chat_repo.check_session_access(
                    session_id=session_id_uuid,
                    user_id=current_user.id if can_view_assigned else None,
                    user_groups=user_group_ids if can_view_assigned else [],
                    include_unassigned=can_view_unassigned
                )
                if not has_access:
                    raise HTTPException(
                        status_code=404,
                        detail="Chat session not found"
                    )
            
            # Get chat detail
            chat_detail = await chat_repo.get_chat_detail(
                session_id=session_id_uuid,
                org_id=organization_id
            )
        
        
        if not chat_detail:
            raise HTTPException(
                status_code=404,
                detail="Chat session not found"
            )

        # Process messages to include Shopify data from attributes
        if hasattr(chat_detail, 'messages') and chat_detail.messages:
            for message in chat_detail.messages:
                if hasattr(message, 'attributes') and message.attributes:
                    try:
                        import json
                        attrs = json.loads(message.attributes) if isinstance(message.attributes, str) else message.attributes
                        
                        # Add Shopify-specific data to message if present
                        if 'shopify_data' in attrs:
                            message.shopify_data = attrs['shopify_data']
                        
                        # Handle shopify_output for backward compatibility
                        if 'shopify_output' in attrs:
                            message.message_type = 'product'
                            message.shopify_output = attrs['shopify_output']
                        
                        # Keep other attributes that might be needed
                        message.end_chat = attrs.get('end_chat')
                        
                        # Handle end_chat_reason - validate against enum values
                        end_chat_reason = attrs.get('end_chat_reason')
                        if end_chat_reason is not None:
                            # Check if value is in the enum
                            from app.models.schemas.chat import EndChatReasonType
                            valid_reasons = [reason.value for reason in EndChatReasonType]
                            if end_chat_reason not in valid_reasons:
                                # If invalid value, set to None
                                logger.warning(f"Invalid end_chat_reason value: {end_chat_reason}. Setting to None.")
                                message.end_chat_reason = None
                            else:
                                message.end_chat_reason = end_chat_reason
                        else:
                            message.end_chat_reason = None
                            
                        message.end_chat_description = attrs.get('end_chat_description')
                            
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(f"Failed to parse message attributes: {e}")
                        continue
        elif isinstance(chat_detail, dict) and 'messages' in chat_detail:
            # Handle case where chat_detail is a dict
            for message in chat_detail['messages']:
                if isinstance(message, dict) and 'attributes' in message and message['attributes']:
                    try:
                        import json
                        attrs = json.loads(message['attributes']) if isinstance(message['attributes'], str) else message['attributes']
                        
                        # Add Shopify-specific data to message if present
                        if 'shopify_data' in attrs:
                            message['shopify_data'] = attrs['shopify_data']
                        
                        # Handle shopify_output for backward compatibility
                        if 'shopify_output' in attrs and attrs['shopify_output'] is not None:
                            message['message_type'] = 'product'
                            message['shopify_output'] = attrs['shopify_output']
                        
                        # Keep other attributes that might be needed
                        message['end_chat'] = attrs.get('end_chat')
                        
                        # Handle end_chat_reason - validate against enum values
                        end_chat_reason = attrs.get('end_chat_reason')
                        if end_chat_reason is not None:
                            # Check if value is in the enum
                            from app.models.schemas.chat import EndChatReasonType
                            valid_reasons = [reason.value for reason in EndChatReasonType]
                            if end_chat_reason not in valid_reasons:
                                # If invalid value, set to None
                                logger.warning(f"Invalid end_chat_reason value: {end_chat_reason}. Setting to None.")
                                message['end_chat_reason'] = None
                            else:
                                message['end_chat_reason'] = end_chat_reason
                        else:
                            message['end_chat_reason'] = None
                            
                        message['end_chat_description'] = attrs.get('end_chat_description')
                            
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(f"Failed to parse message attributes: {e}")
                        continue

        return chat_detail

    except ValueError as e:
        logger.error(f"Invalid UUID format: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail="Invalid UUID format"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting chat detail: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch chat detail"
        )





