from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from app.database import get_db
from app.core.security import hash_password, verify_password, create_access_token, get_current_user
from app.core.config import settings
from bson import ObjectId
from datetime import datetime
import aiofiles, os, uuid
from PIL import Image
import io

router = APIRouter()

def serialize_user(u: dict) -> dict:
    u["id"] = str(u["_id"])
    del u["_id"]
    u.pop("password", None)
    return u

# ── REGISTER ──
class RegisterIn(BaseModel):
    name: str
    email: EmailStr
    password: str

@router.post("/register")
async def register(data: RegisterIn, db=Depends(get_db)):
    if len(data.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    if await db.users.find_one({"email": data.email.lower()}):
        raise HTTPException(400, "Email already registered")

    avatar_initials = "".join(w[0] for w in data.name.split())[:2].upper()
    user = {
        "name": data.name,
        "email": data.email.lower(),
        "password": hash_password(data.password),
        "role": "student",
        "balance": 500,
        "avatar_initials": avatar_initials,
        "avatar_url": None,
        "joined": datetime.utcnow().strftime("%Y-%m-%d"),
        "created_at": datetime.utcnow(),
    }
    result = await db.users.insert_one(user)
    uid = result.inserted_id

    # Welcome bonus transaction
    await db.transactions.insert_one({
        "type": "received", "from": "System", "to": data.name,
        "amount": 500, "note": "Welcome bonus 🎉",
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "user_id": uid, "created_at": datetime.utcnow()
    })

    user["_id"] = uid
    token = create_access_token({"sub": str(uid)})
    return {"token": token, "user": serialize_user(user)}

# ── LOGIN ──
class LoginIn(BaseModel):
    email: EmailStr
    password: str

@router.post("/login")
async def login(data: LoginIn, db=Depends(get_db)):
    user = await db.users.find_one({"email": data.email.lower()})
    if not user or not verify_password(data.password, user["password"]):
        raise HTTPException(401, "Invalid email or password")
    token = create_access_token({"sub": str(user["_id"])})
    return {"token": token, "user": serialize_user(user)}

# ── ME ──
@router.get("/me")
async def me(current_user=Depends(get_current_user)):
    return serialize_user(current_user)

# ── UPLOAD AVATAR ──
ALLOWED_IMG = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_SIZE_MB = 3

@router.post("/me/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    if file.content_type not in ALLOWED_IMG:
        raise HTTPException(400, "Only JPEG, PNG, WEBP, or GIF images allowed")

    contents = await file.read()
    if len(contents) > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"Image must be under {MAX_SIZE_MB}MB")

    # Resize & crop to 200x200 square using Pillow
    img = Image.open(io.BytesIO(contents)).convert("RGB")
    min_side = min(img.width, img.height)
    left = (img.width - min_side) // 2
    top = (img.height - min_side) // 2
    img = img.crop((left, top, left + min_side, top + min_side))
    img = img.resize((200, 200), Image.LANCZOS)

    ext = "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(settings.UPLOAD_DIR, "avatars", filename)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    async with aiofiles.open(path, "wb") as f:
        await f.write(buf.getvalue())

    avatar_url = f"/uploads/avatars/{filename}"

    # Delete old avatar file if exists
    old_url = current_user.get("avatar_url")
    if old_url:
        old_path = old_url.lstrip("/")
        if os.path.exists(old_path):
            os.remove(old_path)

    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"avatar_url": avatar_url}}
    )
    return {"avatar_url": avatar_url}

# ── DELETE AVATAR ──
@router.delete("/me/avatar")
async def delete_avatar(current_user=Depends(get_current_user), db=Depends(get_db)):
    old_url = current_user.get("avatar_url")
    if old_url:
        old_path = old_url.lstrip("/")
        if os.path.exists(old_path):
            os.remove(old_path)
    await db.users.update_one({"_id": current_user["_id"]}, {"$set": {"avatar_url": None}})
    return {"message": "Avatar removed"}

# ── UPDATE PROFILE ──
class ProfileUpdate(BaseModel):
    name: str | None = None
    password: str | None = None

@router.patch("/me")
async def update_profile(data: ProfileUpdate, current_user=Depends(get_current_user), db=Depends(get_db)):
    updates = {}
    if data.name:
        updates["name"] = data.name
        updates["avatar_initials"] = "".join(w[0] for w in data.name.split())[:2].upper()
    if data.password:
        if len(data.password) < 6:
            raise HTTPException(400, "Password must be at least 6 characters")
        updates["password"] = hash_password(data.password)
    if updates:
        await db.users.update_one({"_id": current_user["_id"]}, {"$set": updates})
    updated = await db.users.find_one({"_id": current_user["_id"]})
    return serialize_user(updated)