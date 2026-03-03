from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.database import get_db
from app.core.security import get_current_user
from bson import ObjectId
from datetime import datetime

router = APIRouter()

def serialize_tx(t):
    t["id"] = str(t["_id"])
    del t["_id"]
    t["user_id"] = str(t.get("user_id", ""))
    return t

# ── GET BALANCE ──
@router.get("/balance")
async def get_balance(current_user=Depends(get_current_user)):
    return {"balance": current_user["balance"]}

# ── SEND COINS ──
class SendIn(BaseModel):
    to_user_id: str
    amount: int
    note: str = ""

@router.post("/send")
async def send_coins(data: SendIn, current_user=Depends(get_current_user), db=Depends(get_db)):
    if data.amount <= 0:
        raise HTTPException(400, "Amount must be greater than 0")
    if data.amount > current_user["balance"]:
        raise HTTPException(400, "Insufficient PesaCoin balance")

    recipient = await db.users.find_one({"_id": ObjectId(data.to_user_id)})
    if not recipient:
        raise HTTPException(404, "Recipient not found")
    if str(recipient["_id"]) == str(current_user["_id"]):
        raise HTTPException(400, "Cannot send to yourself")

    now = datetime.utcnow()
    date_str = now.strftime("%Y-%m-%d")

    # Atomic balance updates
    await db.users.update_one({"_id": current_user["_id"]}, {"$inc": {"balance": -data.amount}})
    await db.users.update_one({"_id": recipient["_id"]}, {"$inc": {"balance": data.amount}})

    # Transactions for both parties
    await db.transactions.insert_many([
        {
            "type": "sent", "from": current_user["name"], "to": recipient["name"],
            "amount": data.amount, "note": data.note or f"Sent to {recipient['name']}",
            "date": date_str, "user_id": current_user["_id"], "created_at": now
        },
        {
            "type": "received", "from": current_user["name"], "to": recipient["name"],
            "amount": data.amount, "note": data.note or f"From {current_user['name']}",
            "date": date_str, "user_id": recipient["_id"], "created_at": now
        }
    ])

    updated = await db.users.find_one({"_id": current_user["_id"]})
    return {"message": f"Sent {data.amount} PC to {recipient['name']}", "new_balance": updated["balance"]}

# ── GET TRANSACTIONS ──
@router.get("/transactions")
async def get_transactions(
    limit: int = 50,
    skip: int = 0,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    cursor = db.transactions.find(
        {"user_id": current_user["_id"]}
    ).sort("created_at", -1).skip(skip).limit(limit)
    txs = await cursor.to_list(limit)
    return [serialize_tx(t) for t in txs]

# ── WALLET ADDRESS ──
@router.get("/address")
async def get_wallet_address(current_user=Depends(get_current_user)):
    uid = str(current_user["_id"])[-6:].upper()
    initials = current_user["avatar_initials"]
    address = f"PC-{uid}-{initials}"
    return {"address": address}

# ── LIST USERS (for send dropdown) ──
@router.get("/users")
async def list_users(current_user=Depends(get_current_user), db=Depends(get_db)):
    cursor = db.users.find(
        {"_id": {"$ne": current_user["_id"]}, "role": {"$ne": "admin"}},
        {"name": 1, "balance": 1, "avatar_initials": 1, "avatar_url": 1}
    )
    users = await cursor.to_list(200)
    return [{"id": str(u["_id"]), "name": u["name"], "balance": u["balance"],
             "avatar_initials": u.get("avatar_initials", "??"),
             "avatar_url": u.get("avatar_url")} for u in users]