import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from fastapi import FastAPI

logger = logging.getLogger(__name__)

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for logging request information"""
    
    async def dispatch(self, request: Request, call_next):
        # Generate request ID
        request_id = f"{time.time():.0f}"
        
        # Log request start
        logger.info(f"Request {request_id} started: {request.method} {request.url.path}")
        
        # Time the request
        start_time = time.time()
        
        try:
            # Process the request
            response = await call_next(request)
            
            # Log successful completion
            process_time = time.time() - start_time
            logger.info(
                f"Request {request_id} completed: {response.status_code} in {process_time:.3f}s"
            )
            
            # Add custom headers if needed
            response.headers["X-Process-Time"] = str(process_time)
            
            return response
            
        except Exception as e:
            # Log any exceptions
            process_time = time.time() - start_time
            logger.error(
                f"Request {request_id} failed after {process_time:.3f}s: {str(e)}"
            )
            raise

class RateLimitingMiddleware(BaseHTTPMiddleware):
    """Simple rate limiting middleware"""
    
    def __init__(self, app: FastAPI, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.request_timestamps = {}
        
    async def dispatch(self, request: Request, call_next):
        # Get client IP
        client_ip = request.client.host if request.client else "unknown"
        
        # Clean up old timestamps
        current_time = time.time()
        self.request_timestamps = {
            ip: timestamps for ip, timestamps in self.request_timestamps.items()
            if timestamps[-1] > current_time - 60  # Keep last minute
        }
        
        # Check rate limit
        if client_ip in self.request_timestamps:
            timestamps = self.request_timestamps[client_ip]
            # Count requests in the last minute
            recent_requests = sum(1 for ts in timestamps if ts > current_time - 60)
            
            if recent_requests >= self.requests_per_minute:
                logger.warning(f"Rate limit exceeded for {client_ip}")
                return Response(
                    content="Rate limit exceeded. Please try again later.",
                    status_code=429
                )
            
            # Add current timestamp
            timestamps.append(current_time)
        else:
            # New client
            self.request_timestamps[client_ip] = [current_time]
        
        # Process the request
        return await call_next(request)

def add_middlewares(app: FastAPI):
    """Add all custom middlewares to the app"""
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RateLimitingMiddleware, requests_per_minute=60)