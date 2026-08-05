from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse, HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, EmailStr
from typing import List, Dict, Optional
import os
import shutil
from dotenv import load_dotenv
from datetime import datetime, timedelta
import uuid
import logging
import json
import hashlib

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# ============================================
# CREATE APP INSTANCE FIRST
# ============================================
app = FastAPI(title="Vostud AI API")

# ============================================
# SESSION MIDDLEWARE
# ============================================
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("JWT_SECRET_KEY", "your_super_secret_key_change_this_to_a_long_random_string"),
    session_cookie="vostud_session",
    max_age=3600,
    same_site="lax",
    https_only=True,
)

# ============================================
# CORS MIDDLEWARE
# ============================================
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://vostud-ai.onrender.com")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000", "http://localhost:8000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# STATIC FILES
# ============================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

if not os.path.exists(FRONTEND_DIR):
    FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

logger.info(f"📁 Frontend directory: {FRONTEND_DIR}")

# ============================================
# IMPORTS
# ============================================
from app.smart_engine import SmartAIEngine
from app.rag_engine import RAGEngine
from app.database import Database
from app.auth import validate_api_key
from app.oauth import (
    setup_oauth,
    create_access_token,
    get_current_user,
    require_auth,
    require_api_key_or_oauth,
    optional_auth,
    GoogleUserInfo,
    decode_access_token,
    SECRET_KEY,
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES
)
from authlib.integrations.starlette_client import OAuthError
from app.rate_limiter import limiter, token_tracker, RateLimitMiddleware, TIER_LIMITS
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

# ============================================
# SETUP RATE LIMITER
# ============================================
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ============================================
# SETUP OAUTH
# ============================================
oauth = setup_oauth(app)
if oauth:
    logger.info("✅ OAuth setup complete")
else:
    logger.warning("⚠️ OAuth setup failed")

# ============================================
# INITIALIZE ENGINES
# ============================================
logger.info("🚀 Starting Vostud AI...")

db = None
try:
    db = Database()
    logger.info("✅ Database connected successfully")
except Exception as e:
    logger.error(f"❌ Database connection failed: {e}")

rag_engine = None
try:
    rag_engine = RAGEngine()
    logger.info(f"✅ RAG Engine initialized with {rag_engine.count()} documents")
except Exception as e:
    logger.error(f"❌ RAG Engine failed: {e}")

chat_engine = None
try:
    chat_engine = SmartAIEngine()
    if rag_engine:
        chat_engine.rag = rag_engine
    logger.info("✅ Chat Engine initialized")
except Exception as e:
    logger.error(f"❌ Chat Engine failed: {e}")

# ============================================
# ADD RATE LIMIT MIDDLEWARE
# ============================================
app.add_middleware(RateLimitMiddleware, db=db, token_tracker=token_tracker)

# ============================================
# VALID MODELS LIST
# ============================================

VALID_MODELS = [
    # Vostud Branded Models
    "auto",
    "vostud-2.5-pro",
    "vostud-2.5-flash",
    "vostud-2.0-pro",
    "vostud-2.0-flash",
    "vostud-1.5-pro",
    "vostud-1.5-flash",
    "vostud-pro",
    "vostud-flash",
    "vostud-local",
    # Raw API Models
    "groq/llama-3.3-70b-versatile",
    "groq/llama-3.1-70b-versatile",
    "groq/llama-3.1-8b-instant",
    "groq/gemma2-9b-it",
    "gemini/gemini-2.0-flash",
    "gemini/gemini-1.5-flash",
    "gemini/gemini-1.5-pro",
    "openrouter/google/gemini-2.0-flash-lite-preview-02-05:free",
    "openrouter/google/gemini-flash-1.5:free",
    "openrouter/microsoft/phi-3-mini-128k-instruct:free",
    "openrouter/meta-llama/llama-3.2-3b-instruct:free",
    "openrouter/mistralai/mistral-7b-instruct:free",
    "openai/gpt-3.5-turbo",
    "openai/gpt-4",
    "ollama/llama2:latest"
]

# ============================================
# MODEL VALIDATION FUNCTION
# ============================================

