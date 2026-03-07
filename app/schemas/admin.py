from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime


# ==========================================
# SYSTEM SETTINGS SCHEMAS
# ==========================================

class SystemSettingsUpdate(BaseModel):
    """What Admin sends to update system settings"""
    vat_rate: Optional[float] = None
    po_approval_threshold: Optional[float] = None
    currency_symbol: Optional[str] = None
    currency_code: Optional[str] = None
    default_low_stock_threshold: Optional[int] = None
    critical_stock_threshold: Optional[int] = None
    max_discount_percentage: Optional[float] = None
    allow_negative_stock: Optional[bool] = None
    require_till_number: Optional[bool] = None
    system_name: Optional[str] = None
    timezone: Optional[str] = None


class SystemSettingsResponse(BaseModel):
    """What the API returns when Admin views settings"""
    vat_rate: float
    vat_percentage: str                  # e.g. "7.5%"
    po_approval_threshold: float
    currency_symbol: str
    currency_code: str
    default_low_stock_threshold: int
    critical_stock_threshold: int
    max_discount_percentage: float
    allow_negative_stock: bool
    require_till_number: bool
    system_name: str
    timezone: str
    last_updated_at: datetime
    last_updated_by: Optional[str] = None

    class Config:
        from_attributes = True


# ==========================================
# AUDIT LOG SCHEMAS
# ==========================================

class AuditLogResponse(BaseModel):
    """Single audit log entry"""
    id: str
    user_name: str
    user_role: str
    user_email: str
    branch_name: Optional[str] = None
    action: str
    module: str
    description: str
    target_id: Optional[str] = None
    target_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    timestamp: datetime
    ip_address: Optional[str] = None

    class Config:
        from_attributes = True


class AuditLogListResponse(BaseModel):
    """Paginated list of audit logs"""
    total: int
    page: int
    limit: int
    logs: List[AuditLogResponse]


class UserAuditTrailResponse(BaseModel):
    """Complete action history for one user"""
    user: Dict[str, str]              # name, email, role
    total_actions: int
    logs: List[AuditLogResponse]


class FailedLoginItem(BaseModel):
    """One suspicious account in the failed login report"""
    email: str
    attempts: int
    unique_ips: List[str]
    last_attempt: datetime


class FailedLoginReportResponse(BaseModel):
    """Security report for failed login attempts"""
    period_hours: int
    total_failed_attempts: int
    suspicious_accounts: List[FailedLoginItem]


# ==========================================
# DASHBOARD STAT CARDS
# ==========================================

class SystemHealthSchema(BaseModel):
    """Top stat cards on Admin dashboard"""
    total_branches: int
    active_branches: int
    inactive_branches: int
    total_staff: int
    active_users: int
    inactive_users: int


class RevenueSchema(BaseModel):
    """Revenue summary block"""
    today: float
    this_week: float
    this_month: float
    today_transactions: int
    month_transactions: int


class BranchPerformanceItem(BaseModel):
    """One row in branch performance table"""
    branch_id: str
    branch_name: str
    monthly_revenue: float


class BranchPerformanceSchema(BaseModel):
    """Branch performance section"""
    top_branch: Optional[BranchPerformanceItem] = None
    average_monthly_revenue: float
    all_branches: List[BranchPerformanceItem]
    underperforming_branches: List[BranchPerformanceItem]


class CriticalStockBranchItem(BaseModel):
    """One branch with stock problems"""
    branch_id: str
    branch_name: str
    out_of_stock_count: int
    critical_stock_count: int


class StockAlertsSchema(BaseModel):
    """Stock alerts section"""
    branches_with_critical_stock: int
    details: List[CriticalStockBranchItem]


class UserActivityItem(BaseModel):
    """One user who hasn't logged in"""
    user_id: str
    name: str
    email: str
    role: str
    last_login: str               # "Never" or ISO date string


class RecentLoginItem(BaseModel):
    """One recent login"""
    name: str
    role: str
    last_login: Optional[str] = None


class UserActivitySchema(BaseModel):
    """User activity section"""
    not_logged_in_30_days: List[UserActivityItem]
    recent_logins: List[RecentLoginItem]


class PendingActionsSchema(BaseModel):
    """Things needing Admin attention"""
    po_approvals_needed: int
    transfers_pending: int


# ==========================================
# ADMIN DASHBOARD RESPONSE
# ==========================================

class AdminDashboardResponse(BaseModel):
    """
    Complete Admin dashboard response.
    Returned by GET /dashboard/admin
    """
    system_health: SystemHealthSchema
    revenue: RevenueSchema
    branch_performance: BranchPerformanceSchema
    stock_alerts: StockAlertsSchema
    user_activity: UserActivitySchema
    pending_actions: PendingActionsSchema


# ==========================================
# INVENTORY OVERSIGHT SCHEMAS
# ==========================================

class OutOfStockItem(BaseModel):
    product_name: str
    product_id: str
    branch: str


class CriticalStockItem(BaseModel):
    product_name: str
    quantity: int
    branch: str


class DeadStockItem(BaseModel):
    product_name: str
    quantity: int
    value: float
    branch: str
    last_updated: Optional[datetime] = None


class InventoryOverviewSummary(BaseModel):
    total_products_tracked: int
    total_units_in_stock: int
    total_stock_value: float
    out_of_stock_count: int
    low_stock_count: int
    critical_stock_count: int
    dead_stock_count: int


class InventoryOverviewResponse(BaseModel):
    """Returned by GET /admin/inventory/overview"""
    summary: InventoryOverviewSummary
    out_of_stock: List[OutOfStockItem]
    critical_stock: List[CriticalStockItem]
    dead_stock: List[DeadStockItem]


class ProductBranchInventoryItem(BaseModel):
    """One branch's stock of a product"""
    branch_name: str
    branch_id: str
    quantity: int
    selling_price: float
    reorder_point: int
    status: str                  # "In Stock", "Low Stock", "Out of Stock"


class ProductAcrossBranchesResponse(BaseModel):
    """Returned by GET /admin/inventory/product/{id}/all-branches"""
    product_id: str
    total_units_system_wide: int
    branches: List[ProductBranchInventoryItem]


# ==========================================
# BRANCH PERFORMANCE SCHEMAS
# ==========================================

class BranchPerformanceDetailItem(BaseModel):
    """One branch in the side-by-side comparison"""
    branch_id: str
    branch_name: str
    branch_code: str
    revenue: float
    total_sales: int
    cancelled_sales: int
    staff_count: int
    stock_value: float
    out_of_stock_items: int
    avg_sale_value: float


class BranchPerformanceReportResponse(BaseModel):
    """Returned by GET /admin/branches/performance"""
    period_days: int
    system_total_revenue: float
    system_total_sales: int
    branches: List[BranchPerformanceDetailItem]


# ==========================================
# USER MANAGEMENT SCHEMAS
# ==========================================

class InactiveUserItem(BaseModel):
    """One inactive user in the report"""
    user_id: str
    name: str
    email: str
    role: str
    branch: str
    last_login: str
    days_inactive: Optional[int] = None


class InactiveUsersResponse(BaseModel):
    """Returned by GET /admin/users/inactive"""
    threshold_days: int
    total_inactive: int
    users: List[InactiveUserItem]