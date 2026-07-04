import os
import urllib.parse
import time
from fastapi import Request, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import jwt.algorithms
import httpx

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
    
    # 2. Fallback: Parse DATABASE_URL if it has the format postgresql://...db.project_id.supabase.co...
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        try:
            if "@" in db_url:
                host_part = db_url.split("@")[1].split("/")[0]
                if ":" in host_part:
                    host_part = host_part.split(":")[0]
                parts = host_part.split(".")
                if len(parts) >= 2 and parts[0] == "db":
                    return parts[1]
        except Exception:
            pass
            
    raise RuntimeError("Neither SUPABASE_URL nor DATABASE_URL was found or could be parsed to retrieve the Supabase project ID.")

async def fetch_jwks() -> dict:
    global JWKS_CACHE, JWKS_LAST_FETCH
    now = time.time()
    if JWKS_CACHE and (now - JWKS_LAST_FETCH) < JWKS_TTL:
        return JWKS_CACHE
    
    project_id = get_supabase_project_id()
    jwks_url = f"https://{project_id}.supabase.co/auth/v1/.well-known/jwks.json"
    
    async with httpx.AsyncClient() as client:
        response = await client.get(jwks_url)
        response.raise_for_status()
        JWKS_CACHE = response.json()
        JWKS_LAST_FETCH = now
        return JWKS_CACHE

async def verify_jwt(credentials: HTTPAuthorizationCredentials = Security(security)) -> dict:
    """FastAPI security dependency to verify the JWT from Supabase.
    
    If no authorization credentials are provided, falls back to a guest session.
    Otherwise, cryptographically verifies the token signature against the JWKS.
    """
    if credentials is None:
        # Fallback to guest mode
        return {"sub": "guest"}
        
    token = credentials.credentials
    try:
        jwks = await fetch_jwks()
        headers = jwt.get_unverified_header(token)
        kid = headers.get("kid")
        alg = headers.get("alg", "RS256")
        if not kid:
            raise HTTPException(status_code=401, detail="Missing kid in JWT header")
            
        key_data = next((k for k in jwks["keys"] if k["kid"] == kid), None)
        if not key_data:
            raise HTTPException(status_code=401, detail="Key ID not found in JWKS")
            
        # Select correct algorithm parsing based on the algorithm used by Supabase
        if alg == "RS256":
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
        elif alg == "ES256":
            public_key = jwt.algorithms.ECAlgorithm.from_jwk(key_data)
        else:
            raise HTTPException(status_code=401, detail=f"Unsupported signing algorithm: {alg}")
        
        # Verify the token. Supabase default audience is 'authenticated'.
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256", "ES256"],
            audience="authenticated"
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")