def validate_model(model: str) -> tuple:
    """
    Validate the model parameter.
    Returns (is_valid, error_message, actual_model)
    """
    if not model:
        return False, "⚠️ Model selection required. Please specify a model or use 'auto' for automatic selection.", None
    
    if model == "auto":
        return True, None, "auto"
    
    # Check if it's a valid model
    if model in VALID_MODELS:
        return True, None, model
    
    # Check if it's a Vostud model (without the "vostud-" prefix check)
    if model.startswith("vostud-"):
        # Map to full model name if valid
        full_model = f"vostud-{model.replace('vostud-', '')}"
        if full_model in VALID_MODELS:
            return True, None, full_model
    
    # Check if it's a raw API model
    if "/" in model:
        # Check if any valid model ends with this
        for valid in VALID_MODELS:
            if valid.endswith(model) or model in valid:
                return True, None, valid
    
    # Invalid model - return professional error
    return False, f"""❌ Invalid Model Selection

The model '{model}' is not available in Vostud AI.

Available models:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🤖 AUTO MODE:
  • auto (Recommended - automatically selects the best model)

🌟 VOSTUD MODELS (Recommended):
  • vostud-2.5-pro   - Highest quality, complex reasoning
  • vostud-2.5-flash - Fast, high quality
  • vostud-2.0-pro   - Google Gemini Pro, research
  • vostud-2.0-flash - Google Gemini Flash, speed
  • vostud-1.5-pro   - Qwen 2.5, quality
  • vostud-1.5-flash - Llama 3.2, fast
  • vostud-pro       - OpenAI GPT-4 (paid)
  • vostud-flash     - OpenAI GPT-3.5 (paid)
  • vostud-local     - Local Ollama (privacy)

🔌 RAW API MODELS (Advanced):
  • groq/llama-3.3-70b-versatile
  • groq/llama-3.1-70b-versatile
  • groq/llama-3.1-8b-instant
  • groq/gemma2-9b-it
  • gemini/gemini-2.0-flash
  • gemini/gemini-1.5-flash
  • gemini/gemini-1.5-pro
  • openai/gpt-3.5-turbo
  • openai/gpt-4
  • ollama/llama2:latest

💡 Tip: Use 'auto' for automatic model selection based on your query.
   Example: {{"model": "auto"}}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Please specify a valid model in your request.""", None

# ============================================
# PYDANTIC MODELS
# ============================================

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict]] = None
    use_rag: bool = True
    model: Optional[str] = None
    format: Optional[str] = None  # 'source_only', 'concise', 'detailed'

class ChatResponse(BaseModel):
    response: str
    api_used: Optional[str] = None
    model_used: Optional[str] = None
    mode: Optional[str] = None
    tokens_used: Optional[int] = None

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

class ModeSwitchRequest(BaseModel):
    mode: str  # coding, research, organize, compare, summary

# ============================================
# FRONTEND ROUTES
# ============================================

@app.get("/")
@app.head("/")
async def root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "message": "Vostud AI API is running!",
        "rag_available": rag_engine is not None,
        "model_switcher_available": chat_engine and chat_engine.model_switcher is not None,
        "apis_available": chat_engine.api_priority if chat_engine else [],
        "database_connected": db is not None,
        "oauth_available": bool(os.getenv("GOOGLE_CLIENT_ID"))
    }

@app.get("/platform")
@app.head("/platform")
async def serve_platform():
    platform_path = os.path.join(FRONTEND_DIR, "platform.html")
    if os.path.exists(platform_path):
        return FileResponse(platform_path)
    return HTMLResponse(
        content="<h1>Platform page not found</h1>",
        status_code=404
    )

@app.get("/index.html")
async def serve_index():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="index.html not found")

# ============================================
# OAUTH ROUTES
# ============================================

@app.get("/auth/google")
async def auth_google(request: Request):
    try:
        if not oauth:
            raise HTTPException(status_code=503, detail="OAuth not configured")
        
        state = uuid.uuid4().hex
        request.session['oauth_state'] = state
        redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "https://vostud-ai.onrender.com/auth/google/callback")
        return await oauth.google.authorize_redirect(request, redirect_uri, state=state)
    except Exception as e:
        logger.error(f"❌ OAuth error: {e}")
        raise HTTPException(status_code=500, detail=f"OAuth error: {str(e)}")

