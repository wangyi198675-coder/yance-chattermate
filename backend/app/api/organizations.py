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

from typing import List
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import json
import ipaddress
import secrets

from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.models.schemas.organization import (
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationResponse,
    OrganizationCreateResponse
)
from app.core.auth import get_current_user, require_permissions
from app.core.security import create_access_token, create_refresh_token
from app.core.logger import get_logger
from app.models.role import Role
from app.models.permission import Permission, DEFAULT_AGENT_ROLE_PERMISSIONS
from app.repositories.organization import OrganizationRepository
from app.models.agent import Agent
from app.models.session_to_agent import SessionToAgent
from datetime import datetime, timedelta, timezone
from uuid import UUID
from app.core.cors import update_cors_middleware
from app.core.application import app  # Import the FastAPI app instance from the new location

# Disposable-address rejection lives in the enterprise module: the hosted signup
# flow is what attracts throwaway signups, and the community edition has no
# reason to carry an 8k-domain blocklist. Absent, every address is accepted.
try:
    from app.enterprise.services.email_validation import ensure_not_disposable

    HAS_EMAIL_VALIDATION = True
except ImportError:
    HAS_EMAIL_VALIDATION = False

logger = get_logger(__name__)

# The previous .invalid address was written before response validation and
# cannot pass the native UserResponse EmailStr schema.
_PRIVATE_ADMIN_EMAIL = "local-admin@yance.example.com"
_LEGACY_PRIVATE_ADMIN_EMAIL = "local-admin@yance.invalid"

router = APIRouter(
    tags=["organizations"]
)


def _is_loopback_request(request: Request) -> bool:
    """Private bootstrap is only callable from the local desktop runtime."""
    if request.client is None:
        return False
    host = (request.client.host or "").strip()
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _issue_session_cookies(
    response: Response,
    user: User,
    organization: Organization,
    role: Role,
):
    """Issue the existing ChatterMate access/refresh/user-info session."""
    token_data = {"sub": str(user.id), "org": str(organization.id)}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=1800,
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=604800,
    )
    response.set_cookie(
        key="user_info",
        value=quote(json.dumps({
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "organization_id": str(organization.id),
            "role": role.to_dict(),
        }, default=str)),
        samesite="none",
        secure=True,
        max_age=604800,
    )
    return access_token, refresh_token


def _response_payload(
    organization: Organization,
    admin: User,
    admin_role: Role,
    access_token: str,
    refresh_token: str,
):
    return {
        "id": organization.id,
        "name": organization.name,
        "domain": organization.domain,
        "timezone": organization.timezone,
        "business_hours": organization.business_hours,
        "settings": organization.settings,
        "is_active": organization.is_active,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": admin.id,
            "email": admin.email,
            "full_name": admin.full_name,
            "organization_id": organization.id,
            "role": admin_role.to_dict(),
        },
    }


def _create_first_organization_principal(
    db: Session,
    *,
    name: str,
    domain: str,
    timezone_name: str,
    business_hours,
    admin_email: str,
    admin_name: str,
    admin_password: str,
):
    """Native first-organization transaction shared by interactive and private bootstrap."""
    if db.query(Organization).first():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization already exists",
        )

    organization = OrganizationRepository(db).create_organization(
        name=name,
        domain=domain,
        timezone=timezone_name,
        business_hours=business_hours,
    )

    permissions = {}
    for permission_name, description in Permission.default_permissions():
        permission = db.query(Permission).filter(Permission.name == permission_name).first()
        if not permission:
            permission = Permission(name=permission_name, description=description)
            db.add(permission)
            db.flush()
        permissions[permission_name] = permission

    admin_role = Role(
        name="Admin",
        description="Full access to all features",
        organization_id=organization.id,
        is_default=False,
    )
    admin_role.permissions = list(permissions.values())
    db.add(admin_role)

    agent_role = Role(
        name="Agent",
        description="Access to assigned chats and the unclaimed AI queue",
        organization_id=organization.id,
        is_default=True,
    )
    agent_role.permissions = [
        permissions[permission_name]
        for permission_name in DEFAULT_AGENT_ROLE_PERMISSIONS
    ]
    db.add(agent_role)
    db.flush()

    admin = User(
        email=admin_email,
        full_name=admin_name,
        hashed_password=User.get_password_hash(admin_password),
        organization_id=organization.id,
        role_id=admin_role.id,
        is_active=True,
    )
    db.add(admin)
    db.flush()
    return organization, admin, admin_role


