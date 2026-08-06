"""
Vostud AI - Google OAuth Integration
"""

import os
import jwt
import uuid
import logging
from datetime import datetime, timedelta
from fastapi import HTTPException, Depends, Request
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from starlette.config import Config
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# ============================================
# JWT Helpers
# ============================================

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your_super_secret_key_change_this")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 10080))

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str):
    """Decode JWT access token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError as e:
        logger.error(f"JWT decode error: {e}")
        return None

# ============================================
# OAuth Setup
# ============================================

def setup_oauth(app):
    """Setup Google OAuth"""
    
    try:
        # Get OAuth configuration
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        
        if not client_id or not client_secret:
            logger.error("❌ Google OAuth credentials not configured")
            logger.info("   Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env")
            return None
        
        logger.info(f"✅ Google OAuth configured with client_id: {client_id[:20]}...")
        
        # Configure OAuth
        oauth = OAuth()
        oauth.register(
            name='google',
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_id=client_id,
            client_secret=client_secret,
            client_kwargs={
                'scope': 'openid email profile'
            }
        )
        
        return oauth
        
    except Exception as e:
        logger.error(f"❌ OAuth setup error: {e}")
        return None

# ============================================
# User Models
# ============================================

class GoogleUserInfo(BaseModel):
    email: str
    name: str
    picture: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None

# ============================================
# Auth Dependencies
# ============================================

async def get_current_user(request: Request):
    """Get current user from JWT token in cookie or header"""
    
    # Check cookie first
    token = request.cookies.get("access_token")
    
    # If not in cookie, check Authorization header
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
    
    if not token:
        return None
    
    payload = decode_access_token(token)
    if not payload:
        return None
    
    # Get user from database to get current tier
    try:
        from app.database import Database
        from bson import ObjectId
        db = Database()
        user = db.users.find_one({"_id": ObjectId(payload.get("sub"))})
        if user:
            return {
                "user_id": payload.get("sub"),
                "email": payload.get("email"),
                "name": payload.get("name"),
                "picture": payload.get("picture"),
                "tier": user.get("tier", "free")  # Get tier from database
            }
    except Exception as e:
        logger.error(f"❌ Error getting user from database: {e}")
    
    # Fallback to token data
    return {
        "user_id": payload.get("sub"),
        "email": payload.get("email"),
        "name": payload.get("name"),
        "picture": payload.get("picture"),
        "tier": payload.get("tier", "free")
    }

async def require_auth(request: Request):
    """Require authentication"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

async def require_api_key_or_oauth(request: Request):
    """Allow either API key OR OAuth cookie"""
    
    # Check for API key in header
    api_key = request.headers.get("X-API-Key")
    
    if api_key:
        try:
            from app.database import Database
            db = Database()
            result = db.validate_api_key(api_key)
            if result["valid"]:
                # Get user info from database including tier
                from bson import ObjectId
                try:
                    user = db.users.find_one({"_id": ObjectId(result["user_id"])})
                except:
                    user = db.users.find_one({"_id": result["user_id"]})
                
                return {
                    "auth_type": "api_key",
                    "user_id": result["user_id"],
                    "email": user.get("email") if user else None,
                    "name": user.get("display_name") if user else None,
                    "tier": user.get("tier", "free") if user else "free"
                }
        except Exception as e:
            logger.error(f"API key validation error: {e}")
    
    # Check for OAuth cookie or header
    user = await get_current_user(request)
    if user:
        return {
            "auth_type": "oauth",
            "user_id": user.get("user_id"),
            "email": user.get("email"),
            "name": user.get("name"),
            "tier": user.get("tier", "free")
        }
    
    # If no auth, raise exception
    raise HTTPException(status_code=401, detail="Authentication required")

async def optional_auth(request: Request):
    """Optional authentication (public endpoints)"""
    # Check for API key
    api_key = request.headers.get("X-API-Key")
    if api_key:
        try:
            from app.database import Database
            db = Database()
            result = db.validate_api_key(api_key)
            if result["valid"]:
                return {"auth_type": "api_key", "user_id": result["user_id"]}
        except:
            pass
    
    # Check for OAuth
    user = await get_current_user(request)
    if user:
        return {"auth_type": "oauth", **user}
    
    return None
