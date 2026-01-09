from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from app.models.branch import Branch
from app.models.user import User, UserRole
from app.schemas.branch import BranchCreate, BranchResponse
from app.dependencies.auth import get_current_active_user

router = APIRouter()

# --- SECURITY DEPENDENCY ---
# This ensures only 'System Administrators' can access critical actions.
def check_admin_only(current_user: User = Depends(get_current_active_user)):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="⚠️ Access Denied: Only System Administrators can create branches."
        )
    return current_user

# --- 1. CREATE BRANCH (Admin Only) ---
@router.post("/", response_model=BranchResponse, status_code=status.HTTP_201_CREATED)
async def create_branch(
    branch_in: BranchCreate, 
    current_admin: User = Depends(check_admin_only)
):
    """
    Only System Administrators can call this endpoint.
    Create a new supermarket branch.
    - Checks if the Branch Code (e.g., 'LOS-001') already exists.
    - Saves the branch with default Zones (Receiving, Store, Sales).
    """
    
    # 1. Check for duplicates
    # We query MongoDB to see if this code is already taken.
    if await Branch.find_one(Branch.code == branch_in.code):
        raise HTTPException(
            status_code=400, 
            detail=f"Branch with code '{branch_in.code}' already exists."
        )
        
    # 2. Create and Save
    new_branch = Branch(**branch_in.model_dump())
    await new_branch.insert()
    
    return new_branch

# --- 2. LIST ALL BRANCHES (Open to all Staff) ---
@router.get("/", response_model=List[BranchResponse])
async def get_all_branches(
    current_user: User = Depends(get_current_active_user)
):
    """
    Retrieve a list of all branches. 
    Any logged-in staff member can see this list.
    """
    return await Branch.find_all().to_list()