from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.core.config import settings
# Fixed Import: Point directly to the file, not just the folder
from app.models.user import User
from app.models.branch import Branch  # <--- IMPORT THIS
from app.models.category import Category
from app.models.product import Product
from app.models.supplier import Supplier  # <--- IMPORT THIS
from app.models.purchase_order import PurchaseOrder
from app.models.inventory import Inventory  # <--- IMPORT THIS
async def init_db():
    """Connect to MongoDB and initialize Beanie"""
    
    # Create the client
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    
    # Initialize Beanie
    # Uses settings.DATABASE_NAME (synchronized with config.py)
    await init_beanie(
        database=client[settings.DATABASE_NAME],
        document_models=[User, Branch, Category, Product, Supplier, PurchaseOrder, Inventory]  # <--- 2. ADD THIS TO THE LIST
    )
    
    print(f"✅ Beanie Initialized with database: {settings.DATABASE_NAME}")