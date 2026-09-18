from contextlib import contextmanager
from urllib.parse import urlparse

from pymongo import ASCENDING, MongoClient

from app.modules.analysis.model import AnalysisJob, AnalysisResult
from app.modules.auth.model import RefreshSession, User
from app.modules.emotions.model import EmotionSample
from app.modules.meetings.model import Meeting, Participant
from app.modules.recordings.model import Recording


def _database_name(uri: str) -> str:
    parsed = urlparse(uri)
    name = parsed.path.lstrip("/").split("/", 1)[0]
    return name or "face_emotion"


def model_from_doc(model, doc):
    if doc is None:
        return None
    data = {key: value for key, value in doc.items() if key != "_id"}
    if model is Meeting:
        participants = data.pop("participants", [])
        instance = model(**data)
        instance.participants = [model_from_doc(Participant, p) for p in participants]
        return instance
    return model(**data)


def doc_from_model(instance):
    return {
        column.name: getattr(instance, column.name)
        for column in instance.__table__.columns
        if hasattr(instance, column.name)
    }


def collection_name(model):
    return model.__tablename__


def key_filter(instance):
    if isinstance(instance, RefreshSession):
        return {"jti": instance.jti}
    if isinstance(instance, Participant):
        return {"meeting_id": instance.meeting_id, "user_id": instance.user_id}
    if isinstance(instance, AnalysisResult):
        return {"recording_id": instance.recording_id}
    return {"id": instance.id}


class MongoSession:
    def __init__(self, database):
        self.database = database
        self._tracked = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def collection(self, name):
        return self.database[name]

    @property
    def is_mongo(self):
        return True

    def get(self, model, key):
        if model is User:
            instance = model_from_doc(User, self.collection("users").find_one({"id": key}))
        if model is RefreshSession:
            instance = model_from_doc(
                RefreshSession, self.collection("refresh_sessions").find_one({"jti": key})
            )
        if model is Meeting:
            instance = model_from_doc(Meeting, self.collection("meetings").find_one({"id": key}))
            if instance is not None:
                participants = list(self.collection("participants").find({"meeting_id": key}))
                instance.participants = [model_from_doc(Participant, item) for item in participants]
        if model is Participant:
            meeting_id, user_id = key
            instance = model_from_doc(
                Participant,
                self.collection("participants").find_one(
                    {"meeting_id": meeting_id, "user_id": user_id}
                ),
            )
        if model is Recording:
            instance = model_from_doc(Recording, self.collection("recordings").find_one({"id": key}))
        if model is AnalysisJob:
            instance = model_from_doc(
                AnalysisJob, self.collection("analysis_jobs").find_one({"id": key})
            )
        if model is AnalysisResult:
            instance = model_from_doc(
                AnalysisResult,
                self.collection("analysis_results").find_one({"recording_id": key}),
            )
        if model is EmotionSample:
            instance = model_from_doc(
                EmotionSample, self.collection("emotion_samples").find_one({"id": key})
            )
        if "instance" not in locals():
            raise TypeError(f"Unsupported model: {model!r}")
        if instance is not None:
            self._track(instance)
        return instance

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
            self.collection(collection_name(type(instance))).update_one(
                key_filter(instance), {"$set": doc_from_model(instance)}, upsert=True
            )

    def commit(self):
        self.flush()
        return None

    def rollback(self):
        return None

    def refresh(self, instance):
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
            self.client = MongoClient(self.uri)
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


def make_mongo_database(uri: str):
    database = MongoDatabase(uri)
    return database, database.session
