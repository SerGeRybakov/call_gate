from datetime import timedelta

import uvicorn

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from call_gate import CallGate, ThrottlingError


app = FastAPI()

gate = CallGate(
    "fastapi_api",
    timedelta(seconds=10),
    timedelta(milliseconds=100),
    gate_limit=100,
    frame_limit=2,
    storage="shared",
)


@app.get("/ping")
async def ping() -> JSONResponse:
    await gate.update(throw=False)
    return JSONResponse({"ok": True, "sum": gate.sum})


@app.get("/limited")
async def limited() -> JSONResponse:
    async with gate(value=2, throw=True):
        return JSONResponse({"sum": gate.sum, "data": gate.data})


@app.exception_handler(ThrottlingError)
async def throttling_handler(request: Request, exc: ThrottlingError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=status.HTTP_429_TOO_MANY_REQUESTS)


if __name__ == "__main__":
    uvicorn.run("fastapi_server:app", host="0.0.0.0", port=8000, workers=4)
