"""
Milvus Vector Database Manager - Lightweight Version

Optimized for low-resource servers (4GB RAM, limited CPU).

Features:
    - Lazy initialization to minimize memory footprint
    - Small batch sizes for memory efficiency
    - Explicit resource cleanup
    - Simplified architecture without singleton pattern
    - Memory-conscious embedding model loading
"""

from __future__ import annotations

import gc
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

from langchain_core.documents import Document
from pymilvus import DataType, MilvusClient, MilvusException
from pymilvus.client.types import MetricType

from utils.env_utils import COLLECTION_NAME, MILVUS_URI
from utils.log_utils import log

# Type variables
T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])


class SearchMode(Enum):
    """Search mode enumeration."""
    DENSE_ONLY = "dense_only"
    SPARSE_ONLY = "sparse_only"
    HYBRID = "hybrid"


@dataclass
class MilvusConfig:
    """
    Configuration optimized for low-resource servers.
    
    Default values are conservative for 4GB RAM servers.
    """
    uri: str = MILVUS_URI
    collection_name: str = COLLECTION_NAME
    dense_dim: int = 512
    max_text_length: int = 4000  # Reduced from 6000
    max_metadata_length: int = 500  # Reduced from 1000
    batch_size: int = 20  # Small batch size for low memory
    max_retries: int = 3
    retry_delay: float = 2.0  # Longer delay for slow servers
    retry_backoff: float = 2.0
    connection_timeout: float = 60.0  # Longer timeout
    consistency_level: str = "Bounded"  # Less strict than "Strong"

    # Lightweight index parameters
    hnsw_m: int = 8  # Reduced from 16
    hnsw_ef_construction: int = 32  # Reduced from 64
    hnsw_ef_search: int = 32


@dataclass
class SearchResult:
    """Search result container."""
    id: int
    text: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_document(self) -> Document:
        return Document(
            page_content=self.text,
            metadata={"score": self.score, **self.metadata}
        )


class MilvusConnectionError(Exception):
    """Connection error."""
    pass


class MilvusOperationError(Exception):
    """Operation error."""
    pass


def retry_on_failure(
    max_retries: Optional[int] = None,
    delay: Optional[float] = None,
    backoff: Optional[float] = None,
    exceptions: Tuple[type, ...] = (MilvusException, ConnectionError, TimeoutError)
) -> Callable[[F], F]:
    """Retry decorator with exponential backoff."""
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(self: "MilvusManager", *args: Any, **kwargs: Any) -> Any:
            config = self.config
            _max_retries = max_retries or config.max_retries
            _delay = delay or config.retry_delay
            _backoff = backoff or config.retry_backoff

            last_exception: Optional[Exception] = None
            current_delay = _delay

            for attempt in range(_max_retries + 1):
                try:
                    return func(self, *args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < _max_retries:
                        log.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}): {e}. "
                            f"Retry in {current_delay:.1f}s..."
                        )
                        time.sleep(current_delay)
                        current_delay *= _backoff
                    else:
                        log.error(f"{func.__name__} failed after {_max_retries + 1} attempts")

            raise MilvusOperationError(
                f"{func.__name__} failed after {_max_retries + 1} retries"
            ) from last_exception

        return wrapper  # type: ignore
    return decorator


def _get_embedding_function():
    """
    Lazy-load embedding function to save memory.
    
    Only loads the model when actually needed.
    """
    from langchain_huggingface import HuggingFaceEmbeddings
    
    local_model_path = "/home/ubuntu/LocalModels/bge-small-zh-v1.5"
    
    return HuggingFaceEmbeddings(
        model_name=local_model_path,
        model_kwargs={"device": "cpu"},
        encode_kwargs={
            "normalize_embeddings": True,
            "batch_size": 4,  # Small batch for low memory
        },
    )


