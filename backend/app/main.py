from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, EmailStr
from typing import List, Dict, Optional
import os
import shutil
from dotenv import load_dotenv
from datetime import datetime, timedelta
import uuid
import mimetypes
import logging
import json

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# ============================================
# CREATE APP INSTANCE FIRST
# ============================================
app = FastAPI(title="Vostud AI API")

# ============================================
# SESSION MIDDLEWARE (Required for OAuth)
# ============================================
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("JWT_SECRET_KEY", "your_super_secret_key_change_this_to_a_long_random_string"),
    session_cookie="vostud_session",
    max_age=3600,  # 1 hour
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
# STATIC FILES (Frontend)
# ============================================
# Get the absolute path to the frontend directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

# Ensure frontend directory exists
if not os.path.exists(FRONTEND_DIR):
    FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")
    if not os.path.exists(FRONTEND_DIR):
        logger.warning(f"⚠️ Frontend directory not found at: {FRONTEND_DIR}")

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

# ============================================
# SETUP OAUTH
# ============================================
oauth = setup_oauth(app)
if oauth:
    logger.info("✅ OAuth setup complete")
else:
    logger.warning("⚠️ OAuth setup failed - check Google credentials")

# ============================================
# INITIALIZE ENGINES
# ============================================
logger.info("🚀 Starting Vostud AI...")

# Database
db = None
try:
    db = Database()
    logger.info("✅ Database connected successfully")
except Exception as e:
    logger.error(f"❌ Database connection failed: {e}")

# RAG Engine
rag_engine = None
try:
    rag_engine = RAGEngine()
    logger.info(f"✅ RAG Engine initialized with {rag_engine.count()} documents")
except Exception as e:
    logger.error(f"❌ RAG Engine failed: {e}")

# Chat Engine
chat_engine = None
try:
    chat_engine = SmartAIEngine()
    if rag_engine:
        chat_engine.rag = rag_engine
    logger.info("✅ Chat Engine initialized")
except Exception as e:
    logger.error(f"❌ Chat Engine failed: {e}")

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

class ModeSwitchResponse(BaseModel):
    mode: str
    message: str

# ============================================
# FRONTEND ROUTES
# ============================================

