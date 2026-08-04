"""
Vostud AI - MongoDB Database Connection
Handles API keys, usage tracking, and user data
"""

import os
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from dotenv import load_dotenv
import hashlib
import secrets
import string
from datetime import datetime, timedelta

load_dotenv()

class Database:
    """MongoDB database handler for Vostud AI"""
    
    def __init__(self):
        self.mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.db_name = os.getenv("MONGODB_DB", "vostud_ai")
        
        # Sync client for non-async operations
        self.sync_client = MongoClient(self.mongo_uri)
        self.db = self.sync_client[self.db_name]
        
        # Async client for FastAPI
        self.async_client = AsyncIOMotorClient(self.mongo_uri)
        self.async_db = self.async_client[self.db_name]
        
        # Collections
        self.api_keys = self.db["api_keys"]
        self.usage_logs = self.db["usage_logs"]
        self.users = self.db["users"]
        self.models = self.db["models"]
        
        # Create indexes
        self._create_indexes()
        
        print("✅ MongoDB Connected!")
    
    def _create_indexes(self):
        """Create necessary indexes for performance"""
        # API Keys indexes
        self.api_keys.create_index("key", unique=True)
        self.api_keys.create_index("user_id")
        self.api_keys.create_index("status")
        self.api_keys.create_index("expires_at")
        
        # Usage logs indexes
        self.usage_logs.create_index("api_key")
        self.usage_logs.create_index("timestamp")
        self.usage_logs.create_index("user_id")
        
        # Users indexes
        self.users.create_index("email", unique=True)
        self.users.create_index("username", unique=True)
    
    def generate_api_key(self, prefix="vsd"):
        """Generate a custom API key"""
        # Generate random string (32 characters)
        random_part = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
        # Format: vsd-{random}
        return f"{prefix}-{random_part}"
    
    def hash_api_key(self, api_key: str) -> str:
        """Hash API key for storage"""
        return hashlib.sha256(api_key.encode()).hexdigest()
    
    def create_api_key(self, user_id: str, name: str = None, expires_in_days: int = 365):
        """Create a new API key"""
        # Generate key
        key = self.generate_api_key()
        hashed_key = self.hash_api_key(key)
        
        # Create key document
        key_doc = {
            "key": hashed_key,
            "key_prefix": key[:10],  # Store prefix for display
            "user_id": user_id,
            "name": name or f"Key for {user_id}",
            "status": "active",
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(days=expires_in_days),
            "last_used": None,
            "usage_count": 0,
            "rate_limit": 1000,  # Requests per day
            "daily_usage": [],
            "permissions": ["chat", "upload", "quiz", "models"]
        }
        
        # Insert into database
        self.api_keys.insert_one(key_doc)
        
        return {
            "api_key": key,  # Return full key (only time it's shown)
            "key_prefix": key[:10],
            "user_id": user_id,
            "expires_at": key_doc["expires_at"]
        }
    
    def validate_api_key(self, api_key: str) -> dict:
        """Validate an API key"""
        hashed_key = self.hash_api_key(api_key)
        
        # Find key in database
        key_doc = self.api_keys.find_one({
            "key": hashed_key,
            "status": "active"
        })
        
        if not key_doc:
            return {"valid": False, "error": "Invalid API key"}
        
        # Check expiration
        if key_doc["expires_at"] < datetime.utcnow():
            # Mark as expired
            self.api_keys.update_one(
                {"key": hashed_key},
                {"$set": {"status": "expired"}}
            )
            return {"valid": False, "error": "API key expired"}
        
        # Check rate limit
        today = datetime.utcnow().date()
        daily_usage = [entry for entry in key_doc.get("daily_usage", []) 
                      if entry["date"] == today.isoformat()]
        
        today_count = sum(entry["count"] for entry in daily_usage)
        if today_count >= key_doc.get("rate_limit", 1000):
            return {"valid": False, "error": "Rate limit exceeded"}
        
        # Update usage
        self.api_keys.update_one(
            {"key": hashed_key},
            {
                "$set": {"last_used": datetime.utcnow()},
                "$inc": {"usage_count": 1},
                "$push": {
                    "daily_usage": {
                        "date": today.isoformat(),
                        "count": 1,
                        "timestamp": datetime.utcnow()
                    }
                }
            }
        )
        
        # Log usage
        self.usage_logs.insert_one({
            "api_key": hashed_key,
            "user_id": key_doc["user_id"],
            "timestamp": datetime.utcnow(),
            "endpoint": None,  # Will be filled by the endpoint
            "ip": None,
            "user_agent": None
        })
        
        return {
            "valid": True,
            "user_id": key_doc["user_id"],
            "key_name": key_doc.get("name"),
            "permissions": key_doc.get("permissions", [])
        }
    
    def revoke_api_key(self, api_key: str) -> bool:
        """Revoke an API key"""
        hashed_key = self.hash_api_key(api_key)
        result = self.api_keys.update_one(
            {"key": hashed_key},
            {"$set": {"status": "revoked"}}
        )
        return result.modified_count > 0
    
    def get_key_info(self, api_key: str) -> dict:
        """Get information about an API key"""
        hashed_key = self.hash_api_key(api_key)
        key_doc = self.api_keys.find_one({"key": hashed_key})
        
        if not key_doc:
            return None
        
        return {
            "user_id": key_doc.get("user_id"),
            "name": key_doc.get("name"),
            "status": key_doc.get("status"),
            "created_at": key_doc.get("created_at"),
            "expires_at": key_doc.get("expires_at"),
            "last_used": key_doc.get("last_used"),
            "usage_count": key_doc.get("usage_count", 0),
            "rate_limit": key_doc.get("rate_limit", 1000)
        }
    
    def create_user(self, email: str, username: str, password: str = None):
        """Create a new user"""
        from passlib.hash import bcrypt
        
        user_doc = {
            "email": email,
            "username": username,
            "created_at": datetime.utcnow(),
            "api_keys": [],
            "settings": {
                "default_model": "auto",
                "notifications": True
            }
        }
        
        if password:
            user_doc["password_hash"] = bcrypt.hash(password)
        
        self.users.insert_one(user_doc)
        return user_docs