class MilvusManager:
    """
    Lightweight Milvus manager for low-resource servers.
    
    Key optimizations:
    - No singleton pattern (works with multiprocessing)
    - Lazy embedding model loading
    - Small default batch sizes
    - Explicit cleanup methods
    - Memory-efficient operations
    """

    def __init__(self, config: Optional[MilvusConfig] = None) -> None:
        """Initialize with lazy loading."""
        self.config = config or MilvusConfig()
        self._client: Optional[MilvusClient] = None
        self._embedding_fn = None  # Lazy loaded
        self._collection_loaded = False
        
        log.debug(f"MilvusManager created: {self.config.collection_name}")

    @property
    def client(self) -> MilvusClient:
        """Get Milvus client (lazy initialization)."""
        if self._client is None:
            self._connect()
        return self._client

    @property
    def embedding_function(self):
        """Get embedding function (lazy initialization)."""
        if self._embedding_fn is None:
            log.info("Loading embedding model...")
            self._embedding_fn = _get_embedding_function()
            log.info("Embedding model loaded")
        return self._embedding_fn

    def _connect(self) -> None:
        """Connect to Milvus server."""
        if self._client is not None:
            return
            
        try:
            self._client = MilvusClient(
                uri=self.config.uri,
                timeout=self.config.connection_timeout
            )
            log.info(f"Connected to Milvus: {self.config.uri}")
        except Exception as e:
            raise MilvusConnectionError(f"Connection failed: {e}") from e

    def close(self) -> None:
        """
        Explicitly close connections and free memory.
        
        Call this when done to release resources.
        """
        if self._client is not None:
            try:
                if self._collection_loaded:
                    try:
                        self._client.release_collection(self.config.collection_name)
                    except Exception:
                        pass
            except Exception:
                pass
            finally:
                self._client = None
                self._collection_loaded = False
        
        # Clear embedding function to free memory
        self._embedding_fn = None
        
        # Force garbage collection
        gc.collect()
        log.debug("MilvusManager resources released")

    def __enter__(self) -> "MilvusManager":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - cleanup resources."""
        self.close()

    @retry_on_failure()
    def create_collection(self, drop_if_exists: bool = False) -> bool:
        """Create collection with lightweight schema."""
        log.info(f"Creating collection: {self.config.collection_name}")

        if self.config.collection_name in self.client.list_collections():
            if drop_if_exists:
                log.info(f"Dropping existing collection")
                try:
                    self.client.release_collection(self.config.collection_name)
                except Exception:
                    pass
                self.client.drop_collection(self.config.collection_name)
            else:
                log.info(f"Collection already exists")
                return True

        # Create schema
        schema = self.client.create_schema(auto_id=True, enable_dynamic_field=True)

        # Essential fields only
        schema.add_field(
            field_name="id",
            datatype=DataType.INT64,
            is_primary=True,
            auto_id=True
        )
        schema.add_field(
            field_name="text",
            datatype=DataType.VARCHAR,
            max_length=self.config.max_text_length,
            enable_analyzer=True,
            analyzer_params={"tokenizer": "jieba"}
        )
        schema.add_field(
            field_name="dense",
            datatype=DataType.FLOAT_VECTOR,
            dim=self.config.dense_dim
        )
        # Metadata fields
        schema.add_field(
            field_name="source",
            datatype=DataType.VARCHAR,
            max_length=self.config.max_metadata_length
        )
        schema.add_field(
            field_name="title",
            datatype=DataType.VARCHAR,
            max_length=self.config.max_metadata_length
        )

        # Create index params
        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="dense",
            index_type="HNSW",
            metric_type=MetricType.IP,
            params={
                "M": self.config.hnsw_m,
                "efConstruction": self.config.hnsw_ef_construction
            }
        )

        # Create collection
        self.client.create_collection(
            collection_name=self.config.collection_name,
            schema=schema,
            index_params=index_params
        )

        log.info(f"Collection created: {self.config.collection_name}")
        return True

    def _ensure_collection_loaded(self) -> None:
        """Ensure collection exists and is loaded into memory."""
        if not self._collection_loaded:
            try:
                # Check if collection exists
                collections = self.client.list_collections()
                if self.config.collection_name not in collections:
                    log.warning(f"Collection '{self.config.collection_name}' not found, creating...")
                    self.create_collection(drop_if_exists=False)

                self.client.load_collection(self.config.collection_name)
                self._collection_loaded = True
                log.debug(f"Collection '{self.config.collection_name}' loaded successfully")
            except Exception as e:
                log.error(f"Failed to ensure collection loaded: {e}")
                raise

    @retry_on_failure()
    def add_documents(
        self,
        documents: List[Document],
        batch_size: Optional[int] = None,
        show_progress: bool = True
    ) -> Dict[str, Any]:
        """
        Add documents with memory-efficient batching.
        
        Uses small batches and explicit cleanup to minimize memory usage.
        """
        if not documents:
            return {"inserted": 0, "failed": 0, "total": 0}

        batch_size = batch_size or self.config.batch_size
        total = len(documents)
        inserted = 0
        failed = 0

        log.info(f"Adding {total} documents (batch_size={batch_size})")

        self._ensure_collection_loaded()

        # Process in small batches
        for i in range(0, total, batch_size):
            batch = documents[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total + batch_size - 1) // batch_size

            try:
                # Generate embeddings for this batch
                texts = [doc.page_content for doc in batch]
                embeddings = self.embedding_function.embed_documents(texts)
                
                # Prepare data for insertion
                data = []
                for doc, emb in zip(batch, embeddings):
                    row = {
                        "text": doc.page_content[:self.config.max_text_length],
                        "dense": emb,
                        "source": doc.metadata.get("source", "")[:self.config.max_metadata_length],
                        "title": doc.metadata.get("title", "")[:self.config.max_metadata_length],
                    }
                    # Add additional metadata as dynamic fields
                    for k, v in doc.metadata.items():
                        if k not in row and isinstance(v, (str, int, float, bool)):
                            row[k] = v
                    data.append(row)
                
                # Insert into Milvus
                self.client.insert(
                    collection_name=self.config.collection_name,
                    data=data
                )
                inserted += len(batch)

                if show_progress:
                    log.info(f"Batch {batch_num}/{total_batches}: {inserted}/{total} docs")

                # Clean up to free memory
                del embeddings
                del data
                
                # Periodic garbage collection
                if batch_num % 5 == 0:
                    gc.collect()

            except Exception as e:
                failed += len(batch)
                log.error(f"Batch {batch_num} failed: {e}")
                continue

        result = {
            "inserted": inserted,
            "failed": failed,
            "total": total,
            "success_rate": inserted / total if total > 0 else 0
        }

        log.info(f"Insertion complete: inserted={inserted}, failed={failed}")
        return result

    @retry_on_failure()
    def search(
        self,
        query: str,
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        Search for similar documents.
        
        Memory-efficient search with explicit cleanup.
        """
        log.debug(f"Searching: '{query[:50]}...' (top_k={top_k})")

        try:
            self._ensure_collection_loaded()

            # Generate query embedding
            query_embedding = self.embedding_function.embed_query(query)

            # Search
            search_params = {
                "metric_type": "IP",
                "params": {"ef": self.config.hnsw_ef_search}
            }

            results = self.client.search(
                collection_name=self.config.collection_name,
                data=[query_embedding],
                anns_field="dense",
                search_params=search_params,
                limit=top_k,
                output_fields=["text", "source", "title"],
                filter=filter_expr,
            )

            # Clean up embedding
            del query_embedding

            # Convert results
            search_results = []
            if results and len(results) > 0:
                for hit in results[0]:
                    result = SearchResult(
                        id=hit.get("id", 0),
                        text=hit.get("entity", {}).get("text", ""),
                        score=hit.get("distance", 0.0),
                        metadata={
                            "source": hit.get("entity", {}).get("source", ""),
                            "title": hit.get("entity", {}).get("title", ""),
                        }
                    )
                    search_results.append(result)

            log.debug(f"Found {len(search_results)} results")
            return search_results

        except Exception as e:
            log.error(f"Search failed: {e}")
            raise MilvusOperationError(f"Search failed: {e}") from e

    def query(
        self,
        filter_expr: str,
        output_fields: Optional[List[str]] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Query documents by filter expression."""
        output_fields = output_fields or ["text", "source", "title"]
        
        results = self.client.query(
            collection_name=self.config.collection_name,
            filter=filter_expr,
            output_fields=output_fields,
            limit=limit
        )
        
        return results

    def delete_by_filter(self, filter_expr: str) -> Dict[str, Any]:
        """Delete documents matching filter."""
        log.info(f"Deleting: {filter_expr}")
        result = self.client.delete(
            collection_name=self.config.collection_name,
            filter=filter_expr
        )
        return {"deleted_count": result}

    def get_collection_stats(self) -> Dict[str, Any]:
        """Get collection statistics."""
        try:
            stats = self.client.get_collection_stats(self.config.collection_name)
            return {
                "collection_name": self.config.collection_name,
                "row_count": stats.get("row_count", 0),
            }
        except Exception as e:
            return {"error": str(e)}

    def health_check(self) -> Dict[str, Any]:
        """Check connection health."""
        result = {
            "connected": False,
            "server_info": None,
            "error": None
        }

        try:
            version = self.client.get_server_version()
            result["server_info"] = {"version": version}
            result["collections"] = self.client.list_collections()
            result["connected"] = True
        except Exception as e:
            result["error"] = str(e)

        return result


def get_milvus_manager(collection_name: str = COLLECTION_NAME) -> MilvusManager:
    """Create a MilvusManager instance."""
    config = MilvusConfig(collection_name=collection_name)
    return MilvusManager(config)


def cleanup_milvus_resources():
    """
    Force cleanup of all Milvus-related resources.
    
    Call this when experiencing memory issues.
    """
    gc.collect()
    log.info("Milvus resources cleaned up")


# =============================================================================
# Test / Demo
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Milvus Database Manager Test")
    parser.add_argument(
        "--collection",
        type=str,
        default=COLLECTION_NAME,
        help="Collection name",
    )
    parser.add_argument(
        "--action",
        type=str,
        choices=["health", "stats", "create", "search", "insert-test"],
        default="health",
        help="Action to perform",
    )
    parser.add_argument(
        "--query",
        type=str,
        default="测试查询",
        help="Search query (for search action)",
    )
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop existing collection when creating",
    )
    
    args = parser.parse_args()
    
    # Create manager with context manager for automatic cleanup
    config = MilvusConfig(collection_name=args.collection)
    
    print(f"\n{'='*50}")
    print(f"Milvus Manager Test")
    print(f"Collection: {args.collection}")
    print(f"Action: {args.action}")
    print(f"{'='*50}\n")
    
    try:
        with MilvusManager(config) as manager:
            if args.action == "health":
                result = manager.health_check()
                print("Health Check Result:")
                print(f"  Connected: {result.get('connected')}")
                print(f"  Server Version: {result.get('server_info', {}).get('version', 'N/A')}")
                print(f"  Collections: {result.get('collections', [])}")
                if result.get("error"):
                    print(f"  Error: {result['error']}")
            
            elif args.action == "stats":
                result = manager.get_collection_stats()
                print("Collection Stats:")
                print(f"  Collection: {result.get('collection_name')}")
                print(f"  Row Count: {result.get('row_count', 0)}")
                if result.get("error"):
                    print(f"  Error: {result['error']}")
            
            elif args.action == "create":
                result = manager.create_collection(drop_if_exists=args.drop)
                print(f"Collection created: {result}")
            
            elif args.action == "search":
                print(f"Searching for: '{args.query}'")
                results = manager.search(args.query, top_k=5)
                print(f"\nFound {len(results)} results:")
                for i, r in enumerate(results, 1):
                    print(f"\n--- Result {i} (score: {r.score:.4f}) ---")
                    print(f"  Source: {r.metadata.get('source', 'N/A')}")
                    print(f"  Title: {r.metadata.get('title', 'N/A')}")
                    print(f"  Text: {r.text[:200]}...")
            
            elif args.action == "insert-test":
                # Insert a test document
                test_docs = [
                    Document(
                        page_content="这是一个测试文档，用于验证Milvus插入功能。",
                        metadata={"source": "test.py", "title": "测试文档"}
                    )
                ]
                result = manager.add_documents(test_docs)
                print(f"Insert result: {result}")
    
    except Exception as e:
        print(f"Error: {e}")
        raise
    
    print(f"\n{'='*50}")
    print("Test completed successfully")
    print(f"{'='*50}\n")