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
        
        try:
            self.sync_client = MongoClient(self.mongo_uri)
            self.db = self.sync_client[self.db_name]
            
            self.api_keys = self.db["api_keys"]
            self.usage_logs = self.db["usage_logs"]
            self.users = self.db["users"]
            self.models = self.db["models"]
            
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
            key = self.generate_api_key()
            hashed_key = self.hash_api_key(key)
            
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
        """Validate an API key and track usage"""
        try:
            hashed_key = self.hash_api_key(api_key)
            
            key_doc = self.api_keys.find_one({
                "key": hashed_key,
                "status": "active"
            })
            
            if not key_doc:
                return {"valid": False, "error": "Invalid API key"}
            
            if key_doc["expires_at"] < datetime.utcnow():
                self.api_keys.update_one(
                    {"key": hashed_key},
                    {"$set": {"status": "expired"}}
                )
                return {"valid": False, "error": "API key expired"}
            
            # Update last_used
            self.api_keys.update_one(
                {"key": hashed_key},
                {"$set": {"last_used": datetime.utcnow()}}
            )
            
            return {
                "valid": True,
                "user_id": key_doc["user_id"],
                "key_name": key_doc.get("name"),
                "permissions": key_doc.get("permissions", [])
            }
        except Exception as e:
            logger.error(f"❌ Validate API key error: {e}")
            return {"valid": False, "error": str(e)}
    
    def log_usage(self, user_id: str, api_key: str = None, endpoint: str = None, 
                  model_used: str = None, api_used: str = None, 
                  tokens_used: int = 0, request_size: int = 0, response_size: int = 0,
                  cost: float = 0.0):
        """Log API usage for tracking"""
        try:
            # Count usage for API key
            if api_key:
                hashed_key = self.hash_api_key(api_key)
                # Increment usage_count on the API key
                self.api_keys.update_one(
                    {"key": hashed_key},
                    {"$inc": {"usage_count": 1}}
                )
            
            # Insert usage log
            usage_doc = {
                "user_id": user_id,
                "timestamp": datetime.utcnow(),
                "endpoint": endpoint or "unknown",
                "model_used": model_used or "unknown",
                "api_used": api_used or "unknown",
                "tokens_used": tokens_used,
                "request_size": request_size,
                "response_size": response_size,
                "cost": cost
            }
            
            if api_key:
                hashed_key = self.hash_api_key(api_key)
                usage_doc["api_key"] = hashed_key
            
            self.usage_logs.insert_one(usage_doc)
            
            logger.info(f"📊 Usage logged: {user_id} - {endpoint} - {tokens_used} tokens")
            
        except Exception as e:
            logger.error(f"❌ Log usage error: {e}")
    
    def get_key_stats(self, user_id: str) -> dict:
        """Get API key statistics for a user"""
        try:
            keys = list(self.api_keys.find({"user_id": user_id}))
            
            total_keys = len(keys)
            active_keys = sum(1 for k in keys if k.get("status") == "active")
            total_usage = sum(k.get("usage_count", 0) for k in keys)
            
            return {
                "total_keys": total_keys,
                "active_keys": active_keys,
                "total_usage": total_usage,
                "keys": [{
                    "key_prefix": k.get("key_prefix"),
                    "name": k.get("name"),
                    "status": k.get("status"),
                    "usage_count": k.get("usage_count", 0)
                } for k in keys]
            }
        except Exception as e:
            logger.error(f"❌ Get key stats error: {e}")
            return {"total_keys": 0, "active_keys": 0, "total_usage": 0, "keys": []}
    
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
    
    def get_usage_stats(self, user_id: str, days: int = 30) -> dict:
        """Get usage statistics for a user"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
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
                    "total_days": days,
                    "total_tokens": 0
                }
            
            daily_usage = {}
            model_usage = {}
            api_usage = {}
            total_response_size = 0
            total_request_size = 0
            total_tokens = 0
            total_requests = len(logs)
            
            for log in logs:
                date_key = log["timestamp"].strftime("%Y-%m-%d")
                if date_key not in daily_usage:
                    daily_usage[date_key] = 0
                daily_usage[date_key] += 1
                
                model = log.get("model_used", "unknown")
                if model not in model_usage:
                    model_usage[model] = 0
                model_usage[model] += 1
                
                api = log.get("api_used", "unknown")
                if api not in api_usage:
                    api_usage[api] = 0
                api_usage[api] += 1
                
                total_response_size += log.get("response_size", 0)
                total_request_size += log.get("request_size", 0)
                total_tokens += log.get("tokens_used", 0)
            
            daily_data = [
                {"date": k, "requests": v}
                for k, v in sorted(daily_usage.items())
            ]
            
            model_data = [
                {"model": k, "count": v}
                for k, v in sorted(model_usage.items(), key=lambda x: x[1], reverse=True)
            ]
            
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
                "total_days": days,
                "total_tokens": total_tokens
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
                "request_size": log.get("request_size", 0),
                "tokens_used": log.get("tokens_used", 0)
            } for log in logs]
        except Exception as e:
            logger.error(f"❌ Get detailed usage error: {e}")
            return []
    
    def get_user_usage_summary(self, user_id: str) -> dict:
        """Get a summary of user usage for the dashboard"""
        try:
            # Total usage ever
            total_usage = self.usage_logs.count_documents({"user_id": user_id})
            
            # Last 24 hours
            cutoff_24h = datetime.utcnow() - timedelta(hours=24)
            last_24h = self.usage_logs.count_documents({
                "user_id": user_id,
                "timestamp": {"$gte": cutoff_24h}
            })
            
            # Last 30 days tokens
            cutoff_30d = datetime.utcnow() - timedelta(days=30)
            pipeline = [
                {"$match": {
                    "user_id": user_id,
                    "timestamp": {"$gte": cutoff_30d}
                }},
                {"$group": {
                    "_id": None,
                    "total_tokens": {"$sum": "$tokens_used"}
                }}
            ]
            result = list(self.usage_logs.aggregate(pipeline))
            total_tokens = result[0].get("total_tokens", 0) if result else 0
            
            # API key stats
            keys = list(self.api_keys.find({"user_id": user_id}))
            
            return {
                "total_requests": total_usage,
                "last_24h": last_24h,
                "total_tokens": total_tokens,
                "total_keys": len(keys),
                "active_keys": sum(1 for k in keys if k.get("status") == "active")
            }
        except Exception as e:
            logger.error(f"❌ Get user usage summary error: {e}")
            return {
                "total_requests": 0,
                "last_24h": 0,
                "total_tokens": 0,
                "total_keys": 0,
                "active_keys": 0
            }
