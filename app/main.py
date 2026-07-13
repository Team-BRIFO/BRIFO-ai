from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import briefing, health, news
from app.exceptions import BrifoAIException

app = FastAPI()

app.include_router(health.router)
app.include_router(briefing.router)
app.include_router(news.router)


@app.exception_handler(BrifoAIException)
async def brifo_ai_exception_handler(request: Request, exc: BrifoAIException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"isSuccess": False, "code": exc.code, "message": exc.message},
    )