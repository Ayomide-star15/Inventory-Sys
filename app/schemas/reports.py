from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime


# ==========================================
# SHARED / REUSABLE
# ==========================================

class DateRangeSchema(BaseModel):
    """Reused in every report response"""
    start: datetime
    end: datetime
    days: Optional[int] = None


# ==========================================
# SALES SUMMARY REPORT
# ==========================================
# Endpoint: GET /reports/sales/summary

class RevenueBreakdownSchema(BaseModel):
    gross_revenue: float
    subtotal: float
    total_tax_collected: float
    total_discounts_given: float
    cancelled_revenue_lost: float


class TransactionSummarySchema(BaseModel):
    completed_sales: int
    cancelled_sales: int
    average_transaction: float


class SalesSummaryResponse(BaseModel):
    """
    Returned by GET /reports/sales/summary
    Used by: Finance Manager, Admin
    """
    period: DateRangeSchema
    revenue: RevenueBreakdownSchema
    transactions: TransactionSummarySchema


# ==========================================
# SALES BY BRANCH REPORT
# ==========================================
# Endpoint: GET /reports/sales/by-branch

class BranchSalesItem(BaseModel):
    """One branch in the by-branch report"""
    branch_id: str
    branch_name: str
    revenue: float
    sales_count: int
    tax_collected: float
    discounts_given: float
    avg_transaction: float


class SalesByBranchResponse(BaseModel):
    """
    Returned by GET /reports/sales/by-branch
    Used by: Finance Manager, Admin
    """
    period: DateRangeSchema
    total_revenue: float
    branches: List[BranchSalesItem]


# ==========================================
# PAYMENT METHOD BREAKDOWN
# ==========================================
# Endpoint: GET /reports/sales/by-payment

class PaymentBreakdownItem(BaseModel):
    """One payment method row"""
    payment_method: str
    transaction_count: int
    revenue: float
    percentage: float           # e.g. 45.2 means 45.2%


class PaymentBreakdownResponse(BaseModel):
    """
    Returned by GET /reports/sales/by-payment
    Used by: Finance Manager, Admin
    
    High cash % at a branch = fraud signal
    """
    period: DateRangeSchema
    total_revenue: float
    payment_breakdown: List[PaymentBreakdownItem]


# ==========================================
# PROFIT REPORT
# ==========================================
# Endpoint: GET /reports/profit

class OverallProfitSchema(BaseModel):
    total_revenue: float
    total_cogs: float           # Cost of Goods Sold
    gross_profit: float
    margin_percentage: float


class BranchProfitItem(BaseModel):
    """One branch profit row"""
    branch_name: str
    branch_id: str
    revenue: float
    cogs: float
    gross_profit: float
    margin_percentage: float


class ProfitReportResponse(BaseModel):
    """
    Returned by GET /reports/profit
    Used by: Finance Manager, Admin only
    
    gross_profit = revenue - cost_of_goods_sold
    """
    period: DateRangeSchema
    overall: OverallProfitSchema
    by_branch: List[BranchProfitItem]


# ==========================================
# TAX REPORT
# ==========================================
# Endpoint: GET /reports/tax

class BranchTaxItem(BaseModel):
    branch_name: str
    tax_collected: float


class TaxReportResponse(BaseModel):
    """
    Returned by GET /reports/tax
    Used by: Finance Manager, Admin
    
    Total VAT collected across all branches.
    Needed for tax filings.
    """
    period: DateRangeSchema
    total_vat_collected: float
    total_revenue: float
    effective_tax_rate: float   # Should match VAT rate in settings
    by_branch: List[BranchTaxItem]


# ==========================================
# PROCUREMENT SPEND REPORT
# ==========================================
# Endpoint: GET /reports/procurement/spend

class BranchSpendItem(BaseModel):
    branch: str
    spend: float


class SupplierSpendItem(BaseModel):
    supplier: str
    spend: float


class ProcurementSpendResponse(BaseModel):
    """
    Returned by GET /reports/procurement/spend
    Used by: Finance Manager, Admin
    
    How much was spent on Purchase Orders.
    Compare against revenue to check if branches are overspending.
    """
    period: DateRangeSchema
    total_procurement_spend: float
    total_pos: int
    by_branch: List[BranchSpendItem]
    by_supplier: List[SupplierSpendItem]


