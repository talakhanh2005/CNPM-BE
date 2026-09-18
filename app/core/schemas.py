from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    success: bool = True
    data: T
    message: str = "OK"


class ErrorData(BaseModel):
    code: str
    details: list[dict] | None = None


class ErrorEnvelope(Envelope[ErrorData]):
    success: bool = False


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def ok(data=None, message="OK"):
    return {"success": True, "data": data, "message": message}
