"""Chunking service for splitting documents into searchable chunks."""

import logging
import re
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from ..models.chunk import Chunk, ChunkMetadata
from ..models.document import Document


logger = logging.getLogger(__name__)


class ChunkingService:
    """Service for splitting documents into chunks for vector search."""
    
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        """Initialize the chunking service."""
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
    
    def create_chunks(self, document: Document, content: str, 
                     extracted_data: Dict[str, Any] = None,
                     entities: List[Dict[str, Any]] = None) -> List[Chunk]:
        """Create chunks from document content."""
        try:
            logger.info(f"Creating chunks for document {document.file_name}")
            
            if not content.strip():
                logger.warning(f"No content to chunk for document {document.file_name}")
                return []
            
            # Choose chunking strategy based on document type and content
            strategy = self._determine_chunking_strategy(content, extracted_data)
            
            if strategy == "paragraph":
                chunks = self._chunk_by_paragraphs(document, content, entities)
            elif strategy == "sentence":
                chunks = self._chunk_by_sentences(document, content, entities)
            elif strategy == "semantic":
                chunks = self._chunk_semantically(document, content, entities)
            else:  # fixed_size
                chunks = self._chunk_by_fixed_size(document, content, entities)
            
            # Post-process chunks
            processed_chunks = self._post_process_chunks(chunks, document, extracted_data)
            
            logger.info(f"Created {len(processed_chunks)} chunks for document {document.file_name}")
            
            return processed_chunks
            
        except Exception as e:
            logger.error(f"Failed to create chunks for document {document.file_name}: {e}")
            return []
    
    def _determine_chunking_strategy(self, content: str, 
                                   extracted_data: Dict[str, Any] = None) -> str:
        """Determine the best chunking strategy for the content."""
        try:
            # Analyze content characteristics
            paragraphs = content.split('\n\n')
            avg_paragraph_length = sum(len(p) for p in paragraphs) / len(paragraphs) if paragraphs else 0
            
            # If we have well-structured paragraphs, use paragraph chunking
            if len(paragraphs) > 3 and 200 <= avg_paragraph_length <= 800:
                return "paragraph"
            
            # If content is very long with short paragraphs, use semantic chunking
            if len(content) > 5000 and avg_paragraph_length < 200:
                return "semantic"
            
            # If content has lots of short sentences, use sentence chunking
            sentences = re.split(r'[.!?]+', content)
            avg_sentence_length = sum(len(s.strip()) for s in sentences) / len(sentences) if sentences else 0
            
            if len(sentences) > 10 and 50 <= avg_sentence_length <= 150:
                return "sentence"
            
            # Default to fixed size
            return "fixed_size"
            
        except Exception as e:
            logger.error(f"Failed to determine chunking strategy: {e}")
            return "fixed_size"
    
    def _chunk_by_paragraphs(self, document: Document, content: str,
                           entities: List[Dict[str, Any]] = None) -> List[Chunk]:
        """Chunk content by paragraphs with overlap."""
        chunks = []
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        
        current_chunk = ""
        current_paragraphs = []
        start_offset = 0
        chunk_index = 0
        
        for i, paragraph in enumerate(paragraphs):
            # Calculate where this paragraph starts in the original content
            paragraph_start = content.find(paragraph, start_offset)
            if paragraph_start == -1:
                paragraph_start = start_offset
            
            # Check if adding this paragraph would exceed chunk size
            test_chunk = current_chunk + ("\n\n" if current_chunk else "") + paragraph
            
            if len(test_chunk) > self.chunk_size and current_chunk:
                # Create chunk from current content
                chunk = self._create_chunk(
                    document=document,
                    text=current_chunk.strip(),
                    chunk_index=chunk_index,
                    start_offset=start_offset,
                    strategy="paragraph",
                    entities=entities
                )
                chunks.append(chunk)
                chunk_index += 1
                
                # Handle overlap - keep last paragraph if it's not too long
                overlap_paragraphs = []
                overlap_text = ""
                
                for p in reversed(current_paragraphs):
                    test_overlap = p + ("\n\n" + overlap_text if overlap_text else "")
                    if len(test_overlap) <= self.chunk_overlap:
                        overlap_text = test_overlap
                        overlap_paragraphs.insert(0, p)
                    else:
                        break
                
                current_chunk = overlap_text
                current_paragraphs = overlap_paragraphs.copy()
                start_offset = paragraph_start
            
            # Add current paragraph
            if current_chunk:
                current_chunk += "\n\n" + paragraph
            else:
                current_chunk = paragraph
                start_offset = paragraph_start
            
            current_paragraphs.append(paragraph)
        
        # Add final chunk if there's remaining content
        if current_chunk.strip():
            chunk = self._create_chunk(
                document=document,
                text=current_chunk.strip(),
                chunk_index=chunk_index,
                start_offset=start_offset,
                strategy="paragraph",
                entities=entities
            )
            chunks.append(chunk)
        
        return chunks
    
    def _chunk_by_sentences(self, document: Document, content: str,
                          entities: List[Dict[str, Any]] = None) -> List[Chunk]:
        """Chunk content by sentences with overlap."""
        chunks = []
        
        # Split into sentences
        sentence_pattern = r'(?<=[.!?])\s+'
        sentences = [s.strip() for s in re.split(sentence_pattern, content) if s.strip()]
        
        current_chunk = ""
        current_sentences = []
        start_offset = 0
        chunk_index = 0
        
        for i, sentence in enumerate(sentences):
            # Find sentence position in original content
            sentence_start = content.find(sentence, start_offset)
            if sentence_start == -1:
                sentence_start = start_offset
            
            # Check if adding this sentence would exceed chunk size
            test_chunk = current_chunk + (" " if current_chunk else "") + sentence
            
            if len(test_chunk) > self.chunk_size and current_chunk:
                # Create chunk from current content
                chunk = self._create_chunk(
                    document=document,
                    text=current_chunk.strip(),
                    chunk_index=chunk_index,
                    start_offset=start_offset,
                    strategy="sentence",
                    entities=entities
                )
                chunks.append(chunk)
                chunk_index += 1
                
                # Handle overlap - keep last few sentences
                overlap_sentences = []
                overlap_text = ""
                
                for s in reversed(current_sentences):
                    test_overlap = s + (" " + overlap_text if overlap_text else "")
                    if len(test_overlap) <= self.chunk_overlap:
                        overlap_text = test_overlap
                        overlap_sentences.insert(0, s)
                    else:
                        break
                
                current_chunk = overlap_text
                current_sentences = overlap_sentences.copy()
                start_offset = sentence_start
            
            # Add current sentence
            if current_chunk:
                current_chunk += " " + sentence
            else:
                current_chunk = sentence
                start_offset = sentence_start
            
            current_sentences.append(sentence)
        
        # Add final chunk
        if current_chunk.strip():
            chunk = self._create_chunk(
                document=document,
                text=current_chunk.strip(),
                chunk_index=chunk_index,
                start_offset=start_offset,
                strategy="sentence",
                entities=entities
            )
            chunks.append(chunk)
        
        return chunks
    
    def _chunk_by_fixed_size(self, document: Document, content: str,
                           entities: List[Dict[str, Any]] = None) -> List[Chunk]:
        """Chunk content by fixed character size with overlap."""
        chunks = []
        chunk_index = 0
        
        for i in range(0, len(content), self.chunk_size - self.chunk_overlap):
            end_pos = min(i + self.chunk_size, len(content))
            chunk_text = content[i:end_pos].strip()
            
            if chunk_text:
                # Try to break at word boundaries
                if end_pos < len(content) and not content[end_pos].isspace():
                    # Find last space within the chunk
                    last_space = chunk_text.rfind(' ')
                    if last_space > self.chunk_size * 0.8:  # Only if it's not too far back
                        chunk_text = chunk_text[:last_space]
                
                chunk = self._create_chunk(
                    document=document,
                    text=chunk_text,
                    chunk_index=chunk_index,
                    start_offset=i,
                    strategy="fixed_size",
                    entities=entities
                )
                chunks.append(chunk)
                chunk_index += 1
        
        return chunks
    
    def _chunk_semantically(self, document: Document, content: str,
                          entities: List[Dict[str, Any]] = None) -> List[Chunk]:
        """Chunk content semantically by topics/sections."""
        # This is a simplified semantic chunking - could be enhanced with NLP libraries
        try:
            # Look for section headers and natural breaks
            sections = self._identify_sections(content)
            
            if len(sections) > 1:
                return self._chunk_by_sections(document, sections, entities)
            else:
                # Fall back to paragraph chunking
                return self._chunk_by_paragraphs(document, content, entities)
                
        except Exception as e:
            logger.error(f"Failed to chunk semantically: {e}")
            return self._chunk_by_fixed_size(document, content, entities)
    
    def _identify_sections(self, content: str) -> List[Dict[str, Any]]:
        """Identify sections in the content."""
        sections = []
        
        # Look for common section headers
        header_patterns = [
            r'^[A-Z][A-Z\s]{2,}$',  # ALL CAPS headers
            r'^\d+\.\s+[A-Z]',      # Numbered sections
            r'^[A-Z][a-z]+:',       # Title: format
            r'^\s*-{3,}\s*$',       # Separator lines
            r'^\s*={3,}\s*$',       # Separator lines
        ]
        
        lines = content.split('\n')
        current_section = {"start": 0, "content": "", "title": ""}
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            
            # Check if this line is a header
            is_header = False
            for pattern in header_patterns:
                if re.match(pattern, line_stripped):
                    is_header = True
                    break
            
            if is_header and current_section["content"].strip():
                # Save current section
                sections.append(current_section.copy())
                
                # Start new section
                current_section = {
                    "start": content.find(line),
                    "content": line + "\n",
                    "title": line_stripped[:50]  # Truncate title
                }
            else:
                current_section["content"] += line + "\n"
        
        # Add final section
        if current_section["content"].strip():
            sections.append(current_section)
        
        return sections if len(sections) > 1 else [{"start": 0, "content": content, "title": ""}]
    
    def _chunk_by_sections(self, document: Document, sections: List[Dict[str, Any]],
                          entities: List[Dict[str, Any]] = None) -> List[Chunk]:
        """Chunk content by identified sections."""
        chunks = []
        chunk_index = 0
        
        for section in sections:
            section_content = section["content"].strip()
            section_title = section["title"]
            
            if len(section_content) <= self.chunk_size:
                # Section fits in one chunk
                chunk = self._create_chunk(
                    document=document,
                    text=section_content,
                    chunk_index=chunk_index,
                    start_offset=section["start"],
                    title=section_title,
                    strategy="semantic",
                    entities=entities
                )
                chunks.append(chunk)
                chunk_index += 1
            else:
                # Section needs to be split further
                section_chunks = self._chunk_by_paragraphs(
                    document, section_content, entities
                )
                
                # Update chunk indices and add title
                for chunk in section_chunks:
                    chunk.chunk_index = chunk_index
                    if not chunk.title and section_title:
                        chunk.title = section_title
                    chunk.start_offset += section["start"]
                    chunk.end_offset += section["start"]
                    chunks.append(chunk)
                    chunk_index += 1
        
        return chunks
    
    def _create_chunk(self, document: Document, text: str, chunk_index: int,
                     start_offset: int, strategy: str = "fixed_size",
                     title: str = None, entities: List[Dict[str, Any]] = None) -> Chunk:
        """Create a chunk object with metadata."""
        try:
            end_offset = start_offset + len(text)
            
            # Create chunk metadata
            metadata = ChunkMetadata(
                document_id=document.id,
                page_number=None,  # Could be enhanced to track page numbers
                section_title=title,
                paragraph_index=chunk_index,
                content_type="text",
                account_id=document.metadata.account_id if document.metadata else None,
                owner_email=document.metadata.owner_email if document.metadata else None,
                department=document.metadata.department if document.metadata else None,
                project_name=document.metadata.project_name if document.metadata else None,
                extraction_method="document_intelligence",
                chunk_strategy=strategy
            )
            
            # Create chunk
            chunk = Chunk(
                document_id=document.id,
                chunk_index=chunk_index,
                text=text,
                title=title,
                start_offset=start_offset,
                end_offset=end_offset,
                metadata=metadata
            )
            
            # Add relevant entities to the chunk
            if entities:
                chunk_entities = self._filter_entities_for_chunk(text, entities)
                chunk.entities = chunk_entities
            
            return chunk
            
        except Exception as e:
            logger.error(f"Failed to create chunk: {e}")
            raise
    
    def _filter_entities_for_chunk(self, chunk_text: str, 
                                  entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter entities that are relevant to this chunk."""
        try:
            chunk_entities = []
            chunk_text_lower = chunk_text.lower()
            
            for entity in entities:
                entity_text = entity.get("text", "").lower()
                if entity_text and entity_text in chunk_text_lower:
                    # Find position within chunk
                    start_pos = chunk_text_lower.find(entity_text)
                    if start_pos != -1:
                        chunk_entity = entity.copy()
                        chunk_entity["start"] = start_pos
                        chunk_entity["end"] = start_pos + len(entity_text)
                        chunk_entities.append(chunk_entity)
            
            return chunk_entities
            
        except Exception as e:
            logger.error(f"Failed to filter entities for chunk: {e}")
            return []
    
    def _post_process_chunks(self, chunks: List[Chunk], document: Document,
                           extracted_data: Dict[str, Any] = None) -> List[Chunk]:
        """Post-process chunks to enhance quality."""
        try:
            processed_chunks = []
            
            for chunk in chunks:
                # Skip chunks that are too short or empty
                if len(chunk.text.strip()) < 50:
                    logger.debug(f"Skipping short chunk: {len(chunk.text)} characters")
                    continue
                
                # Clean chunk text
                chunk.text = self._clean_chunk_text(chunk.text)
                
                # Add automatic tags based on content
                chunk.tags = self._generate_chunk_tags(chunk.text, document)
                
                # Update end offset after cleaning
                chunk.end_offset = chunk.start_offset + len(chunk.text)
                
                processed_chunks.append(chunk)
            
            # Renumber chunks after filtering
            for i, chunk in enumerate(processed_chunks):
                chunk.chunk_index = i
            
            return processed_chunks
            
        except Exception as e:
            logger.error(f"Failed to post-process chunks: {e}")
            return chunks
    
    def _clean_chunk_text(self, text: str) -> str:
        """Clean and normalize chunk text."""
        try:
            # Remove excessive whitespace
            cleaned = re.sub(r'\s+', ' ', text.strip())
            
            # Remove control characters
            cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', cleaned)
            
            return cleaned
            
        except Exception as e:
            logger.error(f"Failed to clean chunk text: {e}")
            return text
    
    def _generate_chunk_tags(self, text: str, document: Document) -> List[str]:
        """Generate automatic tags for the chunk based on content."""
        try:
            tags = []
            text_lower = text.lower()
            
            # Document type tags
            if document.document_type:
                tags.append(document.document_type.value)
            
            # Content type tags
            if "table" in text_lower or "|" in text:
                tags.append("table")
            
            if any(keyword in text_lower for keyword in ["agreement", "contract", "terms"]):
                tags.append("contract")
            
            if any(keyword in text_lower for keyword in ["invoice", "bill", "payment"]):
                tags.append("financial")
            
            if any(keyword in text_lower for keyword in ["summary", "conclusion", "overview"]):
                tags.append("summary")
            
            # Length tags
            if len(text) > 800:
                tags.append("long-content")
            elif len(text) < 200:
                tags.append("short-content")
            
            return tags
            
        except Exception as e:
            logger.error(f"Failed to generate chunk tags: {e}")
            return []
    
    def get_optimal_chunk_size(self, content_length: int, 
                             target_chunk_count: int = None) -> int:
        """Calculate optimal chunk size for content."""
        try:
            if target_chunk_count:
                # Calculate size based on desired chunk count
                optimal_size = content_length // target_chunk_count
                # Ensure it's within reasonable bounds
                return max(500, min(2000, optimal_size))
            
            # Use default logic
            if content_length < 2000:
                return min(content_length, 1000)
            elif content_length < 10000:
                return 1200
            else:
                return 1500
                
        except Exception as e:
            logger.error(f"Failed to calculate optimal chunk size: {e}")
            return self.chunk_size
