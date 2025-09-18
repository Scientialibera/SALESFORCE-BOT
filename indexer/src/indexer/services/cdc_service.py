"""Change Data Capture (CDC) service for tracking SharePoint document changes."""

import asyncio
import logging
from typing import Dict, List, Optional, Set, Any, Tuple
from datetime import datetime, timedelta
import json

from ..clients.sharepoint_client import SharePointClient
from ..clients.cosmos_client import CosmosClient
from ..repositories.processed_files_repository import ProcessedFilesRepository
from ..models.document import Document, DocumentStatus
from ..config.settings import Settings


logger = logging.getLogger(__name__)


class CDCEntry:
    """Represents a change data capture entry."""
    
    def __init__(self, 
                 file_id: str,
                 action: str,  # 'added', 'modified', 'deleted'
                 file_path: str,
                 site_url: str = None,
                 etag: str = None,
                 last_modified: datetime = None,
                 detected_at: datetime = None):
        self.file_id = file_id
        self.action = action
        self.file_path = file_path
        self.site_url = site_url
        self.etag = etag
        self.last_modified = last_modified
        self.detected_at = detected_at or datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": f"cdc_{self.file_id}_{int(self.detected_at.timestamp())}",
            "file_id": self.file_id,
            "action": self.action,
            "file_path": self.file_path,
            "site_url": self.site_url,
            "etag": self.etag,
            "last_modified": self.last_modified.isoformat() if self.last_modified else None,
            "detected_at": self.detected_at.isoformat(),
            "type": "cdc_entry"
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CDCEntry':
        """Create from dictionary."""
        return cls(
            file_id=data["file_id"],
            action=data["action"],
            file_path=data["file_path"],
            site_url=data.get("site_url"),
            etag=data.get("etag"),
            last_modified=datetime.fromisoformat(data["last_modified"]) if data.get("last_modified") else None,
            detected_at=datetime.fromisoformat(data["detected_at"])
        )


