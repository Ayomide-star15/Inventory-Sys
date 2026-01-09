# app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import init_db

# ---------------------------------------------------------
# 1. LIFESPAN MANAGER (The Startup/Shutdown Logic)
# ---------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    print("⏳ Initialization Started...")
    try:
        # Connect to MongoDB & Initialize Beanie Models
        await init_db()
        print(f"✅ SUCCESS: Connected to Database '{settings.DATABASE_NAME}'")
        print("   - User Model: Loaded")
    except Exception as e:
        print(f"❌ CRITICAL ERROR: Could not connect to Database. \n   Detail: {e}")
    
    yield # The application runs here
    
    # --- SHUTDOWN ---
    print("🛑 System Shutting Down...")

# ---------------------------------------------------------
# 2. APP INITIALIZATION
# ---------------------------------------------------------
app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan,
    description="API for Multi-Branch Supermarket Inventory System"
)

# ---------------------------------------------------------
# 3. CORS MIDDLEWARE (Security for Frontend Access)
# ---------------------------------------------------------
# This allows your future React/Vue/Angular app to talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace "*" with your specific frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# 4. BASIC ROUTES (Health Checks)
# ---------------------------------------------------------
@app.get("/", tags=["System"])
async def root():
    """Root endpoint to verify the API is online."""
    return {
        "system": settings.PROJECT_NAME,
        "status": "Online",
        "documentation": "/docs"
    }

@app.get("/health", tags=["System"])
async def health_check():
    """Used by Docker/Kubernetes to check if the app is alive."""
    return {"status": "ok", "db": "connected"}

# ---------------------------------------------------------
# 5. ROUTER REGISTRATION (Uncomment as you build them)
# ---------------------------------------------------------
# Once you create 'app/routers/auth.py', uncomment these lines:

# from app.routers import auth, users
# app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
# app.include_router(users.router, prefix="/users", tags=["User Management"])