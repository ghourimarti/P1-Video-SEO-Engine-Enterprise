"""Clerk JWT verification — FastAPI dependency.

Verifies the Bearer token issued by Clerk using their public JWKS endpoint.
The JWKS response is cached in-process (refreshed every 5 minutes) so we do
not hit the network on every request.
"""

from __future__ import annotations

import time
from typing import Annotated

import httpx
import jwt
import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from anime_rag.core.settings import get_settings

log = structlog.get_logger(__name__)

_bearer = HTTPBearer(auto_error=True)

# Simple in-process JWKS cache: (jwks_dict, fetched_at_epoch)
_jwks_cache: tuple[dict, float] | None = None
_JWKS_TTL = 300  # seconds


async def _fetch_jwks(jwks_url: str) -> dict:
    global _jwks_cache
    now = time.monotonic()
    if _jwks_cache and (now - _jwks_cache[1]) < _JWKS_TTL:
        return _jwks_cache[0]

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(jwks_url)
        resp.raise_for_status()
        data = resp.json()

    _jwks_cache = (data, now)
    log.debug("jwks_refreshed", url=jwks_url)
    return data


async def verify_clerk_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> dict:
    """FastAPI dependency — returns the decoded JWT claims on success."""
    settings = get_settings()

    # In development with no Clerk keys configured, skip verification
    if not settings.clerk_jwks_url:
        log.debug("clerk_jwt_skipped", reason="clerk_jwks_url not configured")
        return {"sub": "dev-user", "skip_auth": True}

    token = credentials.credentials
    try:
        jwks = await _fetch_jwks(settings.clerk_jwks_url)
        # PyJWT ≥2.4 can accept a JWKSet dict directly
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(
            next(k for k in jwks["keys"] if k.get("use") == "sig")
        )
        claims = jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            options={"verify_aud": False},   # Clerk JWTs have no aud by default
        )
    except StopIteration:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No signing key in JWKS")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    except Exception as exc:
        log.warning("jwt_verification_failed", error=str(exc))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token verification failed")

    return claims


# Convenience type alias used in router signatures
ClerkUser = Annotated[dict, Depends(verify_clerk_token)]
