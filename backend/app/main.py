from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import athletes, organisations, logs

app = FastAPI(
    title="Valory Athlete-Organisation Resolution API",
    description="Ingests athlete JSON and resolves sponsor/training org "
    "names against existing organisations to prevent duplicates.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # minimal frontend, no auth — fine for this assignment
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(athletes.router)
app.include_router(organisations.router)
app.include_router(logs.router)


@app.get("/")
def health():
    return {"status": "ok", "service": "valory-resolution-pipeline"}
