from fastapi import HTTPException, status


# ==========================================
# BASE EXCEPTIONS
# ==========================================

class AppException(HTTPException):
    """Base exception for all app exceptions"""
    pass


# ==========================================
# AUTH EXCEPTIONS
# ==========================================

class InvalidCredentialsException(AppException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"}
        )


class InactiveUserException(AppException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is not active. Please contact your administrator."
        )


class InvalidTokenException(AppException):
    def __init__(self, message: str = "Invalid or expired token"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=message
        )


class AccessDeniedException(AppException):
    def __init__(self, message: str = "You do not have permission to perform this action"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=message
        )


# ==========================================
# RESOURCE EXCEPTIONS
# ==========================================

class NotFoundException(AppException):
    def __init__(self, resource: str = "Resource"):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource} not found"
        )


class AlreadyExistsException(AppException):
    def __init__(self, resource: str = "Resource"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{resource} already exists"
        )


# ==========================================
# BUSINESS LOGIC EXCEPTIONS
# ==========================================

class InsufficientStockException(AppException):
    def __init__(self, product_name: str, available: int, requested: int):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient stock for '{product_name}'. Available: {available}, Requested: {requested}"
        )


class InvalidPriceException(AppException):
    def __init__(self, message: str = "Invalid price"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )


class BranchMismatchException(AppException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only perform this action for your assigned branch"
        )


class ActivePurchaseOrdersException(AppException):
    def __init__(self, count: int):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete. There are {count} active Purchase Orders linked to this record."
        )


class InvalidStatusTransitionException(AppException):
    def __init__(self, current: str, attempted: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot transition from '{current}' to '{attempted}'"
        )


class NoBranchAssignedException(AppException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your account is not assigned to a branch. Please contact your administrator."
        )