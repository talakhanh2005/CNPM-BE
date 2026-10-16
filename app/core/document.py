"""Plain MongoDB document models: a dataclass per collection, no ORM."""

from dataclasses import dataclass, field, fields
from typing import ClassVar


@dataclass(kw_only=True, eq=False)
class Document:
    """Base for collection documents; compared by identity so sessions can track instances."""

    __collection__: ClassVar[str]

    @classmethod
    def stored_fields(cls):
        return [f.name for f in fields(cls) if f.metadata.get("stored", True)]

    @classmethod
    def from_doc(cls, doc):
        """Build an instance from a Mongo document; `_id` and unknown keys are ignored."""
        names = set(cls.stored_fields())
        return cls(**{key: value for key, value in doc.items() if key in names})

    def to_doc(self):
        return {name: getattr(self, name) for name in self.stored_fields()}


def not_stored(default_factory):
    """A field kept on the instance only (for example the joined participants of a meeting)."""
    return field(default_factory=default_factory, metadata={"stored": False})
