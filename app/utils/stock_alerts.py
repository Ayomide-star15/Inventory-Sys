import logging
from app.models.inventory import Inventory
from app.models.system_settings import SystemSettings
from app.models.user import User, UserRole
from app.models.branch import Branch
from app.core.email import send_low_stock_alert_email, send_critical_stock_alert_email

logger = logging.getLogger(__name__)


async def check_and_send_stock_alerts(
    inventory: Inventory,
    branch_id,
    sys_settings: SystemSettings
):
    """
    Two-tier stock alert check.
    Call this after any stock deduction (sale or adjustment).

    Tier 1: quantity <= reorder_point             → standard "time to reorder" email
    Tier 2: quantity <= critical_stock_threshold  → urgent "nearly out" email
    """
    qty = inventory.quantity
    is_low = qty <= inventory.reorder_point
    is_critical = qty <= sys_settings.critical_stock_threshold

    if not is_low:
        return  # Stock is healthy, no alert needed

    branch = await Branch.get(branch_id)
    branch_name = branch.name if branch else "Unknown"

    store_managers = await User.find(
        User.role == UserRole.STORE_MANAGER,
        User.branch_id == branch_id,
        User.is_active == True
    ).to_list()

    purchase_managers = await User.find(
        User.role == UserRole.PURCHASE,
        User.is_active == True
    ).to_list()

    # Pick the right email function based on severity
    send_fn = send_critical_stock_alert_email if is_critical else send_low_stock_alert_email
    subject_tier = "CRITICAL" if is_critical else "Low stock"

    try:
        for manager in store_managers:
            await send_fn(
                email_to=manager.email,
                first_name=manager.first_name,
                product_name=inventory.product_name,
                branch_name=branch_name,
                quantity=qty,
                role="Store Manager"
            )
            logger.info(
                f"{subject_tier} alert → Store Manager {manager.email} | "
                f"{inventory.product_name} at {branch_name} ({qty} left)"
            )

        for pm in purchase_managers:
            await send_fn(
                email_to=pm.email,
                first_name=pm.first_name,
                product_name=inventory.product_name,
                branch_name=branch_name,
                quantity=qty,
                role="Purchase Manager"
            )
            logger.info(
                f"{subject_tier} alert → Purchase Manager {pm.email} | "
                f"{inventory.product_name} at {branch_name} ({qty} left)"
            )

    except Exception as e:
        logger.error(f"Stock alert email failed for {inventory.product_name}: {e}")