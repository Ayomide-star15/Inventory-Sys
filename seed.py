import asyncio
from app.core.database import init_db
from app.models.user import User, UserRole
from app.core.security import get_password_hash
from app.core.config import settings

async def seed_data():
    print(f"🌱 Connecting to Remote DB: {settings.DATABASE_NAME}...")
    await init_db()
    
    # 1. Get Credentials from .env
    admin_email = settings.ADMIN_EMAIL_1 or "admin@supermarket.com"
    admin_pass = settings.ADMIN_PASSWORD_1 or "admin123"
    
    # 2. Check if Admin already exists
    existing_admin = await User.find_one(User.email == admin_email)
    
    if existing_admin:
        print(f"⚠️  Admin '{admin_email}' already exists.")
        # Optional: Delete to force update password
        await existing_admin.delete() 
        print("🗑️  Old Admin deleted (Re-creating with new settings...)")
    
    # 3. Create New Admin
    admin_user = User(
        email=admin_email,
        first_name="System",
        last_name="Admin",
        hashed_password=get_password_hash(admin_pass),
        role=UserRole.ADMIN,
        is_active=True
    )
    
    await admin_user.insert()
    
    print("\n✅ SUCCESS! Admin User Created.")
    print("------------------------------------------")
    print(f"📧 Username: {admin_email}")
    print(f"🔑 Password: {admin_pass}")
    print("------------------------------------------")
    print("👉 Now restart your server and login with THESE credentials.")

if __name__ == "__main__":
    asyncio.run(seed_data())