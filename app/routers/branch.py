from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from uuid import UUID
from datetime import datetime

from app.models.branch import Branch
from app.models.user import User, UserRole
from app.models.inventory import Inventory
from app.schemas.branch import (
    BranchCreate,
    BranchUpdate,
    BranchAssignManager,
    BranchResponse,
    BranchSummaryResponse,
)
from app.dependencies.auth import get_current_active_user, get_admin_user

router = APIRouter()


# ==========================================
# 1. CREATE BRANCH (Admin only)
# ==========================================

@router.post(
    "/",
    response_model=BranchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new branch (Admin only)"
)
async def create_branch(
    branch_in: BranchCreate,
    admin: User = Depends(get_admin_user)
):
    """
    Create a new supermarket branch.

    - Branch **code** must be unique (e.g. 'LOS-001')
    - Branch **name** must be unique
    - Default zones are auto-assigned but can be customised
    """

    # Check for duplicate code
    if await Branch.find_one(Branch.code == branch_in.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A branch with code '{branch_in.code}' already exists."
        )

    # Check for duplicate name
    if await Branch.find_one(Branch.name == branch_in.name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A branch named '{branch_in.name}' already exists."
        )

    new_branch = Branch(**branch_in.model_dump())
    await new_branch.insert()

    return new_branch


# ==========================================
# 2. LIST ALL BRANCHES
# ==========================================

@router.get(
    "/",
    summary="List all branches"
)
async def get_all_branches(
    current_user: User = Depends(get_current_active_user)
):
    """
    Returns branch list. Response detail depends on role:

    - **Admin / Finance**: Full details (manager_id, timestamps, is_active)
    - **All other staff**: Summary view (name, code, address, is_active only)

    Inactive branches are hidden from Store Staff and Sales Staff.
    """

    is_admin_or_finance = current_user.role in [UserRole.ADMIN, UserRole.FINANCE]

    if is_admin_or_finance:
        # Admin and Finance see ALL branches including inactive ones
        branches = await Branch.find_all().to_list()
        return [
            {
                "id": str(b.id),
                "name": b.name,
                "code": b.code,
                "address": b.address,
                "phone": b.phone,
                "zones": b.zones,
                "manager_id": str(b.manager_id) if b.manager_id else None,
                "is_active": b.is_active,
                "created_at": b.created_at,
                "updated_at": b.updated_at,
            }
            for b in branches
        ]
    else:
        # All other staff only see active branches — summary only
        branches = await Branch.find(Branch.is_active == True).to_list()
        return [
            {
                "id": str(b.id),
                "name": b.name,
                "code": b.code,
                "address": b.address,
                "phone": b.phone,
                "is_active": b.is_active,
            }
            for b in branches
        ]


# ==========================================
# 3. GET SINGLE BRANCH
# ==========================================

@router.get(
    "/{branch_id}",
    summary="Get a single branch by ID"
)
async def get_branch(
    branch_id: UUID,
    current_user: User = Depends(get_current_active_user)
):
    """
    Fetch details of a specific branch.

    - **Admin / Finance**: Can view any branch
    - **Store Manager / Store Staff / Sales Staff**: Can only view their own assigned branch
    """

    branch = await Branch.get(branch_id)
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found")

    is_admin_or_finance = current_user.role in [UserRole.ADMIN, UserRole.FINANCE]

    # Non-admin staff can only see their own branch
    if not is_admin_or_finance:
        if str(current_user.branch_id) != str(branch_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view your own assigned branch."
            )
        # Also block inactive branch from non-admin view
        if not branch.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Branch not found."
            )
        # Return summary for non-admin
        return {
            "id": str(branch.id),
            "name": branch.name,
            "code": branch.code,
            "address": branch.address,
            "phone": branch.phone,
            "is_active": branch.is_active,
        }

    # Full response for Admin / Finance
    return {
        "id": str(branch.id),
        "name": branch.name,
        "code": branch.code,
        "address": branch.address,
        "phone": branch.phone,
        "zones": branch.zones,
        "manager_id": str(branch.manager_id) if branch.manager_id else None,
        "is_active": branch.is_active,
        "created_at": branch.created_at,
        "updated_at": branch.updated_at,
    }


# ==========================================
# 4. UPDATE BRANCH (Admin only)
# ==========================================

