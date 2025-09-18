"""Microsoft Graph / SharePoint client for document access."""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, AsyncGenerator
from urllib.parse import quote
import aiohttp
from azure.identity.aio import DefaultAzureCredential
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..config.settings import Settings


logger = logging.getLogger(__name__)


class SharePointFile:
    """Represents a SharePoint file with metadata."""
    
    def __init__(self, data: Dict[str, Any]):
        self.data = data
    
    @property
    def id(self) -> str:
        return self.data.get("id", "")
    
    @property
    def name(self) -> str:
        return self.data.get("name", "")
    
    @property
    def size(self) -> int:
        return self.data.get("size", 0)
    
    @property
    def created_datetime(self) -> Optional[datetime]:
        created = self.data.get("createdDateTime")
        if created:
            return datetime.fromisoformat(created.replace("Z", "+00:00"))
        return None
    
    @property
    def modified_datetime(self) -> Optional[datetime]:
        modified = self.data.get("lastModifiedDateTime")
        if modified:
            return datetime.fromisoformat(modified.replace("Z", "+00:00"))
        return None
    
    @property
    def web_url(self) -> str:
        return self.data.get("webUrl", "")
    
    @property
    def download_url(self) -> Optional[str]:
        return self.data.get("@microsoft.graph.downloadUrl")
    
    @property
    def file_extension(self) -> str:
        name = self.name.lower()
        if "." in name:
            return name.split(".")[-1]
        return ""
    
    @property
    def mime_type(self) -> str:
        file_ext = self.file_extension
        mime_types = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "doc": "application/msword",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xls": "application/vnd.ms-excel",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "ppt": "application/vnd.ms-powerpoint",
            "txt": "text/plain",
            "md": "text/markdown",
            "html": "text/html",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "tiff": "image/tiff",
            "bmp": "image/bmp"
        }
        return mime_types.get(file_ext, "application/octet-stream")
    
    @property
    def created_by(self) -> Optional[str]:
        created_by = self.data.get("createdBy", {}).get("user", {})
        return created_by.get("email") or created_by.get("displayName")
    
    @property
    def modified_by(self) -> Optional[str]:
        modified_by = self.data.get("lastModifiedBy", {}).get("user", {})
        return modified_by.get("email") or modified_by.get("displayName")
    
    @property
    def parent_path(self) -> str:
        parent_ref = self.data.get("parentReference", {})
        return parent_ref.get("path", "")
    
    @property
    def full_path(self) -> str:
        parent_path = self.parent_path
        if parent_path and not parent_path.endswith("/"):
            parent_path += "/"
        return f"{parent_path}{self.name}"


