import os
import logging
from typing import Any


class Analytics:
    def __init__(self, bot_version: str):
        self.bot_version = bot_version
        self.enabled = False
        self._client = None

        api_key = os.getenv("POSTHOG_API_KEY")
        if not api_key:
            return

        host = os.getenv("POSTHOG_HOST", "https://app.posthog.com")
        debug = os.getenv("POSTHOG_DEBUG", "false").lower() == "true"

        try:
            from posthog import Posthog
        except Exception as e:
            logging.info("PostHog disabled (missing dependency): %s", e)
            return

        try:
            self._client = Posthog(
                project_api_key=api_key,
                host=host,
                debug=debug,
                on_error=lambda error: logging.warning("PostHog error: %s", error),
            )
            self.enabled = True
        except Exception:
            logging.exception("Failed to initialize PostHog; analytics disabled")
            self._client = None
            self.enabled = False

    def capture(
        self,
        event: str,
        distinct_id: str,
        properties: dict[str, Any] | None = None,
        groups: dict[str, str] | None = None,
    ) -> None:
        if not self.enabled or self._client is None:
            return

        props: dict[str, Any] = {}
        if properties:
            try:
                props.update(properties)
            except Exception:
                pass
        props.setdefault("bot_version", self.bot_version)

        try:
            if groups:
                self._client.capture(event, distinct_id=distinct_id, properties=props, groups=groups)
            else:
                self._client.capture(event, distinct_id=distinct_id, properties=props)
        except Exception:
            logging.exception("PostHog capture failed")

    def shutdown(self) -> None:
        if not self.enabled or self._client is None:
            return
        try:
            self._client.shutdown()
        except Exception:
            logging.exception("PostHog shutdown failed")
