from pathlib import Path
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.api.v1.router import api_v1_router
from app.db.init_db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("fastshop.main")


def get_frontend_dir() -> Path | None:
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "frontend",
        Path(__file__).resolve().parent.parent / "frontend",
        Path.cwd() / "frontend",
    ]
    for p in candidates:
        if p.exists() and (p / "index.html").exists():
            return p
    return None


frontend_dir = get_frontend_dir()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.PROJECT_NAME} v{settings.VERSION}...")
    try:
        await init_db()
        logger.info("Database initialized and seeded.")
    except Exception as e:
        logger.error(f"DB initialization error: {e}", exc_info=True)
    yield
    logger.info(f"Shutting down {settings.PROJECT_NAME}...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="SHOPFAST — Self-Checkout Mall System API",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

@app.middleware("http")
async def security_and_camera_headers(request: Request, call_next):
    # Enforce HTTPS on deployed platforms (Render, Railway, Fly, Heroku, Cloudflare, etc.)
    proto = request.headers.get("x-forwarded-proto")
    if proto == "http" and settings.ENVIRONMENT.lower() != "development":
        url = request.url.replace(scheme="https")
        return RedirectResponse(url=str(url), status_code=status.HTTP_301_MOVED_PERMANENTLY)
    
    response = await call_next(request)
    # Ensure browsers grant camera permission to this application
    response.headers["Permissions-Policy"] = "camera=*, microphone=(), geolocation=()"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=r"^https://.*\.onrender\.com$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes — canonical versioned prefix
app.include_router(api_v1_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
    }


@app.get("/", tags=["Frontend"])
@app.get("/landing", tags=["Frontend"])
@app.get("/landing.html", tags=["Frontend"])
async def root():
    """Startup showcase & product landing page."""
    if frontend_dir and (frontend_dir / "landing.html").exists():
        return FileResponse(frontend_dir / "landing.html", media_type="text/html")
    if frontend_dir and (frontend_dir / "index.html").exists():
        return FileResponse(frontend_dir / "index.html", media_type="text/html")
    return {"message": "SHOPFAST API", "docs": "/docs"}


@app.get("/shop", tags=["Frontend"])
@app.get("/shop.html", tags=["Frontend"])
@app.get("/index.html", tags=["Frontend"])
@app.get("/login", tags=["Frontend"])
@app.get("/register", tags=["Frontend"])
@app.get("/scan", tags=["Frontend"])
@app.get("/cart", tags=["Frontend"])
@app.get("/checkout", tags=["Frontend"])
@app.get("/success", tags=["Frontend"])
@app.get("/history", tags=["Frontend"])
async def customer_app():
    """Customer self-checkout shopping application."""
    if frontend_dir and (frontend_dir / "index.html").exists():
        return FileResponse(frontend_dir / "index.html", media_type="text/html")
    return {"message": "Customer app not found."}


@app.get("/admin", tags=["Frontend"])
@app.get("/admin.html", tags=["Frontend"])
async def admin_portal():
    """Admin / Counter Staff verification terminal."""
    if frontend_dir and (frontend_dir / "admin.html").exists():
        return FileResponse(frontend_dir / "admin.html", media_type="text/html")
    return {"message": "Admin terminal not found."}


# Static file serving
if frontend_dir and frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")
