from fastapi import APIRouter, Depends, HTTPException

from backend.dependencies import get_z2
from backend.services import gear
from zone2.core import Zone2

router = APIRouter()


@router.get("")
def list_gear(z2: Zone2 = Depends(get_z2)):
    """Every gear item with its activity rollup — powers the rotation timeline."""
    return gear.gear_list(z2)


@router.get("/{gear_id}")
def gear_detail(gear_id: str, z2: Zone2 = Depends(get_z2)):
    detail = gear.gear_detail(z2, gear_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Unknown gear id {gear_id}")
    return detail
