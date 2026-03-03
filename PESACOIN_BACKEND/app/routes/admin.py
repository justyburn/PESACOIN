from fastapi import APIRouter, Depends, HTTPException
from app.database import get_db
from app.core.security import require_admin
from bson import ObjectId
from pydantic import BaseModel

router = APIRouter()

def serialize(doc):
    doc["id"] = str(doc["_id"])
    del doc["_id"]
    for k in ["seller_id", "user_id"]:
        if k in doc:
            doc[k] = str(doc[k])
    return doc

# ── STATS ──
@router.get("/stats")
async def stats(current_user=Depends(require_admin), db=Depends(get_db)):
    return {
        "total_users": await db.users.count_documents({}),
        "total_materials": await db.materials.count_documents({}),
        "pending": await db.materials.count_documents({"status": "pending"}),
        "approved": await db.materials.count_documents({"status": "approved"}),
        "total_transactions": await db.transactions.count_documents({}),
    }

# ── PENDING MATERIALS ──
@router.get("/materials/pending")
async def pending_materials(current_user=Depends(require_admin), db=Depends(get_db)):
    mats = await db.materials.find({"status": "pending"}).sort("created_at", -1).to_list(100)
    return [serialize(m) for m in mats]

# ── ALL MATERIALS ──
@router.get("/materials")
async def all_materials(current_user=Depends(require_admin), db=Depends(get_db)):
    mats = await db.materials.find({}).sort("created_at", -1).to_list(500)
    return [serialize(m) for m in mats]

# ── APPROVE ──
@router.patch("/materials/{mat_id}/approve")
async def approve(mat_id: str, current_user=Depends(require_admin), db=Depends(get_db)):
    res = await db.materials.update_one({"_id": ObjectId(mat_id)}, {"$set": {"status": "approved"}})
    if res.modified_count == 0:
        raise HTTPException(404, "Material not found")
    return {"message": "Approved"}

# ── REJECT ──
@router.patch("/materials/{mat_id}/reject")
async def reject(mat_id: str, current_user=Depends(require_admin), db=Depends(get_db)):
    res = await db.materials.update_one({"_id": ObjectId(mat_id)}, {"$set": {"status": "rejected"}})
    if res.modified_count == 0:
        raise HTTPException(404, "Material not found")
    return {"message": "Rejected"}

# ── ALL USERS ──
@router.get("/users")
async def all_users(current_user=Depends(require_admin), db=Depends(get_db)):
    users = await db.users.find({}, {"password": 0}).to_list(500)
    return [serialize(u) for u in users]

# ── ADJUST BALANCE ──
class BalanceAdjust(BaseModel):
    amount: int
    note: str = "Admin adjustment"

@router.patch("/users/{user_id}/balance")
async def adjust_balance(user_id: str, data: BalanceAdjust, current_user=Depends(require_admin), db=Depends(get_db)):
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(404, "User not found")
    new_bal = user["balance"] + data.amount
    if new_bal < 0:
        raise HTTPException(400, "Balance cannot go negative")
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"balance": new_bal}})
    return {"message": "Balance adjusted", "new_balance": new_bal}