# ==========================================
# SLOW MOVING INVENTORY REPORT
# ==========================================
# Endpoint: GET /reports/inventory/slow-moving

class SlowMovingItem(BaseModel):
    """One slow-moving product"""
    product_name: str
    branch: str
    quantity: int
    selling_price: float
    value_tied_up: float        # quantity × selling_price
    last_updated: Optional[datetime] = None


class SlowMovingInventoryResponse(BaseModel):
    """
    Returned by GET /reports/inventory/slow-moving
    Used by: Finance Manager, Admin
    
    Products sitting in stock not selling = money not moving.
    Finance uses this to flag items for discount or return to supplier.
    """
    threshold_days: int
    total_slow_items: int
    total_value_tied_up: float
    items: List[SlowMovingItem]


# ==========================================
# DASHBOARD SCHEMAS (Finance + Others)
# ==========================================

# --- Finance Dashboard ---

class FinanceRevenueSchema(BaseModel):
    this_month: float
    last_month: float
    change_percentage: float
    trend: str                  # "up", "down", "flat"


class PendingPOItem(BaseModel):
    po_id: str
    total_amount: float
    created_at: datetime


class PendingPOSchema(BaseModel):
    count: int
    total_value: float
    orders: List[PendingPOItem]


class FinanceDashboardResponse(BaseModel):
    """
    Returned by GET /dashboard/finance
    """
    revenue: FinanceRevenueSchema
    tax_collected: float
    discounts_given: float
    cancelled_revenue_lost: float
    payment_breakdown: Dict[str, float]
    pending_po_approvals: PendingPOSchema


# --- Purchase Manager Dashboard ---

class POSummaryItem(BaseModel):
    po_id: str
    total_amount: float
    status: str
    created_at: datetime


class LowStockAlertItem(BaseModel):
    product_name: str
    quantity: int
    branch: str


class PurchaseManagerDashboardResponse(BaseModel):
    """
    Returned by GET /dashboard/purchase-manager
    """
    pos_summary: Dict[str, object]
    stock_alerts: Dict[str, object]
    active_suppliers: int


# --- Store Manager Dashboard ---

class TodaySummarySchema(BaseModel):
    total_sales: int
    total_revenue: float
    avg_transaction: float


class InventoryStatusSchema(BaseModel):
    total_products: int
    low_stock_count: int
    out_of_stock_count: int
    low_stock_items: List[Dict]


class StaffPerformanceItem(BaseModel):
    name: str
    sales_count: int
    revenue: float


class PendingActionsSchema(BaseModel):
    transfers_to_approve: int
    incoming_transfers: int
    incoming_purchase_orders: int


class StoreManagerDashboardResponse(BaseModel):
    """
    Returned by GET /dashboard/store-manager
    """
    branch_name: str
    today_summary: TodaySummarySchema
    inventory_status: InventoryStatusSchema
    staff_performance_today: List[StaffPerformanceItem]
    pending_actions: PendingActionsSchema


# --- Sales Staff Dashboard ---

class TodayStatsSchema(BaseModel):
    sales_count: int
    revenue_generated: float
    items_sold: int
    avg_transaction: float


class BranchRankSchema(BaseModel):
    my_rank: Optional[int] = None
    total_staff_selling: int


class RecentSaleItem(BaseModel):
    sale_number: str
    total_amount: float
    items_count: int
    payment_method: str
    created_at: datetime


class SalesStaffDashboardResponse(BaseModel):
    """
    Returned by GET /dashboard/sales-staff
    """
    my_name: str
    today: TodayStatsSchema
    branch_rank: BranchRankSchema
    recent_sales: List[RecentSaleItem]


# --- Store Staff Dashboard ---

class TransferTaskItem(BaseModel):
    transfer_id: str
    to_branch: Optional[str] = None
    from_branch: Optional[str] = None
    items_count: int
    priority: str


class POTaskItem(BaseModel):
    po_id: str
    total_amount: float
    items_count: int
    created_at: datetime


class TaskSummarySchema(BaseModel):
    pos_to_receive: int
    transfers_to_ship: int
    transfers_to_receive: int
    total_pending_tasks: int


class StoreStaffDashboardResponse(BaseModel):
    """
    Returned by GET /dashboard/store-staff
    """
    tasks: TaskSummarySchema
    purchase_orders_ready: List[POTaskItem]
    transfers_to_ship: List[TransferTaskItem]
    transfers_to_receive: List[TransferTaskItem]