"""Repositories package for data persistence."""

from .contracts_text_repository import ContractsTextRepository
from .processed_files_repository import ProcessedFilesRepository

__all__ = [
    "ContractsTextRepository",
    "ProcessedFilesRepository"
]