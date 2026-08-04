from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional
import os
import shutil
from dotenv import load_dotenv

load_dotenv()

from app.smart_engine import SmartAIEngine
from app.rag_engine import RAGEngine

app = FastAPI(title="Vostud AI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize engines
print("🚀 Starting Vostud AI...")

rag_engine = None
try:
    rag_engine = RAGEngine()
    print(f"✅ RAG Engine initialized with {rag_engine.count()} documents")
except Exception as e:
    print(f"❌ RAG Engine failed: {e}")

chat_engine = None
try:
    chat_engine = SmartAIEngine()
    if rag_engine:
        chat_engine.rag = rag_engine
    print(f"✅ Chat Engine initialized")
except Exception as e:
    print(f"❌ Chat Engine failed: {e}")

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict]] = None
    use_rag: bool = True
    model: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    api_used: Optional[str] = None
    model_used: Optional[str] = None

class QuizRequest(BaseModel):
    topic: str
    num_questions: int = 5

class ModelSwitchRequest(BaseModel):
    model: str

@app.get("/")
@app.head("/")
async def root():
    return {
        "message": "Vostud AI API is running!",
        "rag_available": rag_engine is not None,
        "model_switcher_available": chat_engine and chat_engine.model_switcher is not None,
        "apis_available": chat_engine.api_priority if chat_engine else []
    }

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    try:
        response = chat_engine.generate_response(
            user_message=request.message,
            conversation_history=request.history,
            use_rag=request.use_rag,
            model_override=request.model
        )
        
        model_used = None
        if chat_engine.model_switcher:
            if request.model:
                model_used = request.model
            elif chat_engine.model_switcher.current_model:
                model_used = chat_engine.model_switcher.current_model
            elif chat_engine.model_switcher.auto_mode:
                model_used = "auto"
        
        return ChatResponse(
            response=response,
            api_used=chat_engine.current_api,
            model_used=model_used
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    if not rag_engine:
        raise HTTPException(status_code=400, detail="RAG engine not available")
    
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ['.pdf', '.txt', '.lua', '.luau']:
        raise HTTPException(status_code=400, detail="Only .pdf, .txt, .lua, .luau files are supported")
    
    try:
        os.makedirs("./data/uploaded_docs", exist_ok=True)
        file_path = f"./data/uploaded_docs/{file.filename}"
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        num_chunks = rag_engine.add_document(
            file_path,
            metadata={"filename": file.filename, "type": file_ext}
        )
        
        return {
            "status": "success",
            "filename": file.filename,
            "file_type": file_ext,
            "chunks_processed": num_chunks,
            "message": f"Added {num_chunks} chunks to knowledge base"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/quiz")
async def generate_quiz(request: QuizRequest):
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    try:
        quiz = chat_engine.generate_quiz(
            topic=request.topic,
            num_questions=request.num_questions
        )
        return {"quiz": quiz}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/add-text")
async def add_text(text: str, metadata: Optional[Dict] = None):
    if not rag_engine:
        raise HTTPException(status_code=400, detail="RAG engine not available")
    
    try:
        num_chunks = rag_engine.add_text(text, metadata)
        return {
            "status": "success",
            "chunks_processed": num_chunks,
            "message": f"Added {num_chunks} chunks to knowledge base"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/knowledge-stats")
async def get_stats():
    if not rag_engine:
        return {"total_documents": 0, "status": "not_available"}
    
    try:
        count = rag_engine.count()
        return {"total_documents": count, "status": "available"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/models")
async def get_models():
    if not chat_engine or not chat_engine.model_switcher:
        raise HTTPException(status_code=503, detail="Model switcher not available")
    
    return {
        "current_model": chat_engine.model_switcher.get_current_model(),
        "auto_mode": chat_engine.model_switcher.auto_mode,
        "available_models": chat_engine.model_switcher.get_available_models_list()
    }

@app.post("/models/switch")
async def switch_model(request: ModelSwitchRequest):
    if not chat_engine or not chat_engine.model_switcher:
        raise HTTPException(status_code=503, detail="Model switcher not available")
    
    result = chat_engine.model_switcher.set_model(request.model)
    return {
        "current_model": chat_engine.model_switcher.get_current_model(),
        "auto_mode": chat_engine.model_switcher.auto_mode,
        "message": result
    }

@app.post("/models/auto")
async def set_auto_mode(enabled: bool = True):
    if not chat_engine or not chat_engine.model_switcher:
        raise HTTPException(status_code=503, detail="Model switcher not available")
    
    result = chat_engine.model_switcher.set_auto_mode(enabled)
    return {
        "auto_mode": chat_engine.model_switcher.auto_mode,
        "message": result
    }

@app.post("/models/next")
async def switch_next():
    if not chat_engine or not chat_engine.model_switcher:
        raise HTTPException(status_code=503, detail="Model switcher not available")
    
    result = chat_engine.model_switcher.switch_to_next_model()
    return {
        "current_model": chat_engine.model_switcher.get_current_model(),
        "message": result
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