@app.get("/auth/google/callback")
async def auth_google_callback(request: Request):
    try:
        if not oauth:
            raise HTTPException(status_code=503, detail="OAuth not configured")
        
        session_state = request.session.get('oauth_state') if request.session else None
        request_state = request.query_params.get("state")
        
        if session_state and request_state:
            if session_state != request_state:
                try:
                    token = await oauth.google.authorize_access_token(request, verify_state=False)
                except Exception as e:
                    raise HTTPException(status_code=400, detail="CSRF verification failed")
            else:
                token = await oauth.google.authorize_access_token(request)
        else:
            token = await oauth.google.authorize_access_token(request, verify_state=False)
        
        if not token:
            raise HTTPException(status_code=400, detail="No token received from Google")
        
        user_info = token.get('userinfo')
        if not user_info:
            raise HTTPException(status_code=400, detail="Failed to get user info")
        
        email = user_info.get('email')
        name = user_info.get('name', email.split('@')[0] if email else 'User')
        picture = user_info.get('picture')
        given_name = user_info.get('given_name', name)
        family_name = user_info.get('family_name', '')
        
        if not email:
            raise HTTPException(status_code=400, detail="No email in user info")
        
        user_id = None
        if db:
            try:
                existing_user = db.users.find_one({"email": email})
                
                if not existing_user:
                    user_doc = {
                        "email": email,
                        "username": name,
                        "display_name": name,
                        "picture": picture,
                        "given_name": given_name,
                        "family_name": family_name,
                        "created_at": datetime.utcnow(),
                        "auth_provider": "google",
                        "last_login": datetime.utcnow(),
                        "tier": "free"
                    }
                    result = db.users.insert_one(user_doc)
                    user_id = str(result.inserted_id)
                else:
                    user_id = str(existing_user["_id"])
                    db.users.update_one(
                        {"_id": existing_user["_id"]},
                        {"$set": {
                            "display_name": name,
                            "picture": picture,
                            "last_login": datetime.utcnow(),
                            "given_name": given_name,
                            "family_name": family_name
                        }}
                    )
            except Exception as e:
                logger.error(f"❌ Database error: {e}")
                user_id = f"user_{uuid.uuid4().hex[:8]}"
        else:
            user_id = f"user_{uuid.uuid4().hex[:8]}"
        
        access_token = create_access_token({
            "sub": user_id,
            "email": email,
            "name": name,
            "picture": picture or "",
            "tier": "free"
        })
        
        if request.session and 'oauth_state' in request.session:
            request.session.pop('oauth_state')
        
        frontend_url = os.getenv("FRONTEND_URL", "https://vostud-ai.onrender.com")
        redirect_url = f"{frontend_url}/platform"
        
        response = RedirectResponse(url=redirect_url)
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            secure=True,
            samesite="lax"
        )
        
        return response
        
    except OAuthError as e:
        raise HTTPException(status_code=400, detail=f"OAuth error: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Callback error: {e}")
        raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")

@app.get("/auth/me")
async def auth_me(request: Request):
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"authenticated": True, "user": user}

@app.post("/auth/logout")
async def auth_logout():
    response = JSONResponse({"message": "Logged out successfully"})
    response.delete_cookie("access_token")
    return response

# ============================================
# API KEY ENDPOINTS
# ============================================

