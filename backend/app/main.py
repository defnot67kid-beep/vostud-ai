from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import List, Dict, Optional
import os
import shutil
from dotenv import load_dotenv
from datetime import datetime, timedelta
import uuid

load_dotenv()

# ============================================
# CREATE APP INSTANCE FIRST
# ============================================
app = FastAPI(title="Vostud AI API")

# ============================================
# CORS MIDDLEWARE
# ============================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# IMPORTS (After app creation)
# ============================================
from app.smart_engine import SmartAIEngine
from app.rag_engine import RAGEngine
from app.database import Database
from app.auth import validate_api_key, validate_optional_api_key

# ============================================
# INITIALIZE ENGINES
# ============================================
print("🚀 Starting Vostud AI...")

# Database
db = None
try:
    db = Database()
    print("✅ Database connected successfully")
except Exception as e:
    print(f"❌ Database connection failed: {e}")

# RAG Engine
rag_engine = None
try:
    rag_engine = RAGEngine()
    print(f"✅ RAG Engine initialized with {rag_engine.count()} documents")
except Exception as e:
    print(f"❌ RAG Engine failed: {e}")

# Chat Engine
chat_engine = None
try:
    chat_engine = SmartAIEngine()
    if rag_engine:
        chat_engine.rag = rag_engine
    print(f"✅ Chat Engine initialized")
except Exception as e:
    print(f"❌ Chat Engine failed: {e}")

# ============================================
# PYDANTIC MODELS
# ============================================

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

class CreateKeyRequest(BaseModel):
    name: Optional[str] = None
    expires_in_days: int = 365
    rate_limit: int = 1000

class CreateKeyResponse(BaseModel):
    api_key: str
    key_prefix: str
    user_id: str
    expires_at: str

class UserCreateRequest(BaseModel):
    email: EmailStr
    username: str
    password: Optional[str] = None

class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    created_at: str

# ============================================
# ROOT ENDPOINTS
# ============================================

@app.get("/")
@app.head("/")
async def root():
    return {
        "message": "Vostud AI API is running!",
        "rag_available": rag_engine is not None,
        "model_switcher_available": chat_engine and chat_engine.model_switcher is not None,
        "apis_available": chat_engine.api_priority if chat_engine else [],
        "database_connected": db is not None
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# ============================================
# AUTH / USER ENDPOINTS
# ============================================

@app.post("/auth/register", response_model=UserResponse)
async def register_user(request: UserCreateRequest):
    """Register a new user"""
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    # Check if user exists
    existing = db.users.find_one({
        "$or": [
            {"email": request.email},
            {"username": request.username}
        ]
    })
    
    if existing:
        raise HTTPException(400, "User already exists")
    
    # Create user
    user = db.create_user(
        email=request.email,
        username=request.username,
        password=request.password
    )
    
    return {
        "id": str(user["_id"]),
        "email": user["email"],
        "username": user["username"],
        "created_at": user["created_at"].isoformat()
    }

# ============================================
# API KEY ENDPOINTS
# ============================================

@app.post("/keys/generate", response_model=CreateKeyResponse)
async def generate_api_key(
    request: CreateKeyRequest,
    auth: dict = Depends(validate_api_key)
):
    """Generate a new API key"""
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    result = db.create_api_key(
        user_id=auth["user_id"],
        name=request.name,
        expires_in_days=request.expires_in_days
    )
    
    return result

@app.get("/keys")
async def list_api_keys(auth: dict = Depends(validate_api_key)):
    """List all API keys for the user"""
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    keys = db.api_keys.find({"user_id": auth["user_id"]})
    
    return [{
        "key_prefix": k.get("key_prefix"),
        "name": k.get("name"),
        "status": k.get("status"),
        "created_at": k.get("created_at"),
        "expires_at": k.get("expires_at"),
        "last_used": k.get("last_used"),
        "usage_count": k.get("usage_count", 0)
    } for k in keys]

@app.delete("/keys/{key_prefix}")
async def revoke_api_key(
    key_prefix: str,
    auth: dict = Depends(validate_api_key)
):
    """Revoke an API key"""
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    # Find the key
    key_doc = db.api_keys.find_one({
        "user_id": auth["user_id"],
        "key_prefix": key_prefix
    })
    
    if not key_doc:
        raise HTTPException(404, "Key not found")
    
    # Revoke it
    db.api_keys.update_one(
        {"_id": key_doc["_id"]},
        {"$set": {"status": "revoked"}}
    )
    
    return {"message": "API key revoked"}

@app.get("/keys/stats")
async def get_usage_stats(auth: dict = Depends(validate_api_key)):
    """Get usage statistics for API key"""
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    stats = db.usage_logs.aggregate([
        {"$match": {"user_id": auth["user_id"]}},
        {"$group": {
            "_id": None,
            "total_requests": {"$sum": 1},
            "last_24h": {
                "$sum": {
                    "$cond": [
                        {"$gte": ["$timestamp", datetime.utcnow() - timedelta(hours=24)]},
                        1,
                        0
                    ]
                }
            }
        }}
    ])
    
    result = list(stats)
    return result[0] if result else {"total_requests": 0, "last_24h": 0}

# ============================================
# CHAT ENDPOINTS
# ============================================

@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    auth: dict = Depends(validate_api_key)
):
    """Chat with Vostud AI (requires API key)"""
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

