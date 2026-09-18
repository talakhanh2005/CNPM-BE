BEGIN TRANSACTION;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

GO

-- Running upgrade  -> 43b6b199dfcd

CREATE TABLE users (
    id VARCHAR(36) NOT NULL, 
    email VARCHAR(320) NOT NULL, 
    password_hash VARCHAR(128) NOT NULL, 
    full_name VARCHAR(150) NOT NULL, 
    role VARCHAR(16) NOT NULL, 
    created_at DATETIMEOFFSET NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_user_role CHECK (role IN ('teacher', 'student')), 
    UNIQUE (email)
);

GO

CREATE TABLE meetings (
    id VARCHAR(36) NOT NULL, 
    code VARCHAR(12) NOT NULL, 
    teacher_id VARCHAR(36) NOT NULL, 
    status VARCHAR(16) NOT NULL, 
    created_at DATETIMEOFFSET NOT NULL, 
    ended_at DATETIMEOFFSET NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_meeting_status CHECK (status IN ('scheduled','ongoing','ended')), 
    FOREIGN KEY(teacher_id) REFERENCES users (id), 
    UNIQUE (code)
);

GO

CREATE INDEX ix_meetings_teacher_id ON meetings (teacher_id);

GO

CREATE TABLE refresh_sessions (
    jti VARCHAR(36) NOT NULL, 
    user_id VARCHAR(36) NOT NULL, 
    expires_at DATETIMEOFFSET NOT NULL, 
    revoked_at DATETIMEOFFSET NULL, 
    PRIMARY KEY (jti), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

GO

CREATE INDEX ix_refresh_sessions_user_id ON refresh_sessions (user_id);

GO

CREATE TABLE emotion_samples (
    id VARCHAR(36) NOT NULL, 
    meeting_id VARCHAR(36) NOT NULL, 
    student_id VARCHAR(36) NOT NULL, 
    timestamp DATETIMEOFFSET NOT NULL, 
    emotion VARCHAR(16) NOT NULL, 
    confidence FLOAT NOT NULL, 
    mock BIT NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(meeting_id) REFERENCES meetings (id), 
    FOREIGN KEY(student_id) REFERENCES users (id)
);

GO

CREATE INDEX ix_emotion_meeting_time ON emotion_samples (meeting_id, timestamp);

GO

CREATE INDEX ix_emotion_samples_student_id ON emotion_samples (student_id);

GO

CREATE TABLE participants (
    meeting_id VARCHAR(36) NOT NULL, 
    user_id VARCHAR(36) NOT NULL, 
    status VARCHAR(16) NOT NULL, 
    joined_at DATETIMEOFFSET NOT NULL, 
    left_at DATETIMEOFFSET NULL, 
    PRIMARY KEY (meeting_id, user_id), 
    CONSTRAINT ck_participant_status CHECK (status IN ('joined','left')), 
    FOREIGN KEY(meeting_id) REFERENCES meetings (id) ON DELETE CASCADE, 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

GO

CREATE TABLE recordings (
    id VARCHAR(36) NOT NULL, 
    meeting_id VARCHAR(36) NOT NULL, 
    cloudinary_url VARCHAR(2048) NOT NULL, 
    public_id VARCHAR(256) NOT NULL, 
    format VARCHAR(16) NOT NULL, 
    duration FLOAT NOT NULL, 
    size_bytes INTEGER NOT NULL, 
    status VARCHAR(16) NOT NULL, 
    created_at DATETIMEOFFSET NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_recording_status CHECK (status IN ('uploaded','pending','processing','completed','failed')), 
    CONSTRAINT ck_recording_duration CHECK (duration > 0), 
    FOREIGN KEY(meeting_id) REFERENCES meetings (id), 
    UNIQUE (public_id)
);

GO

CREATE INDEX ix_recordings_meeting_id ON recordings (meeting_id);

GO

CREATE INDEX ix_recordings_status ON recordings (status);

GO

CREATE TABLE analysis_jobs (
    id VARCHAR(36) NOT NULL, 
    recording_id VARCHAR(36) NOT NULL, 
    state VARCHAR(16) NOT NULL, 
    attempts INTEGER NOT NULL, 
    lease_token VARCHAR(36) NULL, 
    lease_until DATETIMEOFFSET NULL, 
    error_message VARCHAR(256) NULL, 
    created_at DATETIMEOFFSET NOT NULL, 
    updated_at DATETIMEOFFSET NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_job_state CHECK (state IN ('pending','processing','completed','failed')), 
    FOREIGN KEY(recording_id) REFERENCES recordings (id), 
    UNIQUE (recording_id)
);

GO

CREATE INDEX ix_analysis_jobs_lease_until ON analysis_jobs (lease_until);

GO

CREATE INDEX ix_analysis_jobs_state ON analysis_jobs (state);

GO

CREATE TABLE analysis_results (
    recording_id VARCHAR(36) NOT NULL, 
    result NVARCHAR(max) NOT NULL, 
    completed_at DATETIMEOFFSET NOT NULL, 
    PRIMARY KEY (recording_id), 
    FOREIGN KEY(recording_id) REFERENCES recordings (id)
);

GO

INSERT INTO alembic_version (version_num) OUTPUT inserted.version_num VALUES ('43b6b199dfcd');

GO

-- Running upgrade 43b6b199dfcd -> 20260915_unicode

ALTER TABLE users ALTER COLUMN full_name NVARCHAR(150) NOT NULL;

GO

ALTER TABLE analysis_jobs ALTER COLUMN error_message NVARCHAR(256) NULL;

GO

UPDATE alembic_version SET version_num='20260915_unicode' WHERE alembic_version.version_num = '43b6b199dfcd';

GO

COMMIT;

GO

