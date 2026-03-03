from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os

from app.database import connect_db, close_db
from app.core.config import settings
from app.routes import auth, wallet, materials, admin

@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    os.makedirs(f"{settings.UPLOAD_DIR}/avatars", exist_ok=True)
    os.makedirs(f"{settings.UPLOAD_DIR}/materials", exist_ok=True)
    yield
    await close_db()

app = FastAPI(title="PesaCoin API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(wallet.router, prefix="/wallet", tags=["Wallet"])
app.include_router(materials.router, prefix="/materials", tags=["Materials"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])

@app.get("/")
async def root():
    return {"message": "PesaCoin API v2.0", "status": "running"}

@app.get("/health")
async def health():
    return {"status": "ok"}
