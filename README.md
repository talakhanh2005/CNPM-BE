# CNPM Backend API

FastAPI backend with MongoDB persistence, JWT authentication, user management, emotion history, and optional Cloudinary media uploads.

## Run locally

Requirements: Python 3.14 and `uv`.

```powershell
Copy-Item .env.example .env
uv sync --group dev
uv run uvicorn cnpm_be.main:app --reload
```

Set `MONGO_URI` in `.env` if MongoDB is not running on `localhost:27017`. OpenAPI docs are available at <http://localhost:8000/docs>.

## Run with Docker

```powershell
Copy-Item .env.example .env
docker compose up --build
```

The API waits for MongoDB health before starting. MongoDB data persists in the `mongo_data` volume. To remove the test database and its data, run `docker compose down -v`.

To create the initial admin, set both `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `.env` before starting the API. The account is created only if that email does not already exist. Change the sample JWT secret before exposing the service outside local development.

Emotion records can be created without media. To upload images or videos, provide valid Cloudinary credentials in `.env`; the API stores the returned URL and public ID with the MongoDB record. Upload size defaults to 10 MiB. Supported extensions default to jpg, jpeg, png, webp, mp4, and mov.

## API map

All routes use the `/api/v1` prefix. Protected routes require `Authorization: Bearer <access_token>`.

| Method | Route | Access | Purpose |
| --- | --- | --- | --- |
| `POST` | `/auth/register` | Public | Create a user |
| `POST` | `/auth/login` | Public | Get an access token; send form fields `username` and `password` |
| `GET` | `/users/me` | User | Read own profile |
| `PUT` | `/users/me` | User | Update own email, display name, or password |
| `GET` | `/users` | Admin | List users (`offset`, `limit`) |
| `GET` | `/users/{user_id}` | Admin | Read a user |
| `PUT` | `/users/{user_id}` | Admin | Update a user, including role |
| `DELETE` | `/users/{user_id}` | Admin | Delete a user |
| `POST` | `/emotions` | User | Create an emotion using multipart `label` and optional `media_file` |
| `GET` | `/emotions` | User | List own emotions (`offset`, `limit`) |
| `GET` | `/emotions/{emotion_id}` | User | Read own emotion |
| `DELETE` | `/emotions/{emotion_id}` | User | Delete own emotion and associated Cloudinary media |

Emotion records are owned by the authenticated user. Other users' emotion IDs return `404`. Password hashes are never included in API responses. Interactive API docs at `/docs` are the canonical request/response schema.

## Classroom API (frontend contract)

The classroom frontend (`D:\CNPM-FE`) talks to a second API surface under `/api`. Every response is wrapped in `{"success", "data", "message"}` and list/detail objects use camelCase keys.

| Method | Route | Access | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/auth/register` | Public | Register with `{username, password, role}` (`role` is `teacher` or `student`) |
| `POST` | `/api/auth/login` | Public | Login with `{username, password, role}`; returns `data.token` and `data.user` |
| `POST` | `/api/rooms` | Teacher | Create a room from `{name, participantMode, emotionRecognition, analysisMode}` |
| `GET` | `/api/rooms/{room_id}` | Participant | Read a room and refresh presence |
| `POST` | `/api/rooms/join` | User | Join a room by `{code}` |
| `POST` | `/api/rooms/{room_id}/leave` | Participant | Leave a room |
| `POST` | `/api/rooms/{room_id}/end` | Host | Close a room |
| `POST` | `/api/rooms/{room_id}/disconnect` | Participant | Soft-disconnect on page unload |
| `GET` | `/api/meetings/history` | User | List rooms hosted by the current user |
| `GET` | `/api/meetings/{room_id}/ice-config` | Participant | WebRTC ICE servers (`data.iceServers`, `data.turn_configured`) |
| `POST` | `/api/meetings/{room_id}/recording` | Participant | Persist recording metadata and mark batch analysis |

Requirements are intentionally lenient to match the frontend: username is at least 3 characters, password at least 4 characters. Passwords are stored with the same Argon2 hasher as `/api/v1` users. Errors use `{"success": false, "data": {"code"}, "message"}` with codes such as `UNAUTHORIZED`, `FORBIDDEN`, `NOT_A_PARTICIPANT`, `ROOM_NOT_FOUND`, `ROOM_CLOSED`.

## Tests

```powershell
uv run --group dev pytest
```