@app.post("/chat/public")
async def chat_public(
    request: ChatRequest
):
    """Public chat endpoint (no API key required, rate limited)"""
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    try:
        response = chat_engine.generate_response(
            user_message=request.message,
            conversation_history=request.history,
            use_rag=request.use_rag,
            model_override=request.model
        )
        
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# UPLOAD ENDPOINTS
# ============================================

@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    auth: dict = Depends(validate_api_key)
):
    """Upload a document to the RAG database"""
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
            metadata={"filename": file.filename, "type": file_ext, "user_id": auth["user_id"]}
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

@app.post("/add-text")
async def add_text(
    text: str,
    metadata: Optional[Dict] = None,
    auth: dict = Depends(validate_api_key)
):
    """Add raw text to the knowledge base"""
    if not rag_engine:
        raise HTTPException(status_code=400, detail="RAG engine not available")
    
    try:
        num_chunks = rag_engine.add_text(text, metadata or {"user_id": auth["user_id"]})
        return {
            "status": "success",
            "chunks_processed": num_chunks,
            "message": f"Added {num_chunks} chunks to knowledge base"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# QUIZ ENDPOINTS
# ============================================

@app.post("/quiz")
async def generate_quiz(
    request: QuizRequest,
    auth: dict = Depends(validate_api_key)
):
    """Generate a quiz on a topic"""
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

# ============================================
# STATS ENDPOINTS
# ============================================

@app.get("/knowledge-stats")
async def get_stats(
    auth: dict = Depends(validate_api_key)
):
    """Get knowledge base statistics"""
    if not rag_engine:
        return {"total_documents": 0, "status": "not_available"}
    
    try:
        count = rag_engine.count()
        return {"total_documents": count, "status": "available"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# MODEL SWITCHER ENDPOINTS
# ============================================

@app.get("/models")
async def get_models(
    auth: dict = Depends(validate_api_key)
):
    """Get available models and current selection"""
    if not chat_engine or not chat_engine.model_switcher:
        raise HTTPException(status_code=503, detail="Model switcher not available")
    
    return {
        "current_model": chat_engine.model_switcher.get_current_model(),
        "auto_mode": chat_engine.model_switcher.auto_mode,
        "available_models": chat_engine.model_switcher.get_available_models_list()
    }

@app.post("/models/switch")
async def switch_model(
    request: ModelSwitchRequest,
    auth: dict = Depends(validate_api_key)
):
    """Switch to a specific model or auto mode"""
    if not chat_engine or not chat_engine.model_switcher:
        raise HTTPException(status_code=503, detail="Model switcher not available")
    
    result = chat_engine.model_switcher.set_model(request.model)
    return {
        "current_model": chat_engine.model_switcher.get_current_model(),
        "auto_mode": chat_engine.model_switcher.auto_mode,
        "message": result
    }

@app.post("/models/auto")
async def set_auto_mode(
    enabled: bool = True,
    auth: dict = Depends(validate_api_key)
):
    """Enable or disable auto model selection"""
    if not chat_engine or not chat_engine.model_switcher:
        raise HTTPException(status_code=503, detail="Model switcher not available")
    
    result = chat_engine.model_switcher.set_auto_mode(enabled)
    return {
        "auto_mode": chat_engine.model_switcher.auto_mode,
        "message": result
    }

@app.post("/models/next")
async def switch_next(
    auth: dict = Depends(validate_api_key)
):
    """Switch to the next available model"""
    if not chat_engine or not chat_engine.model_switcher:
        raise HTTPException(status_code=503, detail="Model switcher not available")
    
    result = chat_engine.model_switcher.switch_to_next_model()
    return {
        "current_model": chat_engine.model_switcher.get_current_model(),
        "message": result
    }

# ============================================
# DATABASE TEST ENDPOINT
# ============================================

@app.get("/db-test")
async def test_database():
    """Test database connection"""
    if not db:
        return {"status": "error", "message": "Database not connected"}
    
    try:
        # Ping the database
        db.db.command("ping")
        return {"status": "success", "message": "Database connected"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ============================================
# RUN APP (Local development only)
# ============================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
