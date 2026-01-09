from fastapi import APIRouter, HTTPException, Depends, status
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from app.models.product import Product
from app.models.category import Category
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse
from app.models.user import User
from app.dependencies.auth import get_current_user, get_product_manager

router = APIRouter()

# ==========================================
# 🔒 MANAGER ACTIONS (Admin + Purchase Manager)
# ==========================================

@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    product_data: ProductCreate, 
    manager: User = Depends(get_product_manager)
):
    # Check Duplicates
    if await Product.find_one(Product.barcode == product_data.barcode):
        raise HTTPException(400, "Product with this Barcode already exists")
    if await Product.find_one(Product.sku == product_data.sku):
        raise HTTPException(400, "Product with this SKU already exists")

    # Verify Category Exists
    if not await Category.get(product_data.category_id):
        raise HTTPException(404, "The provided Category ID does not exist")

    new_product = Product(**product_data.dict())
    await new_product.save()
    return new_product

@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: UUID, 
    update_data: ProductUpdate, 
    manager: User = Depends(get_product_manager)
):
    product = await Product.get(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    
    # If category is changing, verify the new one
    if update_data.category_id:
        if not await Category.get(update_data.category_id):
            raise HTTPException(404, "New Category ID does not exist")

    data_dict = update_data.dict(exclude_unset=True)
    data_dict["updated_at"] = datetime.utcnow()
    
    await product.update({"$set": data_dict})
    return await Product.get(product_id)

@router.delete("/{product_id}")
async def delete_product(
    product_id: UUID, 
    manager: User = Depends(get_product_manager)
):
    product = await Product.get(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    
    await product.delete()
    return {"message": "Product deleted successfully"}

# ==========================================
# 🌍 PUBLIC ACTIONS (Staff / Cashiers)
# ==========================================

@router.get("/", response_model=List[ProductResponse])
async def get_products(
    search: Optional[str] = None,
    category_id: Optional[UUID] = None,
    user: User = Depends(get_current_user)
):
    query = Product.find_all()
    
    if category_id:
        query = query.find(Product.category_id == category_id)
    
    if search:
        query = query.find(
            {"$or": [
                {"name": {"$regex": search, "$options": "i"}},
                {"sku": {"$regex": search, "$options": "i"}},
                {"barcode": {"$regex": search, "$options": "i"}}
            ]}
        )
        
    return await query.to_list()

@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: UUID, user: User = Depends(get_current_user)):
    product = await Product.get(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    return product