@app.post("/keys/generate", response_model=CreateKeyResponse)
@limiter.limit("5 per hour")
async def generate_api_key(
    request: Request,
    create_request: CreateKeyRequest,
    auth: dict = Depends(require_api_key_or_oauth)
):
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")
        
        user_id = auth.get("user_id") or auth.get("sub")
        email = auth.get("email")
        name = auth.get("name") or "User"
        
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")
        
        user = None
        try:
            from bson import ObjectId
            user = db.users.find_one({"_id": ObjectId(user_id)})
        except:
            user = db.users.find_one({"_id": user_id})
        
        if not user and email:
            user = db.users.find_one({"email": email})
            if user:
                user_id = str(user["_id"])
        
        if not user:
            user_doc = {
                "email": email or f"{user_id}@temp.user",
                "username": name,
                "display_name": name,
                "created_at": datetime.utcnow(),
                "auth_provider": "oauth",
                "last_login": datetime.utcnow(),
                "tier": "free"
            }
            result = db.users.insert_one(user_doc)
            user_id = str(result.inserted_id)
            user = user_doc
        
        result = db.create_api_key(
            user_id=user_id,
            name=create_request.name or f"Key for {user.get('email', user_id)}",
            expires_in_days=create_request.expires_in_days
        )
        
        if not result:
            raise HTTPException(status_code=500, detail="Failed to create API key")
        
        return CreateKeyResponse(
            api_key=result["api_key"],
            key_prefix=result["key_prefix"],
            user_id=result["user_id"],
            expires_at=result["expires_at"].isoformat() if hasattr(result["expires_at"], 'isoformat') else str(result["expires_at"])
        )
    except Exception as e:
        logger.error(f"❌ Key generation error: {e}")
        raise HTTPException(status_code=500, detail=f"Key generation failed: {str(e)}")

@app.get("/keys")
async def list_api_keys(auth: dict = Depends(require_api_key_or_oauth)):
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")
        
        user_id = auth.get("user_id") or auth.get("sub")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")
        
        keys = list(db.api_keys.find({"user_id": user_id}))
        
        return [{
            "key_prefix": k.get("key_prefix"),
            "name": k.get("name"),
            "status": k.get("status"),
            "created_at": k.get("created_at"),
            "expires_at": k.get("expires_at"),
            "last_used": k.get("last_used"),
            "usage_count": k.get("usage_count", 0)
        } for k in keys]
    except Exception as e:
        logger.error(f"❌ List keys error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list keys: {str(e)}")

@app.delete("/keys/{key_prefix}")
async def revoke_api_key(key_prefix: str, auth: dict = Depends(require_api_key_or_oauth)):
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")
        
        user_id = auth.get("user_id") or auth.get("sub")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")
        
        key_doc = db.api_keys.find_one({
            "user_id": user_id,
            "key_prefix": key_prefix
        })
        
        if not key_doc:
            raise HTTPException(404, "Key not found")
        
        result = db.api_keys.update_one(
            {"_id": key_doc["_id"]},
            {"$set": {"status": "revoked"}}
        )
        
        if result.modified_count > 0:
            return {"message": "API key revoked"}
        else:
            return {"message": "Key already revoked or not found"}
    except Exception as e:
        logger.error(f"❌ Revoke key error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to revoke key: {str(e)}")

@app.get("/keys/stats")
async def get_usage_stats(auth: dict = Depends(require_api_key_or_oauth)):
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")
        
        user_id = auth.get("user_id") or auth.get("sub")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")
        
        stats = list(db.usage_logs.aggregate([
            {"$match": {"user_id": user_id}},
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
        ]))
        
        result = stats[0] if stats else {"total_requests": 0, "last_24h": 0}
        return result
    except Exception as e:
        logger.error(f"❌ Stats error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")

# ============================================
# CHAT ENDPOINTS
# ============================================

