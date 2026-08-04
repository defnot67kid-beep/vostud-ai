from app.database import Database
from app.auth import validate_api_key, validate_optional_api_key
from pydantic import BaseModel, EmailStr
from typing import Optional
import uuid

# Initialize database
db = Database()

# ============================================
# API KEY MANAGEMENT MODELS
# ============================================

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
# API KEY ENDPOINTS
# ============================================

@app.post("/auth/register", response_model=UserResponse)
async def register_user(request: UserCreateRequest):
    """Register a new user"""
    
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

@app.post("/keys/generate")
async def generate_api_key(
    request: CreateKeyRequest,
    auth: dict = Depends(validate_api_key)
):
    """Generate a new API key"""
    
    result = db.create_api_key(
        user_id=auth["user_id"],
        name=request.name,
        expires_in_days=request.expires_in_days
    )
    
    return result

@app.get("/keys")
async def list_api_keys(auth: dict = Depends(validate_api_key)):
    """List all API keys for the user"""
    
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
    
    # Find the key
    key_doc = db.api_keys.find_one({
        "user_id": auth["user_id"],
        "key_prefix": key_prefix
    })
    
    if not key_doc:
        raise HTTPException(404, "Key not found")
    
    # Revoke it
    result = db.revoke_api_key_by_hash(key_doc["key"])
    
    return {"message": "API key revoked"}

# ============================================
# UPDATED CHAT ENDPOINT (with API key)
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

# ============================================
# PUBLIC ENDPOINT (No API key required)
# ============================================

@app.post("/chat/public")
async def chat_public(
    request: ChatRequest
):
    """Public chat endpoint (limited, no API key required)"""
    
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    # Rate limit public requests
    # (Implement your own rate limiting here)
    
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
# USAGE STATS ENDPOINT
# ============================================

@app.get("/keys/stats")
async def get_usage_stats(auth: dict = Depends(validate_api_key)):
    """Get usage statistics for API key"""
    
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
