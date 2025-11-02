from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import os
import shutil
from pathlib import Path
import logging

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.vectorstores import Chroma, FAISS
from langchain.schema import Document
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="RAG Service")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
UPLOAD_DIR = Path("./uploads")
CHROMA_DIR = Path("./chroma_db")
UPLOAD_DIR.mkdir(exist_ok=True)
CHROMA_DIR.mkdir(exist_ok=True)

API_KEY = os.getenv("API_KEY", "your-secret-api-key")

# Models
class QueryRequest(BaseModel):
    query: str
    k: int = 3  # Number of documents to retrieve

class QueryResponse(BaseModel):
    context: str
    sources: List[str]
    relevance_scores: List[float]

class IngestResponse(BaseModel):
    status: str
    filename: str
    chunks_created: int

# Security
async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return x_api_key

# RAG Service
class RAGService:
    def __init__(self):
        logger.info("Initializing RAG Service...")
        
        # Load embedding model
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={'device': 'cpu'},  # Use 'cuda' if GPU available
            encode_kwargs={'normalize_embeddings': True}
        )
        
        # Initialize vector store
        self.vector_store = Chroma(
            persist_directory=str(CHROMA_DIR),
            embedding_function=self.embeddings,
            collection_name="documents"
        )
        
        # Text splitter
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
        )
        
        logger.info("RAG Service initialized!")
    
    def load_document(self, file_path: Path) -> List[Document]:
        """Load document based on file type"""
        file_extension = file_path.suffix.lower()
        
        if file_extension == '.pdf':
            loader = PyPDFLoader(str(file_path))
        elif file_extension in ['.docx', '.doc']:
            loader = Docx2txtLoader(str(file_path))
        elif file_extension == '.txt':
            loader = TextLoader(str(file_path))
        else:
            raise ValueError(f"Unsupported file type: {file_extension}")
        
        return loader.load()
    
    def ingest_document(self, file_path: Path) -> int:
        """Ingest document into vector store"""
        logger.info(f"Ingesting document: {file_path.name}")
        
        # Load document
        documents = self.load_document(file_path)
        
        # Add metadata
        for doc in documents:
            doc.metadata['source'] = file_path.name
        
        # Split into chunks
        chunks = self.text_splitter.split_documents(documents)
        
        # Add to vector store
        self.vector_store.add_documents(chunks)
        
        # Persist
        self.vector_store.persist()
        
        logger.info(f"Created {len(chunks)} chunks from {file_path.name}")
        return len(chunks)
    
    def query(self, query: str, k: int = 3) -> tuple[str, List[str], List[float]]:
        """Query vector store"""
        logger.info(f"Querying: {query}")
        
        # Retrieve documents with scores
        results = self.vector_store.similarity_search_with_relevance_scores(
            query, 
            k=k
        )
        
        if not results:
            return "", [], []
        
        # Extract context and metadata
        context_parts = []
        sources = []
        scores = []
        
        for doc, score in results:
            context_parts.append(doc.page_content)
            sources.append(doc.metadata.get('source', 'unknown'))
            scores.append(float(score))
        
        context = "\n\n---\n\n".join(context_parts)
        
        return context, sources, scores
    
    def list_documents(self) -> List[str]:
        """List all ingested documents"""
        collection = self.vector_store._collection
        results = collection.get()
        
        if results and 'metadatas' in results:
            sources = set()
            for metadata in results['metadatas']:
                if 'source' in metadata:
                    sources.add(metadata['source'])
            return list(sources)
        
        return []
    
    def delete_document(self, filename: str) -> bool:
        """Delete all chunks from a specific document"""
        collection = self.vector_store._collection
        results = collection.get(where={"source": filename})
        
        if results and 'ids' in results:
            collection.delete(ids=results['ids'])
            self.vector_store.persist()
            return True
        
        return False

# Initialize RAG service
rag_service = RAGService()

# Endpoints
@app.post("/ingest", response_model=IngestResponse, dependencies=[Depends(verify_api_key)])
async def ingest_document(file: UploadFile = File(...)):
    """Upload and ingest a document"""
    try:
        # Save uploaded file
        file_path = UPLOAD_DIR / file.filename
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Ingest into vector store
        chunks_created = rag_service.ingest_document(file_path)
        
        return IngestResponse(
            status="success",
            filename=file.filename,
            chunks_created=chunks_created
        )
    
    except Exception as e:
        logger.error(f"Ingestion error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query", response_model=QueryResponse, dependencies=[Depends(verify_api_key)])
async def query_documents(request: QueryRequest):
    """Query ingested documents"""
    try:
        context, sources, scores = rag_service.query(request.query, request.k)
        
        if not context:
            raise HTTPException(
                status_code=404, 
                detail="No relevant documents found"
            )
        
        return QueryResponse(
            context=context,
            sources=sources,
            relevance_scores=scores
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Query error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents")
async def list_documents(x_api_key: str = Depends(verify_api_key)):
    """List all ingested documents"""
    return {"documents": rag_service.list_documents()}

@app.delete("/documents/{filename}", dependencies=[Depends(verify_api_key)])
async def delete_document(filename: str):
    """Delete a document from the vector store"""
    success = rag_service.delete_document(filename)
    
    if success:
        return {"status": "success", "message": f"Deleted {filename}"}
    else:
        raise HTTPException(status_code=404, detail="Document not found")

@app.get("/health")
async def health_check():
    """Health check"""
    doc_count = len(rag_service.list_documents())
    return {
        "status": "healthy",
        "documents_ingested": doc_count
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=False)
