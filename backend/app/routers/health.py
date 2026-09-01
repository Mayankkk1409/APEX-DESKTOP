from fastapi import APIRouter, Depends

from app.config import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "status": "ok",
        "env": settings.app_env,
        "market_adapter": "alpaca" if settings.alpaca_keys_present else "demo",
        "data_feed": "opra" if settings.alpaca_trading_mode == "live" and settings.alpaca_keys_present else "indicative",
    }
