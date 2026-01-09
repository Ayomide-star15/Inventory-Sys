from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from app.models.user import User
from app.models.branch import Branch
from app.schemas.user import UserInvite, UserResponse, PasswordSetup, UserProfile,UserUpdate,ForgotPasswordRequest,ResetPasswordRequest
from app.core.security import get_password_hash, create_invite_token, create_access_token
from app.dependencies.auth import get_admin_user, get_current_active_user
from app.core.config import settings
from app.core.email import send_invite_email, send_reset_password_email
from datetime import timedelta
from jose import jwt, JWTError
from uuid import UUID

router = APIRouter()

# ---------------------------------------------------------
# 1. INVITE NEW USER (Admin Only)
# ---------------------------------------------------------
@router.post("/admin/create-user", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_user(
    invite_data: UserInvite, 
    admin: User = Depends(get_admin_user) # 🔒 Only Admin can invite
):
    """
    Step 1 of Onboarding:
    - Admin provides email, role, and branch.
    - System checks if branch exists.
    - System creates an INACTIVE user.
    - System emails a setup link to the user.
    """
    
    # A. Check if user already exists
    if await User.find_one(User.email == invite_data.email):
        raise HTTPException(
            status_code=400, 
            detail=f"User with email {invite_data.email} already exists."
        )

    # B. Validate Branch (If one was assigned)
    if invite_data.branch_id:
        branch = await Branch.get(invite_data.branch_id)
        if not branch:
            raise HTTPException(
                status_code=404, 
                detail=f"Branch ID {invite_data.branch_id} not found."
            )

    # C. Create User
    new_user = User(
        email=invite_data.email,
        first_name=invite_data.first_name,
        last_name=invite_data.last_name,
        role=invite_data.role,
        branch_id=invite_data.branch_id,
        hashed_password=None, 
        is_active=False       
    )
    await new_user.insert()

    # D. Send Email (Keep logic same)
    try:
        token = create_invite_token(invite_data.email)
        await send_invite_email(invite_data.email, token)
        
    except Exception as e:
        await new_user.delete()
        raise HTTPException(status_code=500, detail="Email failed.")

    # ✅ THE FIX: Return a simple message
    # This avoids the "ResponseValidationError" crash completely!
    return {
        "message": f"Invite sent successfully to {invite_data.email}"
    }

# ---------------------------------------------------------
# 2. SETUP PASSWORD (Public / Token Based)
# ---------------------------------------------------------
@router.post("/setup-password", status_code=status.HTTP_200_OK)
async def setup_password(data: PasswordSetup):
    """
    Step 2 of Onboarding:
    - User clicks link in email.
    - Enters valid token and new password.
    - System activates account.
    """
    try:
        # A. Decode and Validate Token
        payload = jwt.decode(data.token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email = payload.get("sub")
        token_type = payload.get("type")
        
        if token_type != "invite":
            raise HTTPException(status_code=400, detail="Invalid token type.")
            
    except JWTError:
        raise HTTPException(status_code=400, detail="Token is invalid or expired.")

    # B. Find the User
    user = await User.find_one(User.email == email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if user.is_active:
        raise HTTPException(status_code=400, detail="Account is already active. Please login.")

    # C. Activate and Save
    user.hashed_password = get_password_hash(data.new_password)
    user.is_active = True
    await user.save()

    return {"message": "Account activated successfully! You can now login."}

# ---------------------------------------------------------
# 3. LIST ALL USERS (Admin Only)
# ---------------------------------------------------------
@router.get("/", response_model=List[dict]) 
async def list_users(admin: User = Depends(get_admin_user)):
    """
    View all employees. 
    Manually handles ID conversion to prevent crashes on mixed ID types.
    """
    # 2. Get all users from DB
    users = await User.find_all().to_list()
    
    # 3. Manually build the list to ensure safety
    clean_users = []
    for user in users:
        clean_users.append({
            "user_id": str(user.user_id),  # <--- Converts both UUID and ObjectId to string safely
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
            "is_active": user.is_active,
            "branch_id": str(user.branch_id) if user.branch_id else None
        })
    
    return clean_users

@router.get("/me", response_model=UserProfile)
async def get_my_profile(current_user: User = Depends(get_current_active_user)):
    """
    Get the profile of the currently logged-in user.
    """
    
    branch_name = "Headquarters"
    
    # 1. Logic to find the branch name
    if current_user.branch_id:
        branch = await Branch.get(current_user.branch_id)
        if branch:
            branch_name = branch.name
            
    # 2. Return the data
    # ⚠️ FIX: We wrap current_user.id in str() to force it to be a string.
    # This prevents the "ObjectId is not a string" crash.
    return {
        "user_id": str(current_user.user_id), 
        "email": current_user.email,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "role": current_user.role,
        "branch_name": branch_name
    }



# ---------------------------------------------------------
# 5. FORGOT PASSWORD (Sends Email)
# ---------------------------------------------------------
@router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    """
    Sends a reset link via email.
    """
    user = await User.find_one(User.email == request.email)
    
    # Security: Pretend we sent it even if user not found to prevent email scraping
    if not user:
        return {"message": "If that email exists, a reset link has been sent."}

    # 1. Generate Token (Valid for 15 mins)
    access_token_expires = timedelta(minutes=15)
    
    # Create token with "reset" type
    reset_token = create_access_token(
        data={"sub": str(user.user_id), "type": "reset"}, 
        expires_delta=access_token_expires
    )

    # 2. Send Email
    try:
        await send_reset_password_email(user.email, reset_token, user.first_name)
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="Email failed to send")

    return {"message": "If that email exists, a reset link has been sent."}
# ---------------------------------------------------------
# 6. RESET PASSWORD (Use Token)
# ---------------------------------------------------------
@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    """
    Takes the token from the email link and the new password.
    """
    try:
        payload = jwt.decode(request.token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        token_type = payload.get("type")
        
        if not user_id or token_type != "reset":
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = await User.find_one(User.user_id == UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = get_password_hash(request.new_password)
    await user.save()

    return {"message": "Password updated successfully"}

# ---------------------------------------------------------
# 7. UPDATE USER (Admin Only)
# ---------------------------------------------------------
@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID, 
    update_data: UserUpdate, 
    admin: User = Depends(get_admin_user)
):
    """
    Update a user's profile (Role, Branch,  Name).
    Only an Admin can access this.
    """
    
    # 1. Find User by UUID
    user = await User.find_one(User.user_id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 2. Update Basic Info
    if update_data.first_name is not None:
        user.first_name = update_data.first_name
    if update_data.last_name is not None:
        user.last_name = update_data.last_name

    # 3. Update Role (Crucial Step)
    if update_data.role is not None:
        # Optional: Prevent an Admin from demoting themselves if they are the only admin
        # if user.id == admin.id and update_data.role != "admin":
        #     raise HTTPException(status_code=400, detail="You cannot demote yourself.")
        user.role = update_data.role

    # 4. Update Active Status
    if update_data.is_active is not None:
        user.is_active = update_data.is_active

    # 5. Update Branch (with Validation)
    if update_data.branch_id is not None:
        # If they are clearing the branch (setting it to None/Empty string)
        if update_data.branch_id == "":
            user.branch_id = None
        else:
            # Verify the branch exists before assigning
            branch = await Branch.get(update_data.branch_id)
            if not branch:
                raise HTTPException(status_code=404, detail=f"Branch {update_data.branch_id} not found")
            user.branch_id = update_data.branch_id

    # 6. Save changes to Database
    await user.save()

    return {
        "id": str(user.id),  # Force convert ObjectId to string
        "user_id": user.user_id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role,
        "is_active": user.is_active,
        "branch_id": user.branch_id
    
    }


# ---------------------------------------------------------
# 8. CHANGE USER STATUS (Deactivate/Reactivate)
# ---------------------------------------------------------
@router.patch("/{user_id}/status", response_model=dict)
async def change_user_status(
    user_id: UUID, 
    active: bool, 
    admin: User = Depends(get_admin_user)
):
    """
    Admin can instantly Deactivate (active=False) or Reactivate (active=True) a user.
    Usage: PATCH /users/{uuid}/status?active=false
    """
    
    # 1. Find User by UUID
    user = await User.find_one(User.user_id == user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 2. Safety Check: Prevent Admin from deactivating themselves
    # (Assuming admin.user_id is available on the logged-in user)
    if user.user_id == admin.user_id:
        raise HTTPException(
            status_code=400, 
            detail="You cannot deactivate your own account."
        )

    # 3. Update Status
    user.is_active = active
    await user.save()

    # 4. Return Confirmation
    status_msg = "activated" if active else "deactivated"
    return {
        "message": f"User {user.first_name} has been {status_msg} successfully.",
        "user_id": str(user.user_id),
        "is_active": user.is_active
    }