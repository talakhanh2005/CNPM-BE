from contextlib import contextmanager
from copy import deepcopy
from urllib.parse import urlparse

from pymongo import ASCENDING, MongoClient

from app.modules.analysis.model import AnalysisResult
from app.modules.auth.model import RefreshSession
from app.modules.emotions.model import EmotionSample
from app.modules.materials.model import Material
from app.modules.meetings.model import Meeting, Participant


def _database_name(uri: str) -> str:
    parsed = urlparse(uri)
    name = parsed.path.lstrip("/").split("/", 1)[0]
    return name or "face_emotion"


# Fields that identify one document of each model; everything else uses ``id``.
KEYS = {
    RefreshSession: ("jti",),
    Participant: ("meeting_id", "user_id"),
    AnalysisResult: ("recording_id",),
}


def key_fields(model):
    return KEYS.get(model, ("id",))


def model_from_doc(model, doc):
    if doc is None:
        return None
    data = {key: value for key, value in doc.items() if key != "_id"}
    # Documents written before these fields existed get the same defaults as new ones.
    if model is EmotionSample:
        data.setdefault("face_detected", True)
        data.setdefault("logged", True)
    if model is Material:
        data.setdefault("shared_with_all", True)
    if model is Meeting:
        data.setdefault("mode", "realtime")
        data.pop("participants", None)
    return model.from_doc(data)


def doc_from_model(instance):
    return instance.to_doc()


def collection_name(model):
    return model.__collection__


def key_filter(instance):
    return {name: getattr(instance, name) for name in key_fields(type(instance))}


class MongoSession:
    """Unit of work over pymongo: tracked documents are written back as `$set` on commit."""

    def __init__(self, database):
        self.database = database
        self._tracked = []
        self._snapshots = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def collection(self, name):
        return self.database[name]

    def get(self, model, key):
        names = key_fields(model)
        values = key if isinstance(key, tuple) else (key,)
        doc = self.collection(collection_name(model)).find_one(dict(zip(names, values)))
        instance = model_from_doc(model, doc)
        if instance is None:
            return None
        if model is Meeting:
            instance.participants = self.participants_of(key)
        self._track(instance)
        self._snapshots[id(instance)] = deepcopy(doc_from_model(instance))
        return instance

    def participants_of(self, meeting_id):
        docs = self.collection("participants").find({"meeting_id": meeting_id})
        return [model_from_doc(Participant, item) for item in docs]

    def _track(self, instance):
        if all(existing is not instance for existing in self._tracked):
            self._tracked.append(instance)

    def add(self, instance):
        self._track(instance)

    def merge(self, instance):
        self.add(instance)
        self.flush()
        return instance

    def flush(self):
        for instance in self._tracked:
            current = doc_from_model(instance)
            previous = self._snapshots.get(id(instance))
            changed = (
                current
                if previous is None
                else {key: value for key, value in current.items() if previous.get(key) != value}
            )
            if changed:
                self.collection(collection_name(type(instance))).update_one(
                    key_filter(instance), {"$set": changed}, upsert=previous is None
                )
            self._snapshots[id(instance)] = deepcopy(current)

    def commit(self):
        self.flush()

    def rollback(self):
        self._tracked.clear()
        self._snapshots.clear()

    def refresh(self, instance):
        values = tuple(key_filter(instance).values())
        fresh = self.get(type(instance), values if len(values) > 1 else values[0])
        if fresh:
            for key, value in doc_from_model(fresh).items():
                setattr(instance, key, value)
            if isinstance(instance, Meeting):
                instance.participants = fresh.participants
            self._snapshots[id(instance)] = deepcopy(doc_from_model(instance))
        return instance

    def expire_all(self):
        return None


class MongoDatabase:
    def __init__(self, uri: str):
        self.uri = uri
        self.client = None
        self.database = None

    def connect(self):
        if self.client is None:
            self.client = MongoClient(self.uri, tz_aware=True)
            self.database = self.client[_database_name(self.uri)]
            self.ensure_indexes()
        return self.database

    @contextmanager
    def session(self):
        yield MongoSession(self.connect())

    def close(self):
        if self.client is not None:
            self.client.close()

    def ping(self):
        self.connect()
        self.client.admin.command("ping")

    def ensure_indexes(self):
        self.database.users.create_index([("email", ASCENDING)], unique=True)
        self.database.refresh_sessions.create_index([("jti", ASCENDING)], unique=True)
        self.database.refresh_sessions.create_index([("user_id", ASCENDING)])
        self.database.meetings.create_index([("id", ASCENDING)], unique=True)
        self.database.meetings.create_index([("code", ASCENDING)], unique=True)
        self.database.meetings.create_index([("teacher_id", ASCENDING)])
        self.database.participants.create_index(
            [("meeting_id", ASCENDING), ("user_id", ASCENDING)], unique=True
        )
        self.database.recordings.create_index([("id", ASCENDING)], unique=True)
        self.database.recordings.create_index([("meeting_id", ASCENDING)])
        self.database.recordings.create_index([("public_id", ASCENDING)], unique=True)
        self.database.recordings.create_index([("status", ASCENDING)])
        self.database.analysis_jobs.create_index([("id", ASCENDING)], unique=True)
        self.database.analysis_jobs.create_index([("recording_id", ASCENDING)], unique=True)
        self.database.analysis_jobs.create_index([("state", ASCENDING), ("lease_until", ASCENDING)])
        self.database.analysis_results.create_index([("recording_id", ASCENDING)], unique=True)
        self.database.emotion_samples.create_index([("id", ASCENDING)], unique=True)
        self.database.emotion_samples.create_index(
            [("meeting_id", ASCENDING), ("timestamp", ASCENDING)]
        )
        self.database.emotion_samples.create_index([("student_id", ASCENDING)])
        self.database.emotion_samples.create_index(
            [
                ("meeting_id", ASCENDING),
                ("student_id", ASCENDING),
                ("logged", ASCENDING),
                ("received_at", -1),
            ]
        )
        self.database.emotion_samples.create_index(
            [("meeting_id", ASCENDING), ("student_id", ASCENDING), ("received_at", -1)]
        )
        self.database.materials.create_index([("id", ASCENDING)], unique=True)
        self.database.materials.create_index([("public_id", ASCENDING)], unique=True)
        self.database.materials.create_index([("meeting_id", ASCENDING), ("created_at", -1)])
        # Merged BE A lookups: public share links, media by public id, history per student.
        self.database.materials.create_index([("share_token", ASCENDING)], sparse=True)
        self.database.meetings.create_index([("recording_public_id", ASCENDING)], sparse=True)
        self.database.participants.create_index([("user_id", ASCENDING)])
        self.database.emotion_segments.create_index(
            [("recording_id", ASCENDING), ("student_id", ASCENDING), ("start_seconds", ASCENDING)]
        )
        self.database.emotion_segments.create_index([("meeting_id", ASCENDING)])
        self.database.emotion_labels.create_index([("id", ASCENDING)], unique=True)
        self.database.emotion_labels.create_index([("user_id", ASCENDING), ("created_at", -1)])


def make_mongo_database(uri: str):
    database = MongoDatabase(uri)
    return database, database.session
