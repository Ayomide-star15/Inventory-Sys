from beanie import Document
from pydantic import Field
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime

class Product(Document):
    id: UUID = Field(default_factory=uuid4)
    
    # --- Identification ---
    name: str = Field(...)
    sku: str = Field(..., unique=True)      # Internal Stock Code
    barcode: str = Field(..., unique=True)  # Scanning Barcode
    description: Optional[str] = None
    
    # --- Financials ---
    price: float = Field(..., gt=0)       # Selling Price (Retail)
    cost_price: float = Field(..., gt=0)  # Buying Price (For Profit Reports)
    
    low_stock_threshold: int = Field(default=10) # Alert Trigger Level
    
    # --- Category Link (Mandatory) ---
    category_id: UUID 
    
    image_url: Optional[str] = "https://placehold.co/400?text=No+Image"
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime =  Field(default_factory=datetime.utcnow)

    class Settings:
        name = "products"