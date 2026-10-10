"""ChatterMate PDF knowledge loading on the Agno 3.x native reader/vector APIs."""

from typing import Any, Dict, Iterator, List, Optional

from agno.knowledge.document import Document
from agno.knowledge.reader.pdf_reader import PDFReader

from app.core.logger import get_logger

logger = get_logger(__name__)


class EnhancedPDFKnowledgeBase:
    """Load one local PDF into the existing ChatterMate PgVector store.

    Agno 3.x removed PDFKnowledgeBase.  ChatterMate already owns the load
    lifecycle and metadata filters, so this thin class composes Agno's native
    PDFReader with the existing vector database instead of recreating a second
    knowledge runtime.
    """

    def __init__(self, path: str, vector_db=None, reader: Optional[PDFReader] = None, **_kwargs):
        self.path = path
        self.vector_db = vector_db
        self.reader = reader or PDFReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        if self.reader is None:
            return
        yield self.reader.read(pdf=self.path)

    def load(
        self,
        recreate: bool = False,
        upsert: bool = True,
        skip_existing: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        del skip_existing
        if self.vector_db is None:
            logger.warning("No vector db provided")
            return

        if recreate:
            self.vector_db.drop()
            self.vector_db.create()
        elif not self.vector_db.exists():
            self.vector_db.create()

        logger.info(f"Loading PDF knowledge base: {self.path}")
        for document_list in self.document_lists:
            for document in document_list:
                if document.embedding is None and getattr(self.vector_db, "embedder", None) is not None:
                    try:
                        document.embed(embedder=self.vector_db.embedder)
                    except Exception as exc:
                        logger.error(f"Error embedding document {document.id}: {exc}")
            if upsert and document_list:
                try:
                    logger.debug(
                        f"Upserting {len(document_list)} documents with filters: {filters}"
                    )
                    self.vector_db.upsert(documents=document_list, filters=filters)
                except Exception as exc:
                    logger.error(f"Error upserting documents: {exc}")
        logger.info(f"Completed loading PDF knowledge base: {self.path}")