def _find_existing_admin(db: Session, organization: Organization):
    users = (
        db.query(User)
        .filter(
            User.organization_id == organization.id,
            User.is_active == True,
        )
        .all()
    )
    for user in users:
        role = user.role
        if not role:
            continue
        permission_names = {permission.name for permission in (role.permissions or [])}
        if (
            role.name == "Admin"
            or "manage_organization" in permission_names
            or "super_admin" in permission_names
        ):
            return user, role
    return None, None


def _repair_failed_private_bootstrap_admin(
    db: Session, organization: Organization, admin: User, role: Role
) -> bool:
    """Repair only the exact single-principal record from the old failed first boot.

    Never change an interactive tenant, another user, or an ambiguous private
    installation. No password/role/organization reset is required or allowed.
    """
    if (
        organization.name != "Yance"
        or organization.domain != "private.yance.invalid"
        or admin.email != _LEGACY_PRIVATE_ADMIN_EMAIL
        or admin.full_name != "Yance Local Admin"
        or not admin.is_active
        or role.name != "Admin"
        or role.organization_id != organization.id
        or db.query(Organization).count() != 1
        or db.query(User).filter(User.organization_id == organization.id).count() != 1
    ):
        return False
    if db.query(User).filter(User.email == _PRIVATE_ADMIN_EMAIL).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Private admin email already belongs to another principal",
        )
    admin.email = _PRIVATE_ADMIN_EMAIL
    db.flush()
    return True


