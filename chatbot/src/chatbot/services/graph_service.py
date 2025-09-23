"""
Concise GraphService

Minimal implementation that focuses on executing Gremlin queries through the
provided `GremlinClient` and returning small, predictable `QueryResult`
objects. It intentionally removes document enrichment and complex formatters
while preserving the public API used elsewhere.
"""
from typing import Any, Dict, List, Optional
from datetime import datetime
import structlog

from chatbot.clients.gremlin_client import GremlinClient
from chatbot.models.rbac import RBACContext
from chatbot.models.result import QueryResult
from chatbot.services.unified_service import UnifiedDataService

logger = structlog.get_logger(__name__)


class GraphService:
    """Minimal graph service: run Gremlin queries and return formatted results."""

    def __init__(
        self,
        gremlin_client: GremlinClient,
        cache_service: UnifiedDataService,
        max_results: int = 100,
        max_traversal_depth: int = 5,
    ):
        self.gremlin_client = gremlin_client
        self.unified_data_service = cache_service
        self.max_results = max_results
        self.max_traversal_depth = max_traversal_depth

    async def _cache_get(self, key: str, rbac_context: RBACContext) -> Optional[Dict[str, Any]]:
        try:
            return await self.unified_data_service.get_query_result(key, rbac_context, "graph")
        except Exception:
            return None

    async def _cache_set(self, key: str, value: Dict[str, Any], rbac_context: RBACContext) -> None:
        try:
            await self.unified_data_service.set_query_result(key, value, rbac_context, "graph")
        except Exception:
            logger.debug("Failed to set graph cache", key=key)

    def _format_results(self, raw: Any) -> List[Dict[str, Any]]:
        """
        Turn raw Gremlin rows into plain dicts.

        Handles:
        - already-dict rows
        - path-like rows exposing `.objects`
        - vertex/edge-like objects with `id`, `label`, `properties`
        - falls back to stringifying unknown objects
        """
        out: List[Dict[str, Any]] = []
        if not raw:
            return out

        for row in raw:
            try:
                if isinstance(row, dict):
                    out.append(row)
                    continue

                objs = getattr(row, "objects", None)
                if objs:
                    path = []
                    for o in objs:
                        if isinstance(o, dict):
                            path.append(o)
                        else:
                            path.append(
                                {
                                    "id": getattr(o, "id", str(o)),
                                    "label": getattr(o, "label", None),
                                    "properties": getattr(o, "properties", {}),
                                }
                            )
                    out.append({"path": path})
                    continue

                if hasattr(row, "id"):
                    out.append(
                        {
                            "id": getattr(row, "id", str(row)),
                            "label": getattr(row, "label", None),
                            "properties": getattr(row, "properties", {}),
                        }
                    )
                    continue

                out.append({"value": str(row)})
            except Exception:
                out.append({"value": str(row)})
        return out

    async def find_account_relationships(
        self,
        account_id: str,
        rbac_context: RBACContext,
        relationship_types: Optional[List[str]] = None,
        max_depth: Optional[int] = None,
    ) -> QueryResult:
        """Return related vertices/paths for a single account."""
        start = datetime.utcnow()
        try:
            depth = min(max_depth or self.max_traversal_depth, self.max_traversal_depth)
            # Basic traversal: start from account vertex and traverse both directions up to depth
            gremlin = f"g.V().has('account','id','{account_id}').repeat(both()).times({depth}).limit({self.max_results})"

            cache_key = f"graph:relationships:{account_id}:{depth}:{relationship_types}"
            cached = await self._cache_get(cache_key, rbac_context)
            if cached:
                return QueryResult(**cached)

            raw = await self.gremlin_client.execute_query(gremlin)
            data = self._format_results(raw)

            elapsed = (datetime.utcnow() - start).total_seconds() * 1000
            result = QueryResult(
                success=True,
                data=data,
                metadata={"account_id": account_id, "depth": depth},
                rows_affected=len(data),
                execution_time_ms=elapsed,
            )

            await self._cache_set(cache_key, result.__dict__, rbac_context)
            return result

        except Exception as e:
            logger.error("Graph query failed", account_id=account_id, error=str(e))
            return QueryResult(success=False, error_message=str(e), data=[], metadata={}, rows_affected=0, execution_time_ms=0)

    async def find_relationships(
        self,
        account_ids: List[str],
        rbac_context: RBACContext,
        relationship_types: Optional[List[str]] = None,
        max_depth: int = 2,
    ) -> List[Dict[str, Any]]:
        """Find relationships for multiple accounts by aggregating single-account calls."""
        out: List[Dict[str, Any]] = []
        for aid in account_ids:
            res = await self.find_account_relationships(aid, rbac_context, relationship_types, max_depth)
            if res and res.success and res.data:
                out.extend(res.data)
        return out

    async def find_shortest_path(self, from_account: str, to_account: str, rbac_context: RBACContext, relationship_types: Optional[List[str]] = None) -> QueryResult:
        """Simple shortest-path using repeated traversal (limited depth)."""
        try:
            gremlin = f"g.V().has('account','id','{from_account}').repeat(both()).until(has('account','id','{to_account}')).path().limit(1)"
            raw = await self.gremlin_client.execute_query(gremlin)
            data = self._format_results(raw)
            return QueryResult(success=True, data=data, metadata={"from": from_account, "to": to_account}, rows_affected=len(data), execution_time_ms=0)
        except Exception as e:
            return QueryResult(success=False, error_message=str(e), data=[], metadata={}, rows_affected=0, execution_time_ms=0)

    async def get_account_neighbors(self, account_id: str, rbac_context: RBACContext, neighbor_types: Optional[List[str]] = None) -> QueryResult:
        """Return immediate neighbors of an account (one hop)."""
        try:
            gremlin = f"g.V().has('account','id','{account_id}').both().limit({self.max_results})"
            raw = await self.gremlin_client.execute_query(gremlin)
            data = self._format_results(raw)
            return QueryResult(success=True, data=data, metadata={"account_id": account_id}, rows_affected=len(data), execution_time_ms=0)
        except Exception as e:
            return QueryResult(success=False, error_message=str(e), data=[], metadata={}, rows_affected=0, execution_time_ms=0)

    async def find_neighbors(self, entity_id: str, rbac_context: RBACContext, relationship_types: Optional[List[str]] = None, limit: int = 50) -> List[Dict[str, Any]]:
        res = await self.get_account_neighbors(entity_id, rbac_context, relationship_types)
        return res.data if res and res.success else []

    async def find_relationships_with_documents(
        self,
        account_ids: List[str],
        rbac_context: RBACContext,
        relationship_types: Optional[List[str]] = None,
        max_depth: int = 2,
        include_document_content: bool = True,
    ) -> Dict[str, Any]:
        """Compatibility wrapper: return relationships and an empty documents_content map (no enrichment)."""
        relationships = await self.find_relationships(account_ids, rbac_context, relationship_types, max_depth)
        return {
            "success": True,
            "account_ids": account_ids,
            "relationships": relationships,
            "documents_found": 0,
            "documents_content": {},
            "metadata": {"relationship_count": len(relationships), "execution_time_ms": 0, "includes_content": False},
        }