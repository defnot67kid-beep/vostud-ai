import os
import pickle
import numpy as np
from typing import List, Dict, Any
from app.document_processor import DocumentProcessor

class RAGEngine:
    """Complete RAG engine with local embeddings and persistence"""
    
    def __init__(self):
        self.processor = DocumentProcessor()
        self.documents = []
        self.embeddings = []
        self.metadatas = []
        self.data_file = "vector_store.pkl"
        
        # Load existing data
        self._load_data()
        print(f"✅ RAG Engine initialized with {len(self.documents)} documents")
    
    def get_embedding(self, text: str) -> np.ndarray:
        """Generate embedding using local method"""
        embedding = np.zeros(128)
        
        # Character-based features
        for i, char in enumerate(text[:500]):
            embedding[i % 128] += ord(char) / 255.0
        
        # Word-based features
        words = text.split()[:50]
        for i, word in enumerate(words):
            idx = (i * 31) % 128
            embedding[idx] += len(word) / 10.0
        
        # Normalize
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        
        return embedding.astype('float32')
    
    def _load_data(self):
        """Load existing data from file"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'rb') as f:
                    data = pickle.load(f)
                    self.documents = data.get('documents', [])
                    self.embeddings = data.get('embeddings', [])
                    self.metadatas = data.get('metadatas', [])
                print(f"✅ Loaded {len(self.documents)} documents from storage")
            except Exception as e:
                print(f"⚠️ Could not load data: {e}")
    
    def _save_data(self):
        """Save data to file"""
        try:
            data = {
                'documents': self.documents,
                'embeddings': self.embeddings,
                'metadatas': self.metadatas
            }
            with open(self.data_file, 'wb') as f:
                pickle.dump(data, f)
            print(f"✅ Saved {len(self.documents)} documents to storage")
        except Exception as e:
            print(f"⚠️ Could not save data: {e}")
    
    def add_document(self, file_path: str, metadata: Dict = None) -> int:
        """Add a document to the vector database (PDF, TXT, etc.)"""
        chunks = self.processor.process_document(file_path)
        if not chunks:
            return 0
        
        for chunk in chunks:
            embedding = self.get_embedding(chunk)
            self.documents.append(chunk)
            self.embeddings.append(embedding)
            self.metadatas.append(metadata or {"source": file_path})
        
        self._save_data()
        return len(chunks)
    
    def add_text(self, text: str, metadata: Dict = None) -> int:
        """Add raw text to the database"""
        chunks = self.processor.process_text(text)
        if not chunks:
            return 0
        
        for chunk in chunks:
            embedding = self.get_embedding(chunk)
            self.documents.append(chunk)
            self.embeddings.append(embedding)
            self.metadatas.append(metadata or {"source": "text_input"})
        
        self._save_data()
        return len(chunks)
    
    def search(self, query: str, n_results: int = 3) -> List[Dict[str, Any]]:
        """Search for relevant documents using cosine similarity"""
        if len(self.documents) == 0:
            return []
        
        query_embedding = self.get_embedding(query)
        n = min(n_results, len(self.documents))
        
        # Calculate cosine similarities
        similarities = []
        for doc_embedding in self.embeddings:
            dot = np.dot(query_embedding, doc_embedding)
            norm_q = np.linalg.norm(query_embedding)
            norm_d = np.linalg.norm(doc_embedding)
            sim = dot / (norm_q * norm_d) if norm_q > 0 and norm_d > 0 else 0
            similarities.append(sim)
        
        # Get top n results
        indices = np.argsort(similarities)[::-1][:n]
        
        results = []
        for idx in indices:
            if idx < len(self.documents):
                results.append({
                    'text': self.documents[idx],
                    'metadata': self.metadatas[idx],
                    'score': float(similarities[idx])
                })
        
        return results
    
    def search_by_file(self, filename: str, n_results: int = 10) -> List[Dict[str, Any]]:
        """Search for documents by filename"""
        results = []
        for i, metadata in enumerate(self.metadatas):
            if 'filename' in metadata and filename in metadata['filename']:
                results.append({
                    'text': self.documents[i],
                    'metadata': metadata
                })
        return results[:n_results]
    
    def clear(self):
        """Clear all documents"""
        self.documents = []
        self.embeddings = []
        self.metadatas = []
        if os.path.exists(self.data_file):
            os.remove(self.data_file)
        print("🗑️ Cleared all documents")
    
    def count(self) -> int:
        """Get total documents count"""
        return len(self.documents)