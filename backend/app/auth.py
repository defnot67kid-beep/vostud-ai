"""
Vostud AI - Authentication & Authorization
API key validation middleware
"""

from fastapi import HTTPException, Header, Depends
from typing import Optional
from app.database import Database
import logging

logger = logging.getLogger(__name__)

# Database instance
db = None

def get_db():
    """Get database instance"""
    global db
    if db is None:
        db = Database()
    return db

async def validate_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None)
):
    """
    Validate API key from either:
    - X-API-Key header
    - Authorization: Bearer {key} header
    """
    
    # Extract API key
    api_key = None
    
    if x_api_key:
        api_key = x_api_key
    elif authorization and authorization.startswith("Bearer "):
        api_key = authorization.replace("Bearer ", "")
    
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API key required. Provide via X-API-Key or Bearer token"
        )
    
    # Validate key
    database = get_db()
    result = database.validate_api_key(api_key)
    
    if not result["valid"]:
        raise HTTPException(
            status_code=401,
            detail=result.get("error", "Invalid API key")
        )
    
    # Get user from database to get current tier
    try:
        from bson import ObjectId
        user = database.users.find_one({"_id": ObjectId(result["user_id"])})
    except:
        user = database.users.find_one({"_id": result["user_id"]})
    
    return {
        "user_id": result["user_id"],
        "permissions": result.get("permissions", []),
        "key_name": result.get("key_name"),
        "api_key": api_key,
        "tier": user.get("tier", "free") if user else "free"
    }

async def validate_optional_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None)
):
    """Optional API key validation (for public endpoints)"""
    
    if not x_api_key and not authorization:
        return None
    
    return await validate_api_key(x_api_key, authorization)
