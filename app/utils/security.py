import re
from typing import Optional


def mask_email(email: str) -> str:
    """
    Returns masked email for safe logging.
    john.doe@gmail.com → j*******@gmail.com
    """
    try:
        local, domain = email.split("@")
        masked_local = local[0] + "*" * (len(local) - 1)
        return f"{masked_local}@{domain}"
    except Exception:
        return "***@***.***"


def sanitize_input(text: str) -> str:
    """
    Strip potentially dangerous characters from user input.
    Prevents NoSQL injection attempts.
    """
    if not text:
        return text
    # Remove MongoDB operator characters
    dangerous = ["$", "{", "}", "(", ")", "<", ">", "\\"]
    for char in dangerous:
        text = text.replace(char, "")
    return text.strip()


def is_strong_password(password: str) -> tuple[bool, str]:
    """
    Validate password strength.
    Returns (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r"\d", password):
        return False, "Password must contain at least one number"
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "Password must contain at least one special character"
    return True, ""


def extract_ip(request) -> Optional[str]:
    """
    Extract real IP address from request.
    Handles proxies and load balancers.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None