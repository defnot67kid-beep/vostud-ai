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
import logging
import json
import hashlib
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# ============================================
# CREATE APP INSTANCE FIRST
# ============================================
app = FastAPI(title="Vostud AI API")

# ============================================
# STATIC FILES (for images, etc.)
# ============================================
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../static")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "images"), exist_ok=True)

app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static",
)

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
# STATIC FILES (Frontend HTML)
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
from app.rate_limiter import rate_limit, token_tracker, RateLimitMiddleware, TIER_LIMITS

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
# ILLEGAL ACTIVITY DETECTION
# ============================================

ILLEGAL_ACTIVITY_PATTERNS = {
    "sql_injection": r'\b(?:SELECT|INSERT|UPDATE|DELETE|DROP|UNION|ALTER|CREATE|EXEC|EXECUTE)\b.*?\b(?:FROM|INTO|TABLE|DATABASE)\b',
    "xss": r'<script.*?>.*?</script>',
    "eval": r'\b(?:eval|exec|system|shell_exec|passthru|popen|proc_open)\s*\(',
    "malware": r'\b(?:virus|malware|trojan|ransomware|keylogger|rootkit|worm)\b',
    "exploit": r'\b(?:exploit|vulnerability|backdoor|shellcode|buffer.?overflow|zero.?day)\b',
    "drugs": r'\b(?:cocaine|heroin|meth|ecstasy|lsd|marijuana|cannabis|drug|trafficking)\b',
    "weapons": r'\b(?:gun|firearm|explosive|bomb|ammunition|weapon|knife|sword)\b',
    "fraud": r'\b(?:fraud|scam|phishing|identity.?theft|credit.?card|stolen|hack|crack)\b',
    "terrorism": r'\b(?:terrorist|terrorism|isis|al-qaeda|bomb|attack|jihad|extremist)\b',
    "pornography": r'\b(?:porn|xxx|explicit|nsfw|adult.?content|child.?abuse|underage)\b',
    "human_trafficking": r'\b(?:trafficking|slavery|forced.?labor|human.?smuggling)\b',
    "piracy": r'\b(?:pirate|pirated|torrent|crack|keygen|serial|license|bypass|DRM|rip)\b',
}

SEVERITY_LEVELS = {
    "critical": ["terrorism", "human_trafficking", "pornography"],
    "high": ["malware", "exploit", "weapons", "fraud", "drugs"],
    "medium": ["sql_injection", "xss", "eval", "piracy"],
    "low": []
}

def detect_illegal_activity(text: str) -> tuple:
    if not text:
        return False, None, []
    
    text_lower = text.lower()
    detected = []
    severity = None
    
    for pattern_name, pattern in ILLEGAL_ACTIVITY_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            detected.append(pattern_name)
    
    if detected:
        if any(p in SEVERITY_LEVELS["critical"] for p in detected):
            severity = "critical"
        elif any(p in SEVERITY_LEVELS["high"] for p in detected):
            severity = "high"
        elif any(p in SEVERITY_LEVELS["medium"] for p in detected):
            severity = "medium"
        else:
            severity = "low"
        
        return True, severity, detected
    
    return False, None, []

def generate_illegal_activity_report(user_id: str, email: str, message: str, severity: str, patterns: list) -> dict:
    return {
        "user_id": user_id,
        "email": email,
        "timestamp": datetime.utcnow().isoformat(),
        "severity": severity,
        "patterns": patterns,
        "message": message[:500],
        "ip": None,
        "status": "reported"
    }

# ============================================
# PROFANITY FILTER
# ============================================

PROFANITY_LIST = [
    "nigger", "nigga", "chink", "gook", "spic", "wetback", "kike",
    "faggot", "dyke", "tranny", "retard",
    "fuck", "shit", "cunt", "pussy", "dick", "asshole", "bastard", 
    "bitch", "whore", "slut", "cocksucker", "motherfucker",
    "hate", "racist", "sexist", "homophobic", "transphobic",
    "kill", "murder", "rape", "abuse", "torture", "bomb", "explosive",
    "weapon", "gun", "knife", "attack", "hurt", "destroy"
]

