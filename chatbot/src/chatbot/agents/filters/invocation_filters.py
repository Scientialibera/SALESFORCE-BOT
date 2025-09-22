"""
Invocation filters for Semantic Kernel function calls.

This module provides pre/post filters for SK invocations including
account resolution, safety checks, logging, and token management.
"""

from typing import Any, Dict, List, Optional
import structlog
from semantic_kernel.functions import KernelArguments
from semantic_kernel.kernel import Kernel

from chatbot.agents.filters.account_resolver_filter import AccountResolverFilter
from chatbot.models.rbac import RBACContext
from chatbot.services.account_resolver_service import AccountResolverService
from chatbot.services.telemetry_service import TelemetryService

logger = structlog.get_logger(__name__)


class AccountResolutionFilter:
    """Filter that resolves account names before function invocation."""
    
    def __init__(
        self,
        account_resolver_service: AccountResolverService,
        telemetry_service: TelemetryService
    ):
        """
        Initialize the account resolution filter.
        
        Args:
            account_resolver_service: Service for account resolution
            telemetry_service: Service for telemetry tracking
        """
        self.account_resolver = account_resolver_service
        self.telemetry = telemetry_service
    
    async def filter_function_invocation(
        self,
        context: Dict[str, Any],
        next_filter: Any
    ) -> Any:
        """
        Pre-filter to resolve account names before function invocation.
        
        Args:
            context: Invocation context containing function and arguments
            next_filter: Next filter in the chain
            
        Returns:
            Filter result
        """
        try:
            function_name = context.get("function", {}).get("name", "unknown")
            arguments: KernelArguments = context.get("arguments", KernelArguments())
            rbac_context: RBACContext = context.get("rbac_context")
            
            logger.info(
                "Account resolution filter triggered",
                function=function_name,
                user_id=rbac_context.user_id if rbac_context else None
            )
            
            # Check if this function needs account resolution
            if self._needs_account_resolution(function_name, arguments):
                user_query = arguments.get("query") or arguments.get("input") or ""
                
                if user_query and rbac_context:
                    # Resolve accounts from the query
                    resolution_result = await self.account_resolver.resolve_account(
                        user_query=user_query,
                        rbac_context=rbac_context
                    )
                    
                    # Add resolved account information to arguments (always as lists)
                    if resolution_result.get("resolved_accounts"):
                        resolved_accounts = resolution_result["resolved_accounts"]
                        account_names = [acc.name for acc in resolved_accounts]
                        account_ids = [acc.id for acc in resolved_accounts]
                        # Always pass lists, even if single or empty
                        arguments["resolved_account_names"] = account_names
                        arguments["resolved_account_ids"] = account_ids
                        arguments["account_resolution_confidence"] = resolution_result.get("confidence", 0.0)
                        logger.info(
                            "Accounts resolved for function (multi-account)",
                            function=function_name,
                            resolved_account_names=account_names,
                            resolved_account_ids=account_ids,
                            confidence=resolution_result.get("confidence", 0.0)
                        )
                    
                    # If disambiguation is needed, add suggestions
                    if resolution_result.get("requires_disambiguation"):
                        suggestions = resolution_result.get("suggestions", [])
                        suggestion_names = [
                            sugg.get("account", {}).get("name", "")
                            for sugg in suggestions
                            if sugg.get("account")
                        ]
                        arguments["account_suggestions"] = suggestion_names
                        
                        logger.info(
                            "Account disambiguation needed",
                            function=function_name,
                            suggestions=suggestion_names
                        )
                    
                    # Track telemetry
                    await self.telemetry.track_account_resolution(
                        user_id=rbac_context.user_id,
                        query=user_query,
                        resolution_result=resolution_result,
                        function_name=function_name
                    )
            
            # Continue to next filter
            return await next_filter(context)
            
        except Exception as e:
            logger.error("Account resolution filter failed", error=str(e), function=function_name)
            # Continue execution even if account resolution fails
            return await next_filter(context)
    
    def _needs_account_resolution(
        self,
        function_name: str,
        arguments: KernelArguments
    ) -> bool:
        """
        Determine if a function needs account resolution.
        
        Args:
            function_name: Name of the function being invoked
            arguments: Function arguments
            
        Returns:
            True if account resolution is needed
        """
        # Functions that typically need account resolution
        account_functions = {
            "sql_query",
            "graph_query",
            "execute_sql",
            "execute_graph_query",
            "get_account_data",
            "search_accounts"
        }
        
        # Check if function name suggests account operations
        if function_name.lower() in account_functions:
            return True
        
        # Check if arguments contain queries that might reference accounts
        user_input = arguments.get("query") or arguments.get("input") or ""
        if user_input and any(keyword in user_input.lower() for keyword in [
            "account", "company", "customer", "client", "organization"
        ]):
            return True
        
        return False


