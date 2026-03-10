# 🛒 Multi-Branch Supermarket Management System

A robust, role-based REST API for managing inventory, sales, procurement, staff, and reporting across multiple supermarket branches. Built with **FastAPI** and **MongoDB**.

---

## 🚀 Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI |
| Database | MongoDB (via Motor + Beanie ODM) |
| Authentication | JWT (OAuth2 Bearer Tokens) |
| Password Hashing | bcrypt (passlib) |
| Email | fastapi-mail |
| Config Management | pydantic-settings |

---

## 📁 Project Structure

```
app/
├── core/
│   ├── config.py          # Environment settings
│   ├── database.py        # MongoDB + Beanie init
│   ├── email.py           # Email sending (invites, resets)
│   └── security.py        # JWT & password utilities
├── dependencies/
│   └── auth.py            # Auth guards (role-based)
├── models/                # Beanie MongoDB documents
│   ├── user.py
│   ├── branch.py
│   ├── product.py
│   ├── inventory.py
│   ├── sale.py
│   ├── purchase_order.py
│   ├── stock_transfer.py
│   ├── supplier.py
│   ├── audit_log.py
│   ├── system_settings.py
│   └── ...
├── routers/               # API route handlers
│   ├── auth.py
│   ├── user.py
│   ├── branch.py
│   ├── product.py
│   ├── inventory.py
│   ├── procurement.py
│   ├── stock_transfer.py
│   ├── sale.py
│   ├── dashboard.py
│   ├── admin.py
│   └── reports.py
├── schemas/               # Pydantic request/response models
└── utils/
    ├── audit.py
    └── security.py
main.py                    # App entry point
```

---

## 👥 User Roles

| Role | Description |
|---|---|
| `System Administrator` | Full system access — manages users, branches, settings |
| `Finance Manager` | Approves purchase orders, views financial reports |
| `Purchase Manager` | Creates and manages purchase orders and suppliers |
| `Store Manager` | Manages their branch — inventory, staff, transfers |
| `Store Staff` | Handles stock receiving and internal transfers |
| `Sales Staff` | Processes sales at the point of sale |

---

## ⚙️ Setup & Installation

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd <project-folder>
```

### 2. Create a Virtual Environment

```bash
python -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the root directory:

```env
# App
APP_NAME="Multi-Branch Supermarket System"
DEBUG=False

# Database
MONGODB_URL=mongodb://localhost:27017
DATABASE_NAME=supermarket_db

# Security
SECRET_KEY=your-very-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# CORS
CORS_ORIGINS=["http://localhost:3000"]

# Email (Gmail example)
MAIL_USERNAME=your@gmail.com
MAIL_PASSWORD=your-app-password
MAIL_FROM=your@gmail.com
MAIL_PORT=587
MAIL_SERVER=smtp.gmail.com

# Admin Seed Accounts
ADMIN_EMAIL_1=admin@example.com
ADMIN_PASSWORD_1=strongpassword
```

### 5. Run the Server

```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`.
Interactive docs: `http://localhost:8000/docs`

---

## 🔐 Authentication Flow

1. **Admin invites a user** → `POST /users/admin/create-user`
2. **User receives an email** with a password setup link
3. **User sets their password** → `POST /users/setup-password`
4. **User logs in** → `POST /auth/login` → receives a JWT Bearer token
5. **Token is included** in subsequent requests via `Authorization: Bearer <token>`

> Password reset is also supported via `POST /users/forgot-password` and `POST /users/reset-password`.

---

## 📡 API Modules

| Prefix | Module | Description |
|---|---|---|
| `/auth` | Authentication | Login |
| `/users` | User Management | Invite, profile, password setup |
| `/branches` | Branch Management | CRUD, inventory summary |
| `/categories` | Category Management | Product categories |
| `/products` | Product Management | CRUD, pricing |
| `/suppliers` | Supplier Management | Supplier records |
| `/procurement` | Purchase Orders | Create, approve, receive POs |
| `/inventory` | Inventory | View, adjust stock levels |
| `/transfers` | Stock Transfers | Inter-branch stock movement |
| `/sales` | Sales | Point-of-sale transactions |
| `/dashboard` | Dashboards | Role-specific dashboards |
| `/admin` | Admin | System-wide settings and oversight |
| `/reports` | Reports | Sales, inventory, audit reports |

---

## 💰 Key Business Rules

- **VAT** is applied automatically at the configured rate (default: 7.5%)
- **Purchase Orders** above the approval threshold require Finance Manager sign-off
- **Stock transfers** between branches are tracked with full audit history
- **Discounts** are capped at the system-configured maximum percentage
- **Negative stock** can be allowed or disallowed via system settings
- All critical actions are recorded in an **audit log**

---

## 🛠️ System Settings (Admin Configurable)

Admins can update these live via `PUT /admin/settings` without redeploying:

- VAT rate
- PO approval threshold
- Default & critical stock thresholds
- Max discount percentage
- Currency symbol
- Allow negative stock
- Require till number at POS

---

## 📊 Reports Available

- Sales summary (revenue, tax, discounts)
- Sales by branch
- Sales by payment method
- Inventory valuation
- Audit logs

---

## 🩺 Health Check

```
GET /         → {"status": "Online"}
GET /health   → {"status": "ok", "db": "connected"}
```

---

## 📝 License

This project is proprietary. All rights reserved.
