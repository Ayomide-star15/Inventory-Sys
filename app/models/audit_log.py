from beanie import Document
from pydantic import Field
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime
from enum import Enum


class AuditAction(str, Enum):
    # Auth
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    PASSWORD_RESET = "PASSWORD_RESET"
    PASSWORD_SETUP = "PASSWORD_SETUP"
    LOGOUT = "LOGOUT"

    # Users
    USER_INVITED = "USER_INVITED"
    USER_ACTIVATED = "USER_ACTIVATED"
    USER_DEACTIVATED = "USER_DEACTIVATED"
    USER_ROLE_CHANGED = "USER_ROLE_CHANGED"
    USER_BRANCH_CHANGED = "USER_BRANCH_CHANGED"
    USER_UPDATED = "USER_UPDATED"

    # Branches
    BRANCH_CREATED = "BRANCH_CREATED"
    BRANCH_UPDATED = "BRANCH_UPDATED"
    BRANCH_DEACTIVATED = "BRANCH_DEACTIVATED"
    BRANCH_ACTIVATED = "BRANCH_ACTIVATED"
    MANAGER_ASSIGNED = "MANAGER_ASSIGNED"

    # Products
    PRODUCT_CREATED = "PRODUCT_CREATED"
    PRODUCT_UPDATED = "PRODUCT_UPDATED"
    PRODUCT_DELETED = "PRODUCT_DELETED"
    PRICE_UPDATED = "PRICE_UPDATED"

    # Categories
    CATEGORY_CREATED = "CATEGORY_CREATED"
    CATEGORY_UPDATED = "CATEGORY_UPDATED"
    CATEGORY_DELETED = "CATEGORY_DELETED"

    # Suppliers
    SUPPLIER_CREATED = "SUPPLIER_CREATED"
    SUPPLIER_UPDATED = "SUPPLIER_UPDATED"
    SUPPLIER_DELETED = "SUPPLIER_DELETED"

    # Purchase Orders
    PO_CREATED = "PO_CREATED"
    PO_APPROVED = "PO_APPROVED"
    PO_REJECTED = "PO_REJECTED"
    PO_RECEIVED = "PO_RECEIVED"

    # Sales
    SALE_COMPLETED = "SALE_COMPLETED"
    SALE_CANCELLED = "SALE_CANCELLED"

    # Stock Transfers
    TRANSFER_REQUESTED = "TRANSFER_REQUESTED"
    TRANSFER_APPROVED = "TRANSFER_APPROVED"
    TRANSFER_REJECTED = "TRANSFER_REJECTED"
    TRANSFER_SHIPPED = "TRANSFER_SHIPPED"
    TRANSFER_RECEIVED = "TRANSFER_RECEIVED"

    # Inventory
    STOCK_ADJUSTED = "STOCK_ADJUSTED"

    # System
    SETTINGS_UPDATED = "SETTINGS_UPDATED"


class AuditModule(str, Enum):
    AUTH = "auth"
    USERS = "users"
    BRANCHES = "branches"
    PRODUCTS = "products"
    CATEGORIES = "categories"
    SUPPLIERS = "suppliers"
    PROCUREMENT = "procurement"
    SALES = "sales"
    TRANSFERS = "transfers"
    INVENTORY = "inventory"
    SYSTEM = "system"


class AuditLog(Document):
    """
    Complete audit trail of every significant action in the system.
    Admin can see who did what, when, and on what.
    """
    id: UUID = Field(default_factory=uuid4)

    # === WHO DID IT ===
    user_id: UUID
    user_name: str          # "John Doe"
    user_role: str          # "Finance Manager"
    user_email: str
    branch_id: Optional[UUID] = None
    branch_name: Optional[str] = None

    # === WHAT THEY DID ===
    action: AuditAction
    module: AuditModule
    description: str        # Human readable: "Approved PO worth ₦45,000"

    # === WHAT IT AFFECTED ===
    target_id: Optional[str] = None     # ID of affected record
    target_type: Optional[str] = None   # "purchase_order", "user", "product"

    # === EXTRA DETAIL ===
    metadata: Optional[dict] = None     # e.g. {"old_price": 800, "new_price": 950}

    # === WHEN & WHERE ===
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    ip_address: Optional[str] = None

    class Settings:
        name = "audit_logs"
        indexes = [
            [("user_id", 1), ("timestamp", -1)],
            [("module", 1), ("timestamp", -1)],
            [("action", 1), ("timestamp", -1)],
            [("branch_id", 1), ("timestamp", -1)],
            [("timestamp", -1)],
            [("target_id", 1)]
        ]