class SafetyFilter:
    """Filter that enforces safety checks and content policies."""
    
    def __init__(self, telemetry_service: TelemetryService):
        """
        Initialize the safety filter.
        
        Args:
            telemetry_service: Service for telemetry tracking
        """
        self.telemetry = telemetry_service
        self.blocked_patterns = [
            "DROP TABLE", "DELETE FROM", "TRUNCATE", "ALTER TABLE",
            "CREATE USER", "GRANT", "REVOKE", "SHUTDOWN"
        ]
    
    async def filter_function_invocation(
        self,
        context: Dict[str, Any],
        next_filter: Any
    ) -> Any:
        """
        Pre-filter to enforce safety checks.
        
        Args:
            context: Invocation context
            next_filter: Next filter in the chain
            
        Returns:
            Filter result or raises exception if unsafe
        """
        try:
            function_name = context.get("function", {}).get("name", "unknown")
            arguments: KernelArguments = context.get("arguments", KernelArguments())
            rbac_context: RBACContext = context.get("rbac_context")
            
            # Check for dangerous SQL patterns
            query = arguments.get("query") or arguments.get("sql") or ""
            if query:
                query_upper = query.upper()
                for pattern in self.blocked_patterns:
                    if pattern in query_upper:
                        error_msg = f"Blocked unsafe SQL pattern: {pattern}"
                        logger.warning(
                            "Safety filter blocked unsafe query",
                            function=function_name,
                            pattern=pattern,
                            user_id=rbac_context.user_id if rbac_context else None
                        )
                        
                        # Track safety violation
                        if rbac_context:
                            await self.telemetry.track_safety_violation(
                                user_id=rbac_context.user_id,
                                violation_type="unsafe_sql",
                                details={"pattern": pattern, "function": function_name}
                            )
                        
                        raise ValueError(error_msg)
            
            # Continue to next filter
            return await next_filter(context)
            
        except Exception as e:
            logger.error("Safety filter error", error=str(e))
            raise


