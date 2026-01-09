from fastapi import APIRouter, HTTPException, Depends, status
from typing import List
from slugify import slugify
from uuid import UUID

from app.models.category import Category
# from app.models.product import Product  <-- Uncomment this later when you have the Product model
from app.models.product import Product
from app.schemas.category import CategoryCreate, CategoryUpdate, CategoryResponse
from app.models.user import User
from app.dependencies.auth import get_admin_user, get_current_user

router = APIRouter()

# ==========================================
# 🔒 ADMIN ENDPOINTS (Create, Update, Delete)
# ==========================================

@router.post(
    "/", 
    response_model=CategoryResponse, 
    status_code=status.HTTP_201_CREATED,
    summary="Create a New Category (Admin Only)",
    description="Creates a new product category. Requires an Admin User token. Auto-generates a slug from the name."
)
async def create_category(
    category_data: CategoryCreate, 
    admin: User = Depends(get_admin_user)
):
    """
    **Restricted to Admins.**
    
    - **name**: Must be unique.
    - **icon**: Optional emoji or string.
    """
    # Check if category already exists
    existing = await Category.find_one(Category.name == category_data.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Category with this name already exists"
        )

    slug = slugify(category_data.name)
    
    # Check if slug exists (edge case)
    existing_slug = await Category.find_one(Category.slug == slug)
    if existing_slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Category slug already exists"
        )

    new_category = Category(
        name=category_data.name,
        description=category_data.description,
        icon=category_data.icon,
        slug=slug
    )
    await new_category.save()
    return new_category


@router.put(
    "/{category_id}", 
    response_model=CategoryResponse,
    summary="Update Category (Admin Only)",
    description="Updates an existing category. You can update name, description, or icon."
)
async def update_category(
    category_id: UUID, 
    update_data: CategoryUpdate, 
    admin: User = Depends(get_admin_user)
):
    """
    **Restricted to Admins.**
    """
    category = await Category.get(category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    data_dict = update_data.dict(exclude_unset=True)
    
    # If name is updated, regenerate the slug to match
    if "name" in data_dict:
        data_dict["slug"] = slugify(data_dict["name"])
        
    await category.update({"$set": data_dict})
    return await Category.get(category_id)


@router.delete(
    "/{category_id}", 
    summary="Delete Category (Admin Only)",
    description="Permanently deletes a category from the database."
)
async def delete_category(
    category_id: UUID, 
    admin: User = Depends(get_admin_user)
):
    """
    **Restricted to Admins.**
    
    *Note: Later we will add a check here to ensure no products are linked to this category before deleting.*
    """
    category = await Category.get(category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    # 2. 🛡️ SAFETY CHECK: Are any products using this?
    # We ask the Product collection: "Do you have anyone with this category_id?"
    products_using_category = await Product.find(
        Product.category_id == category_id
    ).count()

    if products_using_category > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete Category. It is currently assigned to {products_using_category} products. Please reassign or delete them first."
        )
    await category.delete()
    return {"message": "Category deleted successfully"}


# ==========================================
# 🌍 PUBLIC ENDPOINTS (Read Only)
# ==========================================

@router.get(
    "/", 
    response_model=List[CategoryResponse],
    summary="List All Categories",
    description="Returns a list of all available categories. Accessible to any logged-in user (Staff or Admin)."
)
async def get_categories(user: User = Depends(get_current_user)):
    return await Category.find_all().to_list()


@router.get(
    "/{category_id}", 
    response_model=CategoryResponse,
    summary="Get Single Category",
    description="Fetch details of a specific category by its UUID."
)
async def get_category(category_id: UUID, user: User = Depends(get_current_user)):
    category = await Category.get(category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return category