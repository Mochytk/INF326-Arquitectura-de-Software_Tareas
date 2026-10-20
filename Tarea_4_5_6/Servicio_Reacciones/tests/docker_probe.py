"""Run inside the isolated API container: python - initial|outage|pending|recovered."""

import asyncio
import json
import sqlite3
import sys
import time

import aio_pika
import httpx

from app.core.config import settings


def wait_for_health(client, predicate):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            response = client.get("/health")
            if response.status_code == 200 and predicate(response.json()):
                return response.json()
        except httpx.TransportError:
            pass
        time.sleep(0.25)
    raise AssertionError("API did not reach expected health state")


def pending_ids():
    with sqlite3.connect("data/reactions.db") as db:
        return sorted(row[0] for row in db.execute("SELECT event_id FROM outbox_events"))


async def consume(count):
    connection = await aio_pika.connect_robust(settings.EVENT_BROKER_URL, timeout=5)
    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue(settings.EVENT_QUEUE, passive=True)
        messages = []
        for _ in range(count):
            message = await queue.get(timeout=5)
            payload = json.loads(message.body)
            assert message.message_id == payload["event_id"]
            await message.ack()
            messages.append(payload)
        return messages


def main():
    stage = sys.argv[1]
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
        if stage == "initial":
            health = wait_for_health(client, lambda body: body["rabbitmq_connected"])
            assert health["version"] == "1.0.1"
            payload = {"message_id": "integration-live", "user_id": "usr", "reaction_type": "LIKE"}
            created = client.post("/api/v1/reactions", json=payload)
            assert created.status_code == 201, created.text
            assert client.post("/api/v1/reactions", json=payload).status_code == 409
            invalid = client.post("/api/v1/reactions", json={**payload, "reaction_type": "not valid!"})
            assert invalid.status_code == 422 and "error" in invalid.json()
            assert client.get("/missing").json()["error"]["code"] == "http_error"
            wait_for_health(client, lambda body: body["outbox_pending"] == 0)
            events = asyncio.run(consume(1))
            assert events[0]["event_type"] == "REACTION_CREATED"
            assert events[0]["data"]["id"] == created.json()["id"]
            print(json.dumps({"stage": stage, "health": health, "consumed": 1}))
        elif stage == "outage":
            wait_for_health(client, lambda body: not body["rabbitmq_connected"])
            payload = {"message_id": "integration-outage", "user_id": "usr", "reaction_type": "like"}
            created = client.post("/api/v1/reactions", json=payload)
            assert created.status_code == 201, created.text
            deleted = client.delete("/api/v1/reactions/" + created.json()["id"])
            assert deleted.status_code == 204, deleted.text
            health = client.get("/health").json()
            assert health["status"] == "degraded" and health["outbox_pending"] == 2
            print(json.dumps({"stage": stage, "health": health, "event_ids": pending_ids()}))
        elif stage == "pending":
            health = wait_for_health(client, lambda body: body["outbox_pending"] == 2)
            assert health["outbox_pending"] == 2 and health["status"] == "degraded"
            print(json.dumps({"stage": stage, "event_ids": pending_ids()}))
        elif stage == "recovered":
            health = wait_for_health(client, lambda body: body["rabbitmq_connected"] and body["outbox_pending"] == 0)
            events = asyncio.run(consume(2))
            assert {event["event_type"] for event in events} == {"REACTION_CREATED", "REACTION_DELETED"}
            assert all(event["data"]["message_id"] == "integration-outage" for event in events)
            expected = sorted(sys.argv[2].split(","))
            assert sorted(event["event_id"] for event in events) == expected
            print(json.dumps({"stage": stage, "health": health, "consumed": 2, "stable_event_ids": True}))
        else:
            raise ValueError("Unknown stage")


if __name__ == "__main__":
    main()
