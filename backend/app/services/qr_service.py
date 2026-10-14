import io
import base64
from typing import Optional
from starlette.concurrency import run_in_threadpool
import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers.pil import RoundedModuleDrawer
from qrcode.image.styles.colormasks import SolidFillColorMask


def _generate_qr_png_bytes_sync(payload: str) -> bytes:
    """
    Synchronous CPU-bound QR generation helper with custom styling.
    Must be called via run_in_threadpool to keep the async event loop non-blocking.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=3,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=RoundedModuleDrawer(),
        color_mask=SolidFillColorMask(
            back_color=(255, 255, 255),
            front_color=(15, 23, 42)  # Ink dark FastShop color
        )
    )

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


class QRService:
    @staticmethod
    async def generate_qr_bytes(payload: str) -> bytes:
        """
        Non-blocking async wrapper that offloads QR rendering to threadpool.
        """
        return await run_in_threadpool(_generate_qr_png_bytes_sync, payload)

    @staticmethod
    async def generate_qr_base64(payload: str) -> str:
        """
        Returns Base64 Data URL ready to be embedded directly into HTML/JSON.
        """
        png_bytes = await QRService.generate_qr_bytes(payload)
        b64 = base64.b64encode(png_bytes).decode("utf-8")
        return f"data:image/png;base64,{b64}"


qr_service = QRService()