def contains_profanity(text: str) -> bool:
    if not text:
        return False
    text_lower = text.lower()
    pattern = r'\b(?:' + '|'.join(re.escape(word) for word in PROFANITY_LIST) + r')\b'
    return bool(re.search(pattern, text_lower))

def contains_profanity_loose(text: str) -> bool:
    if not text:
        return False
    text_lower = text.lower()
    for word in PROFANITY_LIST:
        if word in text_lower:
            return True
    return False

# ============================================
# VALID MODELS LIST
# ============================================

VALID_MODELS = [
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

def validate_model(model: str) -> tuple:
    if not model:
        return False, "⚠️ Model selection required. Please specify a model or use 'auto' for automatic selection.", None
    
    if contains_profanity_loose(model):
        return False, "❌ Invalid model name. Please use a valid model from the list below.", None
    
    if model == "auto":
        return True, None, "auto"
    
    if model in VALID_MODELS:
        return True, None, model
    
    if model.startswith("vostud-"):
        full_model = f"vostud-{model.replace('vostud-', '')}"
        if full_model in VALID_MODELS:
            return True, None, full_model
    
    if "/" in model:
        for valid in VALID_MODELS:
            if valid.endswith(model) or model in valid:
                return True, None, valid
    
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
# LOGO ENDPOINT
# ============================================

@app.get("/logo")
async def get_logo():
    logo_path = os.path.join(STATIC_DIR, "images", "vostud-logo.png")
    if os.path.exists(logo_path):
        return FileResponse(logo_path, media_type="image/png")
    raise HTTPException(status_code=404, detail="Logo not found")

# ============================================
# PYDANTIC MODELS
# ============================================

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict]] = None
    use_rag: bool = True
    model: Optional[str] = None
    format: Optional[str] = None

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
    mode: str

class SupportTicketRequest(BaseModel):
    subject: str
    message: str
    category: str = "general"

class TicketMessageRequest(BaseModel):
    message: str

class AppealRequest(BaseModel):
    message: str

class AdminAppealRequest(BaseModel):
    approved: bool
    admin_notes: Optional[str] = None

class PublicAppealRequest(BaseModel):
    email: str
    message: str
    user_id: Optional[str] = None

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
    return HTMLResponse(content="<h1>Platform page not found</h1>", status_code=404)

@app.get("/adminpanel")
@app.head("/adminpanel")
async def serve_admin_panel():
    admin_path = os.path.join(FRONTEND_DIR, "admin.html")
    if os.path.exists(admin_path):
        return FileResponse(admin_path)
    return HTMLResponse(content="<h1>Admin panel not found</h1>", status_code=404)

@app.get("/support")
@app.head("/support")
async def serve_support_dashboard():
    support_path = os.path.join(FRONTEND_DIR, "support.html")
    if os.path.exists(support_path):
        return FileResponse(support_path)
    return HTMLResponse(content="<h1>Support dashboard not found</h1>", status_code=404)

@app.get("/index.html")
async def serve_index():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="index.html not found")

# ============================================
# ADMIN PANEL API ROUTES
# ============================================

@app.get("/api/adminpanel")
async def admin_panel(auth: dict = Depends(require_api_key_or_oauth)):
    if auth.get("tier") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    total_users = db.users.count_documents({})
    suspended_users = db.users.count_documents({"suspension_status": "suspended"})
    pending_appeals = db.suspension_appeals.count_documents({"status": "pending"})
    total_keys = db.api_keys.count_documents({})
    
    return {
        "status": "admin",
        "stats": {
            "total_users": total_users,
            "suspended_users": suspended_users,
            "pending_appeals": pending_appeals,
            "total_api_keys": total_keys
        },
        "message": "Welcome to the admin panel"
    }

@app.get("/api/adminpanel/users")
async def admin_users(auth: dict = Depends(require_api_key_or_oauth)):
    if auth.get("tier") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    users = list(db.users.find({}, {"_id": 1, "email": 1, "tier": 1, "suspension_status": 1}))
    
    for user in users:
        user["_id"] = str(user["_id"])
    
    return {"users": users}

