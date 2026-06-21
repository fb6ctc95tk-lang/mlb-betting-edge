from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import games, health, odds, research, teams

app = FastAPI(title="MLB Betting Edge API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(games.router, prefix="/games", tags=["games"])
app.include_router(odds.router, prefix="/odds", tags=["odds"])
app.include_router(teams.router, prefix="/teams", tags=["teams"])
app.include_router(research.router, prefix="/research", tags=["research"])
app.include_router(health.router, prefix="/health", tags=["health"])


@app.get("/health")
def health():
    return {"status": "ok"}
