from fastapi import FastAPI
from app.config import settings
from app.database import engine, Base
from app.routes import router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="API Key Manager")
app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
