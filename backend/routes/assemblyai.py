"""AssemblyAI realtime token generation route.

The frontend needs a short-lived token to connect directly to AssemblyAI's
v3 streaming WebSocket without exposing the server-side API key.

The backend mints a temporary token using the server-side API key via
AssemblyAI's token generation endpoint, then returns only that temporary
token to the browser.
"""

import httpx
from fastapi import APIRouter, HTTPException, Request, status

from backend.config import get_settings

router = APIRouter(prefix="/assemblyai", tags=["assemblyai"])

# AssemblyAI v3 streaming token endpoint
ASSEMBLYAI_V3_TOKEN_URL = "https://streaming.assemblyai.com/v3/token"


@router.post("/token", status_code=status.HTTP_200_OK)
async def get_realtime_token(request: Request) -> dict:
    """Generate a temporary AssemblyAI streaming token for the frontend.

    Calls AssemblyAI's v3 token generation endpoint with the server-side API key,
    returns the short-lived token to the browser.
    """
    settings = get_settings()
    api_key = settings.assemblyai_api_key

    if not api_key or not api_key.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ASSEMBLYAI_NOT_CONFIGURED",
                "message": "AssemblyAI API key is not configured on the backend.",
            },
        )

    # Call AssemblyAI's v3 token generation endpoint (GET with expires_in_seconds)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{ASSEMBLYAI_V3_TOKEN_URL}?expires_in_seconds=60",
            headers={"Authorization": api_key.get_secret_value()},
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "ASSEMBLYAI_TOKEN_FAILED",
                "message": "Failed to generate AssemblyAI streaming token.",
                "detail": response.text,
            },
        )

    data = response.json()
    # AssemblyAI v3 returns: {"token": "...", "expires_in": 60}
    return {"token": data["token"], "expires_in": data.get("expires_in", 60)}