@app.post("/chat", response_model=ChatResponse)
@limiter.limit("10 per 10 minutes")
async def chat(
    request: Request,
    chat_request: ChatRequest,
    auth: dict = Depends(require_api_key_or_oauth)
):
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    # ============================================
    # VALIDATE MODEL
    # ============================================
    model_to_use = chat_request.model
    
    # If no model specified, try to get from auth or default to auto
    if not model_to_use:
        model_to_use = auth.get("default_model", "auto")
    
    is_valid, error_message, actual_model = validate_model(model_to_use)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_message)
    
    # If model is "auto", let the engine decide
    if actual_model == "auto":
        actual_model = None  # Let engine auto-select
    
    user_id = auth.get("user_id") or auth.get("sub")
    tier = auth.get("tier", "free")
    
    # Check token usage limits
    can_proceed, message = await token_tracker.check_limit(user_id, tier)
    if not can_proceed:
        raise HTTPException(status_code=429, detail=message)
    
    try:
        # Estimate tokens
        tokens_used = len(chat_request.message) // 4
        
        response = chat_engine.generate_response(
            user_message=chat_request.message,
            conversation_history=chat_request.history,
            use_rag=chat_request.use_rag,
            model_override=actual_model
        )
        
        tokens_used += len(response) // 4
        model_used = chat_engine.current_api or "unknown"
        
        # Track usage
        await token_tracker.track_usage(
            user_id=user_id,
            tokens_used=tokens_used,
            model=model_used,
            api=chat_engine.current_api or "unknown",
            cost=tokens_used * 0.000002
        )
        
        # Format response if requested
        if chat_request.format == "source_only":
            response = extract_sources_only(response)
        elif chat_request.format == "concise":
            response = extract_concise_response(response)
        
        model_used_display = None
        if chat_engine.model_switcher:
            if chat_request.model:
                model_used_display = chat_request.model
            elif chat_engine.model_switcher.current_model:
                model_used_display = chat_engine.model_switcher.current_model
            elif chat_engine.model_switcher.auto_mode:
                model_used_display = "auto"
        
        return ChatResponse(
            response=response,
            api_used=chat_engine.current_api,
            model_used=model_used_display,
            mode=chat_engine.get_current_mode() if chat_engine else "coding",
            tokens_used=tokens_used
        )
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/public")
@limiter.limit("5 per minute")
async def chat_public(request: Request, chat_request: ChatRequest):
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    # Validate model for public endpoint too
    model_to_use = chat_request.model or "auto"
    is_valid, error_message, actual_model = validate_model(model_to_use)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_message)
    
    if actual_model == "auto":
        actual_model = None
    
    try:
        response = chat_engine.generate_response(
            user_message=chat_request.message,
            conversation_history=chat_request.history,
            use_rag=chat_request.use_rag,
            model_override=actual_model
        )
        return {"response": response}
    except Exception as e:
        logger.error(f"Public chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/sources")