@router.put(
    "/{branch_id}",
    response_model=BranchResponse,
    summary="Update branch details (Admin only)"
)
async def update_branch(
    branch_id: UUID,
    update_data: BranchUpdate,
    admin: User = Depends(get_admin_user)
):
    """
    Update a branch's name, address, phone, or zones.

    - Branch **code** cannot be changed after creation (it is used as a reference key)
    - Only Admin can call this endpoint
    """

    branch = await Branch.get(branch_id)
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found")

    data_dict = update_data.model_dump(exclude_unset=True)

    # Check name uniqueness if name is being changed
    if "name" in data_dict and data_dict["name"] != branch.name:
        if await Branch.find_one(Branch.name == data_dict["name"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A branch named '{data_dict['name']}' already exists."
            )

    data_dict["updated_at"] = datetime.utcnow()
    await branch.update({"$set": data_dict})

    return await Branch.get(branch_id)


# ==========================================
# 5. ASSIGN MANAGER TO BRANCH (Admin only)
# ==========================================

@router.patch(
    "/{branch_id}/manager",
    summary="Assign or change a branch manager (Admin only)"
)
async def assign_branch_manager(
    branch_id: UUID,
    data: BranchAssignManager,
    admin: User = Depends(get_admin_user)
):
    """
    Assign a Store Manager to a branch.

    - The user being assigned **must exist** and **must have the Store Manager role**
    - Replaces any previously assigned manager
    """

    branch = await Branch.get(branch_id)
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found")

    if not branch.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot assign a manager to an inactive branch."
        )

    # Validate the user exists and has the right role
    manager = await User.find_one(User.user_id == data.manager_id)
    if not manager:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if manager.role != UserRole.STORE_MANAGER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{manager.first_name} {manager.last_name}' is not a Store Manager. "
                   f"Their current role is '{manager.role.value}'."
        )

    # Assign manager to branch
    await branch.update({"$set": {
        "manager_id": data.manager_id,
        "updated_at": datetime.utcnow()
    }})

    # Also update the manager's branch_id to match
    await manager.update({"$set": {
        "branch_id": branch_id,
        "updated_at": datetime.utcnow()
    }})

    return {
        "message": f"'{manager.first_name} {manager.last_name}' assigned as manager of '{branch.name}'.",
        "branch_id": str(branch_id),
        "manager_id": str(data.manager_id),
        "manager_name": f"{manager.first_name} {manager.last_name}"
    }


# ==========================================
# 6. DEACTIVATE / REACTIVATE BRANCH (Admin only)
# ==========================================

@router.patch(
    "/{branch_id}/status",
    summary="Deactivate or reactivate a branch (Admin only)"
)
async def set_branch_status(
    branch_id: UUID,
    active: bool,
    admin: User = Depends(get_admin_user)
):
    """
    Soft-delete a branch by setting `is_active = false`.

    - All historical data (sales, inventory, POs) is preserved
    - Inactive branches are hidden from non-admin staff
    - Use `?active=true` to reactivate

    **Never hard-deletes** — branch_id is referenced across the entire system.
    """

    branch = await Branch.get(branch_id)
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found")

    if branch.is_active == active:
        state = "active" if active else "inactive"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Branch is already {state}."
        )

    await branch.update({"$set": {
        "is_active": active,
        "updated_at": datetime.utcnow()
    }})

    action = "activated" if active else "deactivated"
    return {
        "message": f"Branch '{branch.name}' has been {action} successfully.",
        "branch_id": str(branch_id),
        "is_active": active
    }


# ==========================================
# 7. LIST BRANCH STAFF (Admin / own Store Manager)
# ==========================================

@router.get(
    "/{branch_id}/staff",
    summary="List all staff assigned to a branch"
)
async def get_branch_staff(
    branch_id: UUID,
    current_user: User = Depends(get_current_active_user)
):
    """
    Returns all users assigned to a specific branch.

    - **Admin**: Can view staff for any branch
    - **Store Manager**: Can only view staff in their own branch
    - **All other roles**: Access denied
    """

    # Role check
    if current_user.role not in [UserRole.ADMIN, UserRole.STORE_MANAGER]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Only Admins and Store Managers can view branch staff."
        )

    # Store Manager can only view their own branch
    if current_user.role == UserRole.STORE_MANAGER:
        if str(current_user.branch_id) != str(branch_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view staff in your own branch."
            )

    branch = await Branch.get(branch_id)
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found")

    staff = await User.find(User.branch_id == branch_id).to_list()

    return {
        "branch_id": str(branch_id),
        "branch_name": branch.name,
        "total_staff": len(staff),
        "staff": [
            {
                "user_id": str(u.user_id),
                "name": f"{u.first_name} {u.last_name}",
                "email": u.email,
                "role": u.role.value,
                "is_active": u.is_active,
            }
            for u in staff
        ]
    }


# ==========================================
# 8. BRANCH INVENTORY SUMMARY (Admin / Finance / own Store Manager)
# ==========================================

@router.get(
    "/{branch_id}/inventory-summary",
    summary="Get inventory summary for a branch"
)
async def get_branch_inventory_summary(
    branch_id: UUID,
    current_user: User = Depends(get_current_active_user)
):
    """
    Returns a high-level inventory count for a branch.

    - **Admin / Finance**: Any branch
    - **Store Manager**: Own branch only
    - **All other roles**: Access denied
    """

    allowed_roles = [UserRole.ADMIN, UserRole.FINANCE, UserRole.STORE_MANAGER]
    if current_user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Insufficient permissions to view inventory summary."
        )

    if current_user.role == UserRole.STORE_MANAGER:
        if str(current_user.branch_id) != str(branch_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view the inventory summary for your own branch."
            )

    branch = await Branch.get(branch_id)
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found")

    inventory_items = await Inventory.find(
        Inventory.branch_id == str(branch_id)
    ).to_list()

    total_products = len(inventory_items)
    total_units = sum(i.quantity for i in inventory_items)
    low_stock_items = [i for i in inventory_items if i.quantity <= i.reorder_point]
    out_of_stock_items = [i for i in inventory_items if i.quantity == 0]

    return {
        "branch_id": str(branch_id),
        "branch_name": branch.name,
        "total_products": total_products,
        "total_units_in_stock": total_units,
        "low_stock_count": len(low_stock_items),
        "out_of_stock_count": len(out_of_stock_items),
        "low_stock_items": [
            {
                "product_id": i.product_id,
                "product_name": i.product_name,
                "quantity": i.quantity,
                "reorder_point": i.reorder_point,
            }
            for i in low_stock_items
        ],
    }