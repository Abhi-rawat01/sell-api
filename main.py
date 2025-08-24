from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os
import requests
import json

# Load .env
load_dotenv()
USER_API = os.getenv("USER_API")
PROVIDER_API_KEY = os.getenv("PROVIDER_API_KEY")
PROVIDER_BASE_URL = os.getenv("PROVIDER_BASE_URL")  # e.g., https://api.navy/v1
BASE_URL = "http://127.0.0.1:8000/localAPI"

HISTORY_FILE = "conversation_history.json"
USAGE_FILE = "usage.json"

# Load conversation history
if os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "r") as f:
        conversation_history = json.load(f)
else:
    conversation_history = {}

# Load token usage
if os.path.exists(USAGE_FILE):
    with open(USAGE_FILE, "r") as f:
        usage_data = json.load(f)
else:
    usage_data = {"total_tokens": 0}

print(f"API : {USER_API}")
print(f"Base URL: {BASE_URL}")
print("API activated successfully ✅")

app = FastAPI(title="Local API Server")

# Helpers
def save_history():
    with open(HISTORY_FILE, "w") as f:
        json.dump(conversation_history, f, indent=4)

def save_usage():
    with open(USAGE_FILE, "w") as f:
        json.dump(usage_data, f, indent=4)

# Global error handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": "Contact the owner"}
    )

@app.post("/localAPI")
async def local_api(request: Request):
    try:
        data = await request.json()
        message = data.get("message", "")
        model = data.get("model", "gpt-4o")

        # Local auth
        api_key = request.headers.get("Authorization")
        if api_key != f"Bearer {USER_API}":
            raise HTTPException(status_code=401, detail="Invalid API key")

        # Initialize history if not exists
        if USER_API not in conversation_history:
            conversation_history[USER_API] = []

        # Forward to provider API
        response = requests.post(
            f"{PROVIDER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {PROVIDER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": message}]
            },
            timeout=30
        )
        response.raise_for_status()
        result = response.json()

        # Extract reply & token usage
        reply_text = result["choices"][0]["message"]["content"]
        usage = result.get("usage", {}).get("total_tokens", 0)
        usage_data["total_tokens"] += usage

        # Save conversation
        conversation_history[USER_API].append({"role": "user", "message": message})
        conversation_history[USER_API].append({"role": "bot", "message": reply_text})

        # Persist
        save_history()
        save_usage()

        return {"reply": reply_text}

    except Exception:
        return {"error": "Contact the owner"}

@app.get("/history")
async def get_history(api_key: str):
    try:
        if api_key != USER_API:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return {"conversation_history": conversation_history.get(USER_API, [])}
    except Exception:
        return {"error": "Contact the owner"}

@app.get("/usage")
async def get_usage(api_key: str):
    try:
        if api_key != USER_API:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return {"usage": usage_data}
    except Exception:
        return {"error": "Contact the owner"}
