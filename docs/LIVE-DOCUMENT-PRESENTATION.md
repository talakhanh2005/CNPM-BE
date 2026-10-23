# Live document presentation

This feature lets the teacher present a material stored in Cloudinary inside the live meeting UI. PDF pages are synchronized for the whole class. PNG and JPEG images can also be presented. Existing Word, PowerPoint, Excel, and TXT uploads remain downloadable but are not embedded because browsers cannot reliably render authenticated Office files.

## User flow

1. The teacher opens **Tài liệu** in the meeting.
2. The teacher uploads a PDF, PNG, or JPEG, or selects one that was already uploaded.
3. The teacher clicks the `present_to_all` button.
4. The teacher's browser requests the document metadata and a five-minute signed Cloudinary URL from the backend.
5. Only after that request succeeds, the teacher sends `DOCUMENT_PRESENT` through the meeting WebSocket.
6. Every student receives the material ID and requests their own metadata and signed URL.
7. The document viewer replaces the camera grid until the teacher stops the presentation or the student hides it locally.
8. For PDFs, the teacher's page controls broadcast `DOCUMENT_PAGE`. Student viewers update to the same page.
9. `DOCUMENT_STOP` closes the viewer for everyone.

## Why the WebSocket sends only a material ID

Signed Cloudinary URLs are access credentials with a short lifetime. They are never broadcast through signaling. Each client calls:

```http
GET /meetings/{meeting_id}/documents/{material_id}
Authorization: Bearer <access-token>
```

The backend verifies meeting membership and document sharing rules, then returns metadata with a signed URL:

```json
{
  "success": true,
  "data": {
    "id": "material-id",
    "filename": "lesson.pdf",
    "content_type": "application/pdf",
    "download_url": "https://res.cloudinary.com/...signed-attachment...",
    "preview_url": "https://res.cloudinary.com/...signed-inline...",
    "expires_in": 300
  },
  "message": "OK"
}
```

`download_url` keeps the existing attachment behavior. `preview_url` is separately signed with inline delivery for PDF/image presentation. The frontend refreshes these URLs approximately 30 seconds before expiry while the presentation remains open.

## WebSocket protocol

Teacher starts a presentation:

```json
{
  "type": "DOCUMENT_PRESENT",
  "payload": {
    "material_id": "material-id",
    "page": 1
  }
}
```

Teacher changes the PDF page:

```json
{
  "type": "DOCUMENT_PAGE",
  "payload": {
    "material_id": "material-id",
    "page": 3
  }
}
```

Teacher stops presenting:

```json
{
  "type": "DOCUMENT_STOP",
  "payload": {}
}
```

Only the owning teacher may send these messages. Before accepting `DOCUMENT_PRESENT` or `DOCUMENT_PAGE`, the backend verifies that the material exists and belongs to the current meeting. A student attempting to control the presentation receives `FORBIDDEN`.

## Reconnect and late-join behavior

The active presentation is stored in `ConnectionManager`, alongside the existing in-memory room presence. The initial `JOIN` response contains:

```json
{
  "type": "JOIN",
  "presentation": {
    "material_id": "material-id",
    "page": 3
  },
  "peers": []
}
```

This lets refreshed clients and late joiners reopen the current document at the current page. Presentation state is cleared when the teacher sends `DOCUMENT_STOP` or the room closes.

Like the existing signaling presence, this state is local to one API process. A future multi-process deployment must move presence and presentation state to shared pub/sub storage such as Redis.

## Frontend components

- `src/components/MeetingMaterials.jsx` lists/uploads materials and exposes the teacher-only presentation button for PDF and images.
- `src/components/MaterialViewer.jsx` displays PDFs in an iframe, images with an `img` element, and provides teacher PDF page controls.
- `src/pages/Meeting.jsx` owns presentation state, obtains signed URLs, refreshes expiring URLs, and sends/handles presentation events.
- `src/hooks/useWebSocket.js` translates application events to and from the backend wire protocol.
- `src/api/materialApi.js` calls the authorized document-detail endpoint.

## Backend components

- `app/modules/signaling/schema.py` strictly validates presentation messages, material IDs, and page numbers.
- `app/modules/signaling/service.py` enforces teacher ownership and validates the material before broadcasting.
- `app/modules/signaling/manager.py` stores the active per-room presentation and includes it for reconnecting clients.
- `app/modules/signaling/router.py` adds the active presentation to the initial `JOIN` response.
- `app/modules/materials/router.py` supplies authorized metadata and signed URLs through the existing document-detail route.

## Supported formats

| Format | Upload/download | Inline presentation | Page synchronization |
|---|---:|---:|---:|
| PDF | Yes | Yes | Yes |
| PNG/JPG/JPEG | Yes | Yes | Not applicable |
| Word/PowerPoint/Excel/TXT | Yes | No | No |

For Office files, export the document to PDF before uploading. A future conversion service can use a sandboxed LibreOffice worker to create a PDF preview and store its Cloudinary public ID separately. Do not use a public third-party Office viewer for authenticated classroom documents because it requires exposing the signed URL to that service.

## Security properties

- Cloudinary API secrets remain on the backend.
- Stored `public_id` values are not exposed by the material list.
- WebSocket messages contain material IDs, never signed URLs.
- Each participant must pass normal meeting/document authorization before receiving a URL.
- Signed URLs expire after five minutes and document-detail responses use `Cache-Control: no-store`.
- Students cannot start, stop, or change a presentation.
- Invalid material IDs and cross-meeting material IDs are rejected.

## Manual verification

1. Start MongoDB, the backend API, and the frontend.
2. Configure valid `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, and `CLOUDINARY_API_SECRET` values.
3. Open the teacher and student accounts in separate browser sessions.
4. Join the same ongoing meeting.
5. Upload a PDF from the teacher's **Tài liệu** panel.
6. Click the presentation icon and confirm both clients show the PDF.
7. Change the page from the teacher client and confirm the student follows.
8. Refresh the student page and confirm it rejoins the active presentation.
9. Stop the presentation and confirm it closes for both clients.
10. Repeat with PNG or JPEG.

## Automated verification

Backend:

```bash
.venv/bin/python -m pytest -q
```

Frontend:

```bash
npm run lint
npm run build
```

The backend WebSocket test covers teacher authorization, student rejection, presentation broadcast, page synchronization, late-join state, and stop/cleanup behavior.
