from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

client: AsyncIOMotorClient = None

async def connect_db():
    global client
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.DB_NAME]
    # Indexes
    await db.users.create_index("email", unique=True)
    await db.materials.create_index("status")
    await db.transactions.create_index("user_id")
    print(f"✅ Connected to MongoDB: {settings.DB_NAME}")

async def close_db():
    global client
    if client:
        client.close()

async def get_db():
    return client[settings.DB_NAME]