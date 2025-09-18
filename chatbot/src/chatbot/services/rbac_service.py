"""
RBAC (Role-Based Access Control) service for authorization management.

This service handles user authentication, role resolution, and access control
for all data operations throughout the application.
"""

import asyncio
from typing import Optional, List, Dict, Any, Set
from datetime import datetime, timedelta
import structlog

from chatbot.models.user import User, UserClaims
from chatbot.models.rbac import RBACContext, AccessScope, Permission, PREDEFINED_ROLES
from chatbot.config.settings import RBACSettings

logger = structlog.get_logger(__name__)


class RBACService:
    """
    Service for managing role-based access control.
    
    This service handles:
    - JWT token validation and user context creation
    - Role and permission resolution
    - Account-level access control
    - SQL and Gremlin query filtering
    """
    
    def __init__(self, settings: RBACSettings):
        """
        Initialize the RBAC service.
        
        Args:
            settings: RBAC configuration settings
        """
        self.settings = settings
        self.role_cache: Dict[str, Any] = {}
        
        logger.info(
            "Initialized RBAC service",
            enforce_rbac=settings.enforce_rbac,
            admin_users=len(settings.admin_users),
        )
    
    async def create_rbac_context_from_jwt(
        self,
        jwt_claims: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> RBACContext:
        """
        Create RBAC context from JWT token claims.
        
        Args:
            jwt_claims: JWT token claims dictionary
            session_id: Optional session ID
            
        Returns:
            RBAC context for the user
        """
        try:
            # Extract basic user information
            user_id = jwt_claims.get("email", jwt_claims.get("preferred_username", jwt_claims.get("oid", "")))
            email = jwt_claims.get("email", jwt_claims.get("preferred_username", ""))
            tenant_id = jwt_claims.get("tid", "")
            object_id = jwt_claims.get("oid", "")
            
            # Extract roles from claims
            user_roles = jwt_claims.get("roles", [])
            if isinstance(user_roles, str):
                user_roles = [user_roles]
            
            # Check if user is admin
            is_admin = (
                email.lower() in [admin.lower() for admin in self.settings.admin_users]
                or "admin" in user_roles
                or "administrator" in user_roles
            )
            
            # Resolve permissions from roles
            permissions = await self._resolve_permissions(user_roles, is_admin)
            
            # Create access scope
            access_scope = await self._create_access_scope(
                user_id=user_id,
                email=email,
                roles=user_roles,
                is_admin=is_admin,
            )
            
            # Build RBAC context
            rbac_context = RBACContext(
                user_id=user_id,
                email=email,
                tenant_id=tenant_id,
                object_id=object_id,
                roles=user_roles,
                permissions=permissions,
                access_scope=access_scope,
                is_admin=is_admin,
                session_id=session_id,
                created_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(hours=8),  # 8 hour session
            )
            
            logger.info(
                "Created RBAC context",
                user_id=user_id,
                email=email,
                roles=user_roles,
                is_admin=is_admin,
                permissions_count=len(permissions),
            )
            
            return rbac_context
            
        except Exception as e:
            logger.error("Failed to create RBAC context from JWT", error=str(e))
            # Return minimal context for error cases
            return RBACContext(
                user_id="unknown",
                email="unknown@example.com",
                tenant_id="",
                object_id="",
                is_active=False,
            )
    
    async def _resolve_permissions(
        self,
        user_roles: List[str],
        is_admin: bool,
    ) -> Set[Permission]:
        """
        Resolve permissions from user roles.
        
        Args:
            user_roles: List of user role names
            is_admin: Whether user is admin
            
        Returns:
            Set of resolved permissions
        """
        permissions = set()
        
        # Admin gets all permissions
        if is_admin:
            permissions.add(Permission.ADMIN)
            return permissions
        
        # Resolve permissions from predefined roles
        for role_name in user_roles:
            role = PREDEFINED_ROLES.get(role_name.lower())
            if role:
                permissions.update(role.permissions)
        
        # Default permissions for any authenticated user
        if not permissions:
            permissions.update([
                Permission.READ_ACCOUNT,
                Permission.READ_OPPORTUNITY,
                Permission.READ_TASK,
                Permission.READ_CONTRACT,
            ])
        
        return permissions
    
    async def _create_access_scope(
        self,
        user_id: str,
        email: str,
        roles: List[str],
        is_admin: bool,
    ) -> AccessScope:
        """
        Create access scope for the user.
        
        Args:
            user_id: User ID
            email: User email
            roles: User roles
            is_admin: Whether user is admin
            
        Returns:
            Access scope configuration
        """
        # Admin gets access to everything
        if is_admin:
            return AccessScope(all_accounts=True)
        
        # Sales managers get broader access
        if "sales_manager" in roles:
            return AccessScope(team_access=True)
        
        # Sales reps get access to their owned accounts
        if "sales_rep" in roles:
            account_ids = await self._get_user_account_ids(email)
            return AccessScope(
                account_ids=set(account_ids),
                owned_only=True,
            )
        
        # Read-only users get limited access
        if "readonly" in roles:
            account_ids = await self._get_user_account_ids(email)
            return AccessScope(
                account_ids=set(account_ids),
                owned_only=False,
            )
        
        # Default: no access
        return AccessScope()
    
    async def _get_user_account_ids(self, email: str) -> List[str]:
        """
        Get account IDs that a user can access.
        
        Args:
            email: User email
            
        Returns:
            List of accessible account IDs
        """
        # TODO: Implement actual account lookup from SQL database
        # This would query the database for accounts where owner_email = email
        # For now, return empty list
        return []
    
    def get_sql_account_filter(
        self,
        rbac_context: RBACContext,
        table_alias: str = "",
        account_id_column: str = "account_id",
        owner_email_column: str = "owner_email",
    ) -> str:
        """
        Generate SQL WHERE clause for account filtering.
        
        Args:
            rbac_context: RBAC context
            table_alias: Optional table alias
            account_id_column: Name of account ID column
            owner_email_column: Name of owner email column
            
        Returns:
            SQL WHERE clause for filtering
        """
        if not self.settings.enforce_rbac or rbac_context.is_admin:
            return "1=1"  # No filtering for admin
        
        table_prefix = f"{table_alias}." if table_alias else ""
        filters = []
        
        # Account ID filter
        if rbac_context.access_scope.account_ids:
            account_list = "','".join(rbac_context.access_scope.account_ids)
            filters.append(f"{table_prefix}{account_id_column} IN ('{account_list}')")
        
        # Owner filter
        if rbac_context.access_scope.owned_only:
            filters.append(f"{table_prefix}{owner_email_column} = '{rbac_context.email}'")
        
        # All accounts access
        if rbac_context.access_scope.all_accounts:
            return "1=1"
        
        return " AND ".join(filters) if filters else "1=0"  # No access if no filters
    
    def get_gremlin_account_filter(
        self,
        rbac_context: RBACContext,
        vertex_label: str = "Account",
    ) -> str:
        """
        Generate Gremlin predicate for account filtering.
        
        Args:
            rbac_context: RBAC context
            vertex_label: Vertex label to filter
            
        Returns:
            Gremlin predicate for filtering
        """
        if not self.settings.enforce_rbac or rbac_context.is_admin:
            return ""  # No filtering for admin
        
        filters = []
        
        # Account ID filter
        if rbac_context.access_scope.account_ids:
            account_list = "','".join(rbac_context.access_scope.account_ids)
            filters.append(f"has('id', within('{account_list}'))")
        
        # Owner filter
        if rbac_context.access_scope.owned_only:
            filters.append(f"has('owner_email', '{rbac_context.email}')")
        
        # All accounts access
        if rbac_context.access_scope.all_accounts:
            return ""
        
        if filters:
            return f".hasLabel('{vertex_label}').{'.'.join(filters)}"
        else:
            return f".hasLabel('{vertex_label}').has('id', 'non-existent')"  # No access
    
    def validate_account_access(
        self,
        rbac_context: RBACContext,
        account_id: str,
        owner_email: Optional[str] = None,
        required_permission: Permission = Permission.READ_ACCOUNT,
    ) -> bool:
        """
        Validate if user can access a specific account.
        
        Args:
            rbac_context: RBAC context
            account_id: Account ID to check
            owner_email: Optional account owner email
            required_permission: Required permission for access
            
        Returns:
            True if access is allowed
        """
        if not self.settings.enforce_rbac:
            return True
        
        # Check if user has required permission
        if not rbac_context.has_permission(required_permission):
            logger.warning(
                "Access denied: missing permission",
                user_id=rbac_context.user_id,
                account_id=account_id,
                required_permission=required_permission.value,
            )
            return False
        
        # Admin can access everything
        if rbac_context.is_admin:
            return True
        
        # Check account-level access
        return rbac_context.can_access_account(account_id, owner_email)
    
    def filter_accounts_by_access(
        self,
        rbac_context: RBACContext,
        accounts: List[Dict[str, Any]],
        account_id_key: str = "id",
        owner_email_key: str = "owner_email",
    ) -> List[Dict[str, Any]]:
        """
        Filter list of accounts by user access.
        
        Args:
            rbac_context: RBAC context
            accounts: List of account dictionaries
            account_id_key: Key for account ID in dictionaries
            owner_email_key: Key for owner email in dictionaries
            
        Returns:
            Filtered list of accessible accounts
        """
        if not self.settings.enforce_rbac or rbac_context.is_admin:
            return accounts
        
        accessible_accounts = []
        for account in accounts:
            account_id = account.get(account_id_key)
            owner_email = account.get(owner_email_key)
            
            if self.validate_account_access(rbac_context, account_id, owner_email):
                accessible_accounts.append(account)
        
        logger.debug(
            "Filtered accounts by access",
            user_id=rbac_context.user_id,
            total_accounts=len(accounts),
            accessible_accounts=len(accessible_accounts),
        )
        
        return accessible_accounts
    
    async def refresh_user_access_scope(
        self,
        rbac_context: RBACContext,
    ) -> RBACContext:
        """
        Refresh user's access scope (e.g., after role changes).
        
        Args:
            rbac_context: Current RBAC context
            
        Returns:
            Updated RBAC context
        """
        try:
            # Create new access scope
            new_access_scope = await self._create_access_scope(
                user_id=rbac_context.user_id,
                email=rbac_context.email,
                roles=rbac_context.roles,
                is_admin=rbac_context.is_admin,
            )
            
            # Update context
            rbac_context.access_scope = new_access_scope
            
            logger.info(
                "Refreshed user access scope",
                user_id=rbac_context.user_id,
                account_count=len(new_access_scope.account_ids),
                all_accounts=new_access_scope.all_accounts,
            )
            
            return rbac_context
            
        except Exception as e:
            logger.error(
                "Failed to refresh user access scope",
                user_id=rbac_context.user_id,
                error=str(e),
            )
            return rbac_context
