import os
import urllib.parse
import time
from fastapi import Request, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import jwt.algorithms
import httpx
import asyncio

# In-memory cache for JWK
JWKS_CACHE = None
JWKS_LAST_FETCH = 0
JWKS_TTL = 3600 # Cache for 1 hour

security = HTTPBearer(auto_error=False)

def get_supabase_project_id() -> str:
    # 1. Try to get direct SUPABASE_URL or NEXT_PUBLIC_SUPABASE_URL
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    if supabase_url:
        parsed = urllib.parse.urlparse(supabase_url)
        parts = parsed.netloc.split(".")
        if parts:
            return parts[0]
    
    # 2. Fallback: Parse DATABASE_URL
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        try:
            parsed = urllib.parse.urlparse(db_url)
            # Try to parse from username (e.g. postgres.sjqiojrqigyufftigvyp)
            if parsed.username and "." in parsed.username:
                user_parts = parsed.username.split(".")
                if len(user_parts) >= 2:
                    return user_parts[1]
            
            # Try to parse from host (e.g. db.sjqiojrqigyufftigvyp.supabase.co)
            if parsed.hostname:
                host_parts = parsed.hostname.split(".")
                if len(host_parts) >= 2 and host_parts[0] == "db":
                    return host_parts[1]
        except Exception:
            pass
            
    raise RuntimeError("Neither SUPABASE_URL nor DATABASE_URL was found or could be parsed to retrieve the Supabase project ID.")

# Global lock to serialize JWK fetches
JWKS_LOCK = asyncio.Lock()

async def fetch_jwks(force_refresh: bool = False) -> dict:
    global JWKS_CACHE, JWKS_LAST_FETCH
    
    # Lock-free fast path check
    now = time.time()
    if not force_refresh and JWKS_CACHE and (now - JWKS_LAST_FETCH) < JWKS_TTL:
        return JWKS_CACHE
    
    async with JWKS_LOCK:
        # Re-check inside lock to prevent concurrent requests from double-fetching
        now = time.time()
        if not force_refresh and JWKS_CACHE and (now - JWKS_LAST_FETCH) < JWKS_TTL:
            return JWKS_CACHE
            
        project_id = get_supabase_project_id()
        jwks_url = f"https://{project_id}.supabase.co/auth/v1/.well-known/jwks.json"
        
        print(f"[auth.py] fetch_jwks: Cache miss or force-refresh. Fetching JWKS from {jwks_url}...")
        start_time = time.time()
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(jwks_url)
                response.raise_for_status()
                JWKS_CACHE = response.json()
                JWKS_LAST_FETCH = time.time()
                latency_ms = round((JWKS_LAST_FETCH - start_time) * 1000)
                print(f"[auth.py] fetch_jwks: Successfully fetched and cached JWKS in {latency_ms}ms")
                return JWKS_CACHE
        except Exception as e:
            print(f"[auth.py] fetch_jwks: Network fetch failed: {type(e).__name__}: {str(e)}")
            # Fallback to stale cache if available to prevent API blackout
            if JWKS_CACHE:
                print("[auth.py] fetch_jwks: Returning stale cached JWKS as fallback due to network failure.")
                return JWKS_CACHE
            raise RuntimeError(f"Failed to fetch Supabase JWKS from {jwks_url}: {str(e)}") from e

async def verify_jwt(credentials: HTTPAuthorizationCredentials = Security(security)) -> dict:
    """FastAPI security dependency to verify the JWT from Supabase.
    
    If no authorization credentials are provided, falls back to a guest session.
    Otherwise, cryptographically verifies the token signature against the JWKS.
    """
    if credentials is None:
        print("[auth.py] verify_jwt: No credentials/header provided. Raising 401 Unauthorized.")
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please provide a valid Authorization header."
        )
        
    token = credentials.credentials
    print(f"[auth.py] verify_jwt: Authenticating request. JWT token prefix: {token[:15]}...")
    try:
        jwks = await fetch_jwks()
        headers = jwt.get_unverified_header(token)
        print(f"[auth.py] verify_jwt: JWT Headers decoded: {headers}")
        
        kid = headers.get("kid")
        alg = headers.get("alg", "RS256")
        if not kid:
            print("[auth.py] verify_jwt: Validation error - Missing kid in token header")
            raise HTTPException(status_code=401, detail="Missing kid in JWT header")
            
        key_data = next((k for k in jwks["keys"] if k["kid"] == kid), None)
        if not key_data:
            print(f"[auth.py] verify_jwt: Key ID '{kid}' not found in cached JWKS. Forcing immediate refresh...")
            jwks = await fetch_jwks(force_refresh=True)
            key_data = next((k for k in jwks["keys"] if k["kid"] == kid), None)
            
        if not key_data:
            print(f"[auth.py] verify_jwt: Validation error - Key ID '{kid}' not found in JWKS")
            raise HTTPException(status_code=401, detail="Key ID not found in JWKS")
            
        # Select correct algorithm parsing based on the algorithm used by Supabase
        if alg == "RS256":
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
        elif alg == "ES256":
            public_key = jwt.algorithms.ECAlgorithm.from_jwk(key_data)
        else:
            print(f"[auth.py] verify_jwt: Validation error - Unsupported signing algorithm '{alg}'")
            raise HTTPException(status_code=401, detail=f"Unsupported signing algorithm: {alg}")
        
        # Verify the token. Supabase default audience is 'authenticated'.
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256", "ES256"],
            audience="authenticated"
        )
        print(f"[auth.py] verify_jwt: Cryptographic validation succeeded! sub: {payload.get('sub')}, email: {payload.get('email')}, role: {payload.get('role')}")
        return payload
    except jwt.ExpiredSignatureError as e:
        print("[auth.py] verify_jwt: Token signature has expired.")
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as e:
        print(f"[auth.py] verify_jwt: Invalid token error - {str(e)}")
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except Exception as e:
        print(f"[auth.py] verify_jwt: Authentication failed with unhandled exception - {str(e)}")
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")
