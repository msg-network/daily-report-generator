from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from routers import generate, parse

app = FastAPI(title="Daily Report Generator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(parse.router, prefix="/api")
app.include_router(generate.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Lambda handler
handler = Mangum(app, lifespan="off")
