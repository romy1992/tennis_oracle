import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.src.app.db.session import get_db
from backend.src.app.main import app
from backend.src.app.services.telegram_analytics import (
    compute_telegram_stats,
    list_telegram_events,
    record_telegram_event,
    record_telegram_event_safe,
)
from backend.src.entity.base import Base
from backend.src.entity.telegram_bot_event import TelegramBotEvent


class TelegramAnalyticsServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_record_telegram_event_persists_row(self):
        with self.Session() as session:
            row = record_telegram_event(
                db=session,
                event_type="command",
                action="/schedine",
                telegram_user_id=42,
                chat_id=42,
                username="alice",
                first_name="Alice",
                success=True,
            )
            self.assertIsNotNone(row.id)
            stored = session.scalar(select(TelegramBotEvent).where(TelegramBotEvent.id == row.id))
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertEqual(stored.action, "/schedine")
            self.assertEqual(stored.telegram_user_id, 42)
            self.assertEqual(stored.username, "alice")

    def test_record_telegram_event_safe_swallows_errors(self):
        with patch(
            "backend.src.app.services.telegram_analytics.SessionLocal",
            side_effect=RuntimeError("db down"),
        ):
            record_telegram_event_safe(
                event_type="command",
                action="/start",
                telegram_user_id=1,
            )

    def test_stats_and_list_filters(self):
        now = datetime(2026, 7, 20, 12, 0, 0)
        with self.Session() as session:
            record_telegram_event(
                db=session,
                event_type="command",
                action="/start",
                telegram_user_id=1,
                chat_id=1,
                username="alice",
                created_at=now,
            )
            record_telegram_event(
                db=session,
                event_type="command",
                action="/schedine",
                telegram_user_id=1,
                chat_id=1,
                username="alice",
                created_at=now + timedelta(minutes=1),
            )
            record_telegram_event(
                db=session,
                event_type="command",
                action="/schedine",
                telegram_user_id=2,
                chat_id=2,
                username="bob",
                created_at=now + timedelta(minutes=2),
            )
            record_telegram_event(
                db=session,
                event_type="message",
                action="(message)",
                telegram_user_id=3,
                chat_id=3,
                username="carol",
                created_at=now - timedelta(days=2),
            )

            events = list_telegram_events(
                session,
                action="/schedine",
                limit=10,
                offset=0,
            )
            self.assertEqual(events.total, 2)
            self.assertEqual(len(events.items), 2)
            self.assertTrue(all(item.action == "/schedine" for item in events.items))

            by_user = list_telegram_events(session, username="ali", limit=10, offset=0)
            self.assertEqual(by_user.total, 2)

            stats = compute_telegram_stats(
                session,
                from_date=now.date() - timedelta(days=1),
                to_date=now.date(),
            )

            self.assertEqual(stats.total_events, 3)
            self.assertEqual(stats.unique_users, 2)
            self.assertEqual(stats.top_action, "/schedine")
            self.assertEqual(
                {row.action: row.count for row in stats.by_action},
                {"/schedine": 2, "/start": 1},
            )
            self.assertGreaterEqual(len(stats.by_day), 1)


class TelegramAnalyticsApiTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        from backend.tests.auth_helpers import (
            auth_header_for_admin,
            clear_settings_override,
            create_admin,
            make_test_settings,
            override_settings,
        )

        self._clear_settings_override = clear_settings_override
        self.settings = make_test_settings()
        override_settings(self.settings)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        with self.Session() as session:
            admin = create_admin(session)
            self.auth_headers = auth_header_for_admin(admin, self.settings)

    def tearDown(self):
        self._clear_settings_override()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_events_and_stats_endpoints(self):
        with self.Session() as session:
            record_telegram_event(
                db=session,
                event_type="command",
                action="/partite",
                telegram_user_id=99,
                chat_id=99,
                username="dash",
                first_name="Dash",
                success=True,
            )

        events_response = self.client.get("/api/telegram/events", headers=self.auth_headers)
        self.assertEqual(events_response.status_code, 200)
        events_payload = events_response.json()
        self.assertEqual(events_payload["total"], 1)
        self.assertEqual(events_payload["items"][0]["action"], "/partite")
        self.assertEqual(events_payload["items"][0]["username"], "dash")

        stats_response = self.client.get("/api/telegram/stats", headers=self.auth_headers)
        self.assertEqual(stats_response.status_code, 200)
        stats_payload = stats_response.json()
        self.assertEqual(stats_payload["total_events"], 1)
        self.assertEqual(stats_payload["unique_users"], 1)
        self.assertEqual(stats_payload["top_action"], "/partite")