@router.post("", response_model=OrganizationCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    org_data: OrganizationCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    """Create a new organization with an admin user and default roles."""
    try:
        if HAS_EMAIL_VALIDATION:
            ensure_not_disposable(org_data.admin_email)

        organization, admin, admin_role = _create_first_organization_principal(
            db,
            name=org_data.name,
            domain=org_data.domain,
            timezone_name=org_data.timezone,
            business_hours=org_data.business_hours,
            admin_email=org_data.admin_email,
            admin_name=org_data.admin_name,
            admin_password=org_data.admin_password,
        )
        access_token, refresh_token = _issue_session_cookies(
            response, admin, organization, admin_role
        )

        db.commit()
        update_cors_middleware(app)
        return _response_payload(
            organization, admin, admin_role, access_token, refresh_token
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"Organization creation failed: {str(exc)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create organization: {str(exc)}",
        )


@router.post("/private-bootstrap", response_model=OrganizationCreateResponse)
async def private_bootstrap(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Idempotently provision/reuse the single private local admin principal."""
    if not _is_loopback_request(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Private bootstrap is only available from the local runtime",
        )

    try:
        organization = (
            db.query(Organization)
            .filter(Organization.is_active == True)
            .first()
        )

        created = organization is None
        repaired = False
        if created:
            generated_password = secrets.token_urlsafe(48)
            organization, admin, admin_role = _create_first_organization_principal(
                db,
                name="Yance",
                domain="private.yance.invalid",
                timezone_name="UTC",
                business_hours={
                    "monday": {"start": "09:00", "end": "17:00", "enabled": True},
                    "tuesday": {"start": "09:00", "end": "17:00", "enabled": True},
                    "wednesday": {"start": "09:00", "end": "17:00", "enabled": True},
                    "thursday": {"start": "09:00", "end": "17:00", "enabled": True},
                    "friday": {"start": "09:00", "end": "17:00", "enabled": True},
                    "saturday": {"start": "09:00", "end": "17:00", "enabled": False},
                    "sunday": {"start": "09:00", "end": "17:00", "enabled": False},
                },
                admin_email=_PRIVATE_ADMIN_EMAIL,
                admin_name="Yance Local Admin",
                admin_password=generated_password,
            )
        else:
            admin, admin_role = _find_existing_admin(db, organization)
            if admin is None or admin_role is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Existing organization has no active admin principal",
                )
            repaired = _repair_failed_private_bootstrap_admin(
                db, organization, admin, admin_role
            )
            if admin.email == _LEGACY_PRIVATE_ADMIN_EMAIL:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Unrecognized legacy private admin; manual recovery required",
                )

        access_token, refresh_token = _issue_session_cookies(
            response, admin, organization, admin_role
        )
        # Validate against the actual FastAPI response schema before committing.
        # The old flow committed an invalid email and only then raised HTTP 500.
        payload = OrganizationCreateResponse.model_validate(
            _response_payload(
                organization, admin, admin_role, access_token, refresh_token
            )
        )
        if created or repaired:
            db.commit()
            if created:
                update_cors_middleware(app)
        return payload.model_dump()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"Private bootstrap failed: {str(exc)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Private bootstrap failed",
        )

@router.get("/setup-status", response_model=dict)
async def is_organization_setup(
    db: Session = Depends(get_db)
):
    """Check if at least one active organization is set up."""
    try:
        active_org_exists = db.query(Organization.id)\
            .filter(Organization.is_active == True)\
            .first() is not None
        
        return {"is_setup": active_org_exists}
    except Exception as e:
        logger.error(f"Failed to check organization setup status: {str(e)}", exc_info=True)
        # In case of error, conservatively assume setup might be needed or report error
        # Returning False might lock users out if DB is temporarily unavailable
        # A 500 error might be better to indicate a server issue
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check organization setup status"
        )


@router.get("/check-domain/{domain}")
async def check_domain_availability(
    domain: str,
    db: Session = Depends(get_db)
):
    """Check if an organization domain is available"""
    try:
        existing_org = db.query(Organization).filter(Organization.domain == domain).first()
        return {
            "available": not existing_org,
            "message": "Domain is available" if not existing_org else "Domain already exists"
        }
    except Exception as e:
        logger.error(f"Failed to check domain availability: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check domain availability"
        )


def get_own_organization_or_404(db: Session, org_id: UUID, current_user: User) -> Organization:
    """Load an organization the caller actually belongs to.

    These routes take the org id from the path, so without this a user of one
    tenant could read — and with manage_organization, rewrite — another
    tenant's record. 404 rather than 403: the existence of another
    organization isn't the caller's business either.
    """
    if current_user.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )

    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    return org


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get organization by ID"""
    try:
        return get_own_organization_or_404(db, org_id, current_user)
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Failed to get organization {
                     org_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve organization. Please try again later."
        )


@router.patch("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: UUID,
    org_data: OrganizationUpdate,
    current_user: User = Depends(require_permissions("manage_organization")),
    db: Session = Depends(get_db)
):
    """Update organization details including business hours"""
    try:
        org = get_own_organization_or_404(db, org_id, current_user)

        # Update only provided fields
        update_data = org_data.model_dump(exclude_unset=True)
        
        # Validate business hours if provided
        if 'business_hours' in update_data:
            business_hours = update_data['business_hours']
            required_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            required_fields = ['start', 'end', 'enabled']
            
            # Validate all days are present
            if not all(day in business_hours for day in required_days):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Business hours must include all days of the week"
                )
            
            # Validate each day has required fields
            for day in required_days:
                if not all(field in business_hours[day] for field in required_fields):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Business hours for {day} must include start, end, and enabled status"
                    )
                
                # Validate time format (HH:MM)
                start = business_hours[day]['start']
                end = business_hours[day]['end']
                try:
                    hours, minutes = start.split(':')
                    if not (0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59):
                        raise ValueError
                    hours, minutes = end.split(':')
                    if not (0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59):
                        raise ValueError
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid time format for {day}. Use HH:MM format (24-hour)"
                    )

        for field, value in update_data.items():
            setattr(org, field, value)

        db.commit()
        db.refresh(org)

        # Update CORS origins after updating organization
        update_cors_middleware(app)

        return org
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update organization {org_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update organization. Please try again later."
        )


