# migrate_audit_logs.py
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

async def migrate():
    print("🔌 Connecting to database...")
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.DATABASE_NAME]
    collection = db["audit_logs"]

    migrations = [
        ("PO_CREATED",  "PURCHASE_ORDER_CREATED"),
        ("PO_APPROVED", "PURCHASE_ORDER_APPROVED"),
        ("PO_REJECTED", "PURCHASE_ORDER_REJECTED"),
        ("PO_RECEIVED", "PURCHASE_ORDER_RECEIVED"),
    ]

    total_updated = 0

    for old_value, new_value in migrations:
        result = await collection.update_many(
            {"action": old_value},
            {"$set": {"action": new_value}}
        )
        count = result.modified_count
        total_updated += count
        if count > 0:
            print(f"  ✅ '{old_value}' → '{new_value}': {count} record(s) updated")
        else:
            print(f"  ⚪ '{old_value}': no records found (already clean)")

    print(f"\n✅ Migration complete. Total records updated: {total_updated}")
    client.close()

if __name__ == "__main__":
    asyncio.run(migrate())