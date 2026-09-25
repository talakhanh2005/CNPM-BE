from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.modules.emotions.schema import FrameIn


class StrictMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthMessage(StrictMessage):
    type: Literal["AUTH"]
    token: str = Field(min_length=1, max_length=4096)


class JoinMessage(StrictMessage):
    type: Literal["JOIN", "LEAVE"]


class SDP(StrictMessage):
    type: Literal["offer", "answer"]
    sdp: str = Field(min_length=1, max_length=60000)


class DescriptionMessage(StrictMessage):
    type: Literal["OFFER", "ANSWER"]
    target_id: str = Field(min_length=1, max_length=36)
    payload: SDP


class ICE(StrictMessage):
    candidate: str = Field(max_length=8192)
    sdpMid: str | None = Field(default=None, max_length=256)
    sdpMLineIndex: int | None = Field(default=None, ge=0)


class ICEMessage(StrictMessage):
    type: Literal["ICE_CANDIDATE"]
    target_id: str = Field(min_length=1, max_length=36)
    payload: ICE


class StatusPayload(StrictMessage):
    enabled: bool


class StatusMessage(StrictMessage):
    type: Literal["CAMERA_STATUS", "MIC_STATUS"]
    payload: StatusPayload


class FrameMessage(StrictMessage):
    type: Literal["FRAME"]
    payload: FrameIn


ClientMessage = Annotated[
    Union[JoinMessage, DescriptionMessage, ICEMessage, StatusMessage, FrameMessage],
    Field(discriminator="type"),
]
message_adapter = TypeAdapter(ClientMessage)
