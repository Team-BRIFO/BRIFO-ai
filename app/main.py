from fastapi import FastAPI

from app.api import briefing, health, news

app = FastAPI()

app.include_router(health.router)
app.include_router(briefing.router)
app.include_router(news.router)