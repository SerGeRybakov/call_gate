from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI, HTTPException

from call_gate import CallGate, GateStorageType


gate = CallGate(
    "api_gate",
    timedelta(seconds=2),
    timedelta(milliseconds=100),
    gate_limit=10,
    frame_limit=4,
    storage=GateStorageType.redis,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await gate.clear()
    try:
        yield
    finally:
        await gate.clear()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    try:
        await gate.update(throw=True)
        return {"message": "Hello, World!"}
    except Exception:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")  # noqa: B904
