"""
Microsoft Fabric lakehouse client for retrieving document content.

This client handles connections to Microsoft Fabric lakehouse to retrieve
document text content that has been processed by the data engineering team.
"""

import structlog
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
import pyodbc
import httpx
from azure.identity import DefaultAzureCredential

logger = structlog.get_logger(__name__)


class FabricLakehouseClient:
    """Client for Microsoft Fabric lakehouse operations."""
    
    def __init__(
        self,
        lakehouse_sql_endpoint: str,
        lakehouse_database: str,
        lakehouse_workspace_id: Optional[str] = None,
        connection_timeout: int = 30,
        dev_mode: bool = False
    ):
        """
        Initialize the Fabric lakehouse client.
        
        Args:
            lakehouse_sql_endpoint: SQL endpoint for the lakehouse
            lakehouse_database: Database name in the lakehouse
            lakehouse_workspace_id: Optional workspace ID for REST API calls
            connection_timeout: Connection timeout in seconds
            dev_mode: If True, returns dummy data instead of connecting to real lakehouse
        """
        self.lakehouse_sql_endpoint = lakehouse_sql_endpoint
        self.lakehouse_database = lakehouse_database
        self.lakehouse_workspace_id = lakehouse_workspace_id
        self.connection_timeout = connection_timeout
        self.dev_mode = dev_mode
        
        if not self.dev_mode:
            self.credential = DefaultAzureCredential()
            # Build SQL connection string using Azure AD authentication
            self.connection_string = self._build_connection_string()
        else:
            logger.info("Fabric client running in dev mode - using dummy data")
    
    def _get_dummy_document_data(self) -> List[Dict[str, Any]]:
        """Generate dummy document data for testing."""
        return [
            {
                "file_id": "doc_001",
                "account_id": "acc_salesforce",
                "file_name": "Salesforce_Master_Agreement_2024.pdf",
                "file_text": "This Master Service Agreement is entered into between Salesforce and the Customer. The agreement covers software licensing, support services, and data processing terms. Key provisions include: 1) Service Level Agreements with 99.5% uptime guarantee, 2) Data security and privacy protections, 3) Intellectual property rights, 4) Termination clauses and data export procedures.",
                "file_summary": "Master Service Agreement between Salesforce and customer covering licensing, support, and data processing terms with SLA guarantees.",
                "sharepoint_url": "https://company.sharepoint.com/contracts/Salesforce_Master_Agreement_2024.pdf",
                "last_modified": datetime.now(),
                "content_type": "application/pdf",
                "file_size": 245760
            },
            {
                "file_id": "doc_002", 
                "account_id": "acc_microsoft",
                "file_name": "Microsoft_Enterprise_Agreement_2024.pdf",
                "file_text": "Microsoft Enterprise Agreement for software licensing and cloud services. This agreement provides volume licensing for Microsoft 365, Azure, and other enterprise products. Terms include: 1) Volume discount pricing, 2) Annual true-up process, 3) Software Assurance benefits, 4) Usage rights and compliance obligations.",
                "file_summary": "Microsoft Enterprise Agreement covering volume licensing for Microsoft 365, Azure and enterprise products with volume discounts.",
                "sharepoint_url": "https://company.sharepoint.com/contracts/Microsoft_Enterprise_Agreement_2024.pdf",
                "last_modified": datetime.now(),
                "content_type": "application/pdf", 
                "file_size": 342150
            },
            {
                "file_id": "doc_003",
                "account_id": "acc_oracle",
                "file_name": "Oracle_Database_License_Agreement.pdf",
                "file_text": "Oracle Database licensing agreement for enterprise deployment. Covers Oracle Database Enterprise Edition licensing for production and development environments. Key terms: 1) Named User Plus licensing model, 2) High Availability and disaster recovery rights, 3) Development and testing usage permissions, 4) Audit and compliance requirements.",
                "file_summary": "Oracle Database Enterprise Edition licensing agreement with Named User Plus model and high availability rights.",
                "sharepoint_url": "https://company.sharepoint.com/contracts/Oracle_Database_License_Agreement.pdf",
                "last_modified": datetime.now(),
                "content_type": "application/pdf",
                "file_size": 189440
            }
        ]
    
    def _build_connection_string(self) -> str:
        """Build connection string for lakehouse SQL endpoint."""
        return (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={self.lakehouse_sql_endpoint};"
            f"DATABASE={self.lakehouse_database};"
            f"Authentication=ActiveDirectoryMsi;"
            f"Connection Timeout={self.connection_timeout};"
            f"Encrypt=yes;"
            f"TrustServerCertificate=no;"
        )
    
    async def get_document_content(
        self,
        document_id: str,
        account_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve document content from the lakehouse.
        
        Args:
            document_id: Document ID to retrieve
            account_id: Optional account ID for filtering
            
        Returns:
            Dictionary with document content and metadata
        """
        # Return dummy data in dev mode
        if self.dev_mode:
            dummy_docs = self._get_dummy_document_data()
            for doc in dummy_docs:
                if doc["file_id"] == document_id:
                    if account_id is None or doc["account_id"] == account_id:
                        logger.info(f"Returning dummy document data for {document_id}")
                        return doc
            logger.info(f"No dummy document found for {document_id}")
            return None
        
        try:
            query = """
            SELECT 
                file_id,
                account_id,
                file_name,
                file_text,
                file_summary,
                sharepoint_url,
                last_modified,
                content_type,
                file_size
            FROM contracts_text 
            WHERE file_id = ?
            """
            
            params = [document_id]
            
            # Add account filter if provided
            if account_id:
                query += " AND account_id = ?"
                params.append(account_id)
            
            result = await self._execute_query(query, params)
            
            if result:
                return {
                    "file_id": result[0]["file_id"],
                    "account_id": result[0]["account_id"],
                    "file_name": result[0]["file_name"],
                    "file_text": result[0]["file_text"],
                    "file_summary": result[0]["file_summary"],
                    "sharepoint_url": result[0]["sharepoint_url"],
                    "last_modified": result[0]["last_modified"],
                    "content_type": result[0]["content_type"],
                    "file_size": result[0]["file_size"]
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get document content for {document_id}: {e}")
            return None
    
    async def get_documents_by_ids(
        self,
        document_ids: List[str],
        account_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve multiple documents by their IDs.
        
        Args:
            document_ids: List of document IDs to retrieve
            account_id: Optional account ID for filtering
            
        Returns:
            List of document dictionaries
        """
        # Return dummy data in dev mode
        if self.dev_mode:
            dummy_docs = self._get_dummy_document_data()
            matched_docs = []
            for doc_id in document_ids:
                for doc in dummy_docs:
                    if doc["file_id"] == doc_id:
                        if account_id is None or doc["account_id"] == account_id:
                            matched_docs.append(doc)
                            break
            logger.info(f"Returning {len(matched_docs)} dummy documents")
            return matched_docs
        
        try:
            if not document_ids:
                return []
            
            # Create parameter placeholders for the IN clause
            placeholders = ",".join("?" * len(document_ids))
            
            query = f"""
            SELECT 
                file_id,
                account_id,
                file_name,
                file_text,
                file_summary,
                sharepoint_url,
                last_modified,
                content_type,
                file_size
            FROM contracts_text 
            WHERE file_id IN ({placeholders})
            """
            
            params = document_ids.copy()
            
            # Add account filter if provided
            if account_id:
                query += " AND account_id = ?"
                params.append(account_id)
            
            results = await self._execute_query(query, params)
            
            documents = []
            for row in results:
                documents.append({
                    "file_id": row["file_id"],
                    "account_id": row["account_id"],
                    "file_name": row["file_name"],
                    "file_text": row["file_text"],
                    "file_summary": row["file_summary"],
                    "sharepoint_url": row["sharepoint_url"],
                    "last_modified": row["last_modified"],
                    "content_type": row["content_type"],
                    "file_size": row["file_size"]
                })
            
            return documents
            
        except Exception as e:
            logger.error(f"Failed to get documents by IDs: {e}")
            return []
    
    async def get_account_documents(
        self,
        account_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all documents for a specific account.
        
        Args:
            account_id: Account ID to get documents for
            limit: Maximum number of documents to return
            
        Returns:
            List of document dictionaries
        """
        try:
            query = """
            SELECT TOP (?)
                file_id,
                account_id,
                file_name,
                file_text,
                file_summary,
                sharepoint_url,
                last_modified,
                content_type,
                file_size
            FROM contracts_text 
            WHERE account_id = ?
            ORDER BY last_modified DESC
            """
            
            results = await self._execute_query(query, [limit, account_id])
            
            documents = []
            for row in results:
                documents.append({
                    "file_id": row["file_id"],
                    "account_id": row["account_id"],
                    "file_name": row["file_name"],
                    "file_text": row["file_text"],
                    "file_summary": row["file_summary"],
                    "sharepoint_url": row["sharepoint_url"],
                    "last_modified": row["last_modified"],
                    "content_type": row["content_type"],
                    "file_size": row["file_size"]
                })
            
            return documents
            
        except Exception as e:
            logger.error(f"Failed to get documents for account {account_id}: {e}")
            return []
    
    async def search_documents(
        self,
        search_text: str,
        account_id: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Search documents by text content.
        
        Args:
            search_text: Text to search for in document content
            account_id: Optional account ID for filtering
            limit: Maximum number of results to return
            
        Returns:
            List of matching document dictionaries
        """
        try:
            base_query = """
            SELECT TOP (?)
                file_id,
                account_id,
                file_name,
                file_text,
                file_summary,
                sharepoint_url,
                last_modified,
                content_type,
                file_size
            FROM contracts_text 
            WHERE (
                CONTAINS(file_text, ?) 
                OR CONTAINS(file_name, ?)
                OR CONTAINS(file_summary, ?)
            )
            """
            
            params = [limit, search_text, search_text, search_text]
            
            if account_id:
                base_query += " AND account_id = ?"
                params.append(account_id)
            
            base_query += " ORDER BY last_modified DESC"
            
            results = await self._execute_query(base_query, params)
            
            documents = []
            for row in results:
                documents.append({
                    "file_id": row["file_id"],
                    "account_id": row["account_id"],
                    "file_name": row["file_name"],
                    "file_text": row["file_text"],
                    "file_summary": row["file_summary"],
                    "sharepoint_url": row["sharepoint_url"],
                    "last_modified": row["last_modified"],
                    "content_type": row["content_type"],
                    "file_size": row["file_size"]
                })
            
            return documents
            
        except Exception as e:
            logger.error(f"Failed to search documents: {e}")
            return []
    
    async def get_document_chunks(
        self,
        document_id: str,
        chunk_size: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Get document content split into chunks.
        
        Args:
            document_id: Document ID to chunk
            chunk_size: Size of each chunk in characters
            
        Returns:
            List of document chunks with metadata
        """
        try:
            document = await self.get_document_content(document_id)
            
            if not document or not document.get("file_text"):
                return []
            
            text = document["file_text"]
            chunks = []
            
            for i in range(0, len(text), chunk_size):
                chunk_text = text[i:i + chunk_size]
                chunks.append({
                    "file_id": document["file_id"],
                    "chunk_index": i // chunk_size,
                    "chunk_text": chunk_text,
                    "chunk_start": i,
                    "chunk_end": min(i + chunk_size, len(text)),
                    "file_name": document["file_name"],
                    "account_id": document["account_id"],
                    "sharepoint_url": document["sharepoint_url"]
                })
            
            return chunks
            
        except Exception as e:
            logger.error(f"Failed to get document chunks for {document_id}: {e}")
            return []
    
    async def _execute_query(
        self,
        query: str,
        params: Optional[List[Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute SQL query against the lakehouse.
        
        Args:
            query: SQL query to execute
            params: Optional query parameters
            
        Returns:
            List of result dictionaries
        """
        try:
            with pyodbc.connect(self.connection_string) as connection:
                with connection.cursor() as cursor:
                    if params:
                        cursor.execute(query, params)
                    else:
                        cursor.execute(query)
                    
                    # Get column names
                    columns = [desc[0] for desc in cursor.description] if cursor.description else []
                    
                    # Fetch all rows
                    rows = cursor.fetchall()
                    
                    # Convert to list of dictionaries
                    results = []
                    for row in rows:
                        row_dict = {columns[i]: row[i] for i in range(len(columns))}
                        results.append(row_dict)
                    
                    return results
                    
        except Exception as e:
            logger.error(f"Failed to execute query: {e}")
            raise
    
    async def test_connection(self) -> bool:
        """
        Test the connection to the lakehouse.
        
        Returns:
            True if connection is successful, False otherwise
        """
        try:
            result = await self._execute_query("SELECT 1 as test_value")
            return len(result) > 0 and result[0]["test_value"] == 1
            
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
    
    async def get_table_info(self, table_name: str = "contracts_text") -> Dict[str, Any]:
        """
        Get information about a table in the lakehouse.
        
        Args:
            table_name: Name of the table to inspect
            
        Returns:
            Dictionary with table information
        """
        try:
            # Get column information
            columns_query = """
            SELECT 
                COLUMN_NAME,
                DATA_TYPE,
                IS_NULLABLE,
                COLUMN_DEFAULT
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION
            """
            
            columns = await self._execute_query(columns_query, [table_name])
            
            # Get row count
            count_query = f"SELECT COUNT(*) as row_count FROM {table_name}"
            count_result = await self._execute_query(count_query)
            row_count = count_result[0]["row_count"] if count_result else 0
            
            return {
                "table_name": table_name,
                "columns": columns,
                "row_count": row_count
            }
            
        except Exception as e:
            logger.error(f"Failed to get table info for {table_name}: {e}")
            return {"table_name": table_name, "columns": [], "row_count": 0}
    
    async def close(self):
        """Close the client and clean up resources."""
        # No specific cleanup needed for ODBC connections as they auto-close
        logger.info("Fabric lakehouse client closed")