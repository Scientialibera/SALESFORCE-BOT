"""
User model for authentication and authorization.

This module defines the User model with Azure AD claims and RBAC information.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, EmailStr


class UserClaims(BaseModel):
    """Azure AD token claims."""
    
    oid: str = Field(..., description="Object ID from Azure AD")
    tid: str = Field(..., description="Tenant ID from Azure AD")
    email: EmailStr = Field(..., description="User email address")
    name: str = Field(..., description="User display name")
    preferred_username: Optional[str] = Field(default=None, description="Preferred username")
    given_name: Optional[str] = Field(default=None, description="Given name")
    family_name: Optional[str] = Field(default=None, description="Family name")
    roles: List[str] = Field(default_factory=list, description="Application roles")
    groups: List[str] = Field(default_factory=list, description="Group memberships")


class User(BaseModel):
    """User model with authentication and authorization context."""
    
    id: str = Field(..., description="User ID (usually email or oid)")
    email: EmailStr = Field(..., description="User email address")
    display_name: str = Field(..., description="User display name")
    tenant_id: str = Field(..., description="Azure AD tenant ID")
    object_id: str = Field(..., description="Azure AD object ID")
    
    # Authorization
    role: str = Field(default="user", description="User role (admin, user, readonly)")
    is_active: bool = Field(default=True, description="Whether user is active")
    is_admin: bool = Field(default=False, description="Whether user has admin privileges")
    
    # Claims and metadata
    claims: Optional[UserClaims] = Field(default=None, description="Raw Azure AD claims")
    allowed_accounts: List[str] = Field(default_factory=list, description="Account IDs user can access")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, description="User creation timestamp")
    last_login: Optional[datetime] = Field(default=None, description="Last login timestamp")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
    
    @classmethod
    def from_jwt_claims(cls, claims: Dict[str, Any]) -> "User":
        """
        Create User instance from JWT token claims.
        
        Args:
            claims: JWT token claims dictionary
            
        Returns:
            User instance
        """
        user_claims = UserClaims(
            oid=claims.get("oid", ""),
            tid=claims.get("tid", ""),
            email=claims.get("email", claims.get("preferred_username", "")),
            name=claims.get("name", ""),
            preferred_username=claims.get("preferred_username"),
            given_name=claims.get("given_name"),
            family_name=claims.get("family_name"),
            roles=claims.get("roles", []),
            groups=claims.get("groups", []),
        )
        
        return cls(
            id=user_claims.email or user_claims.oid,
            email=user_claims.email,
            display_name=user_claims.name,
            tenant_id=user_claims.tid,
            object_id=user_claims.oid,
            is_admin="admin" in user_claims.roles,
            claims=user_claims,
        )
    
    def has_role(self, role: str) -> bool:
        """
        Check if user has a specific role.
        
        Args:
            role: Role name to check
            
        Returns:
            True if user has the role
        """
        if self.claims:
            return role in self.claims.roles
        return False
    
    def has_group(self, group_id: str) -> bool:
        """
        Check if user is member of a specific group.
        
        Args:
            group_id: Group ID to check
            
        Returns:
            True if user is in the group
        """
        if self.claims:
            return group_id in self.claims.groups
        return False
    
    def can_access_account(self, account_id: str) -> bool:
        """
        Check if user can access a specific account.
        
        Args:
            account_id: Account ID to check
            
        Returns:
            True if user can access the account
        """
        if self.is_admin:
            return True
        
        return account_id in self.allowed_accounts