@app.get("/api/adminpanel/reports")
async def admin_reports(auth: dict = Depends(require_api_key_or_oauth)):
    if auth.get("tier") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    reports = list(db.illegal_activity_logs.find().sort("timestamp", -1).limit(50))
    
    for report in reports:
        report["_id"] = str(report["_id"])
    
    return {"reports": reports}

@app.get("/api/adminpanel/appeals")
async def admin_appeals(auth: dict = Depends(require_api_key_or_oauth)):
    if auth.get("tier") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        appeals = list(db.suspension_appeals.find().sort("created_at", -1))
    except Exception as e:
        return {"appeals": []}
    
    for appeal in appeals:
        appeal["_id"] = str(appeal["_id"])
    
    return {"appeals": appeals}

# ============================================
# SUPPORT API ROUTES
# ============================================

@app.get("/api/support")
async def support_dashboard(auth: dict = Depends(require_api_key_or_oauth)):
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    user_id = auth.get("user_id") or auth.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")
    
    from bson import ObjectId
    tickets = list(db.support_tickets.find({"user_id": user_id}).sort("created_at", -1))
    
    for ticket in tickets:
        ticket["_id"] = str(ticket["_id"])
    
    return {
        "user_id": user_id,
        "tickets": tickets,
        "message": "Your support tickets"
    }

@app.post("/api/support/ticket")
async def create_support_ticket(
    request: SupportTicketRequest,
    auth: dict = Depends(require_api_key_or_oauth)
):
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    user_id = auth.get("user_id") or auth.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")
    
    ticket_id = db.create_support_ticket(
        user_id=user_id,
        subject=request.subject,
        message=request.message,
        category=request.category
    )
    
    if not ticket_id:
        raise HTTPException(status_code=500, detail="Failed to create ticket")
    
    return {
        "ticket_id": ticket_id,
        "message": "Support ticket created. We'll respond as soon as possible."
    }

@app.post("/api/support/ticket/{ticket_id}/message")
async def add_ticket_message(
    ticket_id: str,
    request: TicketMessageRequest,
    auth: dict = Depends(require_api_key_or_oauth)
):
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    user_id = auth.get("user_id") or auth.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")
    
    success = db.add_ticket_message(ticket_id, request.message, from_user=True)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to add message")
    
    return {"message": "Message added to ticket"}

@app.get("/api/support/ticket/{ticket_id}")
async def get_ticket_details(
    ticket_id: str,
    auth: dict = Depends(require_api_key_or_oauth)
):
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    user_id = auth.get("user_id") or auth.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")
    
    from bson import ObjectId
    ticket = db.support_tickets.find_one({
        "_id": ObjectId(ticket_id),
        "user_id": user_id
    })
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    ticket["_id"] = str(ticket["_id"])
    return ticket

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
            return {"total_requests": 0, "last_24h": 0, "total_keys": 0, "active_keys": 0, "total_tokens": 0}
        
        user_id = auth.get("user_id") or auth.get("sub")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")
        
        summary = db.get_user_usage_summary(user_id)
        
        return {
            "total_requests": summary.get("total_requests", 0),
            "last_24h": summary.get("last_24h", 0),
            "total_keys": summary.get("total_keys", 0),
            "active_keys": summary.get("active_keys", 0),
            "total_tokens": summary.get("total_tokens", 0),
            "suspended": summary.get("suspended", False)
        }
    except Exception as e:
        logger.error(f"❌ Stats error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")

# ============================================
# CHAT ENDPOINTS
# ============================================