@app.get("/")
@app.head("/")
async def root():
    """Serve the main index.html or API status"""
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
    """Serve the platform dashboard"""
    platform_path = os.path.join(FRONTEND_DIR, "platform.html")
    if os.path.exists(platform_path):
        return FileResponse(platform_path)
    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html>
        <head><title>Vostud AI Platform</title></head>
        <body style="background: #0f0c29; color: white; display: flex; justify-content: center; align-items: center; height: 100vh; font-family: sans-serif; flex-direction: column;">
            <h1 style="background: linear-gradient(135deg, #667eea, #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">⚡ Vostud AI</h1>
            <p style="color: #888;">Platform page not found. Please make sure platform.html exists in the frontend directory.</p>
            <p style="color: #666; font-size: 0.8em;">Try visiting <a href="/" style="color: #667eea;">the main page</a></p>
        </body>
        </html>
        """,
        status_code=404
    )

@app.get("/index.html")
async def serve_index():
    """Serve index.html"""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="index.html not found")

# ============================================
# OAUTH ROUTES
# ============================================

@app.get("/auth/google")
async def auth_google(request: Request):
    """Redirect to Google OAuth"""
    try:
        if not oauth:
            logger.error("❌ OAuth not configured")
            raise HTTPException(status_code=503, detail="OAuth not configured - missing credentials")
        
        # Generate a random state for CSRF protection
        state = uuid.uuid4().hex
        logger.info(f"🔐 Generated state: {state}")
        
        # Store state in session
        request.session['oauth_state'] = state
        logger.info(f"🔐 State stored in session")
        
        redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "https://vostud-ai.onrender.com/auth/google/callback")
        logger.info(f"🔐 Redirect URI: {redirect_uri}")
        
        # Create the authorization URL
        return await oauth.google.authorize_redirect(request, redirect_uri, state=state)
        
    except Exception as e:
        logger.error(f"❌ OAuth error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"OAuth error: {str(e)}")

@app.get("/auth/google/callback")
async def auth_google_callback(request: Request):
    """Google OAuth callback"""
    try:
        if not oauth:
            logger.error("❌ OAuth not configured")
            raise HTTPException(status_code=503, detail="OAuth not configured - missing credentials")
        
        # Get state from session and request
        session_state = request.session.get('oauth_state') if request.session else None
        request_state = request.query_params.get("state")
        
        logger.info(f"🔐 Session state: {session_state}")
        logger.info(f"🔐 Request state: {request_state}")
        
        # Verify state
        if session_state and request_state:
            if session_state != request_state:
                logger.warning("⚠️ State mismatch - possible CSRF attack")
                # Try to get token without state verification
                try:
                    token = await oauth.google.authorize_access_token(request, verify_state=False)
                    logger.info("✅ Token obtained with verify_state=False")
                except Exception as e:
                    logger.error(f"❌ Token error with verify_state=False: {e}")
                    raise HTTPException(status_code=400, detail="CSRF verification failed")
            else:
                # State matches, get token normally
                token = await oauth.google.authorize_access_token(request)
                logger.info("✅ Token obtained with state verification")
        else:
            # No state to verify, try without verification
            logger.warning("⚠️ No state to verify, trying without verification")
            token = await oauth.google.authorize_access_token(request, verify_state=False)
            logger.info("✅ Token obtained with verify_state=False")
        
        if not token:
            logger.error("❌ No token received from Google")
            raise HTTPException(status_code=400, detail="No token received from Google")
        
        # Get user info
        user_info = token.get('userinfo')
        if not user_info:
            logger.error("❌ No user info in token")
            logger.error(f"Token contents: {token.keys()}")
            raise HTTPException(status_code=400, detail="Failed to get user info from Google")
        
        logger.info(f"👤 User info: {user_info.get('email')}")
        
        # Extract user data
        email = user_info.get('email')
        name = user_info.get('name', email.split('@')[0] if email else 'User')
        picture = user_info.get('picture')
        given_name = user_info.get('given_name', name)
        family_name = user_info.get('family_name', '')
        
        if not email:
            logger.error("❌ No email in user info")
            raise HTTPException(status_code=400, detail="No email in user info")
        
        # Check if user exists in database
        user_id = None
        if db:
            try:
                existing_user = db.users.find_one({"email": email})
                
                if not existing_user:
                    # Create new user
                    user_doc = {
                        "email": email,
                        "username": name,
                        "display_name": name,
                        "picture": picture,
                        "given_name": given_name,
                        "family_name": family_name,
                        "created_at": datetime.utcnow(),
                        "auth_provider": "google",
                        "last_login": datetime.utcnow()
                    }
                    result = db.users.insert_one(user_doc)
                    user_id = str(result.inserted_id)
                    logger.info(f"✅ New user created: {email}")
                else:
                    user_id = str(existing_user["_id"])
                    # Update user info
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
                    logger.info(f"✅ Existing user logged in: {email}")
            except Exception as e:
                logger.error(f"❌ Database error: {e}")
                # Fallback: generate a user ID
                user_id = f"user_{uuid.uuid4().hex[:8]}"
        else:
            # Fallback if database not available
            user_id = f"user_{uuid.uuid4().hex[:8]}"
            logger.warning(f"⚠️ Database not available, using fallback user_id: {user_id}")
        
        # Create JWT token
        access_token = create_access_token({
            "sub": user_id,
            "email": email,
            "name": name,
            "picture": picture or ""
        })
        
        logger.info(f"✅ JWT token created for: {email}")
        
        # Clear session state
        if request.session and 'oauth_state' in request.session:
            request.session.pop('oauth_state')
            logger.info("🔐 Session state cleared")
        
        # Redirect to frontend
        frontend_url = os.getenv("FRONTEND_URL", "https://vostud-ai.onrender.com")
        redirect_url = f"{frontend_url}/platform"
        
        # Set cookie and redirect
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
        logger.error(f"❌ OAuth error: {e}")
        raise HTTPException(status_code=400, detail=f"OAuth error: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Callback error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")

@app.get("/auth/me")
async def auth_me(request: Request):
    """Get current user info"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    return {
        "authenticated": True,
        "user": user
    }

@app.post("/auth/logout")
async def auth_logout():
    """Logout user"""
    response = JSONResponse({"message": "Logged out successfully"})
    response.delete_cookie("access_token")
    return response

# ============================================
# API KEY ENDPOINTS
# ============================================

