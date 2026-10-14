# FASTSHOP — High-Concurrency Async Retail Backend

FASTSHOP is a high-speed retail checkout & queue intelligence platform built on **FastAPI**, **SQLAlchemy 2.0 Async (`asyncpg`)**, **WebSockets**, and **Dynamic QR Generation**.

---

## 🏗️ Architecture & Core Components

```
backend/
├── app/
│   ├── main.py                     # FastAPI app factory, CORS, and lifespan
│   ├── core/
│   │   └── config.py               # Pydantic Settings v2 configuration
│   ├── db/
│   │   ├── session.py              # SQLAlchemy 2.0 async engine & session pool
│   │   └── init_db.py              # Schema creation and seed catalog populator
│   ├── models/
│   │   ├── product.py              # Products & barcodes with indexing
│   │   ├── counter.py              # POS counter registers
│   │   ├── order.py                # Orders & OrderItems with relational integrity
│   │   └── queue.py                # Smart queue tickets
│   ├── schemas/                    # Pydantic v2 validation models
│   ├── services/
│   │   ├── qr_service.py           # Non-blocking QR generator (via run_in_threadpool)
│   │   ├── queue_service.py        # Load-balancing queue allocation algorithm
│   │   └── websocket_manager.py    # Channel pub/sub real-time WebSocket manager
│   └── api/
│       └── v1/
│           ├── router.py           # Master v1 API router
│           └── endpoints/
│               ├── products.py     # Barcode scanning lookup
│               ├── orders.py       # Checkout & QR verification
│               ├── counters.py     # POS load & performance metrics
│               ├── queue.py        # "Find Counter" smart routing
│               └── ws.py           # Live WebSocket stream
└── requirements.txt
```

---

## ⚡ Key Engineering Principles

1. **Non-Blocking First:**
   - QR code generation and PIL image rasterization are offloaded to worker threads via `run_in_threadpool` to prevent event loop stalls.
2. **Database Engine & Session Management:**
   - SQLAlchemy 2.0 async sessions with connection pooling (`pool_size=20`, `max_overflow=10`, `pool_recycle=1800`).
   - Defaults to zero-config async SQLite (`sqlite+aiosqlite:///./fastshop.db`) for immediate testing, and seamlessly connects to PostgreSQL (`postgresql+asyncpg://...`).
3. **Queue Balancing Mathematical Model:**
   - Calculates shortest wait time using counter efficiency factor and item density:
     $$T_{wait}(c) = \sum_{k \in \text{Queue}(c)} \left( \frac{N_{items}(k) \times t_{scan}}{\eta_{counter}} + t_{pay} \right)$$
   - Automatically diverts small baskets ($N \le 5$) to dedicated express lanes.

---

## 🚀 Quickstart & Running the Backend

### 1. Install Dependencies
```bash
cd backend
pip install -r requirements.txt
```

### 2. Start the FastAPI Server
```bash
uvicorn app.main:app --reload --port 8000
```

- **Interactive API Docs (Swagger UI):** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc Documentation:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Health Check:** [http://localhost:8000/health](http://localhost:8000/health)

---

## 📡 API Endpoints Overview

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/products` | Retrieve active store catalog |
| `GET` | `/api/v1/products/barcode/{code}` | Instant barcode lookup for customer scanning |
| `POST` | `/api/v1/orders` | Create order, assign express counter & encode QR |
| `GET` | `/api/v1/orders/{order_num}/qr-image` | Non-blocking dynamic QR PNG stream |
| `POST` | `/api/v1/orders/verify-qr` | Cashier POS scans customer QR & marks verified |
| `POST` | `/api/v1/queue/allocate` | "Find Counter" AI smart queue router |
| `GET` | `/api/v1/counters/{num}/metrics` | Real-time POS metrics (throughput, line size) |
| `WS` | `/api/v1/ws/counter/{num}` | Real-time WebSocket feed for counter terminal |
