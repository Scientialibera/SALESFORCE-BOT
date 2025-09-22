from typing import Dict, Any, Optional
from chatbot.models.rbac import RBACContext

class RBACService:
    """
    Minimal RBAC service: only creates RBACContext from JWT claims for FastAPI dependency.
    All other RBAC logic is removed. Dev mode disables all checks.
    """
    def __init__(self, settings: Any):
        self.settings = settings

    async def create_rbac_context_from_jwt(
        self,
        jwt_claims: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> RBACContext:
        """
        Create RBAC context from JWT token claims. Only extracts user_id, email, tenant_id, object_id, and roles.
        """
        user_id = jwt_claims.get("email") or jwt_claims.get("preferred_username") or jwt_claims.get("oid") or "unknown"
        email = jwt_claims.get("email") or jwt_claims.get("preferred_username") or "unknown@example.com"
        tenant_id = jwt_claims.get("tid", "")
        object_id = jwt_claims.get("oid", "")
        user_roles = jwt_claims.get("roles", [])
        if isinstance(user_roles, str):
            user_roles = [user_roles]
        return RBACContext(
            user_id=user_id,
            email=email,
            tenant_id=tenant_id,
            object_id=object_id,
            roles=user_roles,
            permissions=set(),
            is_admin="admin" in user_roles or "administrator" in user_roles,
            session_id=session_id,
        )
