"""
Vostud AI - Simple Rate Limiting & Token Usage System
"""

import time
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from fastapi import Request, HTTPException
import logging

logger = logging.getLogger(__name__)

# ============================================
# RATE LIMIT CONFIGURATION
# ============================================

TIER_LIMITS = {
    "free": {
        "requests_per_minute": 10,
        "requests_per_10min": 10,
        "requests_per_hour": 50,
        "requests_per_day": 200,
        "tokens_per_month": 50000,
        "concurrent_requests": 3,
        "chat_per_minute": 10
    },
    "pro": {
        "requests_per_minute": 30,
        "requests_per_10min": 50,
        "requests_per_hour": 200,
        "requests_per_day": 1000,
        "tokens_per_month": 250000,
        "concurrent_requests": 10,
        "chat_per_minute": 30
    },
    "enterprise": {
        "requests_per_minute": 60,
        "requests_per_10min": 200,
        "requests_per_hour": 500,
        "requests_per_day": 5000,
        "tokens_per_month": 1000000,
        "concurrent_requests": 25,
        "chat_per_minute": 60
    },
    "admin": {
        "requests_per_minute": 100,
        "requests_per_10min": 200,
        "requests_per_hour": 1000,
        "requests_per_day": 10000,
        "tokens_per_month": 5000000,
        "concurrent_requests": 50,
        "chat_per_minute": 100
    }
}

EXCLUDED_PATHS = [
    "/health",
    "/auth/me",
    "/auth/logout",
    "/keys",
    "/keys/stats",
    "/keys/generate",
    "/models",
    "/models/switch",
    "/models/auto",
    "/models/next",
    "/knowledge-stats",
    "/analytics/stats",
    "/analytics/details",
    "/usage",
    "/usage/check",
    "/mode/current",
    "/oauth-check",
    "/db-test",
    "/debug/session",
    "/platform",
    "/",
    "/index.html",
    "/static"
]

# ============================================
# SIMPLE RATE LIMITER
# ============================================

# In-memory request tracking
_request_counts = defaultdict(list)

