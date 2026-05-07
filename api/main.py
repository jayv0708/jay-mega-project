from fastapi import FastAPI

app = FastAPI(title="Jay Mega Project API", version="0.1.0")

@app.get("/")
async def health_check():
    return {"status": "ok", "service": "api"}

@app.get("/ready")
async def ready():
    return {"status": "ready", "db": "pending"}
