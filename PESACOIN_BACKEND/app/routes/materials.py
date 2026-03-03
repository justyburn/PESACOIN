from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from app.database import get_db
from app.core.security import get_current_user
from app.core.config import settings
from bson import ObjectId
from datetime import datetime
import aiofiles, os, uuid

router = APIRouter()

ALLOWED_FILES = {
    "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

def serialize_mat(m):
    m["id"] = str(m["_id"])
    del m["_id"]
    if "seller_id" in m:
        m["seller_id"] = str(m["seller_id"])
    return m

# ── LIST APPROVED ──
@router.get("/")
async def list_materials(
    category: str = None,
    search: str = None,
    skip: int = 0,
    limit: int = 50,
    db=Depends(get_db)
):
    query = {"status": "approved"}
    if category and category != "All":
        query["category"] = category
    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"seller": {"$regex": search, "$options": "i"}},
        ]
    cursor = db.materials.find(query).sort("upload_date", -1).skip(skip).limit(limit)
    mats = await cursor.to_list(limit)
    return [serialize_mat(m) for m in mats]

# ── UPLOAD MATERIAL ──
@router.post("/upload")
async def upload_material(
    title: str = Form(...),
    category: str = Form(...),
    price: int = Form(...),
    description: str = Form(...),
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    if price < 1:
        raise HTTPException(400, "Price must be at least 1 PC")
    if file.content_type not in ALLOWED_FILES:
        raise HTTPException(400, "Only PDF, DOCX, PPTX files allowed")

    contents = await file.read()
    if len(contents) > 50 * 1024 * 1024:
        raise HTTPException(400, "File must be under 50MB")

    ext = file.filename.rsplit(".", 1)[-1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(settings.UPLOAD_DIR, "materials", filename)

    async with aiofiles.open(path, "wb") as f:
        await f.write(contents)

    mat = {
        "title": title, "seller": current_user["name"],
        "seller_id": current_user["_id"],
        "price": price, "category": category,
        "description": description,
        "status": "pending", "downloads": 0,
        "file_url": f"/uploads/materials/{filename}",
        "original_filename": file.filename,
        "upload_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "created_at": datetime.utcnow()
    }
    result = await db.materials.insert_one(mat)
    mat["_id"] = result.inserted_id
    return serialize_mat(mat)

# ── BUY MATERIAL ──
@router.post("/{mat_id}/buy")
async def buy_material(mat_id: str, current_user=Depends(get_current_user), db=Depends(get_db)):
    mat = await db.materials.find_one({"_id": ObjectId(mat_id), "status": "approved"})
    if not mat:
        raise HTTPException(404, "Material not found")
    if str(mat["seller_id"]) == str(current_user["_id"]):
        raise HTTPException(400, "Cannot buy your own material")

    # Check library
    owned = await db.libraries.find_one({"user_id": current_user["_id"], "material_id": mat["_id"]})
    if owned:
        raise HTTPException(400, "Already in your library")

    if current_user["balance"] < mat["price"]:
        raise HTTPException(400, "Insufficient PesaCoin balance")

    seller = await db.users.find_one({"_id": mat["seller_id"]})
    now = datetime.utcnow()
    date_str = now.strftime("%Y-%m-%d")

    await db.users.update_one({"_id": current_user["_id"]}, {"$inc": {"balance": -mat["price"]}})
    if seller:
        await db.users.update_one({"_id": seller["_id"]}, {"$inc": {"balance": mat["price"]}})
    await db.materials.update_one({"_id": mat["_id"]}, {"$inc": {"downloads": 1}})
    await db.libraries.insert_one({"user_id": current_user["_id"], "material_id": mat["_id"], "purchased_at": now})

    await db.transactions.insert_many([
        {"type": "purchase", "from": current_user["name"], "to": mat["seller"],
         "amount": mat["price"], "note": f"Bought: {mat['title']}",
         "date": date_str, "user_id": current_user["_id"], "created_at": now},
        *([ {"type": "received", "from": current_user["name"], "to": seller["name"],
             "amount": mat["price"], "note": f"Sale: {mat['title']}",
             "date": date_str, "user_id": seller["_id"], "created_at": now}] if seller else [])
    ])

    updated = await db.users.find_one({"_id": current_user["_id"]})
    return {"message": f"Purchased '{mat['title']}'", "new_balance": updated["balance"]}

# ── MY LIBRARY ──
@router.get("/library")
async def my_library(current_user=Depends(get_current_user), db=Depends(get_db)):
    lib_entries = await db.libraries.find({"user_id": current_user["_id"]}).to_list(200)
    mat_ids = [e["material_id"] for e in lib_entries]
    mats = await db.materials.find({"_id": {"$in": mat_ids}}).to_list(200)
    return [serialize_mat(m) for m in mats]

# ── MY UPLOADS ──
@router.get("/my-uploads")
async def my_uploads(current_user=Depends(get_current_user), db=Depends(get_db)):
    cursor = db.materials.find({"seller_id": current_user["_id"]}).sort("created_at", -1)
    mats = await cursor.to_list(200)
    return [serialize_mat(m) for m in mats]