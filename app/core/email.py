import logging
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, To, From
from app.core.config import settings

logger = logging.getLogger(__name__)


async def _send(email_to: str, subject: str, html: str):
    """Internal shared sender — never call directly from routers."""
    try:
        message = Mail(
            from_email=From(settings.MAIL_FROM, settings.MAIL_FROM_NAME),
            to_emails=To(email_to),
            subject=subject,
            html_content=html
        )
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info(f"Email sent to {email_to} | Status: {response.status_code}")
    except Exception as e:
        logger.error(f"SendGrid error | To: {email_to} | {type(e).__name__}: {e}")
        raise


# ==========================================
# 1. USER INVITE
# ==========================================
async def send_invite_email(email_to: str, token: str):
    link = f"{settings.FRONTEND_URL}/setup-password?token={token}"
    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;">
      <div style="background:#f4f4f4;padding:20px;">
        <div style="background:white;padding:20px;border-radius:8px;max-width:500px;margin:auto;">
          <h2 style="color:#2c3e50;">Welcome to the Team!</h2>
          <p>You have been invited to join {settings.MAIL_FROM_NAME}.</p>
          <p>Click below to set your password:</p>
          <a href="{link}" style="display:inline-block;background:#007bff;color:white;
             padding:12px 24px;text-decoration:none;border-radius:5px;font-weight:bold;">
            Set My Password
          </a>
          <p style="margin-top:20px;font-size:12px;color:#777;">
            Link expires in 24 hours.<br>
            If the button doesn't work, copy this link: {link}
          </p>
        </div>
      </div>
    </body></html>
    """
    await _send(email_to, "Action Required: Setup Your Account", html)


# ==========================================
# 2. PASSWORD RESET
# ==========================================
async def send_reset_password_email(email_to: str, token: str, first_name: str):
    link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;">
      <div style="background:#f4f4f4;padding:20px;">
        <div style="background:white;padding:20px;border-radius:8px;max-width:500px;margin:auto;">
          <h2 style="color:#d9534f;">Password Reset Request</h2>
          <p>Hello {first_name},</p>
          <p>Click below to reset your password:</p>
          <a href="{link}" style="display:inline-block;background:#d9534f;color:white;
             padding:12px 24px;text-decoration:none;border-radius:5px;font-weight:bold;">
            Reset Password
          </a>
          <p style="margin-top:20px;font-size:12px;color:#777;">
            Expires in 15 minutes. Ignore if you did not request this.
          </p>
        </div>
      </div>
    </body></html>
    """
    await _send(email_to, "Reset Your Password", html)


# ==========================================
# 3. PO PENDING APPROVAL
# ==========================================
async def send_po_pending_email(
    email_to: str, first_name: str,
    supplier_name: str, amount: float, po_id: str
):
    link = f"{settings.FRONTEND_URL}/procurement/{po_id}"
    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;">
      <div style="background:#f4f4f4;padding:20px;">
        <div style="background:white;padding:20px;border-radius:8px;max-width:500px;margin:auto;">
          <h2 style="color:#e67e22;">Action Required: PO Needs Approval</h2>
          <p>Hello {first_name},</p>
          <p>A purchase order for <strong>{supplier_name}</strong> worth
             <strong>₦{amount:,.2f}</strong> is awaiting your approval.</p>
          <a href="{link}" style="display:inline-block;background:#e67e22;color:white;
             padding:12px 24px;text-decoration:none;border-radius:5px;font-weight:bold;">
            Review Order
          </a>
        </div>
      </div>
    </body></html>
    """
    await _send(email_to, "Action Required: Purchase Order Needs Approval", html)


# ==========================================
# 4. PO APPROVED
# ==========================================
async def send_po_approved_email(
    email_to: str, first_name: str,
    supplier_name: str, amount: float, po_id: str
):
    link = f"{settings.FRONTEND_URL}/procurement/{po_id}"
    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;">
      <div style="background:#f4f4f4;padding:20px;">
        <div style="background:white;padding:20px;border-radius:8px;max-width:500px;margin:auto;">
          <h2 style="color:#27ae60;">Purchase Order Approved</h2>
          <p>Hello {first_name},</p>
          <p>Your PO for <strong>{supplier_name}</strong> worth
             <strong>₦{amount:,.2f}</strong> has been approved.</p>
          <a href="{link}" style="display:inline-block;background:#27ae60;color:white;
             padding:12px 24px;text-decoration:none;border-radius:5px;font-weight:bold;">
            View Purchase Order
          </a>
        </div>
      </div>
    </body></html>
    """
    await _send(email_to, "Purchase Order Approved", html)


