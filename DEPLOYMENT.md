# FASTSHOP — Render Free Tier Deployment Guide

This guide explains how to deploy **FASTSHOP** to [Render](https://render.com) using the **Free Tier**.

---

## 🌟 Architecture Overview

FASTSHOP is configured as a **unified, production-ready full-stack application**:
- **Backend**: FastAPI (Python 3.11+) with Async SQLAlchemy, REST APIs, and WebSocket channels.
- **Frontend**: High-performance, mobile-first Vanilla JS / CSS self-checkout web app served directly by FastAPI at the root URL `/`.
- **Database**: Zero-config async SQLite (auto-seeded on first run) or Render Managed PostgreSQL.
- **1-Service Deployment**: Both frontend and backend run on a single Render Free Web Service, eliminating CORS issues and ensuring 100% reliable instant loads.

---

## 🚀 Quick Deployment Options

### Method 1: 1-Click Blueprint Deploy (`render.yaml`) — Recommended

1. Push your repository to **GitHub** or **GitLab**.
2. Go to the [Render Dashboard](https://dashboard.render.com).
3. Click **New +** → **Blueprint**.
4. Connect your GitHub repository.
5. Render will automatically read `render.yaml` and configure:
   - **Environment**: Python 3.11.9
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --app-dir backend`
   - **Health Check Path**: `/health`
6. Click **Apply**. Your app will build and go live within 2-3 minutes at `https://fastshop-xxxx.onrender.com`.

---

### Method 2: Manual Web Service Setup

If you prefer manual setup on the Render Dashboard:

1. Click **New +** → **Web Service**.
2. Connect your repository.
3. Fill in the following fields:
   - **Name**: `fastshop` (or your preferred name)
   - **Region**: Select the region closest to your users (e.g. Oregon, Frankfurt, Singapore)
   - **Branch**: `main` (or your default branch)
   - **Root Directory**: Leave blank if the repository root contains `requirements.txt` and `backend` (or set to `Shop-F` if you pushed the parent folder)
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --app-dir backend`
   - **Instance Type**: **Free** ($0/month)
4. Under **Advanced Settings**:
   - **Health Check Path**: `/health`
   - **Auto-Deploy**: `Yes`
5. Click **Create Web Service**.

---

## ⚙️ Environment Variables (Optional)

You can configure these environment variables under the **Environment** tab in your Render Web Service dashboard:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `PYTHON_VERSION` | `3.11.9` | Python runtime version |
| `ENVIRONMENT` | `production` | App environment (`development` / `production`) |
| `DEBUG` | `false` | Disable debug logs in production |
| `DATABASE_URL` | `sqlite+aiosqlite:///./fastshop.db` | Database connection string. Supports Render PostgreSQL URLs automatically! |
| `BASE_ITEM_SCAN_SECONDS` | `2.5` | Avg time to scan 1 item for queue wait-time estimation |
| `BASE_PAYMENT_SECONDS` | `20.0` | Avg customer payment duration |

---

## 🗄️ Database Options on Render

### Option A: Zero-Config SQLite (Default)
- Works out of the box with zero configuration.
- On startup, the backend automatically initializes the database tables and populates the initial store catalog with items (Milk, Bread, Snacks, Beverages, etc.) and checkout counters.
- *Note: On Render's Free tier, the ephemeral disk resets on redeploys/cold restarts.*

### Option B: Render Managed PostgreSQL (Persistent Storage)
To use a persistent PostgreSQL database:
1. In the Render Dashboard, click **New +** → **PostgreSQL**.
2. Select the **Free** instance plan.
3. Copy the **Internal Database URL** (e.g., `postgres://user:password@dpg-xxx:5432/fastshop`).
4. In your Web Service settings, add the environment variable:
   - `DATABASE_URL` = `<your-copied-postgres-url>`
5. FASTSHOP will automatically parse and convert the URL to SQLAlchemy's async driver (`postgresql+asyncpg://...`) and seed the tables on startup.

---

## 🔍 Verification & Health Checks

Once deployed, test your live service:

1. **Frontend App**: Visit `https://your-service.onrender.com/` — The customer self-checkout interface will load instantly.
2. **Health Check**: Visit `https://your-service.onrender.com/health`
   ```json
   {
     "status": "healthy",
     "service": "FASTSHOP API",
     "version": "2.0.0",
     "environment": "production"
   }
   ```
3. **Interactive Swagger Docs**: Visit `https://your-service.onrender.com/docs`
4. **Live Product Lookup**: Visit `https://your-service.onrender.com/api/v1/products`

---

## 💡 Render Free Tier Characteristics

- **Inactivity Spin-Down**: Free Web Services sleep after 15 minutes of inactivity. When a customer opens the URL, Render spins up the instance in ~20-30 seconds.
- **Dynamic Connection Discovery**: FASTSHOP includes an automatic API detector in the frontend that connects to the live backend seamlessly whether deployed together or separately.

---

## 📷 Camera & Barcode Scanner Deployment Readiness

- **HTTPS Required for Camera Hardware**: Web standards (W3C WebRTC / MediaDevices) require a **Secure Context** (HTTPS) for mobile and desktop cameras. Render, Railway, AWS, and Cloudflare automatically provide free SSL certificates (`https://`).
- **Auto-HTTPS Upgrade**: The frontend and backend middleware automatically upgrade any `http://` incoming traffic to `https://` so shoppers scanning store QR codes or typing the URL always have camera permissions enabled.
- **Permissions-Policy**: The backend automatically serves `Permissions-Policy: camera=*`, ensuring camera access is never blocked by browser feature policies.
- **Cross-Platform Compatibility**: Automatically detects iOS Safari, Android Chrome, and Windows/Mac webcams, defaulting mobile devices to the rear-facing autofocus camera and filtering out infrared/Windows Hello sensors.
