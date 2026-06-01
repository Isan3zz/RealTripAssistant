"""
api/preferences.py — 用户偏好 API
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from travel_planning_agent.db.session import get_db
from travel_planning_agent.db.models import User, UserPreference

router = APIRouter(prefix="/api/users", tags=["偏好管理"])


class PreferenceResponse(BaseModel):
    key: str
    base_value: dict
    confidence: float
    conditional_values: list | None
    last_updated: str


class SetPreferenceRequest(BaseModel):
    key: str
    value: dict
    context: dict | None = None


@router.get("/{user_id}/preferences", response_model=list[PreferenceResponse])
def list_preferences(user_id: str, db: DBSession = Depends(get_db)):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(404, "用户不存在")
    prefs = db.query(UserPreference).filter(UserPreference.user_id == user_id).all()
    return [
        PreferenceResponse(
            key=p.pref_key,
            base_value=p.base_value,
            confidence=p.confidence,
            conditional_values=p.conditional_values,
            last_updated=p.last_updated.isoformat(),
        )
        for p in prefs
    ]


@router.post("/{user_id}/preferences")
def set_preference(user_id: str, req: SetPreferenceRequest, db: DBSession = Depends(get_db)):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(404, "用户不存在")

    pref = db.query(UserPreference).filter(
        UserPreference.user_id == user_id,
        UserPreference.pref_key == req.key,
    ).first()

    if pref:
        if req.context:
            cv = pref.conditional_values or []
            cv.append({"context": req.context, "value": req.value, "confidence": 0.5})
            pref.conditional_values = cv
        else:
            pref.base_value = req.value
    else:
        pref = UserPreference(
            user_id=user_id,
            pref_key=req.key,
            base_value=req.value,
            conditional_values=[{"context": req.context, "value": req.value, "confidence": 0.5}] if req.context else None,
        )
        db.add(pref)

    db.commit()
    return {"status": "saved", "key": req.key}


@router.delete("/{user_id}/preferences/{pref_key}")
def delete_preference(user_id: str, pref_key: str, db: DBSession = Depends(get_db)):
    pref = db.query(UserPreference).filter(
        UserPreference.user_id == user_id,
        UserPreference.pref_key == pref_key,
    ).first()
    if not pref:
        raise HTTPException(404, "偏好不存在")
    db.delete(pref)
    db.commit()
    return {"status": "deleted"}
