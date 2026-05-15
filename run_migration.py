"""
ONE-TIME MIGRATION SCRIPT
Run this ONCE to reassign all "Store Staff" users to "Sales Staff".
Then delete this file.

Usage:
    python run_migration.py

What it does:
    - Finds every user in MongoDB with role = "Store Staff"
    - Reassigns them to "Sales Staff" (closest equivalent)
    - Prints a report of every user changed
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

# ── paste your values here if .env isn't loading ──────────────
MONGODB_URL = None   # e.g. "mongodb://localhost:27017"  — leave None to use .env
DATABASE_NAME = None # e.g. "supermarket_db"             — leave None to use .env
# ──────────────────────────────────────────────────────────────


async def migrate():
    # Load from .env if not hardcoded above
    if MONGODB_URL is None or DATABASE_NAME is None:
        import sys, os
        sys.path.insert(0, os.path.dirname(__file__))
        from app.core.config import settings
        mongo_url = settings.MONGODB_URL
        db_name   = settings.DATABASE_NAME
    else:
        mongo_url = MONGODB_URL
        db_name   = DATABASE_NAME

    print(f"Connecting to: {mongo_url} / {db_name}")
    client = AsyncIOMotorClient(mongo_url)
    db     = client[db_name]
    users  = db["users"]

    # ── 1. Find all Store Staff documents ─────────────────────
    cursor      = users.find({"role": "Store Staff"})
    found_users = await cursor.to_list(length=None)

    if not found_users:
        print("✅ No 'Store Staff' users found. Database is already clean.")
        client.close()
        return

    print(f"\n Found {len(found_users)} 'Store Staff' user(s):\n")
    for u in found_users:
        email = u.get("email", "unknown")
        name  = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
        print(f"   • {name} <{email}>")

    # ── 2. Reassign all of them to "Store Manager" ──────────────
    result = await users.update_many(
        {"role": "Store Staff"},
        {"$set": {"role": "Store Manager"}}
    )

    print(f"\n✅ Updated {result.modified_count} user(s): 'Store Staff' → 'Store Manager'")

    # ── 3. Verify no Store Staff remain ───────────────────────
    remaining = await users.count_documents({"role": "Store Staff"})
    if remaining == 0:
        print("✅ Verified: zero 'Store Staff' documents remain in the database.")
    else:
        print(f"⚠️  WARNING: {remaining} document(s) still have role 'Store Staff'. Run again.")

    client.close()
    print("\nDone. You can delete this file now.")


if __name__ == "__main__":
    asyncio.run(migrate())