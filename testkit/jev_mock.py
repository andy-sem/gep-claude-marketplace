"""A local HTTP stand-in for the Jev classifier service."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Self

HANG_MAX_SECONDS = 10


def probs(unrelated: float, read_only: float, cloud_or_data_change: float, destructive: float) -> dict:
    return {
        "unrelated": unrelated,
        "read_only": read_only,
        "cloud_or_data_change": cloud_or_data_change,
        "destructive": destructive,
    }


class JevMock:
    """Context manager: `.url`, `.answer(...)`, and the recorded `.bodies` / `.hits`."""

    def __init__(self) -> None:
        self.bodies: list[dict | None] = []
        self._answer: dict[str, Any] = {"kind": "ok", "probs": {}, "question": "cloud_change", "usage": None}
        self._release = threading.Event()
        self._lock = threading.Lock()
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers.get("content-length") or 0))
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = None
                with mock._lock:
                    mock.bodies.append(body)
                    a = dict(mock._answer)
                if a["kind"] == "hang":
                    mock._release.wait(HANG_MAX_SECONDS)
                    self.close_connection = True
                    return
                if a["kind"] == "status":
                    self.send_response(a["status"])
                    self.send_header("content-length", "0")
                    self.end_headers()
                    return
                if a["kind"] == "malformed":
                    payload = b"{"
                else:
                    payload = json.dumps(
                        {
                            "answers": {a["question"]: {"type": "choice", "probabilities": a["probs"]}},
                            "usage": a["usage"] or {"input_tokens": 1000, "output_tokens": 10},
                        }
                    ).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._server.block_on_close = False
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/v1/systemone"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def hits(self) -> int:
        return len(self.bodies)

    def answer(
        self,
        probs: dict | None = None,
        *,
        kind: str = "ok",
        status: int | None = None,
        question: str = "cloud_change",
        usage: dict | None = None,
    ) -> None:
        """Set the next answers and reset the recorded requests."""
        if kind == "ok" and status is not None:
            kind = "status"
        if kind == "status" and status is None:
            raise ValueError("answer(kind='status') needs a status code")
        with self._lock:
            self._answer = {"kind": kind, "probs": probs or {}, "status": status, "question": question, "usage": usage}
            self.bodies = []

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._release.set()
        self._server.shutdown()
        self._server.server_close()
