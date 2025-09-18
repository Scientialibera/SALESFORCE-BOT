"""SharePoint service for managing document discovery and access."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, AsyncGenerator, Set
from ..clients.sharepoint_client import SharePointClient, SharePointFile
from ..models.document import Document, DocumentStatus, DocumentType, DocumentMetadata
from ..repositories.processed_files_repository import ProcessedFilesRepository


logger = logging.getLogger(__name__)


class SharePointService:
    """Service for managing SharePoint document operations."""
    
    def __init__(self, sharepoint_client: SharePointClient,
                 processed_files_repo: ProcessedFilesRepository = None):
        """Initialize the SharePoint service."""
        self.sharepoint_client = sharepoint_client
        self.processed_files_repo = processed_files_repo
        self._site_cache: Dict[str, Any] = {}
    
    async def discover_documents(self, site_urls: List[str],
                               file_extensions: List[str] = None,
                               modified_since: datetime = None,
                               account_filter: str = None) -> AsyncGenerator[Tuple[SharePointFile, Document], None]:
        """Discover documents from SharePoint sites."""
        try:
            file_extensions = file_extensions or [".pdf", ".docx", ".txt", ".md"]
            
            logger.info(f"Starting document discovery for {len(site_urls)} sites")
            
            processed_count = 0
            
            for site_url in site_urls:
                logger.info(f"Discovering documents in site: {site_url}")
                
                try:
                    # Get site information
                    site_info = await self._get_site_info(site_url)
                    if not site_info:
                        logger.warning(f"Could not access site: {site_url}")
                        continue
                    
                    site_id = site_info.get("id")
                    if not site_id:
                        logger.warning(f"No site ID found for: {site_url}")
                        continue
                    
                    # List files in the site
                    async for file in self.sharepoint_client.list_files_in_site(
                        site_id=site_id,
                        file_extensions=file_extensions,
                        modified_since=modified_since
                    ):
                        # Apply account filter if specified
                        if account_filter and not self._matches_account_filter(file, account_filter):
                            continue
                        
                        # Check if file should be processed
                        should_process, reason = await self._should_process_file(file)
                        if not should_process:
                            logger.debug(f"Skipping file {file.name}: {reason}")
                            continue
                        
                        # Create document model
                        document = await self._create_document_from_file(file, site_url)
                        if document:
                            processed_count += 1
                            yield file, document
                            
                            if processed_count % 100 == 0:
                                logger.info(f"Discovered {processed_count} documents so far")
                
                except Exception as e:
                    logger.error(f"Failed to discover documents in site {site_url}: {e}")
                    continue
            
            logger.info(f"Document discovery completed. Found {processed_count} documents to process")
            
        except Exception as e:
            logger.error(f"Failed to discover documents: {e}")
            raise
    
    async def _get_site_info(self, site_url: str) -> Optional[Dict[str, Any]]:
        """Get and cache site information."""
        try:
            if site_url in self._site_cache:
                return self._site_cache[site_url]
            
            site_info = await self.sharepoint_client.get_site_by_url(site_url)
            if site_info:
                self._site_cache[site_url] = site_info
            
            return site_info
            
        except Exception as e:
            logger.error(f"Failed to get site info for {site_url}: {e}")
            return None
    
    def _matches_account_filter(self, file: SharePointFile, account_filter: str) -> bool:
        """Check if file matches account filter criteria."""
        try:
            # Simple path-based filtering - could be enhanced
            file_path = file.full_path.lower()
            account_filter_lower = account_filter.lower()
            
            # Check if account ID is in the path
            return account_filter_lower in file_path
            
        except Exception as e:
            logger.error(f"Failed to apply account filter: {e}")
            return True  # Default to include if filter fails
    
    async def _should_process_file(self, file: SharePointFile) -> tuple[bool, str]:
        """Determine if a file should be processed."""
        try:
            # Check file size limits
            max_file_size = 100 * 1024 * 1024  # 100MB
            if file.size > max_file_size:
                return False, f"File too large: {file.size} bytes"
            
            # Check if file is empty
            if file.size == 0:
                return False, "Empty file"
            
            # Check if already processed (if repository available)
            if self.processed_files_repo:
                is_processed = await self.processed_files_repo.is_file_processed(
                    sharepoint_id=file.id,
                    etag=file.data.get("eTag"),
                    last_modified=file.modified_datetime
                )
                
                if is_processed:
                    return False, "Already processed and up to date"
            
            return True, "Ready for processing"
            
        except Exception as e:
            logger.error(f"Failed to check if file should be processed: {e}")
            return True, "Check failed - defaulting to process"
    
    async def _create_document_from_file(self, file: SharePointFile, 
                                       site_url: str) -> Optional[Document]:
        """Create a Document model from a SharePoint file."""
        try:
            # Extract account information from path
            account_info = self._extract_account_info(file, site_url)
            
            # Create document metadata
            metadata = DocumentMetadata(
                source_system="sharepoint",
                source_url=file.web_url,
                site_url=site_url,
                account_id=account_info.get("account_id"),
                owner_email=file.created_by or file.modified_by,
                department=account_info.get("department"),
                project_name=account_info.get("project_name"),
                content_type=file.mime_type,
                language="en",  # Could be enhanced with detection
                security_classification="internal"
            )
            
            # Determine document type
            doc_type = self._determine_document_type(file)
            
            # Create document
            document = Document(
                sharepoint_id=file.id,
                file_name=file.name,
                file_path=file.full_path,
                file_size=file.size,
                document_type=doc_type,
                etag=file.data.get("eTag"),
                last_modified=file.modified_datetime,
                content_hash=None,  # Will be calculated after download
                status=DocumentStatus.PENDING,
                metadata=metadata
            )
            
            return document
            
        except Exception as e:
            logger.error(f"Failed to create document from file {file.name}: {e}")
            return None
    
    def _extract_account_info(self, file: SharePointFile, site_url: str) -> Dict[str, Any]:
        """Extract account information from file path and metadata."""
        try:
            account_info = {}
            
            # Try to extract account ID from path
            path_parts = file.parent_path.split('/')
            
            # Look for patterns like "account_12345" or "client_xyz"
            import re
            for part in path_parts:
                # Account ID pattern
                account_match = re.search(r'(?:account|client|customer)[-_]?(\w+)', part.lower())
                if account_match:
                    account_info["account_id"] = account_match.group(1)
                
                # Department pattern
                dept_match = re.search(r'(?:dept|department)[-_]?(\w+)', part.lower())
                if dept_match:
                    account_info["department"] = dept_match.group(1)
                
                # Project pattern
                project_match = re.search(r'(?:project|proj)[-_]?(\w+)', part.lower())
                if project_match:
                    account_info["project_name"] = project_match.group(1)
            
            # Use created_by email domain as department if not found
            if not account_info.get("department") and file.created_by:
                if "@" in file.created_by:
                    domain = file.created_by.split("@")[1].split(".")[0]
                    account_info["department"] = domain
            
            return account_info
            
        except Exception as e:
            logger.error(f"Failed to extract account info: {e}")
            return {}
    
    def _determine_document_type(self, file: SharePointFile) -> DocumentType:
        """Determine document type based on file characteristics."""
        try:
            file_name_lower = file.name.lower()
            
            # Check by file name patterns
            if any(keyword in file_name_lower for keyword in ["contract", "agreement", "terms"]):
                return DocumentType.CONTRACT
            
            if any(keyword in file_name_lower for keyword in ["invoice", "bill", "receipt"]):
                return DocumentType.INVOICE
            
            if any(keyword in file_name_lower for keyword in ["report", "analysis", "summary"]):
                return DocumentType.REPORT
            
            if any(keyword in file_name_lower for keyword in ["email", "message", "correspondence"]):
                return DocumentType.EMAIL
            
            if any(keyword in file_name_lower for keyword in ["presentation", "slides", "deck"]):
                return DocumentType.PRESENTATION
            
            # Check by file extension
            extension = file.file_extension.lower()
            
            if extension in ["pptx", "ppt"]:
                return DocumentType.PRESENTATION
            
            if extension in ["xlsx", "xls", "csv"]:
                return DocumentType.SPREADSHEET
            
            # Default
            return DocumentType.DOCUMENT
            
        except Exception as e:
            logger.error(f"Failed to determine document type: {e}")
            return DocumentType.DOCUMENT
    
    async def download_file_content(self, file: SharePointFile) -> Optional[bytes]:
        """Download file content from SharePoint."""
        try:
            logger.debug(f"Downloading file: {file.name}")
            
            content = await self.sharepoint_client.download_file(file)
            
            logger.debug(f"Downloaded {len(content)} bytes for file {file.name}")
            
            return content
            
        except Exception as e:
            logger.error(f"Failed to download file {file.name}: {e}")
            return None
    
    async def get_file_metadata(self, site_url: str, file_id: str) -> Optional[SharePointFile]:
        """Get detailed metadata for a specific file."""
        try:
            site_info = await self._get_site_info(site_url)
            if not site_info:
                return None
            
            site_id = site_info.get("id")
            if not site_id:
                return None
            
            return await self.sharepoint_client.get_file_metadata(site_id, file_id)
            
        except Exception as e:
            logger.error(f"Failed to get file metadata {file_id}: {e}")
            return None
    
    async def search_files(self, site_urls: List[str], query: str,
                          file_extensions: List[str] = None) -> List[SharePointFile]:
        """Search for files across SharePoint sites."""
        try:
            all_files = []
            
            for site_url in site_urls:
                try:
                    site_info = await self._get_site_info(site_url)
                    if not site_info:
                        continue
                    
                    site_id = site_info.get("id")
                    if not site_id:
                        continue
                    
                    files = await self.sharepoint_client.search_files(
                        site_id=site_id,
                        query=query,
                        file_extensions=file_extensions
                    )
                    
                    all_files.extend(files)
                    
                except Exception as e:
                    logger.error(f"Failed to search files in site {site_url}: {e}")
                    continue
            
            logger.info(f"Found {len(all_files)} files matching query: {query}")
            
            return all_files
            
        except Exception as e:
            logger.error(f"Failed to search files: {e}")
            return []
    
    async def get_incremental_changes(self, site_urls: List[str],
                                    since: datetime,
                                    file_extensions: List[str] = None) -> List[Tuple[SharePointFile, Document]]:
        """Get files that have changed since a specific date."""
        try:
            changed_files = []
            
            async for file, document in self.discover_documents(
                site_urls=site_urls,
                file_extensions=file_extensions,
                modified_since=since
            ):
                changed_files.append((file, document))
            
            logger.info(f"Found {len(changed_files)} files changed since {since}")
            
            return changed_files
            
        except Exception as e:
            logger.error(f"Failed to get incremental changes: {e}")
            return []
    
    async def validate_site_access(self, site_urls: List[str]) -> Dict[str, bool]:
        """Validate access to SharePoint sites."""
        try:
            access_results = {}
            
            for site_url in site_urls:
                try:
                    site_info = await self._get_site_info(site_url)
                    access_results[site_url] = site_info is not None
                    
                except Exception as e:
                    logger.error(f"Access validation failed for {site_url}: {e}")
                    access_results[site_url] = False
            
            return access_results
            
        except Exception as e:
            logger.error(f"Failed to validate site access: {e}")
            return {url: False for url in site_urls}
    
    async def get_site_statistics(self, site_urls: List[str]) -> Dict[str, Any]:
        """Get statistics about SharePoint sites."""
        try:
            stats = {
                "total_sites": len(site_urls),
                "accessible_sites": 0,
                "total_files": 0,
                "sites_detail": {}
            }
            
            for site_url in site_urls:
                try:
                    site_info = await self._get_site_info(site_url)
                    if site_info:
                        stats["accessible_sites"] += 1
                        
                        site_id = site_info.get("id")
                        if site_id:
                            # Count files in site
                            file_count = 0
                            async for _ in self.sharepoint_client.list_files_in_site(site_id):
                                file_count += 1
                                if file_count >= 1000:  # Limit for performance
                                    break
                            
                            stats["total_files"] += file_count
                            stats["sites_detail"][site_url] = {
                                "accessible": True,
                                "file_count": file_count,
                                "site_name": site_info.get("displayName", "")
                            }
                        else:
                            stats["sites_detail"][site_url] = {
                                "accessible": False,
                                "error": "No site ID"
                            }
                    else:
                        stats["sites_detail"][site_url] = {
                            "accessible": False,
                            "error": "Site not accessible"
                        }
                        
                except Exception as e:
                    stats["sites_detail"][site_url] = {
                        "accessible": False,
                        "error": str(e)
                    }
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get site statistics: {e}")
            return {"error": str(e)}
    
    def clear_site_cache(self):
        """Clear the site information cache."""
        self._site_cache.clear()
        logger.info("Site cache cleared")
    
    async def batch_download_files(self, files: List[SharePointFile],
                                 max_concurrent: int = 5) -> Dict[str, bytes]:
        """Download multiple files concurrently."""
        try:
            semaphore = asyncio.Semaphore(max_concurrent)
            
            async def download_with_semaphore(file: SharePointFile) -> Tuple[str, Optional[bytes]]:
                async with semaphore:
                    content = await self.download_file_content(file)
                    return file.id, content
            
            tasks = [download_with_semaphore(file) for file in files]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            downloads = {}
            success_count = 0
            
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Batch download error: {result}")
                    continue
                
                file_id, content = result
                if content is not None:
                    downloads[file_id] = content
                    success_count += 1
            
            logger.info(f"Batch downloaded {success_count}/{len(files)} files")
            
            return downloads
            
        except Exception as e:
            logger.error(f"Failed to batch download files: {e}")
            return {}
