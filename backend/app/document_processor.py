import os
from typing import List
from PyPDF2 import PdfReader

class DocumentProcessor:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
    
    def process_document(self, file_path: str) -> List[str]:
        """Process both PDF and TXT files"""
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext == '.pdf':
            return self.process_pdf(file_path)
        elif file_ext == '.txt':
            return self.process_text_file(file_path)
        else:
            print(f"⚠️ Unsupported file type: {file_ext}")
            return []
    
    def process_pdf(self, file_path: str) -> List[str]:
        """Extract and chunk text from PDF"""
        try:
            reader = PdfReader(file_path)
            text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            
            if not text.strip():
                return []
            
            return self._chunk_text(text)
        except Exception as e:
            print(f"Error processing PDF: {e}")
            return []
    
    def process_text_file(self, file_path: str) -> List[str]:
        """Process a text file"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
            if text.strip():
                return self._chunk_text(text)
            return []
        except Exception as e:
            print(f"Error reading text file: {e}")
            return []
    
    def process_text(self, text: str) -> List[str]:
        """Chunk regular text"""
        if not text or not text.strip():
            return []
        return self._chunk_text(text)
    
    def _chunk_text(self, text: str) -> List[str]:
        """Simple text chunking"""
        if not text:
            return []
        
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        if not paragraphs:
            paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
        
        if not paragraphs:
            return [text[:self.chunk_size]]
        
        chunks = []
        current_chunk = ""
        
        for para in paragraphs:
            if len(current_chunk) + len(para) < self.chunk_size:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                if len(current_chunk) > self.chunk_overlap:
                    current_chunk = current_chunk[-self.chunk_overlap:] + "\n\n" + para
                else:
                    current_chunk = para
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks