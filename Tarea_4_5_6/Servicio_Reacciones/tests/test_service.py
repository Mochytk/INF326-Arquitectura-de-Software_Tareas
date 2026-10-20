import asyncio
import json
import logging
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, settings
from app.core.database import Base, get_db
from app.core.errors import EventPublishError, validation_exception_handler
from app.core.version import VERSION
from app.main import app
from app.models.outbox import OutboxEvent
from app.models.reaction import Reaction
from app.schemas.error import ErrorResponse
from app.services.event_producer import RabbitMQEventProducer
from app.services.outbox import dispatch_pending_events, run_outbox

logging.disable(logging.CRITICAL)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{directory}/test.db")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.producer = RabbitMQEventProducer()
        self.stack.enter_context(patch.multiple(
            settings, EVENTS_ENABLED=False, EVENTS_REQUIRED=False,
            EXTERNAL_VALIDATION_ENABLED=False,
        ))
        self.stack.enter_context(patch("app.main.engine", self.engine))
        self.stack.enter_context(patch("app.main.event_producer", self.producer))
        self.stack.enter_context(patch("app.services.event_producer.event_producer", self.producer))
        self.stack.enter_context(patch("app.services.outbox.event_producer", self.producer))
        self.stack.enter_context(patch("app.services.outbox.AsyncSessionLocal", self.sessions))

        async def database_override():
            async with self.sessions() as session:
                yield session

        app.dependency_overrides[get_db] = database_override
        self.stack.callback(app.dependency_overrides.pop, get_db)
        self.client = self.stack.enter_context(TestClient(app, raise_server_exceptions=False))
        self.payload = {"message_id": "msg-test", "user_id": "usr-test", "reaction_type": "like"}

    def post(self, **changes):
        return self.client.post("/api/v1/reactions", json={**self.payload, **changes})

    def count(self, model):
        async def query():
            async with self.sessions() as db:
                return await db.scalar(select(func.count()).select_from(model))
        return self.client.portal.call(query)

    def events(self):
        async def query():
            async with self.sessions() as db:
                result = await db.execute(select(OutboxEvent).order_by(OutboxEvent.created_at))
                return [row.payload for row in result.scalars()]
        return self.client.portal.call(query)

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.text)
        parsed = ErrorResponse.model_validate(response.json())
        self.assertEqual(parsed.error.code, code)

    def test_invalid_reaction_is_422_and_service_still_works(self):
        self.assert_error(self.post(reaction_type="not valid!"), 422, "validation_error")
        self.assertEqual(self.post().status_code, 201)

    def test_validation_handles_missing_wrong_type_and_nonfinite_values(self):
        for value in ("", "  ", 123, None, float("nan")):
            with self.subTest(value=value):
                response = self.client.post(
                    "/api/v1/reactions", content=json.dumps({**self.payload, "reaction_type": value}),
                    headers={"Content-Type": "application/json"},
                )
                self.assert_error(response, 422, "validation_error")
        self.assert_error(self.client.post("/api/v1/reactions", json={}), 422, "validation_error")

    def test_validation_safely_omits_nonserializable_context(self):
        exc = RequestValidationError([{
            "type": "value_error", "loc": ("body", "reaction_type"),
            "msg": "Value error", "ctx": {"error": ValueError("invalid")}, "input": b"\xff",
        }])
        response = self.client.portal.call(validation_exception_handler, None, exc)
        detail = json.loads(response.body)["error"]["details"][0]
        self.assertEqual(detail, {
            "type": "value_error", "loc": ["body", "reaction_type"], "msg": "Value error",
        })

    def test_http_errors_have_uniform_shape_and_allow_header(self):
        self.assert_error(self.client.get("/missing"), 404, "http_error")
        response = self.client.put("/api/v1/reactions")
        self.assert_error(response, 405, "http_error")
        self.assertIn("POST", response.headers["allow"])
        response = self.client.post(
            "/api/v1/reactions", content=b'{"message_id":"\xff"}',
            headers={"Content-Type": "application/json"},
        )
        self.assert_error(response, 400, "http_error")
        self.assert_error(self.client.post(
            "/api/v1/reactions", content="{", headers={"Content-Type": "application/json"},
        ), 422, "validation_error")

    def test_crud_duplicate_summary_and_missing_resources(self):
        created = self.post(reaction_type=" LIKE ")
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["reaction_type"], "like")
        self.assert_error(self.post(), 409, "duplicate_reaction")
        listing = self.client.get("/api/v1/messages/msg-test/reactions").json()
        self.assertEqual(listing["total_reactions"], 1)
        self.assertEqual(listing["summary"], [{"reaction_type": "like", "count": 1}])
        self.assert_error(self.post(message_id="not-found"), 404, "message_not_found")
        self.assert_error(self.post(user_id="not-found"), 404, "user_not_found")
        path = "/api/v1/reactions/" + created.json()["id"]
        deleted = self.client.delete(path)
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(deleted.content, b"")
        self.assert_error(self.client.delete(path), 404, "reaction_not_found")
        self.assertEqual(self.count(OutboxEvent), 0)

    def test_database_error_and_recovery(self):
        with patch.object(AsyncSession, "execute", new=AsyncMock(side_effect=OperationalError(
            "SELECT", {}, Exception("simulated database failure"),
        ))):
            self.assert_error(self.client.get("/api/v1/messages/msg-test/reactions"), 500, "database_error")
            self.assert_error(self.client.get("/health"), 503, "service_unavailable")
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.post().status_code, 201)

    def test_health_timeout(self):
        async def stalled_query(*args, **kwargs):
            await asyncio.sleep(10)
        with patch.object(settings, "HEALTHCHECK_TIMEOUT_SECONDS", 0.01), patch.object(
            AsyncSession, "execute", new=stalled_query,
        ):
            self.assert_error(self.client.get("/health"), 503, "service_unavailable")

    def test_health_reports_optional_and_required_broker(self):
        with patch.multiple(settings, EVENTS_ENABLED=True, EVENTS_REQUIRED=False):
            response = self.client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "degraded")
            with patch.object(settings, "EVENTS_REQUIRED", True):
                self.assert_error(self.client.get("/health"), 503, "service_unavailable")

    def test_external_timeout_is_controlled_and_writes_nothing(self):
        with patch.object(settings, "EXTERNAL_VALIDATION_ENABLED", True), patch(
            "app.services.external.httpx.AsyncClient.get",
            new=AsyncMock(side_effect=httpx.ReadTimeout("simulated timeout")),
        ):
            self.assert_error(self.post(), 503, "external_service_unavailable")
        self.assertEqual(self.count(Reaction), 0)

    def test_external_unexpected_response(self):
        with patch.object(settings, "EXTERNAL_VALIDATION_ENABLED", True), patch(
            "app.services.external.httpx.AsyncClient.get", new=AsyncMock(return_value=httpx.Response(401)),
        ):
            self.assert_error(self.post(), 502, "external_validation_failed")

    def test_unexpected_error_does_not_stop_service(self):
        with patch("app.api.v1.reactions.validate_message_exists", new=AsyncMock(side_effect=RuntimeError("test"))):
            self.assert_error(self.post(), 500, "internal_error")
        self.assertEqual(self.post().status_code, 201)

    def test_required_broker_unavailable_rejects_before_create_or_delete(self):
        created = self.post()
        path = "/api/v1/reactions/" + created.json()["id"]
        with patch.multiple(settings, EVENTS_ENABLED=True, EVENTS_REQUIRED=True), patch.object(
            self.producer, "connect", new=AsyncMock(side_effect=EventPublishError("unavailable")),
        ):
            self.assert_error(self.post(message_id="new"), 503, "event_publish_failed")
            self.assert_error(self.client.delete(path), 503, "event_publish_failed")
        self.assertEqual(self.count(Reaction), 1)
        self.assertEqual(self.count(OutboxEvent), 0)

    def test_required_broker_check_timeout(self):
        async def stalled_connect():
            await asyncio.sleep(10)
        with patch.multiple(settings, EVENTS_ENABLED=True, EVENTS_REQUIRED=True, EVENT_TIMEOUT_SECONDS=0.01), patch.object(
            self.producer, "connect", new=stalled_connect,
        ):
            self.assert_error(self.post(), 503, "event_publish_failed")
        self.assertEqual(self.count(Reaction), 0)

    def test_broker_failure_after_commit_does_not_change_success_response(self):
        with patch.multiple(settings, EVENTS_ENABLED=True, EVENTS_REQUIRED=True), patch.object(
            self.producer, "connect", new=AsyncMock(),
        ), patch.object(self.producer, "publish", new=AsyncMock(return_value=False)):
            created = self.post()
            self.assertEqual(created.status_code, 201, created.text)
            self.assertEqual(self.client.portal.call(dispatch_pending_events), 0)
            self.assertEqual(self.count(Reaction), 1)
            self.assertEqual(self.count(OutboxEvent), 1)
            self.assertEqual(self.client.delete("/api/v1/reactions/" + created.json()["id"]).status_code, 204)
            self.assertEqual(self.count(Reaction), 0)
            self.assertEqual(self.count(OutboxEvent), 2)

    def test_event_retries_keep_identity_and_recovery_drains_outbox(self):
        with patch.object(settings, "EVENTS_ENABLED", True):
            self.assertEqual(self.post().status_code, 201)
            event_id = self.events()[0]["event_id"]
            failed = AsyncMock(return_value=False)
            with patch.object(self.producer, "publish", new=failed):
                self.assertEqual(self.client.portal.call(dispatch_pending_events), 0)
            self.assertEqual(self.events()[0]["event_id"], event_id)
            delivered = AsyncMock(return_value=True)
            with patch.object(self.producer, "publish", new=delivered):
                self.assertEqual(self.client.portal.call(dispatch_pending_events), 1)
            self.assertEqual(delivered.call_args.args[0].event_id, event_id)
            self.assertEqual(self.count(OutboxEvent), 0)

    def test_create_rolls_back_reaction_and_event_when_commit_fails(self):
        with patch.object(settings, "EVENTS_ENABLED", True), patch.object(
            AsyncSession, "commit", new=AsyncMock(side_effect=SQLAlchemyError("simulated commit failure")),
        ):
            self.assert_error(self.post(), 500, "database_error")
        self.assertEqual(self.count(Reaction), 0)
        self.assertEqual(self.count(OutboxEvent), 0)

    def test_delete_rolls_back_reaction_and_event_when_commit_fails(self):
        created = self.post()
        with patch.object(settings, "EVENTS_ENABLED", True), patch.object(
            AsyncSession, "commit", new=AsyncMock(side_effect=SQLAlchemyError("simulated commit failure")),
        ):
            self.assert_error(self.client.delete("/api/v1/reactions/" + created.json()["id"]), 500, "database_error")
        self.assertEqual(self.count(Reaction), 1)
        self.assertEqual(self.count(OutboxEvent), 0)

    def test_outbox_survives_database_reopening(self):
        with patch.object(settings, "EVENTS_ENABLED", True):
            self.assertEqual(self.post().status_code, 201)
        event_id = self.events()[0]["event_id"]
        self.client.portal.call(self.engine.dispose)
        self.assertEqual(self.events()[0]["event_id"], event_id)

    def test_acknowledged_event_is_retained_if_cleanup_commit_fails(self):
        with patch.object(settings, "EVENTS_ENABLED", True):
            self.assertEqual(self.post().status_code, 201)
            event_id = self.events()[0]["event_id"]
            publisher = AsyncMock(return_value=True)
            with patch.object(self.producer, "publish", new=publisher):
                with patch.object(AsyncSession, "commit", new=AsyncMock(side_effect=SQLAlchemyError("cleanup failed"))):
                    with self.assertRaises(SQLAlchemyError):
                        self.client.portal.call(dispatch_pending_events)
                self.assertEqual(self.events()[0]["event_id"], event_id)
                self.assertEqual(self.client.portal.call(dispatch_pending_events), 1)
            self.assertEqual([call.args[0].event_id for call in publisher.call_args_list], [event_id, event_id])
        self.assertEqual(self.count(OutboxEvent), 0)

    def test_required_events_cannot_be_disabled_by_configuration(self):
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, EVENTS_ENABLED=False, EVENTS_REQUIRED=True)

    def test_background_worker_recovers_pending_events(self):
        with patch.multiple(settings, EVENTS_ENABLED=True, OUTBOX_POLL_INTERVAL_SECONDS=0.01):
            self.assertEqual(self.post().status_code, 201)

            async def exercise_worker():
                with patch.object(self.producer, "connect", new=AsyncMock()), patch.object(
                    self.producer, "publish", new=AsyncMock(side_effect=[False, True]),
                ):
                    worker = asyncio.create_task(run_outbox())
                    try:
                        async with asyncio.timeout(2):
                            while True:
                                async with self.sessions() as db:
                                    remaining = await db.scalar(select(func.count()).select_from(OutboxEvent))
                                if remaining == 0:
                                    break
                                await asyncio.sleep(0.01)
                    finally:
                        worker.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await worker

            self.client.portal.call(exercise_worker)
        self.assertEqual(self.count(OutboxEvent), 0)

    def test_openapi_documents_real_error_schema_and_version(self):
        schema = self.client.get("/openapi.json").json()
        self.assertEqual(schema["info"]["version"], VERSION)
        self.assertEqual(VERSION, Path("VERSION").read_text().strip())
        self.assertEqual(schema, json.loads(Path("docs/openapi.json").read_text()))
        responses = schema["paths"]["/api/v1/reactions"]["post"]["responses"]
        for status in ("400", "404", "405", "409", "422", "500", "502", "503"):
            self.assertTrue(responses[status]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse"))
        self.assertIn("pattern", schema["components"]["schemas"]["ReactionCreate"]["properties"]["reaction_type"])
        for path in ("/docs", "/redoc"):
            self.assertEqual(self.client.get(path).status_code, 200)


if __name__ == "__main__":
    unittest.main()
