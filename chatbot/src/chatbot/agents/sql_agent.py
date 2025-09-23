"""
Simplified SQL agent for structured data queries.

This agent specializes in generating and executing SQL queries against
the data lakehouse containing structured Salesforce and SharePoint data.
It always resolves account names first before executing SQL queries to ensure accurate results.
"""

import json
from typing import Any, Dict, List, Optional
import structlog

from chatbot.services.sql_service import SQLService
from chatbot.services.account_resolver_service import AccountResolverService
from chatbot.services.telemetry_service import TelemetryService

logger = structlog.get_logger(__name__)


class SQLAgent:
    """Simplified SQL agent for SQL-based queries."""

    def __init__(
        self,
        sql_service: SQLService,
        account_resolver_service: AccountResolverService,
        telemetry_service: TelemetryService
    ):
        self.sql_service = sql_service
        self.account_resolver_service = account_resolver_service
        self.telemetry_service = telemetry_service

    async def sql_agent(self, query: str, accounts_mentioned: list = None) -> str:
        """
        Query structured data from the SQL database.

        Args:
            query (str): User's natural language query about sales data or business metrics
            accounts_mentioned (list, optional): List of account names/aliases mentioned in the query, or null if none

        Returns:
            str: JSON-encoded query result
        """
        tracking_id = None
        try:
            tracking_id = await self.telemetry_service.start_performance_tracking("sql_agent_query")

            # Ensure accounts_mentioned is always a list (even if None or single)
            if accounts_mentioned is None:
                accounts_mentioned = []
            elif not isinstance(accounts_mentioned, list):
                accounts_mentioned = [accounts_mentioned]

            logger.info(
                "SQL agent function called",
                query=query,
                accounts_mentioned=accounts_mentioned
            )

            # Execute the query using the SQL service
            query_result = await self.sql_service.execute_natural_language_query(
                user_query=query,
                data_types=None,  # Let service determine
                limit=100,  # Default limit
                accounts_mentioned=accounts_mentioned,
                dev_mode=False
            )

            await self.telemetry_service.end_performance_tracking(tracking_id, success=True)
            return query_result

        except Exception as e:
            logger.error("SQL agent function failed", error=str(e), query=query)
            if tracking_id:
                await self.telemetry_service.end_performance_tracking(tracking_id, success=False, error_details={"error": str(e)})
            raise