class CDCService:
    """Service for detecting and tracking changes in SharePoint documents."""
    
    def __init__(self, 
                 settings: Settings,
                 sharepoint_client: SharePointClient,
                 cosmos_client: CosmosClient,
                 processed_files_repo: ProcessedFilesRepository):
        """Initialize the CDC service."""
        self.settings = settings
        self.sharepoint_client = sharepoint_client
        self.cosmos_client = cosmos_client
        self.processed_files_repo = processed_files_repo
        self.container_name = "cdc"  # CDC container
        self._last_scan_time: Optional[datetime] = None
        self._change_batch: List[CDCEntry] = []
        self._batch_size = 100
    
    async def initialize(self):
        """Initialize the service."""
        try:
            # Ensure CDC container exists
            await self.cosmos_client.create_container_if_not_exists(
                container_name=self.container_name,
                partition_key="/file_id"
            )
            
            # Load last scan time
            await self._load_last_scan_time()
            
            logger.info("CDC service initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize CDC service: {e}")
            raise
    
    async def _load_last_scan_time(self):
        """Load the last scan timestamp from storage."""
        try:
            query = """
                SELECT TOP 1 c.detected_at 
                FROM c 
                WHERE c.type = 'cdc_entry' 
                ORDER BY c.detected_at DESC
            """
            
            items = await self.cosmos_client.query_items(
                container_name=self.container_name,
                query=query
            )
            
            if items:
                self._last_scan_time = datetime.fromisoformat(items[0]["detected_at"])
                logger.info(f"Last CDC scan time: {self._last_scan_time}")
            else:
                # First run - set to 24 hours ago to catch recent changes
                self._last_scan_time = datetime.utcnow() - timedelta(hours=24)
                logger.info("First CDC run - scanning last 24 hours")
            
        except Exception as e:
            logger.error(f"Failed to load last scan time: {e}")
            # Default to 24 hours ago
            self._last_scan_time = datetime.utcnow() - timedelta(hours=24)
    
    async def scan_for_changes(self, account_filter: Set[str] = None) -> List[CDCEntry]:
        """Scan SharePoint for document changes since last scan."""
        try:
            logger.info(f"Starting CDC scan from {self._last_scan_time}")
            
            scan_start_time = datetime.utcnow()
            all_changes: List[CDCEntry] = []
            
            # Get sites to scan
            sites = []
            if self.settings.sharepoint.sites:
                sites = self.settings.sharepoint.sites
            elif self.settings.sharepoint.tenant_url:
                # Discover sites automatically
                discovered_sites = await self.sharepoint_client.discover_sites()
                sites = [site["web_url"] for site in discovered_sites]
            
            if not sites:
                logger.warning("No SharePoint sites configured for CDC scan")
                return []
            
            # Scan each site
            for site_url in sites:
                try:
                    site_changes = await self._scan_site_changes(site_url, account_filter)
                    all_changes.extend(site_changes)
                    
                except Exception as e:
                    logger.error(f"Failed to scan site {site_url}: {e}")
            
            # Batch save changes
            if all_changes:
                await self._save_changes_batch(all_changes)
            
            # Update last scan time
            self._last_scan_time = scan_start_time
            
            logger.info(f"CDC scan completed. Found {len(all_changes)} changes")
            
            return all_changes
            
        except Exception as e:
            logger.error(f"Failed to scan for changes: {e}")
            return []
    
    async def _scan_site_changes(self, site_url: str, account_filter: Set[str] = None) -> List[CDCEntry]:
        """Scan a specific site for changes."""
        try:
            changes: List[CDCEntry] = []
            
            # Get current files from SharePoint
            current_files = await self.sharepoint_client.discover_documents(
                site_url=site_url,
                account_filter=account_filter,
                include_metadata=True
            )
            
            # Get processed files from our database
            processed_files = await self.processed_files_repo.get_processed_files_by_site(site_url)
            processed_file_ids = {pf.file_id for pf in processed_files}
            processed_file_map = {pf.file_id: pf for pf in processed_files}
            
            current_file_ids = set()
            
            # Check for new and modified files
            for file_info in current_files:
                file_id = file_info["id"]
                current_file_ids.add(file_id)
                
                processed_file = processed_file_map.get(file_id)
                
                if not processed_file:
                    # New file
                    changes.append(CDCEntry(
                        file_id=file_id,
                        action="added",
                        file_path=file_info["server_relative_url"],
                        site_url=site_url,
                        etag=file_info.get("etag"),
                        last_modified=file_info.get("time_last_modified")
                    ))
                else:
                    # Check if modified
                    current_etag = file_info.get("etag")
                    current_modified = file_info.get("time_last_modified")
                    
                    if (current_etag and current_etag != processed_file.etag) or \
                       (current_modified and current_modified > processed_file.last_modified):
                        changes.append(CDCEntry(
                            file_id=file_id,
                            action="modified",
                            file_path=file_info["server_relative_url"],
                            site_url=site_url,
                            etag=current_etag,
                            last_modified=current_modified
                        ))
            
            # Check for deleted files
            for file_id in processed_file_ids:
                if file_id not in current_file_ids:
                    processed_file = processed_file_map[file_id]
                    changes.append(CDCEntry(
                        file_id=file_id,
                        action="deleted",
                        file_path=processed_file.file_path,
                        site_url=site_url,
                        last_modified=processed_file.last_modified
                    ))
            
            logger.debug(f"Site {site_url}: {len(changes)} changes detected")
            
            return changes
            
        except Exception as e:
            logger.error(f"Failed to scan site {site_url} for changes: {e}")
            return []
    
    async def _save_changes_batch(self, changes: List[CDCEntry]):
        """Save a batch of changes to storage."""
        try:
            for i in range(0, len(changes), self._batch_size):
                batch = changes[i:i + self._batch_size]
                
                # Save to CDC container
                for change in batch:
                    await self.cosmos_client.upsert_item(
                        container_name=self.container_name,
                        item=change.to_dict()
                    )
                
                logger.debug(f"Saved CDC batch {i//self._batch_size + 1}: {len(batch)} changes")
            
        except Exception as e:
            logger.error(f"Failed to save changes batch: {e}")
            raise
    
    async def get_changes_since(self, 
                               since: datetime,
                               action_filter: List[str] = None,
                               limit: int = 1000) -> List[CDCEntry]:
        """Get changes since a specific timestamp."""
        try:
            query_parts = [
                "SELECT * FROM c",
                "WHERE c.type = 'cdc_entry'",
                f"AND c.detected_at >= '{since.isoformat()}'"
            ]
            
            if action_filter:
                actions_str = "', '".join(action_filter)
                query_parts.append(f"AND c.action IN ('{actions_str}')")
            
            query_parts.append("ORDER BY c.detected_at DESC")
            
            if limit:
                query_parts.append(f"OFFSET 0 LIMIT {limit}")
            
            query = " ".join(query_parts)
            
            items = await self.cosmos_client.query_items(
                container_name=self.container_name,
                query=query
            )
            
            return [CDCEntry.from_dict(item) for item in items]
            
        except Exception as e:
            logger.error(f"Failed to get changes since {since}: {e}")
            return []
    
    async def get_pending_changes(self, 
                                 action_filter: List[str] = None,
                                 limit: int = 100) -> List[CDCEntry]:
        """Get changes that haven't been processed yet."""
        try:
            # Get changes since last scan
            if self._last_scan_time:
                return await self.get_changes_since(
                    since=self._last_scan_time,
                    action_filter=action_filter,
                    limit=limit
                )
            else:
                return []
                
        except Exception as e:
            logger.error(f"Failed to get pending changes: {e}")
            return []
    
    async def mark_change_processed(self, change_entry: CDCEntry) -> bool:
        """Mark a change as processed."""
        try:
            # Update the CDC entry with processed timestamp
            change_dict = change_entry.to_dict()
            change_dict["processed_at"] = datetime.utcnow().isoformat()
            change_dict["status"] = "processed"
            
            await self.cosmos_client.upsert_item(
                container_name=self.container_name,
                item=change_dict
            )
            
            logger.debug(f"Marked change {change_entry.file_id} as processed")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to mark change as processed: {e}")
            return False
    
    async def get_change_statistics(self, 
                                  hours_back: int = 24) -> Dict[str, Any]:
        """Get change statistics for the specified time period."""
        try:
            since = datetime.utcnow() - timedelta(hours=hours_back)
            
            # Get change counts by action
            query = f"""
                SELECT c.action, COUNT(1) as count 
                FROM c 
                WHERE c.type = 'cdc_entry' 
                AND c.detected_at >= '{since.isoformat()}'
                GROUP BY c.action
            """
            
            action_counts = await self.cosmos_client.query_items(
                container_name=self.container_name,
                query=query
            )
            
            # Get total changes
            total_query = f"""
                SELECT COUNT(1) as total_changes
                FROM c 
                WHERE c.type = 'cdc_entry' 
                AND c.detected_at >= '{since.isoformat()}'
            """
            
            total_result = await self.cosmos_client.query_items(
                container_name=self.container_name,
                query=total_query
            )
            
            # Get pending changes (unprocessed)
            pending_query = f"""
                SELECT COUNT(1) as pending_changes
                FROM c 
                WHERE c.type = 'cdc_entry' 
                AND c.detected_at >= '{since.isoformat()}'
                AND (NOT IS_DEFINED(c.status) OR c.status != 'processed')
            """
            
            pending_result = await self.cosmos_client.query_items(
                container_name=self.container_name,
                query=pending_query
            )
            
            stats = {
                "time_period_hours": hours_back,
                "total_changes": total_result[0]["total_changes"] if total_result else 0,
                "pending_changes": pending_result[0]["pending_changes"] if pending_result else 0,
                "changes_by_action": {item["action"]: item["count"] for item in action_counts},
                "last_scan_time": self._last_scan_time.isoformat() if self._last_scan_time else None,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get change statistics: {e}")
            return {}
    
    async def cleanup_old_changes(self, days_old: int = 30) -> int:
        """Clean up old CDC entries."""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_old)
            
            # Find old entries
            query = f"""
                SELECT c.id, c.file_id FROM c 
                WHERE c.type = 'cdc_entry' 
                AND c.detected_at < '{cutoff_date.isoformat()}'
                AND (IS_DEFINED(c.status) AND c.status = 'processed')
            """
            
            items = await self.cosmos_client.query_items(
                container_name=self.container_name,
                query=query
            )
            
            deleted_count = 0
            for item in items:
                try:
                    await self.cosmos_client.delete_item(
                        container_name=self.container_name,
                        item_id=item["id"],
                        partition_key=item["file_id"]
                    )
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete old CDC entry {item['id']}: {e}")
            
            logger.info(f"Cleaned up {deleted_count} old CDC entries")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup old CDC entries: {e}")
            return 0
    
    async def force_full_rescan(self) -> bool:
        """Force a full rescan by resetting the last scan time."""
        try:
            self._last_scan_time = datetime.utcnow() - timedelta(days=7)  # Scan last week
            logger.info("Forced full rescan - reset last scan time")
            return True
            
        except Exception as e:
            logger.error(f"Failed to force full rescan: {e}")
            return False
