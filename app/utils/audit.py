from typing import Optional
from app.models.audit_log import AuditLog, AuditAction, AuditModule
from app.models.user import User


async def log_action(
    user: User,
    action: AuditAction,
    module: AuditModule,
    description: str,
    target_id: Optional[str] = None,
    target_type: Optional[str] = None,
    metadata: Optional[dict] = None,
    branch_name: Optional[str] = None,
    ip_address: Optional[str] = None
):
    """
    Write an audit log entry.
    
    Call this after every significant action in every router.
    
    Example:
        await log_action(
            user=current_user,
            action=AuditAction.APPROVED_PO,
            module=AuditModule.PROCUREMENT,
            description=f"Approved PO worth ₦{po.total_amount:,.2f}",
            target_id=str(po.id),
            target_type="purchase_order",
            metadata={"total_amount": po.total_amount}
        )
    """
    try:
        log = AuditLog(
            user_id=user.user_id,
            user_name=f"{user.first_name} {user.last_name}",
            user_role=user.role.value,
            user_email=user.email,
            branch_id=user.branch_id,
            branch_name=branch_name,
            action=action,
            module=module,
            description=description,
            target_id=target_id,
            target_type=target_type,
            metadata=metadata,
            ip_address=ip_address
        )
        await log.insert()
    except Exception as e:
        # Never let audit log failure break the main action
        print(f"Audit log failed: {e}")