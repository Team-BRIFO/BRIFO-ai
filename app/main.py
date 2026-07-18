from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import briefing, health, news
from app.exceptions import BrifoAIException, InvalidRequest
from app.infra.http_client import close_openrouter_client, init_openrouter_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_openrouter_client()
    try:
        yield
    finally:
        await close_openrouter_client()


app = FastAPI(lifespan=lifespan)

app.include_router(health.router)
app.include_router(briefing.router)
app.include_router(news.router)


@app.exception_handler(BrifoAIException)
async def brifo_ai_exception_handler(request: Request, exc: BrifoAIException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"isSuccess": False, "code": exc.code, "message": exc.message},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    fallback = InvalidRequest()
    return JSONResponse(
        status_code=fallback.status_code,
        content={"isSuccess": False, "code": fallback.code, "message": fallback.message},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    fallback = BrifoAIException()
    return JSONResponse(
        status_code=fallback.status_code,
        content={"isSuccess": False, "code": fallback.code, "message": fallback.message},
    )