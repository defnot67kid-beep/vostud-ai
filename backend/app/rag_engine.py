import os
import pickle
import numpy as np
from typing import List, Dict, Any
from app.document_processor import DocumentProcessor

class RAGEngine:
    """Vostud AI - Retrieval-Augmented Generation Engine"""
    
    def __init__(self):
        self.processor = DocumentProcessor()
        self.documents = []
        self.embeddings = []
        self.metadatas = []
        self.data_file = "vector_store.pkl"
        
        self._load_data()
    
    def get_embedding(self, text: str) -> np.ndarray:
        """Simple local embedding for Vostud AI"""
        embedding = np.zeros(128)
        for i, char in enumerate(text[:500]):
            embedding[i % 128] += ord(char) / 255.0
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding.astype('float32')
    
    def _load_data(self):
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'rb') as f:
                    data = pickle.load(f)
                    self.documents = data.get('documents', [])
                    self.embeddings = data.get('embeddings', [])
                    self.metadatas = data.get('metadatas', [])
                print(f"✅ Loaded {len(self.documents)} documents from storage")
            except:
                print("⚠️ Could not load data, starting fresh")
    
    def _save_data(self):
        try:
            data = {
                'documents': self.documents,
                'embeddings': self.embeddings,
                'metadatas': self.metadatas
            }
            with open(self.data_file, 'wb') as f:
                pickle.dump(data, f)
            print(f"✅ Saved {len(self.documents)} documents")
        except Exception as e:
            print(f"⚠️ Could not save: {e}")
    
    def add_document(self, file_path: str, metadata: Dict = None) -> int:
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
        if len(self.documents) == 0:
            return []
        
        query_embedding = self.get_embedding(query)
        n = min(n_results, len(self.documents))
        
        similarities = []
        for doc_embedding in self.embeddings:
            dot = np.dot(query_embedding, doc_embedding)
            norm_q = np.linalg.norm(query_embedding)
            norm_d = np.linalg.norm(doc_embedding)
            sim = dot / (norm_q * norm_d) if norm_q > 0 and norm_d > 0 else 0
            similarities.append(sim)
        
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
    
    def count(self) -> int:
        return len(self.documents)
