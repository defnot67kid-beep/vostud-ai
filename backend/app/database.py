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
import logging

logger = logging.getLogger(__name__)
load_dotenv()

class Database:
    """MongoDB database handler for Vostud AI"""
    
    def __init__(self):
        self.mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.db_name = os.getenv("MONGODB_DB", "vostud_ai")
        
        # Sync client for non-async operations
        try:
            self.sync_client = MongoClient(self.mongo_uri)
            self.db = self.sync_client[self.db_name]
            
            # Collections
            self.api_keys = self.db["api_keys"]
            self.usage_logs = self.db["usage_logs"]
            self.users = self.db["users"]
            self.models = self.db["models"]
            
            # Create indexes
            self._create_indexes()
            
            logger.info("✅ MongoDB Connected!")
        except Exception as e:
            logger.error(f"❌ MongoDB connection error: {e}")
            raise
    
    def _create_indexes(self):
        """Create necessary indexes for performance"""
        try:
            self.api_keys.create_index("key", unique=True)
            self.api_keys.create_index("user_id")
            self.api_keys.create_index("status")
            self.api_keys.create_index("expires_at")
            
            self.usage_logs.create_index("api_key")
            self.usage_logs.create_index("timestamp")
            self.usage_logs.create_index("user_id")
            self.usage_logs.create_index("model_used")
            self.usage_logs.create_index("api_used")
            
            self.users.create_index("email", unique=True)
            self.users.create_index("username", unique=True)
            self.users.create_index("auth_provider")
            
            logger.info("✅ Database indexes created")
        except Exception as e:
            logger.warning(f"⚠️ Index creation warning: {e}")
    
    def generate_api_key(self, prefix="vsd"):
        """Generate a custom API key"""
        random_part = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
        return f"{prefix}-{random_part}"
    
    def hash_api_key(self, api_key: str) -> str:
        """Hash API key for storage"""
        return hashlib.sha256(api_key.encode()).hexdigest()
    
    def create_api_key(self, user_id: str, name: str = None, expires_in_days: int = 365):
        """Create a new API key"""
        try:
            # Generate key
            key = self.generate_api_key()
            hashed_key = self.hash_api_key(key)
            
            # Create key document
            key_doc = {
                "key": hashed_key,
                "key_prefix": key[:10],
                "user_id": user_id,
                "name": name or f"Key for {user_id}",
                "status": "active",
                "created_at": datetime.utcnow(),
                "expires_at": datetime.utcnow() + timedelta(days=expires_in_days),
                "last_used": None,
                "usage_count": 0,
                "rate_limit": 1000,
                "daily_usage": []
            }
            
            # Insert into database
            self.api_keys.insert_one(key_doc)
            
            return {
                "api_key": key,
                "key_prefix": key[:10],
                "user_id": user_id,
                "expires_at": key_doc["expires_at"]
            }
        except Exception as e:
            logger.error(f"❌ Create API key error: {e}")
            return None
    
    def validate_api_key(self, api_key: str) -> dict:
        """Validate an API key"""
        try:
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
            
            # Log usage with more details
            self.usage_logs.insert_one({
                "api_key": hashed_key,
                "user_id": key_doc["user_id"],
                "timestamp": datetime.utcnow(),
                "endpoint": None,
                "ip": None,
                "user_agent": None,
                "model_used": None,
                "api_used": None,
                "response_size": 0,
                "request_size": 0
            })
            
            return {
                "valid": True,
                "user_id": key_doc["user_id"],
                "key_name": key_doc.get("name"),
                "permissions": key_doc.get("permissions", [])
            }
        except Exception as e:
            logger.error(f"❌ Validate API key error: {e}")
            return {"valid": False, "error": str(e)}
    
    def revoke_api_key(self, api_key: str) -> bool:
        """Revoke an API key"""
        try:
            hashed_key = self.hash_api_key(api_key)
            result = self.api_keys.update_one(
                {"key": hashed_key},
                {"$set": {"status": "revoked"}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"❌ Revoke API key error: {e}")
            return False
    
    def get_key_info(self, api_key: str) -> dict:
        """Get information about an API key"""
        try:
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
        except Exception as e:
            logger.error(f"❌ Get key info error: {e}")
            return None
    
    def create_user(self, email: str, username: str, password: str = None):
        """Create a new user"""
        try:
            from passlib.hash import bcrypt
            
            user_doc = {
                "email": email,
                "username": username,
                "display_name": username,
                "created_at": datetime.utcnow(),
                "auth_provider": "email",
                "api_keys": [],
                "settings": {
                    "default_model": "auto",
                    "notifications": True
                }
            }
            
            if password:
                user_doc["password_hash"] = bcrypt.hash(password)
            
            self.users.insert_one(user_doc)
            return user_doc
        except Exception as e:
            logger.error(f"❌ Create user error: {e}")
            return None
    
    # ============================================
    # ANALYTICS METHODS
    # ============================================
    
    def get_usage_stats(self, user_id: str, days: int = 30) -> dict:
        """Get usage statistics for a user"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # Get all usage logs for the user
            logs = list(self.usage_logs.find({
                "user_id": user_id,
                "timestamp": {"$gte": cutoff_date}
            }).sort("timestamp", -1))
            
            if not logs:
                return {
                    "total_requests": 0,
                    "daily_usage": [],
                    "model_usage": [],
                    "api_usage": [],
                    "avg_response_size": 0,
                    "avg_request_size": 0,
                    "total_days": days
                }
            
            # Calculate daily usage
            daily_usage = {}
            model_usage = {}
            api_usage = {}
            total_response_size = 0
            total_request_size = 0
            total_requests = len(logs)
            
            for log in logs:
                # Daily usage
                date_key = log["timestamp"].strftime("%Y-%m-%d")
                if date_key not in daily_usage:
                    daily_usage[date_key] = 0
                daily_usage[date_key] += 1
                
                # Model usage
                model = log.get("model_used", "unknown")
                if model not in model_usage:
                    model_usage[model] = 0
                model_usage[model] += 1
                
                # API usage
                api = log.get("api_used", "unknown")
                if api not in api_usage:
                    api_usage[api] = 0
                api_usage[api] += 1
                
                # Size tracking
                total_response_size += log.get("response_size", 0)
                total_request_size += log.get("request_size", 0)
            
            # Format daily data for charts
            daily_data = [
                {"date": k, "requests": v}
                for k, v in sorted(daily_usage.items())
            ]
            
            # Format model data for charts
            model_data = [
                {"model": k, "count": v}
                for k, v in sorted(model_usage.items(), key=lambda x: x[1], reverse=True)
            ]
            
            # Format API data for charts
            api_data = [
                {"api": k, "count": v}
                for k, v in sorted(api_usage.items(), key=lambda x: x[1], reverse=True)
            ]
            
            return {
                "total_requests": total_requests,
                "daily_usage": daily_data,
                "model_usage": model_data,
                "api_usage": api_data,
                "avg_response_size": round(total_response_size / total_requests, 2) if total_requests > 0 else 0,
                "avg_request_size": round(total_request_size / total_requests, 2) if total_requests > 0 else 0,
                "total_days": days
            }
        except Exception as e:
            logger.error(f"❌ Get usage stats error: {e}")
            return {"error": str(e)}
    
    def get_detailed_usage(self, user_id: str, days: int = 30) -> list:
        """Get detailed usage logs for a user"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            logs = list(self.usage_logs.find({
                "user_id": user_id,
                "timestamp": {"$gte": cutoff_date}
            }).sort("timestamp", -1).limit(100))
            
            return [{
                "timestamp": log["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
                "endpoint": log.get("endpoint", "unknown"),
                "model_used": log.get("model_used", "unknown"),
                "api_used": log.get("api_used", "unknown"),
                "response_size": log.get("response_size", 0),
                "request_size": log.get("request_size", 0)
            } for log in logs]
        except Exception as e:
            logger.error(f"❌ Get detailed usage error: {e}")
            return []