@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    chat_request: ChatRequest,
    auth: dict = Depends(require_api_key_or_oauth)
):
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    is_illegal, severity, patterns = detect_illegal_activity(chat_request.message)
    
    if is_illegal and severity in ["critical", "high"]:
        user_id = auth.get("user_id") or auth.get("sub")
        email = auth.get("email", "unknown")
        api_key = request.headers.get("X-API-Key")
        
        report = generate_illegal_activity_report(
            user_id=user_id,
            email=email,
            message=chat_request.message,
            severity=severity,
            patterns=patterns
        )
        
        if db:
            db.illegal_activity_logs.insert_one(report)
            reason = f"🚫 Illegal activity detected: {', '.join(patterns)}"
            db.suspend_user(user_id, reason, severity, patterns)
            db.create_support_ticket(
                user_id=user_id,
                subject=f"Account Suspension - {severity.upper()} Severity",
                message=f"Your account has been automatically suspended due to illegal activity detection.\n\nPatterns detected: {', '.join(patterns)}\n\nTo appeal this suspension, please use the appeal system or contact support.",
                category="suspension"
            )
        
        logger.warning(f"🚫 ILLEGAL ACTIVITY DETECTED - User: {email}, Severity: {severity}, Patterns: {patterns}")
        logger.warning(f"⛔ User {user_id} has been suspended")
        
        if severity == "critical":
            raise HTTPException(
                status_code=403,
                detail=f"""🚫 **ACCOUNT PERMANENTLY SUSPENDED**

Your account has been permanently suspended due to severe violation of our Terms of Service.

Reason: {', '.join(patterns)}

📝 **What you can do:**
1. Submit an appeal: POST /support/appeal
2. Contact support: POST /support/ticket
3. Check appeal status: GET /support/appeal
4. If you can't authenticate, use: POST /support/public-appeal

🆔 Your User ID: {user_id}

⛔ All API keys associated with this account have been revoked.

This decision was made automatically to protect our platform and users."""
            )
        else:
            raise HTTPException(
                status_code=403,
                detail=f"""🚫 **ACCOUNT SUSPENDED**

Your account has been temporarily suspended due to violation of our Terms of Service.

Reason: {', '.join(patterns)}

📝 **What you can do:**
1. Submit an appeal: POST /support/appeal
2. Contact support: POST /support/ticket
3. Check appeal status: GET /support/appeal
4. If you can't authenticate, use: POST /support/public-appeal

🆔 Your User ID: {user_id}

⛔ All API keys associated with this account have been revoked.

This decision can be reviewed by our support team."""
            )
    
    if contains_profanity(chat_request.message):
        raise HTTPException(
            status_code=400, 
            detail="❌ Your message contains inappropriate language. Please keep the conversation professional."
        )
    
    model_to_use = chat_request.model
    
    if not model_to_use:
        model_to_use = auth.get("default_model", "auto")
    
    is_valid, error_message, actual_model = validate_model(model_to_use)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_message)
    
    if actual_model == "auto":
        actual_model = None
    
    user_id = auth.get("user_id") or auth.get("sub")
    tier = auth.get("tier", "free")
    
    can_proceed, message = await token_tracker.check_limit(user_id, tier)
    if not can_proceed:
        raise HTTPException(status_code=429, detail=message)
    
    try:
        api_key = request.headers.get("X-API-Key")
        tokens_used = len(chat_request.message) // 4
        
        response = chat_engine.generate_response(
            user_message=chat_request.message,
            conversation_history=chat_request.history,
            use_rag=chat_request.use_rag,
            model_override=actual_model
        )
        
        tokens_used += len(response) // 4
        model_used = chat_engine.current_api or "unknown"
        
        if db:
            db.log_usage(
                user_id=user_id,
                api_key=api_key,
                endpoint="/chat",
                model_used=model_used,
                api_used=chat_engine.current_api or "unknown",
                tokens_used=tokens_used,
                request_size=len(chat_request.message),
                response_size=len(response),
                cost=tokens_used * 0.000002
            )
            
            await token_tracker.track_usage(
                user_id=user_id,
                tokens_used=tokens_used,
                model=model_used,
                api=chat_engine.current_api or "unknown",
                cost=tokens_used * 0.000002
            )
        
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
async def chat_public(request: Request, chat_request: ChatRequest):
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    is_illegal, severity, patterns = detect_illegal_activity(chat_request.message)
    if is_illegal and severity in ["critical", "high"]:
        raise HTTPException(
            status_code=403,
            detail=f"🚫 Access denied. Illegal activity detected: {', '.join(patterns)}"
        )
    
    if contains_profanity(chat_request.message):
        raise HTTPException(
            status_code=400, 
            detail="❌ Your message contains inappropriate language. Please keep the conversation professional."
        )
    
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
    
    if file_ext == '.txt':
        try:
            content = await file.read()
            file_text = content.decode('utf-8', errors='ignore')
            is_illegal, severity, patterns = detect_illegal_activity(file_text)
            if is_illegal and severity in ["critical", "high"]:
                raise HTTPException(
                    status_code=403,
                    detail=f"🚫 File rejected. Illegal content detected: {', '.join(patterns)}"
                )
            await file.seek(0)
        except:
            await file.seek(0)
    
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
    
    is_illegal, severity, patterns = detect_illegal_activity(text)
    if is_illegal and severity in ["critical", "high"]:
        raise HTTPException(
            status_code=403,
            detail=f"🚫 Content rejected. Illegal activity detected: {', '.join(patterns)}"
        )
    
    if contains_profanity(text):
        raise HTTPException(
            status_code=400, 
            detail="❌ Your text contains inappropriate language. Please keep the content professional."
        )
    
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
    request: Request,
    quiz_request: QuizRequest,
    auth: dict = Depends(require_api_key_or_oauth)
):
    if not chat_engine:
        raise HTTPException(status_code=503, detail="Chat engine not available")
    
    is_illegal, severity, patterns = detect_illegal_activity(quiz_request.topic)
    if is_illegal and severity in ["critical", "high"]:
        raise HTTPException(
            status_code=403,
            detail=f"🚫 Topic rejected. Illegal activity detected: {', '.join(patterns)}"
        )
    
    if contains_profanity(quiz_request.topic):
        raise HTTPException(
            status_code=400, 
            detail="❌ Your topic contains inappropriate language. Please keep the content professional."
        )
    
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
# ANALYTICS ENDPOINTS
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
# USAGE ENDPOINTS
# ============================================