class TokenLimitFilter:
    """Filter that enforces token limits and manages context size."""
    
    def __init__(self, max_tokens: int = 4000, telemetry_service: TelemetryService = None):
        """
        Initialize the token limit filter.
        
        Args:
            max_tokens: Maximum tokens allowed for function input
            telemetry_service: Service for telemetry tracking
        """
        self.max_tokens = max_tokens
        self.telemetry = telemetry_service
    
    async def filter_function_invocation(
        self,
        context: Dict[str, Any],
        next_filter: Any
    ) -> Any:
        """
        Pre-filter to enforce token limits.
        
        Args:
            context: Invocation context
            next_filter: Next filter in the chain
            
        Returns:
            Filter result
        """
        try:
            function_name = context.get("function", {}).get("name", "unknown")
            arguments: KernelArguments = context.get("arguments", KernelArguments())
            rbac_context: RBACContext = context.get("rbac_context")
            
            # Estimate token count (rough approximation: 1 token ≈ 4 characters)
            total_chars = 0
            for key, value in arguments.items():
                if isinstance(value, str):
                    total_chars += len(value)
            
            estimated_tokens = total_chars // 4
            
            if estimated_tokens > self.max_tokens:
                logger.warning(
                    "Token limit exceeded",
                    function=function_name,
                    estimated_tokens=estimated_tokens,
                    max_tokens=self.max_tokens,
                    user_id=rbac_context.user_id if rbac_context else None
                )
                
                # Track token limit violation
                if self.telemetry and rbac_context:
                    await self.telemetry.track_event(
                        user_id=rbac_context.user_id,
                        event_type="token_limit_exceeded",
                        properties={
                            "function": function_name,
                            "estimated_tokens": estimated_tokens,
                            "max_tokens": self.max_tokens
                        }
                    )
                
                # Truncate input to fit within limits
                query = arguments.get("query") or arguments.get("input") or ""
                if query:
                    # Keep the first part of the query (most important)
                    max_chars = self.max_tokens * 4
                    if len(query) > max_chars:
                        arguments["query"] = query[:max_chars] + "... [truncated]"
                        logger.info("Query truncated to fit token limit")
            
            # Continue to next filter
            return await next_filter(context)
            
        except Exception as e:
            logger.error("Token limit filter error", error=str(e))
            return await next_filter(context)


class LoggingFilter:
    """Filter that logs function invocations for debugging and monitoring."""
    
    def __init__(self, telemetry_service: TelemetryService):
        """
        Initialize the logging filter.
        
        Args:
            telemetry_service: Service for telemetry tracking
        """
        self.telemetry = telemetry_service
    
    async def filter_function_invocation(
        self,
        context: Dict[str, Any],
        next_filter: Any
    ) -> Any:
        """
        Filter that logs function invocations.
        
        Args:
            context: Invocation context
            next_filter: Next filter in the chain
            
        Returns:
            Filter result
        """
        function_name = context.get("function", {}).get("name", "unknown")
        arguments: KernelArguments = context.get("arguments", KernelArguments())
        rbac_context: RBACContext = context.get("rbac_context")
        
        start_time = logger.info(
            "Function invocation started",
            function=function_name,
            user_id=rbac_context.user_id if rbac_context else None,
            argument_keys=list(arguments.keys())
        )
        
        try:
            # Execute next filter
            result = await next_filter(context)
            
            logger.info(
                "Function invocation completed",
                function=function_name,
                user_id=rbac_context.user_id if rbac_context else None,
                success=True
            )
            
            # Track successful invocation
            if self.telemetry and rbac_context:
                await self.telemetry.track_function_invocation(
                    user_id=rbac_context.user_id,
                    function_name=function_name,
                    success=True,
                    arguments=dict(arguments)
                )
            
            return result
            
        except Exception as e:
            logger.error(
                "Function invocation failed",
                function=function_name,
                user_id=rbac_context.user_id if rbac_context else None,
                error=str(e)
            )
            
            # Track failed invocation
            if self.telemetry and rbac_context:
                await self.telemetry.track_function_invocation(
                    user_id=rbac_context.user_id,
                    function_name=function_name,
                    success=False,
                    error=str(e),
                    arguments=dict(arguments)
                )
            
            raise


def create_filter_chain(
    account_resolver_service: AccountResolverService,
    telemetry_service: TelemetryService,
    max_tokens: int = 4000
) -> List[Any]:
    """
    Create a chain of invocation filters.
    
    Args:
        account_resolver_service: Account resolution service
        telemetry_service: Telemetry service
        max_tokens: Maximum tokens for input
        
    Returns:
        List of filters in execution order
    """
    return [
        LoggingFilter(telemetry_service),
        SafetyFilter(telemetry_service),
        TokenLimitFilter(max_tokens, telemetry_service),
        AccountResolutionFilter(account_resolver_service, telemetry_service)
    ]