# @router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
# async def delete_organization(
#     org_id: UUID,
#     current_user: User = Depends(require_permissions("manage_organization")),
#     db: Session = Depends(get_db)
# ):
#     """
#     Hard delete organization and all related data.
    
#     This operation permanently removes:
#     - Users and their notifications, knowledge queue items, session assignments, ratings
#     - Customers and their ratings, chat histories
#     - Agents and their customizations, widgets, knowledge links, tool links, ratings, chat histories
#     - Workflows and workflow nodes
#     - Enterprise subscriptions and PayPal orders (if available)
#     - AI configurations
#     - Knowledge sources and knowledge-to-agent links
#     - MCP tools and their agent links
#     - User groups
#     - Roles and their permission associations
#     - Integration data (Shopify shops, Jira tokens)
#     - All remaining chat histories
#     - The organization itself
    
#     WARNING: This operation cannot be undone.
#     """
#     try:
#         # Check if organization exists
#         org = db.query(Organization).filter(Organization.id == org_id).first()
#         if not org:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail="Organization not found"
#             )

#         # Verify user belongs to this organization
#         if current_user.organization_id != org_id:
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail="You can only delete your own organization"
#             )

#         logger.info(f"Starting hard delete for organization {org_id}")

#         # Import models that might not be available in all environments
#         try:
#             from app.enterprise.models.subscription import Subscription
#             from app.enterprise.models.order import PayPalOrder
#             enterprise_available = True
#         except ImportError:
#             enterprise_available = False
#             logger.info("Enterprise models not available")

#         # Import all required models
#         from app.models.user import User, UserGroup
#         from app.models.role import Role
#         from app.models.permission import Permission
#         from app.models.agent import Agent, AgentCustomization
#         from app.models.widget import Widget
#         from app.models.ai_config import AIConfig
#         from app.models.knowledge import Knowledge
#         from app.models.knowledge_to_agent import KnowledgeToAgent
#         from app.models.knowledge_queue import KnowledgeQueue
#         from app.models.chat_history import ChatHistory
#         from app.models.customer import Customer
#         from app.models.session_to_agent import SessionToAgent
#         from app.models.rating import Rating
#         from app.models.workflow import Workflow
#         from app.models.workflow_node import WorkflowNode
#         from app.models.mcp_tool import MCPTool, MCPToolToAgent
#         from app.models.notification import Notification
#         from app.models.shopify.shopify_shop import ShopifyShop
#         from app.models.jira import JiraToken

#         # 1. Delete users and their related data first
#         logger.info("Deleting users and related data...")
#         users = db.query(User).filter(User.organization_id == org_id).all()
#         for user in users:
#             # Delete user notifications
#             db.query(Notification).filter(Notification.user_id == user.id).delete()
#             # Delete user knowledge queue items
#             db.query(KnowledgeQueue).filter(KnowledgeQueue.user_id == user.id).delete()
#             # Delete user session assignments
#             db.query(SessionToAgent).filter(SessionToAgent.user_id == user.id).delete()
#             # Delete user ratings
#             db.query(Rating).filter(Rating.user_id == user.id).delete()
        
#         # Delete users themselves (this will cascade to user_groups via the association table)
#         db.query(User).filter(User.organization_id == org_id).delete()

#         # 2. Delete customer-related data
#         logger.info("Deleting customer data...")
#         customers = db.query(Customer).filter(Customer.organization_id == org_id).all()
#         for customer in customers:
#             # Delete customer ratings
#             db.query(Rating).filter(Rating.customer_id == customer.id).delete()
#             # Delete customer chat histories
#             db.query(ChatHistory).filter(ChatHistory.customer_id == customer.id).delete()
        
#         # Delete customers
#         db.query(Customer).filter(Customer.organization_id == org_id).delete()

