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


class DocumentPresentPayload(StrictMessage):
    material_id: str = Field(min_length=1, max_length=64)
    page: int = Field(default=1, ge=1, le=10000)


class DocumentPresentMessage(StrictMessage):
    type: Literal["DOCUMENT_PRESENT"]
    payload: DocumentPresentPayload


class DocumentPagePayload(StrictMessage):
    material_id: str = Field(min_length=1, max_length=64)
    page: int = Field(ge=1, le=10000)


class DocumentPageMessage(StrictMessage):
    type: Literal["DOCUMENT_PAGE"]
    payload: DocumentPagePayload


class EmptyPayload(StrictMessage):
    pass


class DocumentStopMessage(StrictMessage):
    type: Literal["DOCUMENT_STOP"]
    payload: EmptyPayload = Field(default_factory=EmptyPayload)


ClientMessage = Annotated[
    Union[
        JoinMessage,
        DescriptionMessage,
        ICEMessage,
        StatusMessage,
        FrameMessage,
        DocumentPresentMessage,
        DocumentPageMessage,
        DocumentStopMessage,
    ],
    Field(discriminator="type"),
]
message_adapter = TypeAdapter(ClientMessage)
