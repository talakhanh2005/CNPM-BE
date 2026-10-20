"""Export offline OpenAPI, executable Postman regression, and a schema fingerprint."""

import hashlib
import json
from pathlib import Path

from app.core.config import Settings
from app.core.schemas import Envelope
from app.main import create_app
from app.modules.emotions.analytics_schema import AggregateOut

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def request(name, method, path, role=None, body=None, status=200, extra_tests=None, headers=None):
    checks = [
        f"pm.test('HTTP {status}', () => pm.response.to.have.status({status}));",
        "const body = pm.response.json();",
        "pm.test('Envelope', () => { pm.expect(body).to.have.keys('success','data','message'); });",
        f"pm.test('Success flag', () => pm.expect(body.success).to.eql({str(status < 400).lower()}));",
    ]
    checks.extend(extra_tests or [])
    value = {
        "method": method,
        "header": [{"key": "Content-Type", "value": "application/json"}],
        "url": "{{base_url}}" + path,
    }
    if role:
        value["header"].append({"key": "Authorization", "value": "Bearer {{" + role + "_token}}"})
    value["header"].extend(headers or [])
    if body is not None:
        value["body"] = {
            "mode": "raw",
            "raw": json.dumps(body),
            "options": {"raw": {"language": "json"}},
        }
    return {
        "name": name,
        "request": value,
        "event": [{"listen": "test", "script": {"type": "text/javascript", "exec": checks}}],
    }


def main():
    # Inject a factory so export never opens a production DB or reads local secrets.
    settings = Settings(
        _env_file=None,
        jwt_secret="offline-contract-export-secret-00000000",
        ai_api_key="offline-contract-export",
    )
    app = create_app(settings=settings, session_factory=lambda: None)
    write_json(ROOT / "docs/openapi.json", app.openapi())
    write_json(
        ROOT / "docs/emotion-aggregate.schema.json", Envelope[AggregateOut].model_json_schema()
    )
    items = [request("Health", "GET", "/health")]
    for role in ("teacher", "student", "student2", "student3", "outsider", "admin"):
        items.append(
            request(
                f"Login {role}",
                "POST",
                "/auth/login",
                body={"email": "{{" + role + "_email}}", "password": "{{" + role + "_password}}"},
                extra_tests=[
                    f"if (body.success) {{ pm.environment.set('{role}_token', body.data.access_token); }}",
                    "pm.test('JWT fields', () => { pm.expect(body.data.access_token).to.be.a('string'); pm.expect(body.data.refresh_token).to.be.a('string'); });",
                ],
            )
        )
        items.append(
            request(
                f"Identity {role}",
                "GET",
                "/auth/me",
                role=role,
                extra_tests=[
                    f"if (body.success) pm.environment.set('{role}_id', body.data.id);",
                ],
            )
        )
    items.extend(
        [
            request(
                "Create realtime meeting",
                "POST",
                "/meetings",
                "teacher",
                {},
                201,
                [
                    "if (body.success) { pm.environment.set('meeting_id', body.data.id); pm.environment.set('meeting_code', body.data.code); }",
                    "pm.test('Meeting schema', () => { pm.expect(body.data.participants).to.be.an('array'); pm.expect(body.data.student_ids).to.be.an('array'); });",
                ],
            ),
            request("Student cannot create meeting", "POST", "/meetings", "student", {}, 403),
        ]
    )
    for role in ("student", "student2", "student3"):
        items.append(
            request(f"Join {role}", "POST", "/meetings/join", role, {"code": "{{meeting_code}}"})
        )
    items.extend(
        [
            request("Join idempotent", "POST", "/meetings/{{meeting_id}}/join", "student"),
            request(
                "Teacher cannot join other teacher room",
                "POST",
                "/meetings/{{meeting_id}}/join",
                "outsider",
                status=403,
            ),
            request("No auth dashboard", "GET", "/meetings/{{meeting_id}}/dashboard", status=401),
            request(
                "Invalid JWT",
                "GET",
                "/meetings/{{meeting_id}}/dashboard",
                headers=[{"key": "Authorization", "value": "Bearer invalid"}],
                status=401,
            ),
        ]
    )
    for endpoint in ("dashboard", "summary", "report", "emotion-logs"):
        items.extend(
            [
                request(
                    f"Owner {endpoint}", "GET", "/meetings/{{meeting_id}}/" + endpoint, "teacher"
                ),
                request(
                    f"Student denied {endpoint}",
                    "GET",
                    "/meetings/{{meeting_id}}/" + endpoint,
                    "student",
                    status=403,
                ),
                request(
                    f"Cross-owner denied {endpoint}",
                    "GET",
                    "/meetings/{{meeting_id}}/" + endpoint,
                    "outsider",
                    status=403,
                ),
            ]
        )
    items.extend(
        [
            request(
                "Dashboard student filter",
                "GET",
                "/meetings/{{meeting_id}}/dashboard?student_id={{student_id}}",
                "teacher",
                extra_tests=[
                    "pm.test('Analytics schema', () => { pm.expect(body.data.distribution).to.be.an('object'); pm.expect(body.data.trend).to.be.an('array'); pm.expect(body.data.sample_count).to.be.a('number'); });",
                ],
            ),
            request(
                "Paginated log",
                "GET",
                "/meetings/{{meeting_id}}/emotion-logs?offset=0&limit=1",
                "teacher",
                extra_tests=[
                    "pm.test('Pagination', () => { pm.expect(body.data.items.length).to.be.at.most(1); pm.expect(body.data.total).to.be.a('number'); });",
                ],
            ),
            request("Admin users", "GET", "/admin/users", "admin"),
            request("Teacher denied admin", "GET", "/admin/users", "teacher", status=403),
            request("Student denied admin", "GET", "/admin/meetings", "student", status=403),
            request("Student leave", "POST", "/meetings/{{meeting_id}}/leave", "student"),
            request("Student rejoin", "POST", "/meetings/{{meeting_id}}/join", "student"),
            request("Owner end", "POST", "/meetings/{{meeting_id}}/end", "teacher"),
            request(
                "Cannot join ended", "POST", "/meetings/{{meeting_id}}/join", "student", status=409
            ),
        ]
    )
    collection = {
        "info": {
            "name": "Backend 1.2 regression",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "description": "Run with six pre-provisioned users; each run creates a fresh room. WebSocket and ingest regression are covered by pytest.",
        },
        "item": items,
    }
    write_json(ROOT / "docs/backend.postman_collection.json", collection)
    variables = [{"key": "base_url", "value": "http://localhost:8000", "enabled": True}]
    for role in ("teacher", "student", "student2", "student3", "outsider", "admin"):
        variables.extend(
            [
                {"key": role + "_email", "value": "", "enabled": True},
                {"key": role + "_password", "value": "", "type": "secret", "enabled": True},
            ]
        )
    write_json(
        ROOT / "docs/backend.postman_environment.json",
        {"name": "Backend local", "values": variables, "_postman_variable_scope": "environment"},
    )
    paths = (
        "openapi.json",
        "websocket-auth.schema.json",
        "websocket-client.schema.json",
        "emotion-aggregate.schema.json",
    )
    write_json(
        ROOT / "docs/contract-manifest.json",
        {
            "version": "1.2.0",
            "candidate": True,
            "sha256": {
                name: hashlib.sha256((ROOT / "docs" / name).read_bytes()).hexdigest()
                for name in paths
            },
        },
    )
    print(f"Exported OpenAPI, {len(items)} Postman requests, environment and contract manifest")


if __name__ == "__main__":
    main()