#         # 3. Delete agents and their related data
#         logger.info("Deleting agents and related data...")
#         agents = db.query(Agent).filter(Agent.organization_id == org_id).all()
#         for agent in agents:
#             # Delete agent customizations
#             db.query(AgentCustomization).filter(AgentCustomization.agent_id == agent.id).delete()
#             # Delete widgets for this agent
#             db.query(Widget).filter(Widget.agent_id == agent.id).delete()
#             # Delete knowledge-to-agent links
#             db.query(KnowledgeToAgent).filter(KnowledgeToAgent.agent_id == agent.id).delete()
#             # Delete MCP tool-to-agent links
#             db.query(MCPToolToAgent).filter(MCPToolToAgent.agent_id == agent.id).delete()
#             # Delete agent session assignments
#             db.query(SessionToAgent).filter(SessionToAgent.agent_id == agent.id).delete()
#             # Delete agent ratings
#             db.query(Rating).filter(Rating.agent_id == agent.id).delete()
#             # Delete agent chat histories
#             db.query(ChatHistory).filter(ChatHistory.agent_id == agent.id).delete()
        
#         # Delete agents themselves
#         db.query(Agent).filter(Agent.organization_id == org_id).delete()

#         # 4. Delete workflows and workflow nodes
#         logger.info("Deleting workflows...")
#         workflows = db.query(Workflow).filter(Workflow.organization_id == org_id).all()
#         for workflow in workflows:
#             # Delete workflow nodes
#             db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow.id).delete()
        
#         # Delete workflows
#         db.query(Workflow).filter(Workflow.organization_id == org_id).delete()

#         # 5. Delete remaining widgets (not associated with agents)
#         logger.info("Deleting remaining widgets...")
#         db.query(Widget).filter(Widget.organization_id == org_id).delete()

#         # 6. Delete enterprise subscriptions and orders if available
#         if enterprise_available:
#             logger.info("Deleting enterprise subscriptions and orders...")
#             # Delete PayPal orders first (they reference subscriptions)
#             db.query(PayPalOrder).filter(PayPalOrder.organization_id == org_id).delete()
#             # Delete subscriptions
#             db.query(Subscription).filter(Subscription.organization_id == org_id).delete()

#         # 7. Delete AI configs
#         logger.info("Deleting AI configs...")
#         db.query(AIConfig).filter(AIConfig.organization_id == org_id).delete()

#         # 8. Delete knowledge sources and related data
#         logger.info("Deleting knowledge sources...")
#         knowledge_sources = db.query(Knowledge).filter(Knowledge.organization_id == org_id).all()
#         for knowledge in knowledge_sources:
#             # Delete any remaining knowledge-to-agent links
#             db.query(KnowledgeToAgent).filter(KnowledgeToAgent.knowledge_id == knowledge.id).delete()
        
#         # Delete knowledge sources
#         db.query(Knowledge).filter(Knowledge.organization_id == org_id).delete()

#         # 9. Delete remaining knowledge queue items
#         logger.info("Deleting knowledge queue items...")
#         db.query(KnowledgeQueue).filter(KnowledgeQueue.organization_id == org_id).delete()

#         # 10. Delete MCP tools
#         logger.info("Deleting MCP tools...")
#         mcp_tools = db.query(MCPTool).filter(MCPTool.organization_id == org_id).all()
#         for tool in mcp_tools:
#             # Delete any remaining MCP tool-to-agent links
#             db.query(MCPToolToAgent).filter(MCPToolToAgent.mcp_tool_id == tool.id).delete()
        
#         # Delete MCP tools
#         db.query(MCPTool).filter(MCPTool.organization_id == org_id).delete()

#         # 11. Delete user groups
#         logger.info("Deleting user groups...")
#         db.query(UserGroup).filter(UserGroup.organization_id == org_id).delete()

#         # 12. Delete roles and their permission associations
#         logger.info("Deleting roles and their permissions...")
        
#         # First, directly delete entries from the role_permissions association table
#         from app.models.permission import role_permissions
        
#         # Get all role IDs for this organization
#         role_ids = [role_id for role_id, in db.query(Role.id).filter(Role.organization_id == org_id).all()]
        
#         if role_ids:
#             # Delete from the association table using raw SQL
#             # This is necessary because SQLAlchemy ORM doesn't directly support bulk deletion from association tables
#             delete_stmt = role_permissions.delete().where(role_permissions.c.role_id.in_(role_ids))
#             db.execute(delete_stmt)
#             db.flush()
        
