from pydantic import BaseModel
from typing import Optional
from uuid import UUID

# Input: What you send to create a category
class CategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None
    icon: Optional[str] = "📦"

# Input: What you send to update a category
class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None

# Output: What the API sends back to you
class CategoryResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    description: Optional[str]
    icon: str
    
    class Config:
        from_attributes = True