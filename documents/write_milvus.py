"""
Milvus Vector Database Writer - Lightweight Version

Optimized for low-resource servers (4GB RAM, limited CPU).

Features:
    - Single-process architecture (avoids multiprocessing overhead)
    - Memory-efficient streaming processing
    - Small batch sizes for low memory
    - Explicit resource cleanup
    - Progress tracking with tqdm
"""

from __future__ import annotations

import gc
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document

from documents.markdown_parser import MarkdownParser
from documents.milvus_db import MilvusManager, MilvusConfig
from utils.env_utils import COLLECTION_NAME, MILVUS_URI
from utils.log_utils import log

# Try to import tqdm
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    tqdm = None  # type: ignore

__all__ = [
    "MilvusWriterConfig",
    "WriterStats",
    "DocumentWriter",
    "write_documents_to_milvus",
]


@dataclass
class MilvusWriterConfig:
    """
    Configuration for low-resource servers.
    
    Default values optimized for 4GB RAM servers.
    """
    source_dir: str = ""
    milvus_uri: str = MILVUS_URI
    collection_name: str = COLLECTION_NAME
    
    # Small batch sizes for low memory
    batch_size: int = 20
    max_file_size_mb: int = 20
    
    # File processing
    include_patterns: Tuple[str, ...] = (".md",)
    recursive: bool = True
    
    # Logging
    log_interval: int = 5
    show_progress: bool = True


@dataclass
class WriterStats:
    """Statistics for the writing process."""
    files_scanned: int = 0
    files_parsed: int = 0
    files_failed: int = 0
    files_skipped: int = 0
    documents_parsed: int = 0
    documents_written: int = 0
    documents_failed: int = 0
    total_time_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "files": {
                "scanned": self.files_scanned,
                "parsed": self.files_parsed,
                "failed": self.files_failed,
                "skipped": self.files_skipped,
            },
            "documents": {
                "parsed": self.documents_parsed,
                "written": self.documents_written,
                "failed": self.documents_failed,
            },
            "performance": {
                "total_time_seconds": round(self.total_time_seconds, 2),
                "docs_per_second": round(
                    self.documents_written / self.total_time_seconds, 2
                ) if self.total_time_seconds > 0 else 0,
            },
        }


def _scan_files(
    source_dir: Path,
    patterns: Tuple[str, ...],
    recursive: bool,
    max_size_mb: int,
) -> Tuple[List[Path], List[Tuple[Path, str]]]:
    """Scan directory for files."""
    files: List[Path] = []
    skipped: List[Tuple[Path, str]] = []
    max_size_bytes = max_size_mb * 1024 * 1024
    
    for pattern in patterns:
        if recursive:
            matched = list(source_dir.rglob(f"*{pattern}"))
        else:
            matched = list(source_dir.glob(f"*{pattern}"))
        
        for file_path in matched:
            if not file_path.is_file():
                continue
            
            file_size = file_path.stat().st_size
            if file_size > max_size_bytes:
                skipped.append((file_path, f"Size exceeds {max_size_mb}MB"))
                continue
            
            files.append(file_path)
    
    return sorted(set(files)), skipped


