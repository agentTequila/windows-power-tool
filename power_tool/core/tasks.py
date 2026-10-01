import sys
import threading
from typing import Any, Callable, Optional


class BackgroundTask:
    def __init__(self, app, work: Callable[[], Any],
                 on_done: Callable[[Any], None],
                 on_error: Optional[Callable[[BaseException], None]] = None,
                 poll_ms: int = 100):
        self._app = app
        self._work = work
        self._on_done = on_done
        self._on_error = on_error
        self._poll_ms = poll_ms
        self._result: Any = None
        self._error: Optional[BaseException] = None
        self._done = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        self._app.after(self._poll_ms, self._poll)

    def _run(self) -> None:
        try:
            self._result = self._work()
        except BaseException as exc:
            self._error = exc
        finally:
            self._done = True

    def _poll(self) -> None:
        if not self._done:
            self._app.after(self._poll_ms, self._poll)
            return
        if self._error is not None:
            if self._on_error is not None:
                self._on_error(self._error)
            else:
                print(f"BackgroundTask failed: {self._error}", file=sys.stderr)
        else:
            self._on_done(self._result)
