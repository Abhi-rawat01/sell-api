import os
import json
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import uvicorn

# Load .env variables
load_dotenv()
USER_API = os.getenv("USER_API", "")
PROVIDER_API_KEY = os.getenv("PROVIDER_API_KEY", "")
PROVIDER_BASE_URL = (os.getenv("PROVIDER_BASE_URL", "") or "").rstrip("/")  # e.g., https://api.openai.com/v1
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*")  # e.g., "http://localhost:5173,https://yourdomain.com"

# Files to store history and usage
HISTORY_FILE = "conversation_history.json"
USAGE_FILE = "usage.json"

def _load_json(path: str, fallback):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Failed to read {path}: {e}")
    return fallback

conversation_history = _load_json(HISTORY_FILE, {})
usage_data = _load_json(USAGE_FILE, {"total_tokens": 0})

print(f"USER_API: {'set' if USER_API else 'missing'}")
print("API activated successfully ✅")

app = FastAPI(title="Local API Server")

# CORS
origins = ["*"] if ALLOWED_ORIGINS == "*" else [o.strip() for o in ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,  # keep False if using "*" origins
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

# Helpers
def save_history():
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(conversation_history, f, indent=4)
    except Exception as e:
        print(f"Error saving history: {e}")

def save_usage():
    try:
        with open(USAGE_FILE, "w") as f:
            json.dump(usage_data, f, indent=4)
    except Exception as e:
        print(f"Error saving usage: {e}")

def bearer_from_header(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        return auth.split(" ", 1)[1].strip()
    return None

def extract_api_key(request: Request, api_key_qs: Optional[str]) -> Optional[str]:
    # Prefer header, fallback to query param for compatibility
    return bearer_from_header(request) or api_key_qs

# Global error handler (doesn't override FastAPI's built-in HTTPException handler)
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"Unhandled error: {exc}")
    return JSONResponse(status_code=500, content={"error": "Contact the owner"})

# Health check
@app.get("/health")
async def health_check():
    return {"status": "running"}

# Main local API endpoint
@app.post("/localAPI")
async def local_api(request: Request):
    # Validate server config
    if not USER_API:
        raise HTTPException(status_code=500, detail="Server missing USER_API")
    if not PROVIDER_API_KEY or not PROVIDER_BASE_URL:
        raise HTTPException(status_code=500, detail="Provider not configured")

    data = await request.json()
    message = data.get("message", "")
    model = data.get("model", "gpt-4o")

    # Check Authorization header
    key = bearer_from_header(request)
    if key != USER_API:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Initialize history for this user if missing
    if USER_API not in conversation_history:
        conversation_history[USER_API] = []

    # Async request to provider API
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(
                f"{PROVIDER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {PROVIDER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": message}],
                },
            )
            response.raise_for_status()
            result = response.json()
    except httpx.ReadTimeout:
        raise HTTPException(status_code=504, detail="Upstream provider timeout")
    except httpx.HTTPError as e:
        print(f"Provider HTTP error: {e}")
        raise HTTPException(status_code=502, detail="Upstream provider error")

    # Extract reply and usage across common shapes
    reply_text = (
        result.get("choices", [{}])[0].get("message", {}).get("content")
        or result.get("choices", [{}])[0].get("text")
        or ""
    )
    used_tokens = (
        result.get("usage", {}).get("total_tokens")
        or result.get("usage", {}).get("total")
        or 0
    )

    # Save conversation history
    conversation_history[USER_API].append({"role": "user", "message": message})
    conversation_history[USER_API].append({"role": "bot", "message": reply_text})
    usage_data["total_tokens"] = int(usage_data.get("total_tokens", 0)) + int(used_tokens or 0)

    # Persist data
    save_history()
    save_usage()

    return {"reply": reply_text, "usage": used_tokens}

# Conversation history
@app.get("/history")
async def get_history(request: Request, api_key: Optional[str] = None):
    try:
        key = extract_api_key(request, api_key)
        if key != USER_API:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return {"conversation_history": conversation_history.get(USER_API, [])}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in /history: {e}")
        raise HTTPException(status_code=500, detail="Contact the owner")

# Usage
@app.get("/usage")
async def get_usage(request: Request, api_key: Optional[str] = None):
    try:
        key = extract_api_key(request, api_key)
        if key != USER_API:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return {"usage": usage_data}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in /usage: {e}")
        raise HTTPException(status_code=500, detail="Contact the owner")

# Run server
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
