from fastapi import APIRouter

from backend.config import settings

router = APIRouter()


@router.get("")
def client_config():
    """Runtime settings the browser needs. Read on every page load, so keep
    it cheap and free of secrets that aren't already client-visible — the
    CARTO key travels in tile URLs from the browser either way."""
    return {"carto_api_key": settings.carto_api_key}