class DocumentWriter:
    """
    Single-process document writer for low-resource servers.
    
    Memory-efficient design:
    - Processes files one at a time
    - Uses small batches
    - Explicit garbage collection
    - Context manager for resource cleanup
    """

    def __init__(self, config: Optional[MilvusWriterConfig] = None) -> None:
        self.config = config or MilvusWriterConfig()
        self._parser: Optional[MarkdownParser] = None
        self._milvus: Optional[MilvusManager] = None

    def _init_parser(self) -> MarkdownParser:
        """Initialize parser lazily."""
        if self._parser is None:
            self._parser = MarkdownParser()
        return self._parser

    def _init_milvus(self) -> MilvusManager:
        """Initialize Milvus connection lazily."""
        if self._milvus is None:
            config = MilvusConfig(
                uri=self.config.milvus_uri,
                collection_name=self.config.collection_name,
                batch_size=self.config.batch_size,
            )
            self._milvus = MilvusManager(config)
        return self._milvus

    def _cleanup(self) -> None:
        """Cleanup resources."""
        if self._milvus is not None:
            self._milvus.close()
            self._milvus = None
        
        self._parser = None
        gc.collect()

    def run(self) -> WriterStats:
        """
        Run the document writing pipeline.
        
        Returns:
            WriterStats with processing statistics
        """
        start_time = time.perf_counter()
        stats = WriterStats()

        log.info("=" * 50)
        log.info("Document Writer Starting (Lightweight Mode)")
        log.info(f"Source: {self.config.source_dir}")
        log.info(f"Collection: {self.config.collection_name}")
        log.info(f"Batch size: {self.config.batch_size}")
        log.info("=" * 50)

        # Validate source
        source_path = Path(self.config.source_dir)
        if not source_path.exists():
            log.error(f"Source directory not found: {source_path}")
            stats.total_time_seconds = time.perf_counter() - start_time
            return stats

        # Scan files
        log.info("Scanning files...")
        files, skipped = _scan_files(
            source_path,
            self.config.include_patterns,
            self.config.recursive,
            self.config.max_file_size_mb,
        )
        stats.files_scanned = len(files)
        stats.files_skipped = len(skipped)

        if skipped:
            log.info(f"Skipped {len(skipped)} files (size limit)")

        if not files:
            log.warning(f"No files found in {source_path}")
            stats.total_time_seconds = time.perf_counter() - start_time
            return stats

        log.info(f"Found {len(files)} files to process")

        try:
            # Initialize Milvus
            milvus = self._init_milvus()
            milvus.create_collection(drop_if_exists=False)
            
            # Initialize parser
            parser = self._init_parser()

            # Process files
            all_docs: List[Document] = []
            
            if TQDM_AVAILABLE and self.config.show_progress:
                file_iter = tqdm(files, desc="Parsing files", unit="file")
            else:
                file_iter = files

            for file_path in file_iter:
                try:
                    docs = parser.parse_markdown_to_documents(file_path)
                    if docs:
                        all_docs.extend(docs)
                        stats.files_parsed += 1
                        stats.documents_parsed += len(docs)
                    else:
                        stats.files_skipped += 1

                    # Log progress
                    if stats.files_parsed % self.config.log_interval == 0:
                        log.info(f"Parsed {stats.files_parsed}/{len(files)} files, "
                                f"{stats.documents_parsed} documents")

                except Exception as e:
                    log.error(f"Failed to parse {file_path}: {e}")
                    stats.files_failed += 1

            # Write documents to Milvus
            if all_docs:
                log.info(f"Writing {len(all_docs)} documents to Milvus...")
                
                result = milvus.add_documents(
                    documents=all_docs,
                    batch_size=self.config.batch_size,
                    show_progress=True
                )
                
                stats.documents_written = result.get("inserted", 0)
                stats.documents_failed = result.get("failed", 0)
                
                # Clear documents to free memory
                all_docs.clear()
                gc.collect()

        except Exception as e:
            log.error(f"Pipeline error: {e}")
            raise

        finally:
            self._cleanup()

        stats.total_time_seconds = time.perf_counter() - start_time
        self._log_summary(stats)

        return stats

    def _log_summary(self, stats: WriterStats) -> None:
        """Log summary."""
        log.info("=" * 50)
        log.info("Document Writer Completed")
        log.info("=" * 50)
        log.info(f"Files: {stats.files_parsed} parsed, {stats.files_failed} failed")
        log.info(f"Documents: {stats.documents_written} written, {stats.documents_failed} failed")
        log.info(f"Total time: {stats.total_time_seconds:.2f}s")
        if stats.total_time_seconds > 0:
            log.info(f"Throughput: {stats.documents_written / stats.total_time_seconds:.2f} docs/sec")
        log.info("=" * 50)


def write_documents_to_milvus(
    source_dir: str,
    collection_name: Optional[str] = None,
    batch_size: int = 20,
) -> Dict[str, Any]:
    """
    Convenience function to write documents to Milvus.
    
    Args:
        source_dir: Directory containing markdown files
        collection_name: Target collection name
        batch_size: Documents per batch (small for low memory)
    
    Returns:
        Dictionary with statistics
    """
    config = MilvusWriterConfig(
        source_dir=source_dir,
        collection_name=collection_name or COLLECTION_NAME,
        batch_size=batch_size,
    )

    writer = DocumentWriter(config)
    stats = writer.run()
    return stats.to_dict()


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Write markdown documents to Milvus (Lightweight Mode)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python -m documents.write_milvus --source-dir /path/to/md

  # With custom batch size
  python -m documents.write_milvus --source-dir /path/to/md --batch-size 10

  # Non-recursive scan
  python -m documents.write_milvus --source-dir /path/to/md --no-recursive
        """
    )
    parser.add_argument(
        "--source-dir",
        type=str,
        default="/home/ubuntu/Project/RAG/md",
        help="Directory containing markdown files",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=COLLECTION_NAME,
        help="Milvus collection name",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Documents per batch (small for low memory)",
    )
    parser.add_argument(
        "--max-file-size",
        type=int,
        default=20,
        help="Maximum file size in MB",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not scan directories recursively",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bar",
    )

    args = parser.parse_args()

    config = MilvusWriterConfig(
        source_dir=args.source_dir,
        collection_name=args.collection,
        batch_size=args.batch_size,
        max_file_size_mb=args.max_file_size,
        recursive=not args.no_recursive,
        show_progress=not args.no_progress,
    )

    writer = DocumentWriter(config)
    stats = writer.run()

    # Print summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"Files processed: {stats.files_parsed}")
    print(f"Files failed: {stats.files_failed}")
    print(f"Documents written: {stats.documents_written}")
    print(f"Documents failed: {stats.documents_failed}")
    print(f"Total time: {stats.total_time_seconds:.2f}s")
    if stats.total_time_seconds > 0:
        print(f"Throughput: {stats.documents_written / stats.total_time_seconds:.2f} docs/sec")
    print("=" * 50)

    if stats.files_failed > 0 or stats.documents_failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()