class SharePointClient:
    """Client for Microsoft Graph SharePoint API."""
    
    def __init__(self, settings: Settings):
        """Initialize the SharePoint client."""
        self.settings = settings
        self.credential = DefaultAzureCredential()
        self.session: Optional[aiohttp.ClientSession] = None
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize the client."""
        if self._initialized:
            return
        
        try:
            self.session = aiohttp.ClientSession()
            await self._refresh_token()
            
            self._initialized = True
            logger.info("SharePoint client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize SharePoint client: {e}")
            raise
    
    async def close(self):
        """Close the client and clean up resources."""
        if self.session:
            await self.session.close()
        if self.credential:
            await self.credential.close()
        self._initialized = False
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def _refresh_token(self):
        """Refresh the access token."""
        try:
            # Get token for Microsoft Graph
            token_response = await self.credential.get_token("https://graph.microsoft.com/.default")
            self.access_token = token_response.token
            self.token_expires_at = datetime.now(timezone.utc).replace(
                microsecond=0
            ) + timedelta(seconds=token_response.expires_on - datetime.now().timestamp())
            
        except Exception as e:
            logger.error(f"Failed to refresh access token: {e}")
            raise
    
    async def _ensure_token_valid(self):
        """Ensure the access token is valid."""
        if not self.access_token or not self.token_expires_at:
            await self._refresh_token()
        elif datetime.now(timezone.utc) >= self.token_expires_at:
            await self._refresh_token()
    
    async def _make_request(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        """Make an authenticated request to Microsoft Graph."""
        await self._ensure_token_valid()
        
        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"
        headers["Accept"] = "application/json"
        kwargs["headers"] = headers
        
        async with self.session.request(method, url, **kwargs) as response:
            if response.status == 401:
                # Token might be expired, try refresh once
                await self._refresh_token()
                headers["Authorization"] = f"Bearer {self.access_token}"
                
                async with self.session.request(method, url, **kwargs) as retry_response:
                    retry_response.raise_for_status()
                    return await retry_response.json()
            
            response.raise_for_status()
            return await response.json()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError,))
    )
    async def list_sites(self) -> List[Dict[str, Any]]:
        """List SharePoint sites."""
        if not self._initialized:
            await self.initialize()
        
        url = "https://graph.microsoft.com/v1.0/sites"
        
        try:
            response = await self._make_request("GET", url)
            return response.get("value", [])
            
        except Exception as e:
            logger.error(f"Failed to list sites: {e}")
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError,))
    )
    async def get_site_by_url(self, site_url: str) -> Optional[Dict[str, Any]]:
        """Get site information by URL."""
        if not self._initialized:
            await self.initialize()
        
        # Extract hostname and site path from URL
        # Example: https://tenant.sharepoint.com/sites/sitename
        try:
            from urllib.parse import urlparse
            parsed = urlparse(site_url)
            hostname = parsed.netloc
            site_path = parsed.path
            
            # Encode the site URL
            encoded_url = f"{hostname}:{site_path}"
            url = f"https://graph.microsoft.com/v1.0/sites/{encoded_url}"
            
            response = await self._make_request("GET", url)
            return response
            
        except Exception as e:
            logger.error(f"Failed to get site by URL {site_url}: {e}")
            return None
    
    async def list_files_in_site(self, site_id: str, 
                                file_extensions: List[str] = None,
                                modified_since: datetime = None) -> AsyncGenerator[SharePointFile, None]:
        """List files in a SharePoint site with optional filtering."""
        if not self._initialized:
            await self.initialize()
        
        file_extensions = file_extensions or [".pdf", ".docx", ".txt", ".md"]
        extensions_lower = [ext.lower() for ext in file_extensions]
        
        # Get document libraries (drives)
        drives_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives"
        
        try:
            drives_response = await self._make_request("GET", drives_url)
            drives = drives_response.get("value", [])
            
            for drive in drives:
                drive_id = drive.get("id")
                if not drive_id:
                    continue
                
                # List files in this drive
                async for file in self._list_files_in_drive(site_id, drive_id, extensions_lower, modified_since):
                    yield file
                    
        except Exception as e:
            logger.error(f"Failed to list files in site {site_id}: {e}")
            raise
    
    async def _list_files_in_drive(self, site_id: str, drive_id: str, 
                                  extensions_lower: List[str],
                                  modified_since: datetime = None) -> AsyncGenerator[SharePointFile, None]:
        """List files in a specific drive."""
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives/{drive_id}/root/children"
        
        await self._list_files_recursive(url, extensions_lower, modified_since)
    
    async def _list_files_recursive(self, url: str, extensions_lower: List[str],
                                   modified_since: datetime = None) -> AsyncGenerator[SharePointFile, None]:
        """Recursively list files in folders."""
        try:
            response = await self._make_request("GET", url)
            items = response.get("value", [])
            
            for item in items:
                if "folder" in item:
                    # Recursively process folders
                    folder_id = item.get("id")
                    if folder_id:
                        folder_url = f"{url.split('/children')[0]}/items/{folder_id}/children"
                        async for file in self._list_files_recursive(folder_url, extensions_lower, modified_since):
                            yield file
                
                elif "file" in item:
                    # Process files
                    file_name = item.get("name", "").lower()
                    
                    # Check file extension
                    if not any(file_name.endswith(ext) for ext in extensions_lower):
                        continue
                    
                    # Check modification date
                    if modified_since:
                        modified = item.get("lastModifiedDateTime")
                        if modified:
                            file_modified = datetime.fromisoformat(modified.replace("Z", "+00:00"))
                            if file_modified < modified_since:
                                continue
                    
                    yield SharePointFile(item)
            
            # Handle pagination
            next_link = response.get("@odata.nextLink")
            if next_link:
                async for file in self._list_files_recursive(next_link, extensions_lower, modified_since):
                    yield file
                    
        except Exception as e:
            logger.error(f"Failed to list files recursively from {url}: {e}")
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError,))
    )
    async def download_file(self, file: SharePointFile) -> bytes:
        """Download a file from SharePoint."""
        if not self._initialized:
            await self.initialize()
        
        download_url = file.download_url
        if not download_url:
            raise ValueError(f"No download URL available for file {file.name}")
        
        try:
            # Download file content
            async with self.session.get(download_url) as response:
                response.raise_for_status()
                content = await response.read()
                
                logger.debug(f"Downloaded file {file.name}: {len(content)} bytes")
                return content
                
        except Exception as e:
            logger.error(f"Failed to download file {file.name}: {e}")
            raise
    
    async def get_file_metadata(self, site_id: str, file_id: str) -> Optional[SharePointFile]:
        """Get detailed metadata for a specific file."""
        if not self._initialized:
            await self.initialize()
        
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{file_id}"
        
        try:
            response = await self._make_request("GET", url)
            return SharePointFile(response)
            
        except Exception as e:
            logger.error(f"Failed to get file metadata for {file_id}: {e}")
            return None
    
    async def search_files(self, site_id: str, query: str, 
                          file_extensions: List[str] = None) -> List[SharePointFile]:
        """Search for files in a SharePoint site."""
        if not self._initialized:
            await self.initialize()
        
        # Build search query
        search_query = query
        if file_extensions:
            ext_filter = " OR ".join([f"fileextension:{ext.replace('.', '')}" for ext in file_extensions])
            search_query = f"({query}) AND ({ext_filter})"
        
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/search(q='{quote(search_query)}')"
        
        try:
            response = await self._make_request("GET", url)
            items = response.get("value", [])
            
            return [SharePointFile(item) for item in items if "file" in item]
            
        except Exception as e:
            logger.error(f"Failed to search files in site {site_id}: {e}")
            return []
    
    async def test_connection(self) -> bool:
        """Test the connection to SharePoint."""
        try:
            await self.initialize()
            
            # Try to list sites as a connection test
            sites = await self.list_sites()
            return len(sites) >= 0  # Even 0 sites means we connected successfully
            
        except Exception as e:
            logger.error(f"SharePoint connection test failed: {e}")
            return False
    
    async def get_site_usage_stats(self, site_id: str) -> Dict[str, Any]:
        """Get usage statistics for a SharePoint site."""
        if not self._initialized:
            await self.initialize()
        
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/analytics"
        
        try:
            response = await self._make_request("GET", url)
            return response
            
        except Exception as e:
            logger.warning(f"Failed to get site usage stats for {site_id}: {e}")
            return {}
