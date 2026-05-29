from .common import router as common_router
from .info import router as info_router
from .pairs import router as pairs_router
from .review import router as review_router
from .tiktok import router as tiktok_router
from .youtube import router as youtube_router

__all__ = [
    "common_router",
    "info_router",
    "pairs_router",
    "review_router",
    "tiktok_router",
    "youtube_router",
]
