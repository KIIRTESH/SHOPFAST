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


import re

def _sanitize_error_message(err_str: str) -> str:
    """Sanitize error messages to ensure no passwords or connection strings are exposed in logs or API responses."""
    if not err_str:
        return "Unknown database error"
    # Mask password in URLs: ://user:password@ -> ://user:***@
    sanitized = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", err_str)
    # Mask password=... in query strings or DSNs
    sanitized = re.sub(r"password=([^\s;]+)", "password=***", sanitized, flags=re.IGNORECASE)
    # Mask token/secret
    sanitized = re.sub(r"(token|secret|key)=([^\s;]+)", r"\1=***", sanitized, flags=re.IGNORECASE)
    return sanitized


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.PROJECT_NAME} v{settings.VERSION}...")
    app.state.db_ready = False
    app.state.db_error = None
    try:
        await init_db()
        app.state.db_ready = True
        logger.info("Database initialized and seeded.")
    except Exception as e:
        safe_error = _sanitize_error_message(str(e))
        app.state.db_error = safe_error
        logger.error(f"DB initialization error: {safe_error}", exc_info=True)
        if settings.ENVIRONMENT.lower() in ("production", "prod"):
            raise
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


@app.get("/health/live", tags=["Health"])
async def liveness_check():
    """
    Liveness probe: verifies process responsiveness without requiring database connectivity.
    """
    return {
        "status": "alive",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
    }


@app.get("/health", tags=["Health"])
@app.get("/health/ready", tags=["Health"])
async def health_check():
    """
    Readiness probe for orchestrators (Render, K8s, Docker).
    Probes database readiness and connectivity, returning 503 if unavailable.
    """
    from sqlalchemy import text
    from app.db.session import engine

    db_ready = getattr(app.state, "db_ready", None)
    if db_ready is False:
        raw_error = getattr(app.state, "db_error", "Database initialization not completed")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "database": "uninitialized",
                "detail": _sanitize_error_message(str(raw_error)),
                "service": settings.PROJECT_NAME,
                "version": settings.VERSION,
                "environment": settings.ENVIRONMENT,
            }
        )

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        safe_error = _sanitize_error_message(str(e))
        logger.warning(f"Health check DB probe failed: {safe_error}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "database": "unavailable",
                "detail": safe_error,
                "service": settings.PROJECT_NAME,
                "version": settings.VERSION,
                "environment": settings.ENVIRONMENT,
            }
        )

    return {
        "status": "healthy",
        "database": "connected",
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
