# ⚡ ShopFast (FASTSHOP) — Smart Self-Checkout & Queue Intelligence

> **Production-Ready Self-Checkout Platform for Modern Retail & Supermarkets.**  
> Turn every customer's smartphone into a self-checkout scanner: scan items in-aisle, pay digitally via UPI/Cards, and clear checkout in under 15 seconds through express verification lanes.

---

## 🌟 Key Highlights

- **📱 Mobile-First In-Aisle Scanner**: Real-time camera barcode scanner powered by `html5-qrcode` + WebAssembly ZXing. Scans standard retail 1D formats (`EAN-13`, `EAN-8`, `Code-128`, `Code-39`, `UPC-A`, `UPC-E`) and 2D QR codes with hardware acceleration, continuous autofocus, and haptic feedback.
- **🖥️ Cashier POS Verification Terminal**: Real-time counter clearance interface with synchronized camera/hardware gun barcode scanning, item-by-item verification, discrepancy flagging, audio synth beeps, and digital invoice generation.
- **⚡ Zero-Queue Fast-Pass**: Generates high-contrast Code-128 barcodes and dynamic QR codes linked to the customer's verified, paid transaction for instant clearance.
- **🛡️ Resilient Dual CDN & Full-Frame Engine**: Both customer and admin scanners run on a resilient full-frame (10 FPS) engine with unpkg + jsDelivr redundancy, free from `qrbox` dimensional crashes and canvas buffer collapse.
- **🧠 Queue Load Balancing**: Intelligent least-load counter assignment algorithm with express lane routing (≤ 5 items).
- **🔄 Live Store WebSockets**: Bi-directional real-time stock synchronization and instant checkout clearance chimes.
- **☁️ 100% Free-Tier Ready**: Single-service architecture optimized for **Render Free Tier**, Railway, Fly.io, or Docker with zero-config async SQLite or managed PostgreSQL.

---

## 🏗️ System Architecture

```
                                    ┌────────────────────────────────────────────────────────┐
                                    │                Render Free Web Service                 │
                                    │                                                        │
┌─────────────────────────┐         │  ┌───────────────────────┐   ┌──────────────────────┐  │
│  Customer Mobile Phone  │─────────┼─▶│ FastAPI Unified Server│──▶│ SQLite / PostgreSQL  │  │
│  (/shop - Self-Checkout)│◀────────┼──│ (REST API + WebSockets│◀──│ (Async SQLAlchemy)   │  │
└─────────────────────────┘  HTTPS  │  └───────────────────────┘   └──────────────────────┘  │
                             WSS    │              │                                         │
┌─────────────────────────┐         │              ▼                                         │
│ Cashier Verification POS│─────────┼─▶┌───────────────────────┐                             │
│ (/admin - Counter Lane) │◀────────┼──│ Static Web Apps       │                             │
└─────────────────────────┘         │  │ / (Landing), /shop,   │                             │
                                    │  │ /admin, /docs         │                             │
                                    │  └───────────────────────┘                             │
                                    └────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start (Localhost)

### 1. Prerequisites
- **Python 3.11+** installed
- Modern browser (Chrome, Edge, Safari, Firefox)

### 2. Setup & Installation
```powershell
# Clone the repository
git clone https://github.com/FastShopOfficial/hm.git
cd hm

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1   # On Linux/macOS: source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run Development Server
```powershell
# Windows PowerShell
python -m uvicorn app.main:app --app-dir backend --reload --port 8000

# Linux / macOS
uvicorn app.main:app --app-dir backend --reload --port 8000
```