@app.get("/usage")
async def get_usage(auth: dict = Depends(require_api_key_or_oauth)):
    user_id = auth.get("user_id") or auth.get("sub")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    
    tier = auth.get("tier", "free")
    
    if db:
        cutoff_date = datetime.utcnow() - timedelta(days=30)
        pipeline = [
            {"$match": {
                "user_id": user_id,
                "timestamp": {"$gte": cutoff_date}
            }},
            {"$group": {
                "_id": None,
                "tokens_used": {"$sum": "$tokens_used"},
                "requests": {"$sum": 1}
            }}
        ]
        result = list(db.usage_logs.aggregate(pipeline))
        
        monthly_tokens = result[0].get("tokens_used", 0) if result else 0
        monthly_requests = result[0].get("requests", 0) if result else 0
        
        cutoff_daily = datetime.utcnow() - timedelta(days=1)
        daily_requests = db.usage_logs.count_documents({
            "user_id": user_id,
            "timestamp": {"$gte": cutoff_daily}
        })
        
        return {
            "tier": tier,
            "limits": TIER_LIMITS.get(tier, TIER_LIMITS["free"]),
            "usage": {
                "monthly": {
                    "tokens_used": monthly_tokens,
                    "requests": monthly_requests
                },
                "daily": {
                    "requests": daily_requests
                }
            }
        }
    
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
# SUPPORT & SUSPENSION ENDPOINTS
# ============================================

@app.post("/support/public-appeal")
async def public_appeal(
    request: PublicAppealRequest
):
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    user = None
    if request.user_id:
        from bson import ObjectId
        try:
            user = db.users.find_one({"_id": ObjectId(request.user_id)})
        except:
            pass
    
    if not user and request.email:
        user = db.users.find_one({"email": request.email})
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found. Please provide a valid email or user_id.")
    
    if user.get("suspension_status") != "suspended":
        raise HTTPException(status_code=400, detail="Your account is not currently suspended.")
    
    appeal_id = db.create_appeal(str(user["_id"]), request.message)
    if not appeal_id:
        raise HTTPException(status_code=500, detail="Failed to create appeal")
    
    return {
        "appeal_id": appeal_id,
        "message": "Appeal submitted successfully. We'll review your case.",
        "user_id": str(user["_id"]),
        "email": user.get("email")
    }