@app.post("/keys/generate", response_model=CreateKeyResponse)
async def generate_api_key(
    request: CreateKeyRequest,
    auth: dict = Depends(require_api_key_or_oauth)
):
    """Generate a new API key - auto-creates user if not found"""
    try:
        if not db:
            logger.error("❌ Database not available")
            raise HTTPException(status_code=503, detail="Database not available")
        
        # Get user info from auth
        user_id = auth.get("user_id") or auth.get("sub")
        email = auth.get("email")
        name = auth.get("name") or "User"
        
        if not user_id:
            logger.error("❌ User ID not found in auth")
            raise HTTPException(status_code=400, detail="User ID not found")
        
        logger.info(f"🔑 Generating API key for user: {user_id}")
        logger.info(f"📝 Key name: {request.name}")
        logger.info(f"📅 Expires in: {request.expires_in_days} days")
        
        # Try to find the user by ID first
        user = None
        try:
            from bson import ObjectId
            user = db.users.find_one({"_id": ObjectId(user_id)})
        except:
            # If ObjectId conversion fails, try as string
            user = db.users.find_one({"_id": user_id})
        
        # If user not found by ID, try by email
        if not user and email:
            user = db.users.find_one({"email": email})
            if user:
                logger.info(f"👤 Found user by email: {email}")
                user_id = str(user["_id"])
        
        # If user still not found, create a new user
        if not user:
            logger.warning(f"⚠️ User not found, creating new user: {email or user_id}")
            
            # Create user document
            user_doc = {
                "email": email or f"{user_id}@temp.user",
                "username": name,
                "display_name": name,
                "created_at": datetime.utcnow(),
                "auth_provider": "oauth",
                "last_login": datetime.utcnow()
            }
            
            # Insert the user
            result = db.users.insert_one(user_doc)
            user_id = str(result.inserted_id)
            logger.info(f"✅ New user created with ID: {user_id}")
            user = user_doc
        
        # Now generate the API key for the (now confirmed) user
        result = db.create_api_key(
            user_id=user_id,
            name=request.name or f"Key for {user.get('email', user_id)}",
            expires_in_days=request.expires_in_days
        )
        
        if not result:
            logger.error("❌ Failed to create API key")
            raise HTTPException(status_code=500, detail="Failed to create API key")
        
        logger.info(f"✅ API key generated: {result['key_prefix']}")
        
        return CreateKeyResponse(
            api_key=result["api_key"],
            key_prefix=result["key_prefix"],
            user_id=result["user_id"],
            expires_at=result["expires_at"].isoformat() if hasattr(result["expires_at"], 'isoformat') else str(result["expires_at"])
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Key generation error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Key generation failed: {str(e)}")

@app.get("/keys")
async def list_api_keys(
    auth: dict = Depends(require_api_key_or_oauth)
):
    """List all API keys for the user"""
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")
        
        user_id = auth.get("user_id") or auth.get("sub")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")
        
        logger.info(f"🔑 Listing API keys for user: {user_id}")
        
        # Find all keys for this user
        keys = list(db.api_keys.find({"user_id": user_id}))
        
        logger.info(f"📊 Found {len(keys)} keys")
        
        return [{
            "key_prefix": k.get("key_prefix"),
            "name": k.get("name"),
            "status": k.get("status"),
            "created_at": k.get("created_at"),
            "expires_at": k.get("expires_at"),
            "last_used": k.get("last_used"),
            "usage_count": k.get("usage_count", 0)
        } for k in keys]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ List keys error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to list keys: {str(e)}")

@app.delete("/keys/{key_prefix}")
async def revoke_api_key(
    key_prefix: str,
    auth: dict = Depends(require_api_key_or_oauth)
):
    """Revoke an API key"""
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")
        
        user_id = auth.get("user_id") or auth.get("sub")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")
        
        logger.info(f"🔑 Revoking API key: {key_prefix} for user: {user_id}")
        
        # Find the key
        key_doc = db.api_keys.find_one({
            "user_id": user_id,
            "key_prefix": key_prefix
        })
        
        if not key_doc:
            logger.warning(f"⚠️ Key not found: {key_prefix}")
            raise HTTPException(404, "Key not found")
        
        # Revoke it
        result = db.api_keys.update_one(
            {"_id": key_doc["_id"]},
            {"$set": {"status": "revoked"}}
        )
        
        if result.modified_count > 0:
            logger.info(f"✅ Key revoked: {key_prefix}")
            return {"message": "API key revoked"}
        else:
            logger.warning(f"⚠️ Key not modified: {key_prefix}")
            return {"message": "Key already revoked or not found"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Revoke key error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to revoke key: {str(e)}")

@app.get("/keys/stats")
async def get_usage_stats(
    auth: dict = Depends(require_api_key_or_oauth)
):
    """Get usage statistics for API key"""
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")
        
        user_id = auth.get("user_id") or auth.get("sub")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")
        
        logger.info(f"📊 Getting stats for user: {user_id}")
        
        # Get stats from usage logs
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
        logger.info(f"📊 Stats: {result}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Stats error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")

# ============================================
# CHAT ENDPOINTS
# ============================================

@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    auth: dict = Depends(require_api_key_or_oauth)
):
    """Chat with Vostud AI (requires authentication)"""
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    try:
        response = chat_engine.generate_response(
            user_message=request.message,
            conversation_history=request.history,
            use_rag=request.use_rag,
            model_override=request.model
        )
        
        # Format response if requested
        if request.format == "source_only":
            response = extract_sources_only(response)
        elif request.format == "concise":
            response = extract_concise_response(response)
        
        model_used = None
        if chat_engine.model_switcher:
            if request.model:
                model_used = request.model
            elif chat_engine.model_switcher.current_model:
                model_used = chat_engine.model_switcher.current_model
            elif chat_engine.model_switcher.auto_mode:
                model_used = "auto"
        
        # Log usage with details
        if db:
            try:
                user_id = auth.get("user_id") or auth.get("sub")
                if user_id:
                    db.usage_logs.insert_one({
                        "user_id": user_id,
                        "timestamp": datetime.utcnow(),
                        "endpoint": "/chat",
                        "model_used": model_used or "unknown",
                        "api_used": chat_engine.current_api or "unknown",
                        "response_size": len(response) if response else 0,
                        "request_size": len(request.message) if request.message else 0,
                        "format": request.format or "detailed"
                    })
            except Exception as e:
                logger.warning(f"⚠️ Failed to log usage: {e}")
        
        return ChatResponse(
            response=response,
            api_used=chat_engine.current_api,
            model_used=model_used,
            mode=chat_engine.get_current_mode() if chat_engine else "coding"
        )
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/public")
async def chat_public(
    request: ChatRequest
):
    """Public chat endpoint (no authentication, rate limited)"""
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
        logger.error(f"Public chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# CHAT SOURCES ENDPOINT
# ============================================

@app.post("/chat/sources")
async def get_sources_only(
    request: ChatRequest,
    auth: dict = Depends(require_api_key_or_oauth)
):
    """Get only the sources from the response"""
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    try:
        # Get full response
        response = chat_engine.generate_response(
            user_message=request.message,
            conversation_history=request.history,
            use_rag=request.use_rag,
            model_override=request.model
        )
        
        # Extract sources
        import re
        sources = re.findall(r'\[Source:[^\]]*\]', response)
        
        if not sources:
            # Try to find Sources section
            sources_section = re.search(r'Sources?:?\s*\n?([\s\S]*?)(?=\n\n|$)', response)
            if sources_section:
                return {
                    "sources": [s.strip() for s in sources_section.group(1).split('\n') if s.strip()],
                    "topic": request.message[:50] + "..."
                }
        
        # Remove duplicates
        unique_sources = list(dict.fromkeys(sources))
        
        return {
            "sources": unique_sources,
            "topic": request.message[:50] + "..."
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# RESEARCH MODE ENDPOINTS
# ============================================

@app.post("/mode/research")
async def enable_research_mode(
    auth: dict = Depends(require_api_key_or_oauth)
):
    """Enable research mode"""
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    result = chat_engine.enable_research_mode()
    return {"message": result, "mode": "research"}

@app.post("/mode/organize")
async def enable_organize_mode(
    auth: dict = Depends(require_api_key_or_oauth)
):
    """Enable organization mode"""
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    result = chat_engine.set_organization_mode()
    return {"message": result, "mode": "organize"}

@app.post("/mode/compare")
async def enable_compare_mode(
    auth: dict = Depends(require_api_key_or_oauth)
):
    """Enable comparison mode"""
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    result = chat_engine.set_comparison_mode()
    return {"message": result, "mode": "compare"}

@app.post("/mode/summary")
async def enable_summary_mode(
    auth: dict = Depends(require_api_key_or_oauth)
):
    """Enable summary mode"""
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    result = chat_engine.set_summary_mode()
    return {"message": result, "mode": "summary"}

@app.post("/mode/coding")
async def enable_coding_mode(
    auth: dict = Depends(require_api_key_or_oauth)
):
    """Reset to coding mode"""
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    result = chat_engine.reset_to_coding_mode()
    return {"message": result, "mode": "coding"}

@app.get("/mode/current")
async def get_current_mode(
    auth: dict = Depends(require_api_key_or_oauth)
):
    """Get current mode"""
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    return {
        "mode": chat_engine.get_current_mode(),
        "research_mode": chat_engine.research_mode
    }

# ============================================
# UPLOAD ENDPOINTS
# ============================================

@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    auth: dict = Depends(require_api_key_or_oauth)
):
    """Upload a document to the RAG database"""
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
    """Add raw text to the knowledge base"""
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
async def generate_quiz(
    request: QuizRequest,
    auth: dict = Depends(require_api_key_or_oauth)
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
        logger.error(f"Quiz error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# STATS ENDPOINTS
# ============================================

@app.get("/knowledge-stats")
async def get_stats(
    auth: dict = Depends(require_api_key_or_oauth)
):
    """Get knowledge base statistics"""
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
async def get_models(
    auth: dict = Depends(require_api_key_or_oauth)
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
    auth: dict = Depends(require_api_key_or_oauth)
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
    auth: dict = Depends(require_api_key_or_oauth)
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
    auth: dict = Depends(require_api_key_or_oauth)
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
# ANALYTICS ENDPOINTS
# ============================================

@app.get("/analytics/stats")
async def get_analytics_stats(
    days: int = 30,
    auth: dict = Depends(require_api_key_or_oauth)
):
    """Get usage statistics for the user"""
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
    """Get detailed usage logs"""
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
# HEALTH & TEST ENDPOINTS
# ============================================

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.get("/db-test")
async def test_database():
    """Test database connection"""
    if not db:
        return {"status": "error", "message": "Database not connected"}
    
    try:
        db.db.command("ping")
        return {"status": "success", "message": "Database connected"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/oauth-check")
async def oauth_check():
    """Check OAuth configuration"""
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

@app.get("/debug/session")
async def debug_session(request: Request):
    """Debug session state"""
    session = request.session if request.session else {}
    return {
        "session_exists": bool(request.session),
        "session_keys": list(session.keys()) if session else [],
        "cookies": list(request.cookies.keys()),
        "has_oauth_state": "oauth_state" in session if session else False,
        "session_data": {k: str(v)[:50] for k, v in session.items()} if session else {}
    }

# ============================================
# FALLBACK FOR 404 - Serve frontend
# ============================================

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Handle 404 errors by serving the frontend if the path might be a frontend route"""
    path = request.url.path
    
    # If it's an API path, return JSON error
    if path.startswith("/api") or path.startswith("/auth") or path.startswith("/keys") or path.startswith("/models"):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    
    # Try to serve the index.html for frontend routes
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    
    return HTMLResponse(
        content=f"<h1>404 - Page not found</h1><p>The requested path '{path}' does not exist.</p>",
        status_code=404
    )

# ============================================
# ERROR HANDLERS
# ============================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler to return JSON instead of HTML"""
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
    """Extract only the sources/citations from the response"""
    import re
    
    # Find all [Source: ...] patterns
    source_pattern = r'\[Source:[^\]]*\]'
    sources = re.findall(source_pattern, response)
    
    # Also look for "Sources:" section
    if not sources:
        sources_section = re.search(r'Sources?:?\s*\n?([\s\S]*?)(?=\n\n|$)', response)
        if sources_section:
            return f"Sources:\n{sources_section.group(1).strip()}"
    
    if sources:
        # Remove duplicates
        unique_sources = list(dict.fromkeys(sources))
        return "Sources:\n" + "\n".join([f"• {s}" for s in unique_sources])
    
    # If no sources found, return a message
    return "No specific sources cited in the response."

def extract_concise_response(response: str) -> str:
    """Extract just the key points from the response"""
    import re
    
    # Look for bullet points or numbered lists
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
    
    # Try to find the first paragraph
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
