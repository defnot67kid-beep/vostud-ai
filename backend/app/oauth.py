"""
Vostud AI - Google OAuth Integration
"""

import os
import jwt
from datetime import datetime, timedelta
from fastapi import HTTPException, Depends, Request
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from starlette.config import Config
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional

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
    except jwt.PyJWTError:
        return None

# ============================================
# OAuth Setup
# ============================================

def setup_oauth(app):
    """Setup Google OAuth"""
    
    config = Config('.env')
    oauth = OAuth(config)
    
    oauth.register(
        name='google',
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_id=os.getenv('GOOGLE_CLIENT_ID'),
        client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
        client_kwargs={
            'scope': 'openid email profile'
        }
    )
    
    return oauth

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
    """Get current user from JWT token"""
    token = request.cookies.get("access_token")
    
    if not token:
        return None
    
    payload = decode_access_token(token)
    if not payload:
        return None
    
    return {
        "user_id": payload.get("sub"),
        "email": payload.get("email"),
        "name": payload.get("name"),
        "picture": payload.get("picture")
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
        from app.database import Database
        db = Database()
        result = db.validate_api_key(api_key)
        if result["valid"]:
            return {"auth_type": "api_key", "user_id": result["user_id"]}
    
    # Check for OAuth cookie
    user = await get_current_user(request)
    if user:
        return {"auth_type": "oauth", **user}
    
    raise HTTPException(status_code=401, detail="Authentication required")

async def optional_auth(request: Request):
    """Optional authentication (public endpoints)"""
    # Check for API key
    api_key = request.headers.get("X-API-Key")
    if api_key:
        from app.database import Database
        db = Database()
        result = db.validate_api_key(api_key)
        if result["valid"]:
            return {"auth_type": "api_key", "user_id": result["user_id"]}
    
    # Check for OAuth cookie
    user = await get_current_user(request)
    if user:
        return {"auth_type": "oauth", **user}
    
    return None
