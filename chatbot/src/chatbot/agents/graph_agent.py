"""
Simplified Graph agent for relationship-based queries using Cosmos DB.

This agent specializes in querying the Cosmos DB graph database to find relationships,
patterns, and connections between entities in the Salesforce and SharePoint data.
"""

import json
import structlog

logger = structlog.get_logger(__name__)


class GraphAgent:
    """Simplified Graph agent for graph-based relationship queries."""

    def __init__(self, graph_service, telemetry_service):
        self.graph_service = graph_service
        self.telemetry_service = telemetry_service

    async def graph_agent(self, query: str, accounts_mentioned: list = None) -> str:
        """
        Query relationships and connections from the graph database.

        Args:
            query (str): User's natural language query about relationships, connections, or account information
            accounts_mentioned (list, optional): List of account names/aliases mentioned in the query, or null if none

        Returns:
            str: JSON-encoded query result
        """
        tracking_id = None
        try:
            tracking_id = await self.telemetry_service.start_performance_tracking("graph_agent_query")

            # Ensure accounts_mentioned is always a list (even if None or single)
            if accounts_mentioned is None:
                accounts_mentioned = []
            elif not isinstance(accounts_mentioned, list):
                accounts_mentioned = [accounts_mentioned]

            logger.info(
                "Graph agent function called",
                query=query,
                accounts_mentioned=accounts_mentioned
            )

            # For now, return a mock response until graph service is fully implemented
            result = {
                "success": True,
                "relationships": [
                    {
                        "from": "Microsoft Corporation",
                        "to": "John Doe",
                        "relationship": "has_contact",
                        "properties": {"role": "Sales Manager", "email": "john.doe@microsoft.com"}
                    }
                ] if accounts_mentioned else [],
                "documents": [
                    {
                        "name": "Partnership Agreement",
                        "summary": "Strategic partnership document",
                        "url": "https://example.com/doc.pdf"
                    }
                ] if accounts_mentioned else [],
                "query": query,
                "accounts_mentioned": accounts_mentioned,
                "message": "Graph agent executed successfully"
            }

            await self.telemetry_service.end_performance_tracking(tracking_id, success=True)
            return json.dumps(result)

        except Exception as e:
            logger.error("Graph agent function failed", error=str(e), query=query)
            if tracking_id:
                await self.telemetry_service.end_performance_tracking(tracking_id, success=False, error_details={"error": str(e)})

            error_result = {
                "success": False,
                "error": f"Graph agent failed: {str(e)}",
                "query": query,
                "accounts_mentioned": accounts_mentioned
            }
            return json.dumps(error_result)
