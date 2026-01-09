import asyncio
from app.core.database import init_db
from app.models.user import User

async def reset_users():
    print("🧹 connecting to database...")
    await init_db()
    
    print("🔥 Deleting ALL users...")
    # This wipes every single user document, clearing the corrupted ObjectIds
    await User.delete_all()
    
    print("✅ Database is clean! You can now run 'python seed.py'.")

if __name__ == "__main__":
    asyncio.run(reset_users())