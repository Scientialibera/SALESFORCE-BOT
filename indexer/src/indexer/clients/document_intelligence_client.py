"""Azure AI Document Intelligence client for document analysis."""

import asyncio
import logging
from io import BytesIO
from typing import Dict, List, Optional, Any, BinaryIO
from azure.identity.aio import DefaultAzureCredential
from azure.ai.documentintelligence.aio import DocumentIntelligenceClient as AIDocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, AnalyzeResult
from azure.core.exceptions import HttpResponseError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..config.settings import Settings


logger = logging.getLogger(__name__)


class DocumentIntelligenceClient:
    """Client for Azure AI Document Intelligence services."""
    
    def __init__(self, settings: Settings):
        """Initialize the Document Intelligence client."""
        self.settings = settings
        self.credential = DefaultAzureCredential()
        self.client: Optional[AIDocumentIntelligenceClient] = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize the async client."""
        if self._initialized:
            return
        
        try:
            self.client = AIDocumentIntelligenceClient(
                endpoint=self.settings.document_intelligence.endpoint,
                credential=self.credential
            )
            
            self._initialized = True
            logger.info("Document Intelligence client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Document Intelligence client: {e}")
            raise
    
    async def close(self):
        """Close the client and clean up resources."""
        if self.client:
            await self.client.close()
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
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((HttpResponseError,))
    )
    async def analyze_document(self, document_content: bytes, content_type: str = "application/pdf") -> Dict[str, Any]:
        """Analyze a document and extract text, tables, and structure."""
        if not self._initialized:
            await self.initialize()
        
        try:
            logger.debug(f"Starting document analysis for {len(document_content)} bytes")
            
            # Create analyze request
            analyze_request = AnalyzeDocumentRequest(bytes_source=document_content)
            
            # Start the analysis operation
            poller = await self.client.begin_analyze_document(
                model_id="prebuilt-layout",  # Use layout model for comprehensive extraction
                analyze_request=analyze_request,
                content_type=content_type
            )
            
            # Wait for completion
            result: AnalyzeResult = await poller.result()
            
            # Extract comprehensive information
            extracted_data = self._process_analysis_result(result)
            
            logger.info(f"Document analysis completed. Found {len(extracted_data.get('pages', []))} pages")
            
            return extracted_data
            
        except HttpResponseError as e:
            logger.error(f"Document Intelligence API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to analyze document: {e}")
            raise
    
    def _process_analysis_result(self, result: AnalyzeResult) -> Dict[str, Any]:
        """Process the analysis result into a structured format."""
        extracted_data = {
            "content": result.content or "",
            "pages": [],
            "tables": [],
            "paragraphs": [],
            "key_value_pairs": [],
            "entities": [],
            "styles": []
        }
        
        # Process pages
        if result.pages:
            for page in result.pages:
                page_data = {
                    "page_number": page.page_number,
                    "width": page.width,
                    "height": page.height,
                    "unit": page.unit,
                    "angle": page.angle,
                    "words": [],
                    "lines": [],
                    "selection_marks": []
                }
                
                # Extract words
                if page.words:
                    for word in page.words:
                        word_data = {
                            "content": word.content,
                            "confidence": word.confidence,
                            "polygon": [{"x": point.x, "y": point.y} for point in word.polygon] if word.polygon else []
                        }
                        page_data["words"].append(word_data)
                
                # Extract lines
                if page.lines:
                    for line in page.lines:
                        line_data = {
                            "content": line.content,
                            "polygon": [{"x": point.x, "y": point.y} for point in line.polygon] if line.polygon else []
                        }
                        page_data["lines"].append(line_data)
                
                # Extract selection marks (checkboxes, etc.)
                if page.selection_marks:
                    for mark in page.selection_marks:
                        mark_data = {
                            "state": mark.state,
                            "confidence": mark.confidence,
                            "polygon": [{"x": point.x, "y": point.y} for point in mark.polygon] if mark.polygon else []
                        }
                        page_data["selection_marks"].append(mark_data)
                
                extracted_data["pages"].append(page_data)
        
        # Process tables
        if result.tables:
            for table in result.tables:
                table_data = {
                    "row_count": table.row_count,
                    "column_count": table.column_count,
                    "cells": []
                }
                
                if table.cells:
                    for cell in table.cells:
                        cell_data = {
                            "content": cell.content,
                            "row_index": cell.row_index,
                            "column_index": cell.column_index,
                            "row_span": cell.row_span or 1,
                            "column_span": cell.column_span or 1,
                            "confidence": cell.confidence,
                            "kind": cell.kind
                        }
                        table_data["cells"].append(cell_data)
                
                extracted_data["tables"].append(table_data)
        
        # Process paragraphs
        if result.paragraphs:
            for paragraph in result.paragraphs:
                paragraph_data = {
                    "content": paragraph.content,
                    "role": paragraph.role,
                    "bounding_regions": []
                }
                
                if paragraph.bounding_regions:
                    for region in paragraph.bounding_regions:
                        region_data = {
                            "page_number": region.page_number,
                            "polygon": [{"x": point.x, "y": point.y} for point in region.polygon] if region.polygon else []
                        }
                        paragraph_data["bounding_regions"].append(region_data)
                
                extracted_data["paragraphs"].append(paragraph_data)
        
        # Process key-value pairs
        if result.key_value_pairs:
            for kv_pair in result.key_value_pairs:
                kv_data = {
                    "key": kv_pair.key.content if kv_pair.key else None,
                    "value": kv_pair.value.content if kv_pair.value else None,
                    "confidence": kv_pair.confidence
                }
                extracted_data["key_value_pairs"].append(kv_data)
        
        # Process styles
        if result.styles:
            for style in result.styles:
                style_data = {
                    "is_handwritten": style.is_handwritten,
                    "confidence": style.confidence,
                    "spans": [{"offset": span.offset, "length": span.length} for span in style.spans] if style.spans else []
                }
                extracted_data["styles"].append(style_data)
        
        return extracted_data
    
    async def extract_text_only(self, document_content: bytes, content_type: str = "application/pdf") -> str:
        """Extract only the text content from a document."""
        try:
            result = await self.analyze_document(document_content, content_type)
            return result.get("content", "")
        except Exception as e:
            logger.error(f"Failed to extract text: {e}")
            return ""
    
    async def extract_tables(self, document_content: bytes, content_type: str = "application/pdf") -> List[Dict[str, Any]]:
        """Extract table data from a document."""
        try:
            result = await self.analyze_document(document_content, content_type)
            return result.get("tables", [])
        except Exception as e:
            logger.error(f"Failed to extract tables: {e}")
            return []
    
    async def get_document_structure(self, document_content: bytes, content_type: str = "application/pdf") -> Dict[str, Any]:
        """Get document structure including headers, paragraphs, and layout."""
        try:
            result = await self.analyze_document(document_content, content_type)
            
            structure = {
                "page_count": len(result.get("pages", [])),
                "paragraph_count": len(result.get("paragraphs", [])),
                "table_count": len(result.get("tables", [])),
                "has_handwriting": any(style.get("is_handwritten", False) for style in result.get("styles", [])),
                "key_value_pairs": result.get("key_value_pairs", []),
                "content_length": len(result.get("content", ""))
            }
            
            return structure
            
        except Exception as e:
            logger.error(f"Failed to get document structure: {e}")
            return {}
    
    async def analyze_layout(self, document_content: bytes, content_type: str = "application/pdf") -> Dict[str, Any]:
        """Analyze document layout and reading order."""
        if not self._initialized:
            await self.initialize()
        
        try:
            # Use read model for layout analysis
            analyze_request = AnalyzeDocumentRequest(bytes_source=document_content)
            
            poller = await self.client.begin_analyze_document(
                model_id="prebuilt-read",
                analyze_request=analyze_request,
                content_type=content_type
            )
            
            result: AnalyzeResult = await poller.result()
            
            layout_data = {
                "content": result.content or "",
                "pages": len(result.pages) if result.pages else 0,
                "reading_order": [],
                "text_blocks": []
            }
            
            # Extract reading order and text blocks
            if result.pages:
                for page in result.pages:
                    if page.lines:
                        for line in page.lines:
                            layout_data["reading_order"].append({
                                "page": page.page_number,
                                "content": line.content,
                                "polygon": [{"x": p.x, "y": p.y} for p in line.polygon] if line.polygon else []
                            })
            
            return layout_data
            
        except Exception as e:
            logger.error(f"Failed to analyze layout: {e}")
            raise
    
    async def test_connection(self) -> bool:
        """Test the connection to Document Intelligence."""
        try:
            await self.initialize()
            
            # Create a minimal test document (1x1 pixel PNG)
            test_doc = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\nIDATx\x9cc\xf8\x00\x00\x00\x01\x00\x01\x00\x00\x00\x00IEND\xaeB`\x82'
            
            analyze_request = AnalyzeDocumentRequest(bytes_source=test_doc)
            
            poller = await self.client.begin_analyze_document(
                model_id="prebuilt-read",
                analyze_request=analyze_request,
                content_type="image/png"
            )
            
            await poller.result()
            return True
            
        except Exception as e:
            logger.error(f"Document Intelligence connection test failed: {e}")
            return False
    
    def get_supported_formats(self) -> List[str]:
        """Get list of supported document formats."""
        return [
            "application/pdf",
            "image/jpeg",
            "image/png", 
            "image/tiff",
            "image/bmp",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
            "text/html"
        ]
