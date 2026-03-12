from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import init_db
from app.core.rate_limit import limiter  # <--- NEW 
from app.routers import auth, branch, user, category, product, supplier, procurement, inventory, stock_transfer, sale, dashboard, admin, reports  # <--- NEW
# ---------------------------------------------------------
# 1. LIFESPAN MANAGER
# ---------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    print("Initialization Started...")
    try:
        await init_db() # This now exists in database.py
        print(f"SUCCESS: Connected to Database '{settings.DATABASE_NAME}'")
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
    
    yield
    
    # --- SHUTDOWN ---
    print("System Shutting Down...")

# ---------------------------------------------------------
# 2. APP INITIALIZATION
# ---------------------------------------------------------
app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
    description="API for Multi-Branch Supermarket Inventory System"
)

# ← ADD THESE TWO LINES
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],

)

# INCLUDE THE ROUTER
app.include_router(auth.router, prefix="/auth", tags=["Authentication"]) # <--- NEW
app.include_router(user.router, prefix="/users", tags=["User Management"])
app.include_router(branch.router, prefix="/branches", tags=["Branch Management"])
app.include_router(category.router, prefix="/categories", tags=["Category Management"]) # <--- NEW
app.include_router(product.router, prefix="/products", tags=["Product Management"]) # <--- NEW
app.include_router(supplier.router, prefix="/suppliers", tags=["Supplier Management"]) # <--- NEW
app.include_router(procurement.router) # <--- NEW
app.include_router(inventory.router, prefix="/inventory", tags=["Inventory Management"]) # <--- NEW
app.include_router(stock_transfer.router, prefix="/transfers", tags=["Stock Transfers"]) # <--- NEW
app.include_router(sale.router, prefix="/sales", tags=["Sales Management"]) # <--- NEW
app.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"]) # <--- NEW
app.include_router(admin.router, prefix="/admin", tags=["Admin"]) # <--- NEW
app.include_router(reports.router, prefix="/reports", tags=["Reports"]) # <--- NEW

@app.get("/")
def root():
    return {"message": "System Online"}