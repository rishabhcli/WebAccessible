from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from backend.app.browser.controller import BrowserController, is_provider_block
from backend.app.config import RuntimeMode, Settings
from backend.app.contracts.models import AgentActionKind
from backend.app.integrations.local_browser import LocalBrowserAdapter
from backend.app.main import cors_origins
from backend.app.persistence.repository import OperationalRepository


class _NavigationHandler(BaseHTTPRequestHandler):
    pages: ClassVar[dict[str, str]] = {
        "/start": """<!doctype html><html><head><title>Local navigation</title></head>
        <body><main><h1>Local navigation</h1>
        <a id="continue" href="/complete">Continue to finish</a></main></body></html>""",
        "/complete": """<!doctype html><html><head><title>Task complete</title></head>
        <body><main><h1>Task complete</h1><p>Navigation worked.</p></main></body></html>""",
    }

    def do_GET(self) -> None:  # noqa: N802
        body = self.pages.get(self.path)
        if body is None:
            self.send_error(404)
            return
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class LocalBrowserIntegrationTests(unittest.TestCase):
    def test_local_chromium_observes_clicks_navigates_and_captures_live_view(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _NavigationHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        temporary_directory = tempfile.TemporaryDirectory()
        repository = OperationalRepository(
            str(Path(temporary_directory.name) / "operations.sqlite3")
        )
        settings = Settings(
            _env_file=None,
            app_env=RuntimeMode.DEVELOPMENT,
            browser_execution_provider="local",
            action_planner_provider="local",
            api_public_url="http://localhost:8000",
        )
        controller = BrowserController(
            adapter=LocalBrowserAdapter(settings),
            repository=repository,
        )
        session_id = uuid4()
        start_url = f"http://127.0.0.1:{server.server_port}/start"

        async def scenario() -> None:
            view = await controller.start(
                web_session_id=session_id,
                user_id="local-user",
                start_url=start_url,
            )
            self.assertIn("/v1/local-browser/local-", view.live_view_url or "")
            candidates = await controller.snapshot(session_id)
            target = next(
                item for item in candidates if item.accessible_name == "Continue to finish"
            )
            outcome = await controller.act(
                session_id,
                action=AgentActionKind.CLICK,
                candidate_id=target.candidate_id,
            )
            self.assertTrue(outcome.performed)
            state = await controller.page_state(session_id)
            self.assertEqual(state.title, "Task complete")
            self.assertEqual(state.redacted_path, "/complete")
            image = await controller.screenshot(view.browserbase_session_id)
            self.assertTrue(image.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertTrue(await controller.stop(session_id, "test_complete"))

        try:
            asyncio.run(scenario())
        finally:
            asyncio.run(controller.stop_all("test_cleanup"))
            repository.close()
            temporary_directory.cleanup()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_provider_navigation_block_pages_are_recognized(self) -> None:
        self.assertTrue(
            is_provider_block("https://www.browserbase.com/navigation-blocked?destination=x")
        )
        self.assertTrue(is_provider_block("https://example.com/", "Navigation Blocked"))
        self.assertFalse(is_provider_block("https://example.com/navigation-blocked"))


class RuntimeConfigurationTests(unittest.TestCase):
    def test_development_defaults_to_local_execution(self) -> None:
        settings = Settings(_env_file=None)

        self.assertTrue(settings.local_browser_enabled)
        self.assertEqual(settings.action_planner_provider, "local")

    def test_production_rejects_local_execution(self) -> None:
        with self.assertRaisesRegex(ValueError, "require Browserbase"):
            Settings(_env_file=None, app_env=RuntimeMode.PRODUCTION)

    def test_development_cors_accepts_both_loopback_hostnames(self) -> None:
        settings = Settings(
            _env_file=None,
            app_public_url="http://localhost:5173",
        )

        self.assertEqual(
            cors_origins(settings),
            ["http://localhost:5173", "http://127.0.0.1:5173"],
        )


if __name__ == "__main__":
    unittest.main()
