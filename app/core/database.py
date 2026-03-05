from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.core.config import settings
from app.models.user import User
from app.models.branch import Branch
from app.models.category import Category
from app.models.product import Product
from app.models.supplier import Supplier
from app.models.purchase_order import PurchaseOrder
from app.models.inventory import Inventory, AdjustmentLog
from app.models.stock_transfer import StockTransfer
from app.models.sale import Sale
from app.models.price_history import PriceHistory  # ← ADD THIS

async def init_db():
    """Connect to MongoDB and initialize Beanie"""
    
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    
    await init_beanie(
        database=client[settings.DATABASE_NAME], # type: ignore
        document_models=[
            User, 
            Branch, 
            Category, 
            Product, 
            Supplier, 
            PurchaseOrder, 
            Inventory, 
            AdjustmentLog, 
            StockTransfer, 
            Sale,
            PriceHistory  # ← ADD THIS
        ]
    )
    
    print(f"✅ Beanie Initialized with database: {settings.DATABASE_NAME}")