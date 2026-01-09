import os
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from pydantic import EmailStr
from dotenv import load_dotenv

# Load env variables
load_dotenv()

# 1. Configure the Connection
conf = ConnectionConfig(
    MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
    MAIL_FROM=os.getenv("MAIL_FROM"),
    MAIL_PORT=int(os.getenv("MAIL_PORT", 587)),
    MAIL_SERVER=os.getenv("MAIL_SERVER"),
    MAIL_STARTTLS=True,           # Crucial for Gmail
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True
)

# 2. Define the Sending Function
async def send_invite_email(email_to: EmailStr, token: str):
    """
    Sends a styled HTML email with the password setup link.
    """
    # In production, change localhost to your real website URL
    link = f"http://localhost:3000/setup-password?token={token}"

    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <div style="background-color: #f4f4f4; padding: 20px;">
                <div style="background-color: white; padding: 20px; border-radius: 8px; max-width: 500px; margin: auto;">
                    <h2 style="color: #2c3e50;">Welcome to the Team!</h2>
                    <p>You have been invited to join the Supermarket System.</p>
                    <p>Click the button below to set your password:</p>
                    
                    <a href="{link}" style="display: inline-block; background-color: #007bff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">
                        Set My Password
                    </a>
                    
                    <p style="margin-top: 20px; font-size: 12px; color: #777;">
                        If the button doesn't work, copy this link:<br>
                        {link}
                    </p>
                </div>
            </div>
        </body>
    </html>
    """

    message = MessageSchema(
        subject="Action Required: Setup Your Account",
        recipients=[email_to], # List of recipients
        body=html,
        subtype=MessageType.html
    )

    fm = FastMail(conf)
    
    # This actually sends the email
    await fm.send_message(message)
    return True

async def send_reset_password_email(email_to: EmailStr, token: str, first_name: str):
    """
    Sends a styled HTML email for password resets.
    """
    # This link points to your React/Frontend Reset Page
    link = f"http://localhost:3000/reset-password?token={token}"

    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <div style="background-color: #f4f4f4; padding: 20px;">
                <div style="background-color: white; padding: 20px; border-radius: 8px; max-width: 500px; margin: auto;">
                    <h2 style="color: #d9534f;">Password Reset Request</h2>
                    <p>Hello {first_name},</p>
                    <p>We received a request to reset your password. If this was you, click the button below:</p>
                    
                    <a href="{link}" style="display: inline-block; background-color: #d9534f; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">
                        Reset Password
                    </a>
                    
                    <p style="margin-top: 20px; font-size: 12px; color: #777;">
                        This link expires in 15 minutes.<br>
                        If you did not request this, you can safely ignore this email.
                    </p>
                    <p style="font-size: 12px; color: #aaa; margin-top: 10px;">
                        Link: {link}
                    </p>
                </div>
            </div>
        </body>
    </html>
    """

    message = MessageSchema(
        subject="Reset Your Password",
        recipients=[email_to],
        body=html,
        subtype=MessageType.html
    )

    fm = FastMail(conf)
    await fm.send_message(message)
    return True
