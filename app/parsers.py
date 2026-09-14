from typing import Optional, Dict, Any, Literal
from pydantic import BaseModel, Field


class SuccessTextResponse(BaseModel):
    status: Literal["success"] = "success"
    provider: str
    type: Literal["text"] = "text"
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SuccessImageResponse(BaseModel):
    status: Literal["success"] = "success"
    provider: str
    type: Literal["image"] = "image"
    file_path: str
    mime_type: str = "image/png"
    content: Optional[str] = "Image generated successfully."
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    status: Literal["failed"] = "failed"
    provider: str
    error_code: str
    message: str
    retryable: bool = False
    screenshot_path: Optional[str] = None


def format_text_success(provider: str, content: str, duration_seconds: float = 0.0, extra: Optional[Dict[str, Any]] = None) -> dict:
    meta = {"duration_seconds": round(duration_seconds, 2)}
    if extra:
        meta.update(extra)
    return SuccessTextResponse(
        provider=provider,
        content=content,
        metadata=meta
    ).model_dump()


def format_image_success(
    provider: str,
    file_path: str,
    mime_type: str = "image/png",
    content: Optional[str] = "Image generated successfully.",
    extra: Optional[Dict[str, Any]] = None
) -> dict:
    meta = extra or {}
    return SuccessImageResponse(
        provider=provider,
        file_path=file_path,
        mime_type=mime_type,
        content=content,
        metadata=meta
    ).model_dump()


def format_error(provider: str, error_code: str, message: str, retryable: bool = False, screenshot_path: Optional[str] = None) -> dict:
    return ErrorResponse(
        provider=provider,
        error_code=error_code,
        message=message,
        retryable=retryable,
        screenshot_path=screenshot_path
    ).model_dump()
