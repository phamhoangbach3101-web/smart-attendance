"""Pydantic request bodies (responses are plain dicts built by the services)."""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ClassIn(BaseModel):
    name: str = Field(..., max_length=64)
    description: str = Field('', max_length=200)


class ClassPatch(BaseModel):
    description: str = Field('', max_length=200)


class CourseIn(BaseModel):
    class_name: str = Field(..., max_length=64)
    subject: str = Field(..., max_length=64)
    subject_name: str = Field('', max_length=120)


class CoursePatch(BaseModel):
    subject_name: str = Field('', max_length=120)


class StudentPatch(BaseModel):
    student_id: Optional[str] = Field(None, max_length=64)
    full_name: Optional[str] = Field(None, max_length=120)


class SessionIn(BaseModel):
    class_name: str = Field(..., max_length=64)
    subject: str = Field(..., max_length=64)
    slot: int = Field(..., ge=1, le=20)
    duration_minutes: Optional[int] = Field(15, ge=1, le=600, description='null = không giới hạn')
    camera_type: Literal['browser', 'rtsp'] = 'browser'
    reopen: bool = False


class ReopenIn(BaseModel):
    duration_minutes: Optional[int] = Field(15, ge=1, le=600)
    camera_type: Literal['browser', 'rtsp'] = 'browser'


class RtspStartIn(BaseModel):
    url: Optional[str] = Field(None, max_length=500)
    use_saved: bool = False
    record: bool = True


class RtspPatch(BaseModel):
    record: bool


class SettingsIn(BaseModel):
    cosine_threshold: Optional[float] = None
    adaface_cosine_threshold: Optional[float] = None
    min_margin: Optional[float] = None
    detection_threshold: Optional[float] = None
    preprocessing: Optional[bool] = None
    antispoof_mode: Optional[Literal['off', 'model', 'texture_experimental']] = None
    antispoof_threshold: Optional[float] = None
    frame_rate: Optional[float] = None
    default_duration_minutes: Optional[int] = None
    rtsp_url: Optional[str] = Field(None, max_length=500)


class ImportCommitIn(BaseModel):
    session_token: str
    overrides: Optional[dict] = None
    default_conflict: Optional[str] = 'skip'
    default_class: Optional[str] = None

