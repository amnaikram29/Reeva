from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.appointment import Appointment
from app.services.appointment_service import (
    cancel_appointment,
    get_appointment,
    list_appointments,
)

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.get("/", response_model=list[Appointment])
async def get_all():
    return await list_appointments()


@router.get("/{appt_id}", response_model=Appointment)
async def get_one(appt_id: str):
    appt = await get_appointment(appt_id)
    if appt is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appt


@router.delete("/{appt_id}", status_code=204)
async def cancel(appt_id: str):
    ok = await cancel_appointment(appt_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Appointment not found")
