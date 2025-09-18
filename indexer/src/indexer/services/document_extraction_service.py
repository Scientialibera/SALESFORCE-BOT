"""Document extraction service for processing documents with Azure AI Document Intelligence."""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Tuple
from io import BytesIO
from ..clients.document_intelligence_client import DocumentIntelligenceClient
from ..clients.aoai_client import AzureOpenAIClient
from ..models.document import Document, DocumentStatus, DocumentType


logger = logging.getLogger(__name__)


class DocumentExtractionService:
    """Service for extracting text and metadata from documents."""
    
    def __init__(self, document_intelligence_client: DocumentIntelligenceClient,
                 aoai_client: AzureOpenAIClient = None):
        """Initialize the document extraction service."""
        self.doc_intel_client = document_intelligence_client
        self.aoai_client = aoai_client
    
    async def extract_document_content(self, document_content: bytes, 
                                     content_type: str,
                                     document: Document) -> Tuple[str, Dict[str, Any]]:
        """Extract text and structured data from a document."""
        try:
            logger.info(f"Starting document extraction for {document.file_name}")
            
            # Extract content using Document Intelligence
            extracted_data = await self.doc_intel_client.analyze_document(
                document_content=document_content,
                content_type=content_type
            )
            
            # Get the main text content
            main_content = extracted_data.get("content", "")
            
            if not main_content.strip():
                logger.warning(f"No text content extracted from {document.file_name}")
                return "", extracted_data
            
            # Enhance content with additional processing
            enhanced_content = await self._enhance_extracted_content(
                main_content, extracted_data, document
            )
            
            logger.info(f"Successfully extracted {len(enhanced_content)} characters from {document.file_name}")
            
            return enhanced_content, extracted_data
            
        except Exception as e:
            logger.error(f"Failed to extract content from {document.file_name}: {e}")
            raise
    
    async def _enhance_extracted_content(self, content: str, 
                                       extracted_data: Dict[str, Any],
                                       document: Document) -> str:
        """Enhance extracted content with additional processing."""
        try:
            enhanced_content = content
            
            # Process tables into readable text
            tables = extracted_data.get("tables", [])
            if tables:
                table_text = self._process_tables_to_text(tables)
                if table_text:
                    enhanced_content += f"\n\n=== TABLES ===\n{table_text}"
            
            # Process key-value pairs
            kv_pairs = extracted_data.get("key_value_pairs", [])
            if kv_pairs:
                kv_text = self._process_key_value_pairs(kv_pairs)
                if kv_text:
                    enhanced_content += f"\n\n=== KEY INFORMATION ===\n{kv_text}"
            
            # Clean and normalize the content
            enhanced_content = self._clean_and_normalize_text(enhanced_content)
            
            return enhanced_content
            
        except Exception as e:
            logger.error(f"Failed to enhance extracted content: {e}")
            return content  # Return original content if enhancement fails
    
    def _process_tables_to_text(self, tables: List[Dict[str, Any]]) -> str:
        """Convert table data to readable text."""
        try:
            table_texts = []
            
            for i, table in enumerate(tables):
                table_text = f"Table {i + 1}:\n"
                
                # Create a grid to organize cell content
                rows = {}
                max_row = 0
                max_col = 0
                
                for cell in table.get("cells", []):
                    row_idx = cell.get("row_index", 0)
                    col_idx = cell.get("column_index", 0)
                    content = cell.get("content", "").strip()
                    
                    if row_idx not in rows:
                        rows[row_idx] = {}
                    rows[row_idx][col_idx] = content
                    
                    max_row = max(max_row, row_idx)
                    max_col = max(max_col, col_idx)
                
                # Convert grid to text
                for row_idx in range(max_row + 1):
                    row_cells = []
                    for col_idx in range(max_col + 1):
                        cell_content = rows.get(row_idx, {}).get(col_idx, "")
                        row_cells.append(cell_content)
                    
                    if any(cell.strip() for cell in row_cells):  # Skip empty rows
                        table_text += " | ".join(row_cells) + "\n"
                
                table_texts.append(table_text)
            
            return "\n\n".join(table_texts)
            
        except Exception as e:
            logger.error(f"Failed to process tables to text: {e}")
            return ""
    
    def _process_key_value_pairs(self, kv_pairs: List[Dict[str, Any]]) -> str:
        """Convert key-value pairs to readable text."""
        try:
            kv_texts = []
            
            for kv in kv_pairs:
                key = kv.get("key", "").strip()
                value = kv.get("value", "").strip()
                
                if key and value:
                    kv_texts.append(f"{key}: {value}")
            
            return "\n".join(kv_texts)
            
        except Exception as e:
            logger.error(f"Failed to process key-value pairs: {e}")
            return ""
    
    def _clean_and_normalize_text(self, text: str) -> str:
        """Clean and normalize extracted text."""
        try:
            # Remove excessive whitespace
            lines = text.split('\n')
            cleaned_lines = []
            
            for line in lines:
                # Strip whitespace and normalize
                line = line.strip()
                
                # Skip empty lines but preserve intentional breaks
                if line or (cleaned_lines and cleaned_lines[-1]):
                    cleaned_lines.append(line)
            
            # Join lines back together
            cleaned_text = '\n'.join(cleaned_lines)
            
            # Remove excessive newlines (more than 2 consecutive)
            import re
            cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
            
            return cleaned_text.strip()
            
        except Exception as e:
            logger.error(f"Failed to clean and normalize text: {e}")
            return text
    
    async def extract_entities_from_content(self, content: str) -> List[Dict[str, Any]]:
        """Extract named entities from document content using AI."""
        try:
            if not self.aoai_client or not content.strip():
                return []
            
            # Split content into chunks if too long
            max_chunk_size = 2000
            chunks = []
            
            if len(content) > max_chunk_size:
                # Split by paragraphs first
                paragraphs = content.split('\n\n')
                current_chunk = ""
                
                for paragraph in paragraphs:
                    if len(current_chunk) + len(paragraph) > max_chunk_size:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                        current_chunk = paragraph
                    else:
                        if current_chunk:
                            current_chunk += '\n\n' + paragraph
                        else:
                            current_chunk = paragraph
                
                if current_chunk:
                    chunks.append(current_chunk.strip())
            else:
                chunks = [content]
            
            # Extract entities from each chunk
            all_entities = []
            for chunk in chunks:
                if chunk.strip():
                    chunk_entities = await self.aoai_client.extract_entities(chunk)
                    all_entities.extend(chunk_entities)
            
            # Deduplicate entities
            unique_entities = []
            seen_entities = set()
            
            for entity in all_entities:
                entity_key = (entity.get("type", ""), entity.get("text", "").lower())
                if entity_key not in seen_entities:
                    seen_entities.add(entity_key)
                    unique_entities.append(entity)
            
            logger.debug(f"Extracted {len(unique_entities)} unique entities")
            return unique_entities
            
        except Exception as e:
            logger.error(f"Failed to extract entities: {e}")
            return []
    
    async def generate_document_summary(self, content: str) -> str:
        """Generate a summary of the document content."""
        try:
            if not self.aoai_client or not content.strip():
                return ""
            
            summary = await self.aoai_client.summarize_document(content)
            
            logger.debug(f"Generated document summary: {len(summary)} characters")
            return summary
            
        except Exception as e:
            logger.error(f"Failed to generate document summary: {e}")
            return ""
    
    async def analyze_document_structure(self, extracted_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze document structure and characteristics."""
        try:
            structure = {
                "page_count": len(extracted_data.get("pages", [])),
                "paragraph_count": len(extracted_data.get("paragraphs", [])),
                "table_count": len(extracted_data.get("tables", [])),
                "has_tables": len(extracted_data.get("tables", [])) > 0,
                "has_key_value_pairs": len(extracted_data.get("key_value_pairs", [])) > 0,
                "content_length": len(extracted_data.get("content", "")),
                "word_count": len(extracted_data.get("content", "").split()),
                "has_handwriting": False
            }
            
            # Check for handwriting
            styles = extracted_data.get("styles", [])
            for style in styles:
                if style.get("is_handwritten", False):
                    structure["has_handwriting"] = True
                    break
            
            # Calculate reading time (average 200 words per minute)
            if structure["word_count"] > 0:
                structure["estimated_reading_time_minutes"] = max(1, structure["word_count"] // 200)
            else:
                structure["estimated_reading_time_minutes"] = 0
            
            # Determine document complexity
            complexity_score = 0
            if structure["page_count"] > 10:
                complexity_score += 2
            if structure["table_count"] > 5:
                complexity_score += 2
            if structure["has_handwriting"]:
                complexity_score += 1
            if structure["paragraph_count"] > 50:
                complexity_score += 1
            
            if complexity_score >= 4:
                structure["complexity"] = "high"
            elif complexity_score >= 2:
                structure["complexity"] = "medium"
            else:
                structure["complexity"] = "low"
            
            return structure
            
        except Exception as e:
            logger.error(f"Failed to analyze document structure: {e}")
            return {}
    
    async def extract_document_metadata(self, extracted_data: Dict[str, Any],
                                      content: str) -> Dict[str, Any]:
        """Extract additional metadata from the document."""
        try:
            metadata = {}
            
            # Language detection (basic heuristic)
            metadata["language"] = self._detect_language(content)
            
            # Document type classification
            metadata["document_type"] = self._classify_document_type(content, extracted_data)
            
            # Extract dates
            metadata["extracted_dates"] = self._extract_dates(content)
            
            # Extract monetary amounts
            metadata["extracted_amounts"] = self._extract_monetary_amounts(content)
            
            # Content quality assessment
            metadata["content_quality"] = self._assess_content_quality(content, extracted_data)
            
            return metadata
            
        except Exception as e:
            logger.error(f"Failed to extract document metadata: {e}")
            return {}
    
    def _detect_language(self, content: str) -> str:
        """Simple language detection."""
        # This is a basic implementation - could be enhanced with proper language detection
        english_words = ["the", "and", "or", "of", "to", "in", "for", "with", "on", "at"]
        content_lower = content.lower()
        
        english_count = sum(1 for word in english_words if word in content_lower)
        
        return "en" if english_count >= 3 else "unknown"
    
    def _classify_document_type(self, content: str, extracted_data: Dict[str, Any]) -> str:
        """Classify document type based on content patterns."""
        content_lower = content.lower()
        
        # Contract indicators
        contract_terms = ["agreement", "contract", "terms", "conditions", "party", "whereas"]
        contract_score = sum(1 for term in contract_terms if term in content_lower)
        
        # Invoice indicators
        invoice_terms = ["invoice", "bill", "total", "amount", "due", "payment"]
        invoice_score = sum(1 for term in invoice_terms if term in content_lower)
        
        # Report indicators
        report_terms = ["report", "analysis", "summary", "findings", "conclusion"]
        report_score = sum(1 for term in report_terms if term in content_lower)
        
        # Determine type based on highest score
        scores = {
            "contract": contract_score,
            "invoice": invoice_score,
            "report": report_score
        }
        
        max_score = max(scores.values())
        if max_score >= 2:
            return max(scores, key=scores.get)
        
        return "document"
    
    def _extract_dates(self, content: str) -> List[str]:
        """Extract date patterns from content."""
        import re
        
        # Common date patterns
        date_patterns = [
            r'\d{1,2}/\d{1,2}/\d{4}',  # MM/DD/YYYY
            r'\d{1,2}-\d{1,2}-\d{4}',  # MM-DD-YYYY
            r'\d{4}-\d{1,2}-\d{1,2}',  # YYYY-MM-DD
            r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}'
        ]
        
        dates = []
        for pattern in date_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            dates.extend(matches)
        
        return list(set(dates))  # Remove duplicates
    
    def _extract_monetary_amounts(self, content: str) -> List[str]:
        """Extract monetary amounts from content."""
        import re
        
        # Monetary patterns
        money_patterns = [
            r'\$[\d,]+\.?\d*',  # $1,000.00
            r'USD\s*[\d,]+\.?\d*',  # USD 1000
            r'[\d,]+\.?\d*\s*(?:dollars?|USD)',  # 1000 dollars
        ]
        
        amounts = []
        for pattern in money_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            amounts.extend(matches)
        
        return list(set(amounts))  # Remove duplicates
    
    def _assess_content_quality(self, content: str, extracted_data: Dict[str, Any]) -> Dict[str, Any]:
        """Assess the quality of extracted content."""
        try:
            quality = {
                "text_to_noise_ratio": 1.0,
                "has_meaningful_content": True,
                "extraction_confidence": 1.0
            }
            
            # Calculate text to noise ratio
            if content:
                words = content.split()
                meaningful_words = [w for w in words if len(w) > 2 and w.isalpha()]
                quality["text_to_noise_ratio"] = len(meaningful_words) / len(words) if words else 0
            
            # Check for meaningful content
            if len(content.strip()) < 50:
                quality["has_meaningful_content"] = False
            
            # Estimate extraction confidence based on document structure
            pages = extracted_data.get("pages", [])
            if pages:
                total_confidence = 0
                word_count = 0
                
                for page in pages:
                    for word in page.get("words", []):
                        confidence = word.get("confidence", 0)
                        if confidence > 0:
                            total_confidence += confidence
                            word_count += 1
                
                if word_count > 0:
                    quality["extraction_confidence"] = total_confidence / word_count
            
            return quality
            
        except Exception as e:
            logger.error(f"Failed to assess content quality: {e}")
            return {"text_to_noise_ratio": 1.0, "has_meaningful_content": True, "extraction_confidence": 1.0}
    
    async def process_document_complete(self, document_content: bytes,
                                      content_type: str,
                                      document: Document) -> Dict[str, Any]:
        """Complete document processing with extraction, entities, and summary."""
        try:
            # Extract main content
            content, extracted_data = await self.extract_document_content(
                document_content, content_type, document
            )
            
            # Analyze structure
            structure = await self.analyze_document_structure(extracted_data)
            
            # Extract metadata
            metadata = await self.extract_document_metadata(extracted_data, content)
            
            # Extract entities and generate summary in parallel if OpenAI client available
            entities = []
            summary = ""
            
            if self.aoai_client and content.strip():
                try:
                    # Run entity extraction and summarization in parallel
                    entities_task = self.extract_entities_from_content(content)
                    summary_task = self.generate_document_summary(content)
                    
                    entities, summary = await asyncio.gather(
                        entities_task, summary_task, return_exceptions=True
                    )
                    
                    # Handle exceptions
                    if isinstance(entities, Exception):
                        logger.error(f"Entity extraction failed: {entities}")
                        entities = []
                    
                    if isinstance(summary, Exception):
                        logger.error(f"Summary generation failed: {summary}")
                        summary = ""
                        
                except Exception as e:
                    logger.error(f"Failed to run AI processing: {e}")
            
            return {
                "content": content,
                "extracted_data": extracted_data,
                "structure": structure,
                "metadata": metadata,
                "entities": entities,
                "summary": summary
            }
            
        except Exception as e:
            logger.error(f"Failed to process document completely: {e}")
            raise