@limiter.limit("10 per hour")
async def get_sources_only(
    request: Request,
    chat_request: ChatRequest,
    auth: dict = Depends(require_api_key_or_oauth)
):
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    # Validate model
    model_to_use = chat_request.model or "auto"
    is_valid, error_message, actual_model = validate_model(model_to_use)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_message)
    
    if actual_model == "auto":
        actual_model = None
    
    try:
        response = chat_engine.generate_response(
            user_message=chat_request.message,
            conversation_history=chat_request.history,
            use_rag=chat_request.use_rag,
            model_override=actual_model
        )
        
        import re
        sources = re.findall(r'\[Source:[^\]]*\]', response)
        
        if not sources:
            sources_section = re.search(r'Sources?:?\s*\n?([\s\S]*?)(?=\n\n|$)', response)
            if sources_section:
                return {
                    "sources": [s.strip() for s in sources_section.group(1).split('\n') if s.strip()],
                    "topic": chat_request.message[:50] + "..."
                }
        
        unique_sources = list(dict.fromkeys(sources))
        return {"sources": unique_sources, "topic": chat_request.message[:50] + "..."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# RESEARCH MODE ENDPOINTS
# ============================================

@app.post("/mode/research")
async def enable_research_mode(auth: dict = Depends(require_api_key_or_oauth)):
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    result = chat_engine.enable_research_mode()
    return {"message": result, "mode": "research"}

@app.post("/mode/organize")
async def enable_organize_mode(auth: dict = Depends(require_api_key_or_oauth)):
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    result = chat_engine.set_organization_mode()
    return {"message": result, "mode": "organize"}

@app.post("/mode/compare")
async def enable_compare_mode(auth: dict = Depends(require_api_key_or_oauth)):
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    result = chat_engine.set_comparison_mode()
    return {"message": result, "mode": "compare"}

@app.post("/mode/summary")
async def enable_summary_mode(auth: dict = Depends(require_api_key_or_oauth)):
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    result = chat_engine.set_summary_mode()
    return {"message": result, "mode": "summary"}

@app.post("/mode/coding")
async def enable_coding_mode(auth: dict = Depends(require_api_key_or_oauth)):
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    result = chat_engine.reset_to_coding_mode()
    return {"message": result, "mode": "coding"}

@app.get("/mode/current")
async def get_current_mode(auth: dict = Depends(require_api_key_or_oauth)):
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    return {"mode": chat_engine.get_current_mode(), "research_mode": chat_engine.research_mode}

# ============================================
# UPLOAD ENDPOINTS
# ============================================

@app.post("/upload")
@limiter.limit("20 per hour")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    auth: dict = Depends(require_api_key_or_oauth)
):
    if not rag_engine:
        raise HTTPException(status_code=400, detail="RAG engine not available")
    
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ['.pdf', '.txt', '.lua', '.luau']:
        raise HTTPException(status_code=400, detail="Only .pdf, .txt, .lua, .luau files are supported")
    
    user_id = auth.get("user_id") or auth.get("sub")
    
    try:
        os.makedirs("./data/uploaded_docs", exist_ok=True)
        file_path = f"./data/uploaded_docs/{file.filename}"
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        num_chunks = rag_engine.add_document(
            file_path,
            metadata={"filename": file.filename, "type": file_ext, "user_id": user_id}
        )
        
        return {
            "status": "success",
            "filename": file.filename,
            "file_type": file_ext,
            "chunks_processed": num_chunks,
            "message": f"Added {num_chunks} chunks to knowledge base"
        }
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/add-text")
async def add_text(
    text: str,
    metadata: Optional[Dict] = None,
    auth: dict = Depends(require_api_key_or_oauth)
):
    if not rag_engine:
        raise HTTPException(status_code=400, detail="RAG engine not available")
    
    user_id = auth.get("user_id") or auth.get("sub")
    
    try:
        num_chunks = rag_engine.add_text(text, metadata or {"user_id": user_id})
        return {
            "status": "success",
            "chunks_processed": num_chunks,
            "message": f"Added {num_chunks} chunks to knowledge base"
        }
    except Exception as e:
        logger.error(f"Add text error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# QUIZ ENDPOINTS
# ============================================

@app.post("/quiz")
@limiter.limit("10 per hour")
async def generate_quiz(
    request: Request,
    quiz_request: QuizRequest,
    auth: dict = Depends(require_api_key_or_oauth)
):
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    try:
        quiz = chat_engine.generate_quiz(
            topic=quiz_request.topic,
            num_questions=quiz_request.num_questions
        )
        return {"quiz": quiz}
    except Exception as e:
        logger.error(f"Quiz error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# STATS ENDPOINTS
# ============================================

@app.get("/knowledge-stats")
async def get_stats(auth: dict = Depends(require_api_key_or_oauth)):
    if not rag_engine:
        return {"total_documents": 0, "status": "not_available"}
    try:
        count = rag_engine.count()
        return {"total_documents": count, "status": "available"}
    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# MODEL SWITCHER ENDPOINTS
# ============================================

@app.get("/models")
async def get_models(auth: dict = Depends(require_api_key_or_oauth)):
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
    auth: dict = Depends(require_api_key_or_oauth)
):
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
    auth: dict = Depends(require_api_key_or_oauth)
):
    if not chat_engine or not chat_engine.model_switcher:
        raise HTTPException(status_code=503, detail="Model switcher not available")
    result = chat_engine.model_switcher.set_auto_mode(enabled)
    return {
        "auto_mode": chat_engine.model_switcher.auto_mode,
        "message": result
    }

@app.post("/models/next")
async def switch_next(auth: dict = Depends(require_api_key_or_oauth)):
    if not chat_engine or not chat_engine.model_switcher:
        raise HTTPException(status_code=503, detail="Model switcher not available")
    result = chat_engine.model_switcher.switch_to_next_model()
    return {
        "current_model": chat_engine.model_switcher.get_current_model(),
        "message": result
    }

