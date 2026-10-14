from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.models.product import Product
from app.schemas.product import ProductRead, ProductCreate
from app.core.auth import require_admin
from app.models.user import User

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("", response_model=List[ProductRead])
async def list_products(
    db: AsyncSession = Depends(get_db),
    search: str = "",
    skip: int = 0,
    limit: int = 50
):
    """Retrieve available retail products, optionally filtered by name/barcode search."""
    from sqlalchemy import or_
    stmt = select(Product).where(Product.is_active == True)
    if search.strip():
        q = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            or_(
                Product.name.ilike(q),
                Product.barcode.ilike(q),
                Product.category.ilike(q)
            )
        )
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new product in the live catalog. Used during in-person demos when
    a scanned barcode isn't in the catalog yet - the item is added on the spot
    and is instantly available for every future scan of that barcode.
    If the barcode already exists, update its details instead of duplicating it.
    """
    stmt = select(Product).where(Product.barcode == payload.barcode)
    result = await db.execute(stmt)
    existing = result.scalars().first()

    if existing:
        existing.name = payload.name
        existing.description = payload.description
        existing.price = payload.price
        existing.category = payload.category
        existing.icon = payload.icon
        existing.stock_qty = payload.stock_qty
        existing.is_active = True
        await db.commit()
        await db.refresh(existing)
        return existing

    product = Product(
        barcode=payload.barcode,
        name=payload.name,
        description=payload.description,
        price=payload.price,
        category=payload.category,
        icon=payload.icon,
        stock_qty=payload.stock_qty,
        is_active=True
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


@router.get("/barcode/{barcode}", response_model=ProductRead)
async def get_product_by_barcode(
    barcode: str,
    db: AsyncSession = Depends(get_db)
):
    """Instant barcode lookup for in-aisle customer smartphone scanning."""
    barcode = barcode.strip()
    stmt = select(Product).where(Product.barcode == barcode, Product.is_active == True)
    result = await db.execute(stmt)
    product = result.scalars().first()

    if not product:
        # Fallback for EAN-13 check digit (e.g. 13-digit physical barcode vs 12-digit seed)
        if len(barcode) == 13:
            fallback_stmt = select(Product).where(Product.barcode == barcode[:12], Product.is_active == True)
            res = await db.execute(fallback_stmt)
            product = res.scalars().first()
        elif len(barcode) == 12:
            fallback_stmt = select(Product).where(Product.barcode.startswith(barcode), Product.is_active == True)
            res = await db.execute(fallback_stmt)
            product = res.scalars().first()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with barcode '{barcode}' not found in catalog."
        )
    return product
