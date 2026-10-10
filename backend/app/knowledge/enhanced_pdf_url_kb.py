"""ChatterMate PDF-URL knowledge loading on Agno 3.x native readers."""

from io import BytesIO
from typing import Any, Dict, Iterator, List, Optional

import requests
from agno.knowledge.document import Document
from agno.knowledge.reader.pdf_reader import PDFReader

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)


class EnhancedPDFUrlKnowledgeBase:
    """Load remote PDFs without the removed Agno 1.x PDFUrlKnowledgeBase."""

    def __init__(self, urls: Optional[List[str]] = None, vector_db=None, reader: Optional[PDFReader] = None, **_kwargs):
        self.urls = list(urls or [])
        self.vector_db = vector_db
        self.reader = reader or PDFReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        for url in self.urls:
            response = requests.get(url, timeout=settings.KB_TIMEOUT)
            response.raise_for_status()
            stream = BytesIO(response.content)
            stream.name = url.rsplit("/", 1)[-1] or "document.pdf"
            yield self.reader.read(pdf=stream, name=url)

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

        if not self.urls:
            logger.warning("No URLs provided")
            return

        logger.info(f"Loading PDF URL knowledge base: {len(self.urls)} URLs")
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
        logger.info("Completed loading PDF URL knowledge base")