# ==========================================
# 5. PO REJECTED
# ==========================================
async def send_po_rejected_email(
    email_to: str, first_name: str,
    supplier_name: str, amount: float,
    po_id: str, reason: str
):
    link = f"{settings.FRONTEND_URL}/procurement/{po_id}"
    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;">
      <div style="background:#f4f4f4;padding:20px;">
        <div style="background:white;padding:20px;border-radius:8px;max-width:500px;margin:auto;">
          <h2 style="color:#e74c3c;">Purchase Order Rejected</h2>
          <p>Hello {first_name},</p>
          <p>Your PO for <strong>{supplier_name}</strong> worth
             <strong>₦{amount:,.2f}</strong> was rejected.</p>
          <p><strong>Reason:</strong> {reason}</p>
          <a href="{link}" style="display:inline-block;background:#e74c3c;color:white;
             padding:12px 24px;text-decoration:none;border-radius:5px;font-weight:bold;">
            View Order
          </a>
        </div>
      </div>
    </body></html>
    """
    await _send(email_to, "Purchase Order Rejected", html)


# ==========================================
# 6. TRANSFER REQUEST (notify source branch)
# ==========================================
async def send_transfer_request_email(
    email_to: str, first_name: str,
    requesting_branch: str, transfer_id: str
):
    link = f"{settings.FRONTEND_URL}/transfers/{transfer_id}"
    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;">
      <div style="background:#f4f4f4;padding:20px;">
        <div style="background:white;padding:20px;border-radius:8px;max-width:500px;margin:auto;">
          <h2 style="color:#8e44ad;">New Stock Transfer Request</h2>
          <p>Hello {first_name},</p>
          <p><strong>{requesting_branch}</strong> is requesting stock from your branch.</p>
          <a href="{link}" style="display:inline-block;background:#8e44ad;color:white;
             padding:12px 24px;text-decoration:none;border-radius:5px;font-weight:bold;">
            Review Request
          </a>
        </div>
      </div>
    </body></html>
    """
    await _send(email_to, f"Stock Transfer Request from {requesting_branch}", html)


# ==========================================
# 7. TRANSFER APPROVED (notify requesting branch)
# ==========================================
async def send_transfer_approved_email(
    email_to: str, first_name: str,
    from_branch: str, to_branch: str, transfer_id: str
):
    link = f"{settings.FRONTEND_URL}/transfers/{transfer_id}"
    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;">
      <div style="background:#f4f4f4;padding:20px;">
        <div style="background:white;padding:20px;border-radius:8px;max-width:500px;margin:auto;">
          <h2 style="color:#2980b9;">Stock Transfer Approved</h2>
          <p>Hello {first_name},</p>
          <p>Your stock transfer request from <strong>{from_branch}</strong> to
             <strong>{to_branch}</strong> has been approved.</p>
          <a href="{link}" style="display:inline-block;background:#2980b9;color:white;
             padding:12px 24px;text-decoration:none;border-radius:5px;font-weight:bold;">
            View Transfer
          </a>
        </div>
      </div>
    </body></html>
    """
    await _send(email_to, "Stock Transfer Approved", html)


# ==========================================
# 8. LOW STOCK ALERT
# (Replaces old send_low_stock_email)
# Notifies Store Manager AND Purchase Manager
# with role-specific action instructions
# ==========================================
async def send_low_stock_alert_email(
    email_to: str,
    first_name: str,
    product_name: str,
    branch_name: str,
    quantity: int,
    role: str
):
    if role == "Store Manager":
        action_text = f"""
        Please request a <strong>stock transfer</strong> from another
        branch to <strong>{branch_name}</strong> immediately.
        """
        color = "#e67e22"
        action_title = "Request Stock Transfer"
    else:
        action_text = f"""
        Please raise a <strong>Purchase Order</strong> for
        <strong>{product_name}</strong> and target it to
        <strong>{branch_name}</strong> immediately before
        stock runs out completely.
        """
        color = "#e74c3c"
        action_title = "Raise a Purchase Order"

    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;">
      <div style="background:#f4f4f4;padding:20px;">
        <div style="background:white;padding:20px;border-radius:8px;
                    max-width:500px;margin:auto;border-top:4px solid {color};">

          <h2 style="color:{color};margin-top:0;">
            Critical Stock Alert
          </h2>

          <p>Hello {first_name},</p>
          <p>A product at one of your branches has reached a
             <strong>critical stock level</strong> and requires
             your immediate attention.</p>

          <!-- Product & Branch Info Box -->
          <div style="background:#fff8f8;border:1px solid {color};
                      padding:16px;border-radius:8px;margin:16px 0;">
            <table style="width:100%;font-size:14px;">
              <tr>
                <td style="color:#888;padding:4px 0;width:40%;">
                  Product:
                </td>
                <td style="font-weight:bold;color:#333;padding:4px 0;">
                  {product_name}
                </td>
              </tr>
              <tr>
                <td style="color:#888;padding:4px 0;">Branch:</td>
                <td style="font-weight:bold;color:#333;padding:4px 0;">
                  {branch_name}
                </td>
              </tr>
              <tr>
                <td style="color:#888;padding:4px 0;">
                  Stock Remaining:
                </td>
                <td style="padding:4px 0;">
                  <span style="color:{color};font-size:20px;
                               font-weight:bold;">
                    {quantity} unit(s)
                  </span>
                </td>
              </tr>
            </table>
          </div>

          <!-- Action Required -->
          <div style="background:#f8f8f8;padding:12px 16px;
                      border-radius:6px;margin:16px 0;">
            <p style="margin:0;font-size:13px;">
              <strong style="color:{color};">
                Action Required — {action_title}
              </strong><br><br>
              {action_text}
            </p>
          </div>

          <p style="font-size:11px;color:#999;margin-top:24px;
                    border-top:1px solid #eee;padding-top:12px;">
            This is an automated alert from {settings.MAIL_FROM_NAME}.<br>
            Triggered when stock at <strong>{branch_name}</strong>
            dropped to {quantity} unit(s) of
            <strong>{product_name}</strong>.
          </p>
        </div>
      </div>
    </body></html>
    """
    await _send(
        email_to,
        f"URGENT: {product_name} is critically low at {branch_name} ({quantity} units left)",
        html
    )