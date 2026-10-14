from fastapi import APIRouter
from app.api.v1.endpoints import products, orders, counters, queue, ws, carts, admin, auth, customer

api_v1_router = APIRouter()

api_v1_router.include_router(auth.router)
api_v1_router.include_router(customer.router)
api_v1_router.include_router(products.router)
api_v1_router.include_router(carts.router)
api_v1_router.include_router(orders.router)
api_v1_router.include_router(counters.router)
api_v1_router.include_router(queue.router)
api_v1_router.include_router(ws.router)
api_v1_router.include_router(admin.router)
