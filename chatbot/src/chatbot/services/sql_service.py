"""
SQL service for executing queries with RBAC filtering.

This service handles SQL query generation, validation, RBAC filter injection,
and execution against Fabric SQL endpoints or data warehouses.
"""

import re
import sqlparse
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import structlog
import pyodbc

from chatbot.models.rbac import RBACContext
from chatbot.models.result import QueryResult
from chatbot.repositories.sql_schema_repository import SQLSchemaRepository
from chatbot.services.cache_service import CacheService

logger = structlog.get_logger(__name__)


class SQLService:
    """Service for SQL query execution with security and validation."""
    
    def __init__(
        self,
        connection_string: str,
        schema_repository: SQLSchemaRepository,
        cache_service: CacheService,
        max_rows: int = 1000,
        query_timeout_seconds: int = 60
    ):
        """
        Initialize the SQL service.
        
        Args:
            connection_string: SQL Server connection string
            schema_repository: Repository for schema metadata
            cache_service: Cache service for query results
            max_rows: Maximum rows to return per query
            query_timeout_seconds: Query execution timeout
        """
        self.connection_string = connection_string
        self.schema_repository = schema_repository
        self.cache_service = cache_service
        self.max_rows = max_rows
        self.query_timeout_seconds = query_timeout_seconds
        
        # Allowed SQL operations (security whitelist)
        self.allowed_operations = {"SELECT", "WITH"}
        
        # Dangerous keywords to block
        self.blocked_keywords = {
            "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE",
            "TRUNCATE", "EXEC", "EXECUTE", "sp_", "xp_", "BACKUP",
            "RESTORE", "SHUTDOWN", "RECONFIGURE"
        }
    
    async def execute_query(
        self,
        query: str,
        rbac_context: RBACContext,
        parameters: Optional[Dict[str, Any]] = None,
        use_cache: bool = True
    ) -> QueryResult:
        """
        Execute SQL query with RBAC filtering and validation.
        
        Args:
            query: SQL query to execute
            rbac_context: User's RBAC context for filtering
            parameters: Optional query parameters
            use_cache: Whether to use query result caching
            
        Returns:
            Query result with data, metadata, and execution info
        """
        try:
            start_time = datetime.utcnow()
            
            logger.info(
                "Executing SQL query",
                user_id=rbac_context.user_id,
                query_length=len(query),
                has_parameters=bool(parameters)
            )
            
            # Step 1: Validate and sanitize the query
            validation_result = await self._validate_query(query)
            if not validation_result["is_valid"]:
                return QueryResult(
                    success=False,
                    error_message=f"Query validation failed: {validation_result['error']}",
                    execution_time_ms=0,
                    rows_affected=0,
                    data=[],
                    metadata={}
                )
            
            # Step 2: Inject RBAC filters
            filtered_query = await self._inject_rbac_filters(query, rbac_context)
            
            # Step 3: Check cache if enabled
            if use_cache:
                cached_result = await self.cache_service.get_query_result(
                    filtered_query, rbac_context, "sql"
                )
                if cached_result:
                    logger.info("Returning cached SQL result", user_id=rbac_context.user_id)
                    return QueryResult(**cached_result)
            
            # Step 4: Execute the query
            result = await self._execute_sql_query(filtered_query, parameters)
            
            # Step 5: Cache the result if successful
            if result.success and use_cache:
                await self.cache_service.set_query_result(
                    filtered_query, result.__dict__, rbac_context, "sql"
                )
            
            execution_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            result.execution_time_ms = execution_time
            
            logger.info(
                "SQL query completed",
                user_id=rbac_context.user_id,
                success=result.success,
                rows_returned=len(result.data) if result.data else 0,
                execution_time_ms=execution_time
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "Failed to execute SQL query",
                user_id=rbac_context.user_id,
                error=str(e)
            )
            return QueryResult(
                success=False,
                error_message=f"Query execution failed: {str(e)}",
                execution_time_ms=0,
                rows_affected=0,
                data=[],
                metadata={}
            )
    
    async def _validate_query(self, query: str) -> Dict[str, Any]:
        """
        Validate SQL query for security and syntax.
        
        Args:
            query: SQL query to validate
            
        Returns:
            Validation result with is_valid flag and error message
        """
        try:
            # Check for blocked keywords
            query_upper = query.upper()
            for keyword in self.blocked_keywords:
                if keyword in query_upper:
                    return {
                        "is_valid": False,
                        "error": f"Blocked keyword detected: {keyword}"
                    }
            
            # Parse the query to check structure
            try:
                parsed = sqlparse.parse(query)
                if not parsed:
                    return {
                        "is_valid": False,
                        "error": "Unable to parse SQL query"
                    }
                
                # Check that all statements are SELECT or WITH
                for statement in parsed:
                    stmt_type = statement.get_type()
                    if stmt_type not in self.allowed_operations:
                        return {
                            "is_valid": False,
                            "error": f"Operation '{stmt_type}' is not allowed"
                        }
                
            except Exception as parse_error:
                return {
                    "is_valid": False,
                    "error": f"SQL parsing error: {str(parse_error)}"
                }
            
            # Additional security checks
            if self._contains_dangerous_patterns(query):
                return {
                    "is_valid": False,
                    "error": "Query contains potentially dangerous patterns"
                }
            
            return {"is_valid": True, "error": None}
            
        except Exception as e:
            return {
                "is_valid": False,
                "error": f"Validation error: {str(e)}"
            }
    
    def _contains_dangerous_patterns(self, query: str) -> bool:
        """
        Check for dangerous SQL patterns.
        
        Args:
            query: SQL query to check
            
        Returns:
            True if dangerous patterns are found
        """
        dangerous_patterns = [
            r";\s*(DROP|DELETE|UPDATE|INSERT)",  # Multiple statements
            r"UNION\s+ALL\s+SELECT.*FROM\s+INFORMATION_SCHEMA",  # Schema probing
            r"@@\w+",  # System variables
            r"WAITFOR\s+DELAY",  # Time-based attacks
            r"OPENROWSET",  # File operations
            r"OPENDATASOURCE",  # External data access
        ]
        
        query_upper = query.upper()
        for pattern in dangerous_patterns:
            if re.search(pattern, query_upper):
                logger.warning("Dangerous SQL pattern detected", pattern=pattern)
                return True
        
        return False
    
    async def _inject_rbac_filters(self, query: str, rbac_context: RBACContext) -> str:
        """
        Inject RBAC filters into SQL query.
        
        Args:
            query: Original SQL query
            rbac_context: User's RBAC context
            
        Returns:
            Modified query with RBAC filters
        """
        try:
            # Get user's accessible accounts and data scope
            allowed_accounts = rbac_context.access_scope.allowed_accounts
            allowed_territories = rbac_context.access_scope.allowed_territories
            
            # If user is admin, don't inject filters
            if "admin" in rbac_context.roles or "global_admin" in rbac_context.roles:
                logger.debug("Admin user - no RBAC filters applied", user_id=rbac_context.user_id)
                return query
            
            # Parse the query to identify tables and add WHERE clauses
            filtered_query = query
            
            # Add account filtering if accounts are specified
            if allowed_accounts:
                account_filter = f"account_id IN ({','.join(f'\\'{acc}\\'' for acc in allowed_accounts)})"
                filtered_query = self._add_where_clause(filtered_query, account_filter)
            
            # Add territory filtering if territories are specified
            if allowed_territories:
                territory_filter = f"territory IN ({','.join(f'\\'{terr}\\'' for terr in allowed_territories)})"
                filtered_query = self._add_where_clause(filtered_query, territory_filter)
            
            # Add user-specific filtering (e.g., for sales reps seeing only their data)
            if "sales_rep" in rbac_context.roles:
                user_filter = f"owner_email = '{rbac_context.email}'"
                filtered_query = self._add_where_clause(filtered_query, user_filter)
            
            if filtered_query != query:
                logger.info(
                    "RBAC filters applied to query",
                    user_id=rbac_context.user_id,
                    filters_applied=True
                )
            
            return filtered_query
            
        except Exception as e:
            logger.error(
                "Failed to inject RBAC filters",
                user_id=rbac_context.user_id,
                error=str(e)
            )
            # Return original query if filtering fails
            return query
    
    def _add_where_clause(self, query: str, condition: str) -> str:
        """
        Add WHERE clause condition to SQL query.
        
        Args:
            query: Original SQL query
            condition: WHERE condition to add
            
        Returns:
            Modified query with added condition
        """
        try:
            # Simple approach: look for existing WHERE clause
            query_upper = query.upper()
            
            if " WHERE " in query_upper:
                # Add to existing WHERE clause with AND
                where_pos = query_upper.rfind(" WHERE ")
                before_where = query[:where_pos + 7]  # Include " WHERE "
                after_where = query[where_pos + 7:]
                
                return f"{before_where}({condition}) AND ({after_where})"
            else:
                # Add new WHERE clause
                # Find the main SELECT statement and add WHERE before ORDER BY, GROUP BY, etc.
                order_by_pos = query_upper.find(" ORDER BY")
                group_by_pos = query_upper.find(" GROUP BY")
                having_pos = query_upper.find(" HAVING")
                
                # Find the earliest clause position
                clause_positions = [pos for pos in [order_by_pos, group_by_pos, having_pos] if pos > 0]
                insert_pos = min(clause_positions) if clause_positions else len(query)
                
                before_clause = query[:insert_pos]
                after_clause = query[insert_pos:]
                
                return f"{before_clause} WHERE {condition}{after_clause}"
                
        except Exception as e:
            logger.error("Failed to add WHERE clause", condition=condition, error=str(e))
            return query
    
    async def _execute_sql_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> QueryResult:
        """
        Execute SQL query against the database.
        
        Args:
            query: SQL query to execute
            parameters: Optional query parameters
            
        Returns:
            Query execution result
        """
        try:
            # Add row limit to prevent large result sets
            limited_query = self._add_row_limit(query)
            
            # Execute the query
            with pyodbc.connect(
                self.connection_string,
                timeout=self.query_timeout_seconds
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(limited_query)
                    
                    # Fetch results
                    columns = [desc[0] for desc in cursor.description] if cursor.description else []
                    rows = cursor.fetchall()
                    
                    # Convert rows to list of dictionaries
                    data = []
                    for row in rows:
                        row_dict = {columns[i]: row[i] for i in range(len(columns))}
                        data.append(row_dict)
                    
                    return QueryResult(
                        success=True,
                        data=data,
                        metadata={
                            "columns": columns,
                            "row_count": len(data),
                            "query": limited_query,
                            "has_more_data": len(data) >= self.max_rows
                        },
                        rows_affected=len(data),
                        execution_time_ms=0,  # Will be set by caller
                        error_message=None
                    )
                    
        except pyodbc.Error as db_error:
            logger.error("Database error during query execution", error=str(db_error))
            return QueryResult(
                success=False,
                error_message=f"Database error: {str(db_error)}",
                data=[],
                metadata={},
                rows_affected=0,
                execution_time_ms=0
            )
        except Exception as e:
            logger.error("Unexpected error during query execution", error=str(e))
            return QueryResult(
                success=False,
                error_message=f"Execution error: {str(e)}",
                data=[],
                metadata={},
                rows_affected=0,
                execution_time_ms=0
            )
    
    def _add_row_limit(self, query: str) -> str:
        """
        Add row limit to query if not already present.
        
        Args:
            query: Original SQL query
            
        Returns:
            Query with row limit
        """
        query_upper = query.upper().strip()
        
        # Check if TOP clause already exists
        if "SELECT TOP" in query_upper:
            return query
        
        # Check if ORDER BY exists for OFFSET/FETCH
        if "OFFSET" in query_upper and "FETCH" in query_upper:
            return query
        
        # Add TOP clause to SELECT statements
        if query_upper.startswith("SELECT"):
            return query.replace("SELECT", f"SELECT TOP {self.max_rows}", 1)
        elif query_upper.startswith("WITH"):
            # For CTE queries, add TOP to the final SELECT
            # This is a simplified approach - more complex CTEs might need better handling
            lines = query.split('\n')
            for i, line in enumerate(lines):
                if line.strip().upper().startswith("SELECT") and "TOP" not in line.upper():
                    lines[i] = line.replace("SELECT", f"SELECT TOP {self.max_rows}", 1)
                    break
            return '\n'.join(lines)
        
        return query
    
    async def get_table_preview(
        self,
        schema_name: str,
        table_name: str,
        rbac_context: RBACContext,
        limit: int = 10
    ) -> QueryResult:
        """
        Get a preview of table data.
        
        Args:
            schema_name: Database schema name
            table_name: Table name
            rbac_context: User's RBAC context
            limit: Number of rows to preview
            
        Returns:
            Query result with preview data
        """
        preview_query = f"SELECT TOP {limit} * FROM [{schema_name}].[{table_name}]"
        
        return await self.execute_query(
            preview_query,
            rbac_context,
            use_cache=True
        )
