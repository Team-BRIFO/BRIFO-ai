from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import briefing, health, news
from app.exceptions import (
    BrifoAIException,
    InvalidFieldType,
    InvalidJsonBody,
    InvalidRequest,
    MissingRequiredField,
)
from app.infra.http_client import close_openrouter_client, init_openrouter_client
from app.infra.redis_client import close_redis_client, init_redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_openrouter_client()
        init_redis_client()
        yield
    finally:
        await close_redis_client()
        await close_openrouter_client()


app = FastAPI(lifespan=lifespan)

app.include_router(health.router)
app.include_router(briefing.router)
app.include_router(news.router)


@app.exception_handler(BrifoAIException)
async def brifo_ai_exception_handler(
    request: Request, exc: BrifoAIException
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"isSuccess": False, "code": exc.code, "message": exc.message},
    )


def _field_path(loc: tuple) -> str:
    """loc == ("body", "excludeTerms") -> "excludeTerms" 처럼 body/query/path 접두사를 뗀 필드 경로를 만든다."""
    parts = loc[1:] if len(loc) > 1 else loc
    return ".".join(str(part) for part in parts)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    fallback: BrifoAIException = InvalidRequest()

    if errors:
        error_type = errors[0].get("type", "")

        if error_type == "json_invalid":
            detail = errors[0].get("ctx", {}).get("error")
            message = "요청 본문이 올바른 JSON 형식이 아닙니다."
            if detail:
                message += f" ({detail})"
            fallback = InvalidJsonBody(message)
        elif error_type == "missing":
            fields = [_field_path(e["loc"]) for e in errors if e.get("type") == "missing"]
            fallback = MissingRequiredField(
                f"필수 필드가 누락되었습니다: {', '.join(fields)}"
            )
        elif error_type.endswith("_type") or error_type.endswith("_parsing"):
            field = _field_path(errors[0]["loc"])
            expected = error_type.removesuffix("_type").removesuffix("_parsing")
            fallback = InvalidFieldType(
                f"'{field}' 필드의 타입이 올바르지 않습니다. ({expected} 타입이어야 합니다.)"
            )

    return JSONResponse(
        status_code=fallback.status_code,
        content={
            "isSuccess": False,
            "code": fallback.code,
            "message": fallback.message,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    fallback = BrifoAIException()
    return JSONResponse(
        status_code=fallback.status_code,
        content={
            "isSuccess": False,
            "code": fallback.code,
            "message": fallback.message,
        },
    )
