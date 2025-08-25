import os
import json
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware  # NEW
import httpx
import uvicorn

# Load .env variables
load_dotenv()
USER_API = os.getenv("USER_API")
PROVIDER_API_KEY = os.getenv("PROVIDER_API_KEY")
PROVIDER_BASE_URL = os.getenv("PROVIDER_BASE_URL")  # e.g., https://api.navy/v1

# Files to store history and usage
HISTORY_FILE = "conversation_history.json"
USAGE_FILE = "usage.json"

# Load or initialize conversation history
if os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "r") as f:
        conversation_history = json.load(f)
else:
    conversation_history = {}

# Load or initialize usage data
if os.path.exists(USAGE_FILE):
    with open(USAGE_FILE, "r") as f:
        usage_data = json.load(f)
else:
    usage_data = {"total_tokens": 0}

print(f"API Key: {USER_API}")
print("API activated successfully ✅")

app = FastAPI(title="Local API Server")

# NEW: CORS — allow your dev origins (add prod origin later)
ALLOWED_ORIGINS = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://localhost:3000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,      # for quick dev: use ["*"]
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,            # you’re not using cookies
    max_age=86400
)

# Helper functions
def save_history():
    with open(HISTORY_FILE, "w") as f:
        json.dump(conversation_history, f, indent=4)

def save_usage():
    with open(USAGE_FILE, "w") as f:
        json.dump(usage_data, f, indent=4)

# Global error handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"Error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Contact the owner"}
    )

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "running"}

# Main local API endpoint
@app.post("/localAPI")
async def local_api(request: Request):
    try:
        data = await request.json()
        message = data.get("message", "")
        model = data.get("model", "gpt-4o")

        # Check Authorization header
        api_key = request.headers.get("Authorization")
        if api_key != f"Bearer {USER_API}":
            raise HTTPException(status_code=401, detail="Invalid API key")

        # Initialize history for this user if missing
        if USER_API not in conversation_history:
            conversation_history[USER_API] = []

        # Async request to provider API
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{PROVIDER_BASE_URL.rstrip('/')}/chat/completions",  # rstrip safety
                headers={
                    "Authorization": f"Bearer {PROVIDER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": message}]
                }
            )
            response.raise_for_status()
            result = response.json()

        # Extract reply and usage
        reply_text = result["choices"][0]["message"]["content"]
        usage = result.get("usage", {}).get("total_tokens", 0)
        usage_data["total_tokens"] += usage

        # Save conversation history
        conversation_history[USER_API].append({"role": "user", "message": message})
        conversation_history[USER_API].append({"role": "bot", "message": reply_text})

        # Persist data
        save_history()
        save_usage()

        return {"reply": reply_text, "usage": usage}

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in /localAPI: {e}")
        return {"error": "Contact the owner"}

# Endpoint to get conversation history
@app.get("/history")
async def get_history(api_key: str):
    try:
        if api_key != USER_API:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return {"conversation_history": conversation_history.get(USER_API, [])}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in /history: {e}")
        return {"error": "Contact the owner"}

# Endpoint to get usage
@app.get("/usage")
async def get_usage(api_key: str):
    try:
        if api_key != USER_API:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return {"usage": usage_data}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in /usage: {e}")
        return {"error": "Contact the owner"}

# Run server continuously (local dev)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
