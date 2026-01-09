from beanie import Document
from pydantic import Field
from typing import Optional
from uuid import UUID, uuid4

class Category(Document):
    id: UUID = Field(default_factory=uuid4)  # Generates a random unique ID
    name: str = Field(..., unique=True)
    description: Optional[str] = None
    slug: str = Field(..., unique=True)      # e.g., "beverages"
    icon: Optional[str] = "📦"               # Default emoji

    class Settings:
        name = "categories"