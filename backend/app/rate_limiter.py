"""
Vostud AI - Rate Limiting & Token Usage System
Protects API endpoints from excessive usage
"""

import time
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from collections import defaultdict
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import logging

logger = logging.getLogger(__name__)

# ============================================
# RATE LIMIT CONFIGURATION
# ============================================

# Default limits per user tier
TIER_LIMITS = {
    "free": {
        "requests_per_hour": 50,
        "requests_per_day": 500,
        "tokens_per_month": 100000,
        "concurrent_requests": 5,
        "chat_per_minute": 10
    },
    "pro": {
        "requests_per_hour": 200,
        "requests_per_day": 5000,
        "tokens_per_month": 1000000,
        "concurrent_requests": 20,
        "chat_per_minute": 30
    },
    "enterprise": {
        "requests_per_hour": 1000,
        "requests_per_day": 25000,
        "tokens_per_month": 10000000,
        "concurrent_requests": 100,
        "chat_per_minute": 60
    }
}

# Paths to exclude from rate limiting (internal/analytics endpoints)
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
    "/platform",
    "/static"
]

# ============================================
# TOKEN USAGE TRACKER
# ============================================

class TokenUsageTracker:
    """Track token usage per user/api key"""
    
    def __init__(self, db=None):
        self.db = db
        self._cache = {}  # In-memory cache for fast lookups
        self._cache_ttl = 60  # Cache TTL in seconds
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
            
            # Check cache
            if self._is_cache_valid(cache_key) and cache_key in self._cache:
                return self._cache[cache_key]
            
            # Get from database
            if self.db:
                # Get usage logs for the period
                cutoff_date = datetime.utcnow()
                if period == "day":
                    cutoff_date -= timedelta(days=1)
                elif period == "week":
                    cutoff_date -= timedelta(days=7)
                elif period == "month":
                    cutoff_date -= timedelta(days=30)
                else:
                    cutoff_date -= timedelta(days=30)
                
                # Aggregate token usage from logs
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
                
                # Cache the result
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
            # Invalidate cache
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
            
            # Store in database
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
            # Get usage for the month
            usage = await self.get_usage(user_id, "month")
            monthly_limit = TIER_LIMITS.get(tier, TIER_LIMITS["free"]).get("tokens_per_month", 100000)
            
            if usage["tokens_used"] >= monthly_limit:
                return False, f"Monthly token limit exceeded ({monthly_limit} tokens). Upgrade your plan."
            
            # Check daily limit
            daily_usage = await self.get_usage(user_id, "day")
            daily_limit = TIER_LIMITS.get(tier, TIER_LIMITS["free"]).get("requests_per_day", 500)
            
            if daily_usage["requests"] >= daily_limit:
                return False, f"Daily request limit exceeded ({daily_limit} requests per day)."
            
            return True, "OK"
            
        except Exception as e:
            logger.error(f"❌ Check limit error: {e}")
            return True, "OK"

# ============================================
# RATE LIMITER SETUP
# ============================================

# Create rate limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["100 per hour"])
token_tracker = TokenUsageTracker()

# ============================================
# RATE LIMIT MIDDLEWARE
# ============================================

class RateLimitMiddleware:
    """Custom middleware for rate limiting with path exclusions"""
    
    def __init__(self, app, db=None, token_tracker=None):
        self.app = app
        self.db = db
        self.token_tracker = token_tracker or TokenUsageTracker(db)
        self.request_counts = defaultdict(list)
        self.user_tiers = {}
        self.excluded_paths = EXCLUDED_PATHS
    
    def _is_excluded_path(self, path: str) -> bool:
        """Check if the path should be excluded from rate limiting"""
        # Exact match
        if path in self.excluded_paths:
            return True
        
        # Check if path starts with any excluded path (for /static/*, /platform/*, etc.)
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
        
        # Extract user ID from auth
        user_id = None
        api_key = request.headers.get("X-API-Key")
        if api_key and self.db:
            try:
                hashed_key = hashlib.sha256(api_key.encode()).hexdigest()
                key_doc = self.db.api_keys.find_one({"key": hashed_key})
                if key_doc:
                    user_id = key_doc.get("user_id")
                    # Get user tier
                    user = self.db.users.find_one({"_id": user_id})
                    if user:
                        tier = user.get("tier", "free")
                        self.user_tiers[user_id] = tier
            except:
                pass
        
        if not user_id:
            # Use IP address as fallback
            user_id = get_remote_address(request)
            self.user_tiers[user_id] = "free"
        
        # Store user_id in request state for later use
        request.state.user_id = user_id
        request.state.rate_key = user_id
        request.state.tier = self.user_tiers.get(user_id, "free")
        
        # Check rate limits
        tier = self.user_tiers.get(user_id, "free")
        limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
        
        # Check per-minute limit
        minute_key = f"{user_id}:{int(time.time() / 60)}"
        if minute_key in self.request_counts:
            self.request_counts[minute_key] = [t for t in self.request_counts[minute_key] if time.time() - t < 60]
            if len(self.request_counts[minute_key]) >= limits.get("chat_per_minute", 10):
                response = JSONResponse(
                    status_code=429,
                    content={"detail": f"Rate limit exceeded. Max {limits['chat_per_minute']} requests per minute."}
                )
                await response(scope, receive, send)
                return
        else:
            self.request_counts[minute_key] = []
        
        self.request_counts[minute_key].append(time.time())
        
        # Proceed with the request
        await self.app(scope, receive, send)