# ============================================
# ANALYTICS ENDPOINTS (No rate limits)
# ============================================

@app.get("/analytics/stats")
async def get_analytics_stats(
    days: int = 30,
    auth: dict = Depends(require_api_key_or_oauth)
):
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    user_id = auth.get("user_id") or auth.get("sub")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    try:
        stats = db.get_usage_stats(user_id, days)
        return stats
    except Exception as e:
        logger.error(f"❌ Analytics stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/analytics/details")
async def get_analytics_details(
    days: int = 30,
    auth: dict = Depends(require_api_key_or_oauth)
):
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    user_id = auth.get("user_id") or auth.get("sub")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    try:
        logs = db.get_detailed_usage(user_id, days)
        return {"logs": logs}
    except Exception as e:
        logger.error(f"❌ Analytics details error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# USAGE ENDPOINTS (No rate limits)
# ============================================

@app.get("/usage")
async def get_usage(auth: dict = Depends(require_api_key_or_oauth)):
    user_id = auth.get("user_id") or auth.get("sub")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    tier = auth.get("tier", "free")
    usage = await token_tracker.get_usage(user_id, "month")
    daily_usage = await token_tracker.get_usage(user_id, "day")
    return {
        "tier": tier,
        "limits": TIER_LIMITS.get(tier, TIER_LIMITS["free"]),
        "usage": {
            "monthly": usage,
            "daily": daily_usage
        }
    }

@app.get("/usage/check")
async def check_usage(auth: dict = Depends(require_api_key_or_oauth)):
    user_id = auth.get("user_id") or auth.get("sub")
    tier = auth.get("tier", "free")
    can_proceed, message = await token_tracker.check_limit(user_id, tier)
    return {
        "can_proceed": can_proceed,
        "message": message,
        "tier": tier,
        "limits": TIER_LIMITS.get(tier, TIER_LIMITS["free"])
    }

# ============================================
# HEALTH & TEST ENDPOINTS
# ============================================

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.get("/db-test")
async def test_database():
    if not db:
        return {"status": "error", "message": "Database not connected"}
    try:
        db.db.command("ping")
        return {"status": "success", "message": "Database connected"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/oauth-check")
async def oauth_check():
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    return {
        "client_id_configured": bool(client_id),
        "client_secret_configured": bool(client_secret),
        "redirect_uri": redirect_uri,
        "oauth_available": bool(oauth),
        "client_id_preview": client_id[:20] + "..." if client_id else None
    }

# ============================================
# FALLBACK & ERROR HANDLERS
# ============================================

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    path = request.url.path
    if path.startswith("/api") or path.startswith("/auth") or path.startswith("/keys") or path.startswith("/models"):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse(content=f"<h1>404 - Page not found</h1>", status_code=404)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"❌ Global error: {exc}")
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal Server Error: {str(exc)}"}
    )

# ============================================
# HELPER FUNCTIONS
# ============================================

def extract_sources_only(response: str) -> str:
    import re
    source_pattern = r'\[Source:[^\]]*\]'
    sources = re.findall(source_pattern, response)
    if not sources:
        sources_section = re.search(r'Sources?:?\s*\n?([\s\S]*?)(?=\n\n|$)', response)
        if sources_section:
            return f"Sources:\n{sources_section.group(1).strip()}"
    if sources:
        unique_sources = list(dict.fromkeys(sources))
        return "Sources:\n" + "\n".join([f"• {s}" for s in unique_sources])
    return "No specific sources cited in the response."

def extract_concise_response(response: str) -> str:
    import re
    lines = response.split('\n')
    key_points = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('•') or stripped.startswith('-') or stripped.startswith('*'):
            key_points.append(stripped)
        elif re.match(r'^\d+\.', stripped):
            key_points.append(stripped)
    if key_points:
        return "Key Points:\n" + "\n".join(key_points)
    paragraphs = [p for p in response.split('\n\n') if p.strip() and len(p.strip()) > 50]
    if paragraphs:
        return "Summary:\n" + paragraphs[0]
    return response[:500] + "..." if len(response) > 500 else response

# ============================================
# RUN APP
# ============================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
