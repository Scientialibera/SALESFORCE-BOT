"""
SQL agent for structured data queries.

This agent specializes in generating and executing SQL queries against
the data lakehouse containing structured Salesforce and SharePoint data.
The data engineering team extracts and loads this data from the source systems.
It always resolves account names first before executing SQL queries to ensure accurate results.
"""

import json
from typing import Any, Dict, List, Optional
import structlog

from semantic_kernel import Kernel
from semantic_kernel.functions import KernelPlugin
from semantic_kernel.functions import KernelFunction, kernel_function

from chatbot.services.sql_service import SQLService
from chatbot.services.account_resolver_service import AccountResolverService
from chatbot.services.rbac_service import RBACService
from chatbot.services.telemetry_service import TelemetryService
 

logger = structlog.get_logger(__name__)


class SQLAgent:
    """Semantic Kernel agent for SQL-based queries (RBAC handled by WHERE clause injection outside this class)."""

    def __init__(
        self,
        kernel: Kernel,
        sql_service: SQLService,
        account_resolver_service: AccountResolverService,
        telemetry_service: TelemetryService
    ):
        self.kernel = kernel
        self.sql_service = sql_service
        self.account_resolver_service = account_resolver_service
        self.telemetry_service = telemetry_service
        self._register_plugin()

    def _register_plugin(self):
        try:
            plugin = KernelPlugin.from_object(plugin_instance=self, plugin_name="sql_agent")
            self.kernel.add_plugin(plugin)
            logger.info("SQL agent plugin registered with kernel")
        except Exception as e:
            logger.error("Failed to register SQL agent plugin", error=str(e))
            logger.info("SQL agent plugin registration skipped - using basic functionality")

    @kernel_function(
        description="Executes a natural language query against the SQL database.",
        name="sql_agent"
    )
    async def sql_agent(self, user_query: str, data_types: list = None, limit: int = 100, accounts_mentioned: list = None, dev_mode: bool = False) -> str:
        """
        Executes a natural language query against the SQL database.
        Args:
            user_query (str): The user's natural language query.
            data_types (list, optional): List of data types to query.
            limit (int, optional): Max number of results.
            accounts_mentioned (list, optional): List of resolved account IDs to filter the query.
            dev_mode (bool, optional): If True, enables verbose output for debugging.
        Returns:
            str: JSON-encoded query result.
        """
        tracking_id = None
        try:
            tracking_id = await self.telemetry_service.start_performance_tracking("sql_agent_query")
            # Compose the query using the provided parameters
            query_result = await self.sql_service.execute_natural_language_query(
                user_query=user_query,
                data_types=data_types,
                limit=limit,
                accounts_mentioned=accounts_mentioned,
                dev_mode=dev_mode
            )
            await self.telemetry_service.end_performance_tracking(tracking_id, success=True)
            return query_result
        except Exception as e:
            logger.error(f"SQLAgent query failed: {e}")
            if tracking_id:
                await self.telemetry_service.end_performance_tracking(tracking_id, success=False, error=str(e))
            raise
            # Removed legacy code fragment