def rate_limit(limit_per_minute: int = 10, key_func=None):
    """
    Simple rate limit decorator
    
    Usage:
        @rate_limit(limit_per_minute=10)
        async def my_endpoint(request: Request):
            ...
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Get request from args or kwargs
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request and "request" in kwargs:
                request = kwargs["request"]
            
            if request:
                # Build rate limit key
                client_ip = request.client.host if request.client else "unknown"
                api_key = request.headers.get("X-API-Key")
                
                if api_key:
                    # Use API key hash for rate limiting
                    key = f"apikey:{hashlib.md5(api_key.encode()).hexdigest()[:10]}:{int(time.time() / 60)}"
                else:
                    key = f"ip:{client_ip}:{int(time.time() / 60)}"
                
                # Clean old entries (older than 60 seconds)
                if key in _request_counts:
                    _request_counts[key] = [t for t in _request_counts[key] if time.time() - t < 60]
                else:
                    _request_counts[key] = []
                
                # Check limit
                if len(_request_counts[key]) >= limit_per_minute:
                    raise HTTPException(
                        status_code=429,
                        detail=f"Rate limit exceeded. Max {limit_per_minute} requests per minute."
                    )
                
                # Add current request
                _request_counts[key].append(time.time())
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# ============================================
# TOKEN USAGE TRACKER
# ============================================

class TokenUsageTracker:
    """Track token usage per user/api key"""
    
    def __init__(self, db=None):
        self.db = db
        self._cache = {}
        self._cache_ttl = 60
        self._cache_timestamps = {}
    
    def _get_cache_key(self, user_id: str, period: str = "month") -> str:
        return f"{user_id}:{period}"
    
    def _is_cache_valid(self, key: str) -> bool:
        if key not in self._cache_timestamps:
            return False
        return (time.time() - self._cache_timestamps[key]) < self._cache_ttl
    
    async def get_usage(self, user_id: str, period: str = "month") -> dict:
        """Get token usage for a user"""
        try:
            cache_key = self._get_cache_key(user_id, period)
            
            if self._is_cache_valid(cache_key) and cache_key in self._cache:
                return self._cache[cache_key]
            
            if self.db:
                cutoff_date = datetime.utcnow()
                if period == "day":
                    cutoff_date -= timedelta(days=1)
                elif period == "week":
                    cutoff_date -= timedelta(days=7)
                elif period == "month":
                    cutoff_date -= timedelta(days=30)
                else:
                    cutoff_date -= timedelta(days=30)
                
                pipeline = [
                    {"$match": {
                        "user_id": user_id,
                        "timestamp": {"$gte": cutoff_date}
                    }},
                    {"$group": {
                        "_id": None,
                        "total_tokens": {"$sum": "$tokens_used"},
                        "total_requests": {"$sum": 1},
                        "cost": {"$sum": "$cost"}
                    }}
                ]
                
                result = list(self.db.usage_logs.aggregate(pipeline))
                
                if result:
                    usage_data = {
                        "tokens_used": result[0].get("total_tokens", 0),
                        "requests": result[0].get("total_requests", 0),
                        "cost": result[0].get("cost", 0.0)
                    }
                else:
                    usage_data = {
                        "tokens_used": 0,
                        "requests": 0,
                        "cost": 0.0
                    }
                
                self._cache[cache_key] = usage_data
                self._cache_timestamps[cache_key] = time.time()
                
                return usage_data
            
            return {"tokens_used": 0, "requests": 0, "cost": 0.0}
            
        except Exception as e:
            logger.error(f"❌ Token usage error: {e}")
            return {"tokens_used": 0, "requests": 0, "cost": 0.0}
    
    async def track_usage(self, user_id: str, tokens_used: int, model: str = "unknown", api: str = "unknown", cost: float = 0.0):
        """Track token usage for a request"""
        try:
            cache_keys = [
                self._get_cache_key(user_id, "day"),
                self._get_cache_key(user_id, "week"),
                self._get_cache_key(user_id, "month")
            ]
            for key in cache_keys:
                if key in self._cache:
                    del self._cache[key]
                if key in self._cache_timestamps:
                    del self._cache_timestamps[key]
            
            if self.db:
                self.db.usage_logs.insert_one({
                    "user_id": user_id,
                    "timestamp": datetime.utcnow(),
                    "tokens_used": tokens_used,
                    "model": model,
                    "api": api,
                    "cost": cost,
                    "endpoint": "chat"
                })
                
        except Exception as e:
            logger.error(f"❌ Track usage error: {e}")
    
    async def check_limit(self, user_id: str, tier: str = "free") -> Tuple[bool, str]:
        """Check if user has exceeded their token limit"""
        try:
            if self.db:
                cutoff_date = datetime.utcnow() - timedelta(days=30)
                
                pipeline = [
                    {"$match": {
                        "user_id": user_id,
                        "timestamp": {"$gte": cutoff_date}
                    }},
                    {"$group": {
                        "_id": None,
                        "total_tokens": {"$sum": "$tokens_used"},
                        "total_requests": {"$sum": 1}
                    }}
                ]
                
                result = list(self.db.usage_logs.aggregate(pipeline))
                
                if result:
                    monthly_tokens = result[0].get("total_tokens", 0)
                else:
                    monthly_tokens = 0
            else:
                usage = await self.get_usage(user_id, "month")
                monthly_tokens = usage.get("tokens_used", 0)
            
            monthly_limit = TIER_LIMITS.get(tier, TIER_LIMITS["free"]).get("tokens_per_month", 50000)
            
            if monthly_tokens >= monthly_limit:
                return False, f"Monthly token limit exceeded ({monthly_limit} tokens). Upgrade your plan."
            
            return True, "OK"
            
        except Exception as e:
            logger.error(f"❌ Check limit error: {e}")
            return True, "OK"

# ============================================
# RATE LIMIT MIDDLEWARE
# ============================================

token_tracker = TokenUsageTracker()

class RateLimitMiddleware:
    """Custom middleware for rate limiting with path exclusions"""
    
    def __init__(self, app, db=None, token_tracker=None):
        self.app = app
        self.db = db
        self.token_tracker = token_tracker or TokenUsageTracker(db)
        self.excluded_paths = EXCLUDED_PATHS
        self.request_counts = defaultdict(list)
        self.user_tiers = {}
    
    def _is_excluded_path(self, path: str) -> bool:
        if path in self.excluded_paths:
            return True
        
        for excluded in self.excluded_paths:
            if path.startswith(excluded + "/") or path.startswith(excluded + "?"):
                return True
        
        return False
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        request = Request(scope, receive)
        path = request.url.path
        
        # Skip rate limiting for excluded paths
        if self._is_excluded_path(path):
            await self.app(scope, receive, send)
            return
        
        # Get user tier from request state
        tier = getattr(request.state, "tier", "free")
        limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
        
        # Get rate limit key
        api_key = request.headers.get("X-API-Key")
        if api_key:
            key = f"apikey:{hashlib.md5(api_key.encode()).hexdigest()[:10]}"
        else:
            client_ip = request.client.host if request.client else "unknown"
            key = f"ip:{client_ip}"
        
        minute_key = f"{key}:{int(time.time() / 60)}"
        
        # Clean old entries
        if minute_key in self.request_counts:
            self.request_counts[minute_key] = [t for t in self.request_counts[minute_key] if time.time() - t < 60]
            if len(self.request_counts[minute_key]) >= limits.get("chat_per_minute", 10):
                from fastapi.responses import JSONResponse
                response = JSONResponse(
                    status_code=429,
                    content={"detail": f"Rate limit exceeded. Max {limits['chat_per_minute']} requests per minute."}
                )
                await response(scope, receive, send)
                return
        else:
            self.request_counts[minute_key] = []
        
        self.request_counts[minute_key].append(time.time())
        
        await self.app(scope, receive, send)