@app.post("/support/appeal")
async def create_appeal(
    request: AppealRequest,
    auth: dict = Depends(require_api_key_or_oauth)
):
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    user_id = auth.get("user_id") or auth.get("sub")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    
    user = db.users.find_one({"_id": user_id})
    if not user or user.get("suspension_status") != "suspended":
        raise HTTPException(status_code=400, detail="Your account is not suspended")
    
    appeal_id = db.create_appeal(user_id, request.message)
    if not appeal_id:
        raise HTTPException(status_code=500, detail="Failed to create appeal")
    
    return {
        "appeal_id": appeal_id,
        "message": "Appeal submitted. We'll review your case."
    }

@app.get("/support/appeal")
async def get_appeal_status(
    auth: dict = Depends(require_api_key_or_oauth)
):
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    user_id = auth.get("user_id") or auth.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")
    
    from bson import ObjectId
    
    # Find appeals for this user
    try:
        appeals = list(db.suspension_appeals.find({"user_id": user_id}).sort("created_at", -1))
    except Exception as e:
        # If collection doesn't exist or has no data
        return {"status": "no_appeal", "message": "No appeal found"}
    
    if not appeals:
        return {"status": "no_appeal", "message": "No appeal found"}
    
    appeal = appeals[0]
    appeal["_id"] = str(appeal["_id"])
    return appeal

# ============================================
# ADMIN ENDPOINTS (API)
# ============================================

@app.get("/admin/suspended-users")
async def get_suspended_users(
    auth: dict = Depends(require_api_key_or_oauth)
):
    if auth.get("tier") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    users = list(db.users.find({"suspension_status": "suspended"}))
    
    for user in users:
        user["_id"] = str(user["_id"])
    
    return {"suspended_users": users}

@app.post("/admin/unsuspend/{user_id}")
async def admin_unsuspend_user(
    user_id: str,
    auth: dict = Depends(require_api_key_or_oauth)
):
    if auth.get("tier") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    from bson import ObjectId
    user = db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    success = db.unsuspend_user(user_id, "Admin manually restored")
    if not success:
        raise HTTPException(status_code=500, detail="Failed to unsuspend user")
    
    return {"message": f"User {user.get('email')} has been unsuspended"}

@app.get("/admin/appeals")
async def get_pending_appeals(
    auth: dict = Depends(require_api_key_or_oauth)
):
    if auth.get("tier") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        appeals = list(db.suspension_appeals.find({"status": "pending"}).sort("created_at", 1))
    except Exception as e:
        return {"appeals": []}
    
    for appeal in appeals:
        appeal["_id"] = str(appeal["_id"])
    
    return {"appeals": appeals}

@app.post("/admin/appeal/{appeal_id}/resolve")
async def resolve_appeal(
    appeal_id: str,
    request: AdminAppealRequest,
    auth: dict = Depends(require_api_key_or_oauth)
):
    if auth.get("tier") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    from bson import ObjectId
    appeal = db.suspension_appeals.find_one({"_id": ObjectId(appeal_id)})
    if not appeal:
        raise HTTPException(status_code=404, detail="Appeal not found")
    
    success = db.resolve_appeal(
        appeal_id=appeal_id,
        approved=request.approved,
        admin_notes=request.admin_notes
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to resolve appeal")
    
    return {
        "message": f"Appeal {appeal_id} resolved. Approved: {request.approved}",
        "approved": request.approved
    }

@app.get("/admin/illegal-activity")
async def get_illegal_activity(
    limit: int = 50,
    severity: Optional[str] = None,
    auth: dict = Depends(require_api_key_or_oauth)
):
    if auth.get("tier") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    query = {}
    if severity:
        query["severity"] = severity
    
    reports = list(db.illegal_activity_logs.find(query).sort("timestamp", -1).limit(limit))
    
    for report in reports:
        report["_id"] = str(report["_id"])
    
    return reports

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