Open your browser:
- 🌐 **Store Showcase / Landing:** [http://localhost:8000/](http://localhost:8000/)
- 🛍️ **Customer Self-Checkout:** [http://localhost:8000/shop](http://localhost:8000/shop)
- 🖥️ **Cashier Staff POS Terminal:** [http://localhost:8000/admin](http://localhost:8000/admin)
- 📖 **Interactive API Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)

---

## ☁️ Deploying to Render Free Tier

### Method A: 1-Click Blueprint (Recommended)
1. Fork or push this repository to your **GitHub** account.
2. Go to the [Render Dashboard](https://dashboard.render.com/).
3. Click **New +** → **Blueprint**.
4. Select `FastShopOfficial/hm`. Render automatically detects `render.yaml`.
5. Click **Apply**. Your app will build and go live at `https://<service-name>.onrender.com` in ~2 minutes!

### Method B: Manual Web Service
1. Click **New +** → **Web Service**.
2. Connect your repository: `FastShopOfficial/hm`.
3. Configure the following settings:
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT --app-dir backend`
   - **Health Check Path:** `/health`
   - **Instance Type:** `Free`
4. Click **Create Web Service**.

---

## 🔑 Demo & Test Credentials

All databases initialize and seed automatically on the first boot:

| Role | Username | PIN | Assigned Counter / Notes |
| :--- | :--- | :--- | :--- |
| **Store Admin** | `admin3` | `333333` | Counter 03 (Primary Station) |
| **Cashier 01** | `staff01` | `1234` | Counter 01 (General Lane) |
| **Cashier 02** | `staff02` | `1234` | Counter 02 (General Lane) |
| **Cashier 03** | `staff03` | `1234` | Counter 03 (Express Lane ≤ 5 items) |
| **Cashier 04** | `staff04` | `1234` | Counter 04 (General Lane) |
| **Cashier 07** | `staff07` | `1234` | Counter 07 (Supervisor Station) |
| **Customer (Demo)** | `customer` | `1234` | Pre-registered shopper account |
| **Guest Shopper** | *Instant 1-Tap* | *None* | Automatically generated on entrance |

---

## 🏷️ Test Barcodes (Instant Testing)

Use these seeded grocery barcodes with your webcam, smartphone camera, or manual input bar:

| Barcode | Product Name | Category | Price |
| :--- | :--- | :--- | :--- |
| `890105885264` | Maggi 2-Minute Noodles (4-Pack) | Instant Food | ₹56.00 |
| `890149110183` | Lay's India's Magic Masala | Snacks | ₹30.00 |
| `890103035821` | Nescafe Classic Coffee 50g | Beverage | ₹180.00 |
| `762220172584` | Cadbury Oreo Vanilla 120g | Biscuits | ₹50.00 |
| `7622201412389`| Cadbury Dairy Milk Silk 150g | Chocolates | ₹175.00 |
| `9002490100070`| Red Bull Energy Drink 250ml | Beverage | ₹125.00 |
| `890106301201` | Tropicana Orange Juice 1L | Beverage | ₹95.00 |
| `8901396388431`| Dettol Original Bathing Soap | Personal Care | ₹45.00 |
| `8901314010529`| Colgate MaxFresh Toothpaste | Personal Care | ₹98.00 |
| `8901499008502`| Doritos Cheese Supreme Nachos | Snacks | ₹50.00 |

---

## 📷 Barcode Scanner Specifications & Architecture

Both the **Customer Self-Checkout** (`/shop`) and the **Cashier Terminal** (`/admin`) use an identical camera barcode engine:

- **Library & Redundancy:** `html5-qrcode` v2.3.8 loaded from `unpkg.com` with automatic fallback to `cdn.jsdelivr.net`.
- **Supported 1D/2D Formats:** EAN-13, EAN-8, UPC-A, UPC-E, Code-128, Code-39, QR Code.
- **Engine Configuration:**
  - **Full-Frame Decoding:** Runs at 10 FPS without fixed `qrbox` boundaries, eliminating `config.qrbox dimensions should not be greater than root element` exceptions.
  - **Non-Destructive CSS:** Retains complete canvas buffer resolution (no `width:0`/`height:0` canvas destruction), allowing ZXing full access to raw image frames.
  - **Adaptive Constraint Ladder:**
    - *Mobile Phones:* Auto-selects rear environment camera (`facingMode: "environment"`) with front camera fallback.
    - *Desktop/POS Terminals:* Connects directly to webcam (`facingMode: "user"`), avoiding `OverconstrainedError`.
  - **Stream Track Optimizations:** Automatically applies `playsinline`, `autoplay`, and continuous autofocus/autoexposure where supported by hardware.
  - **Debounce Protection:** 1.2-second scan throttle prevents duplicate network calls when an item remains in the camera's field of view.
  - **Manual Barcode Fallback:** Dedicated manual SKU/barcode entry input allows cashier and customer to enter items if the physical barcode is torn or unreadable.
  - **Hardware Scanners:** Native keyboard wedge support for USB and Bluetooth 1D/2D barcode guns.

> **Note on Mobile Browsers:** Mobile operating systems (iOS Safari, Android Chrome) enforce camera access **only under Secure Contexts (HTTPS)** or `localhost`. When deploying to production, ensure traffic is served over HTTPS.

---

## ⚙️ Environment Variables (Optional)

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `ENVIRONMENT` | `production` | Enables HTTPS redirects and security headers |
| `DEBUG` | `false` | Controls SQL query logging |
| `DATABASE_URL` | `sqlite+aiosqlite:///./fastshop.db` | Supports SQLite or Render PostgreSQL (`postgres://` is auto-converted) |
| `CORS_ORIGINS` | `https://*.onrender.com` | Allowed CORS origins for external integrations |
| `BASE_ITEM_SCAN_SECONDS`| `2.5` | Average scan time per item for queue wait time estimates |
| `BASE_PAYMENT_SECONDS`  | `20.0` | Average payment duration |

---

## 📜 License

MIT License. Designed and engineered for high-throughput retail deployments.