#         # Now delete the roles
#         db.query(Role).filter(Role.organization_id == org_id).delete()

#         # 13. Delete integration-specific data
#         logger.info("Deleting integration data...")
#         # Delete Shopify shops
#         db.query(ShopifyShop).filter(ShopifyShop.organization_id == org_id).delete()
#         # Delete Jira tokens
#         db.query(JiraToken).filter(JiraToken.organization_id == org_id).delete()

#         # 14. Delete any remaining chat histories
#         logger.info("Deleting remaining chat histories...")
#         db.query(ChatHistory).filter(ChatHistory.organization_id == org_id).delete()

#         # 15. Finally, delete the organization itself
#         logger.info("Deleting organization...")
#         db.delete(org)

#         # Commit all changes
#         db.commit()
#         logger.info(f"Successfully hard deleted organization {org_id}")

#         # Update CORS origins after deleting organization
#         update_cors_middleware(app)

#         return None
#     except HTTPException as he:
#         db.rollback()
#         raise he
#     except Exception as e:
#         db.rollback()
#         logger.error(f"Failed to delete organization {org_id}: {str(e)}", exc_info=True)
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Failed to delete organization. Please try again later."
#         )


@router.get("/{org_id}/stats")
async def get_organization_stats(
    org_id: UUID,
    current_user: User = Depends(require_permissions("view_organization")),
    db: Session = Depends(get_db)
):
    """Get organization statistics"""
    org = get_own_organization_or_404(db, org_id, current_user)

    # --- Members ---
    total_users = db.query(User).filter(User.organization_id == org_id).count()
    active_users = db.query(User).filter(
        User.organization_id == org_id,
        User.is_active == True
    ).count()
    # Count admins consistently with the team-overview endpoint (users.py):
    # a user is an admin if their role grants manage_organization/super_admin,
    # or the role is literally named "Admin". A plain Role.name == "Admin"
    # match misses custom/renamed roles that still hold admin permissions.
    org_users = db.query(User).filter(User.organization_id == org_id).all()
    admins = sum(
        1
        for u in org_users
        if u.role and (
            {"manage_organization", "super_admin"} & {p.name for p in (u.role.permissions or [])}
            or u.role.name == "Admin"
        )
    )
    members_agents = total_users - admins

    # --- Active now (online) ---
    active_now = db.query(User).filter(
        User.organization_id == org_id,
        User.is_online == True
    ).count()

    # --- AI agents (live vs draft) ---
    agents_total = db.query(Agent).filter(Agent.organization_id == org_id).count()
    agents_live = db.query(Agent).filter(
        Agent.organization_id == org_id,
        Agent.is_active == True
    ).count()
    agents_draft = agents_total - agents_live

    # --- Conversations (last 30d vs previous 30d) ---
    now = datetime.now(timezone.utc)
    d30 = now - timedelta(days=30)
    d60 = now - timedelta(days=60)
    conversations_30d = db.query(SessionToAgent).filter(
        SessionToAgent.organization_id == org_id,
        SessionToAgent.assigned_at >= d30
    ).count()
    conversations_prev_30d = db.query(SessionToAgent).filter(
        SessionToAgent.organization_id == org_id,
        SessionToAgent.assigned_at >= d60,
        SessionToAgent.assigned_at < d30
    ).count()
    if conversations_prev_30d:
        conversations_change_pct = round(
            (conversations_30d - conversations_prev_30d) / conversations_prev_30d * 100
        )
    else:
        conversations_change_pct = 100 if conversations_30d else 0

    return {
        "total_users": total_users,
        "active_users": active_users,
        "settings": org.settings,
        # Design KPI strip
        "members_total": total_users,
        "members_admins": admins,
        "members_agents": members_agents,
        "active_now": active_now,
        "agents_total": agents_total,
        "agents_live": agents_live,
        "agents_draft": agents_draft,
        "conversations_30d": conversations_30d,
        "conversations_prev_30d": conversations_prev_30d,
        "conversations_change_pct": conversations_change_pct,
    }
