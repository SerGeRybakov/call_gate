from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI, HTTPException

from call_gate import GateStorageType
from tests.parameters import create_call_gate


# Use fixed gate name so all workers share the same distributed gate
gate = create_call_gate(
    "asgi_shared_gate",
    timedelta(seconds=2),
    timedelta(milliseconds=100),
    gate_limit=10,
    frame_limit=4,
    storage=GateStorageType.redis,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Don't clear gate at startup - let workers share the distributed state
    try:
        yield
    finally:
        # Only clear at shutdown to clean up
        await gate.clear()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    try:
        await gate.update(throw=True)
        return {"message": "Hello, World!"}
    except Exception:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")  # noqa: B904
