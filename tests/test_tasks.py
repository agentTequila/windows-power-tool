import unittest

from power_tool.core import tasks


class FakeApp:
    def after(self, ms, cb):
        return "after-id"


class BackgroundTaskTests(unittest.TestCase):
    def test_done_callback_receives_result(self):
        seen = []
        task = tasks.BackgroundTask(FakeApp(), work=lambda: 42, on_done=seen.append)
        task._run()
        task._poll()
        self.assertEqual(seen, [42])

    def test_error_callback_receives_exception(self):
        seen = []

        def boom():
            raise RuntimeError("kaboom")

        task = tasks.BackgroundTask(FakeApp(), work=boom, on_done=lambda r: None,
                                    on_error=seen.append)
        task._run()
        task._poll()
        self.assertEqual(len(seen), 1)
        self.assertIsInstance(seen[0], RuntimeError)

    def test_poll_reschedules_while_running(self):
        calls = []

        class PollApp:
            def after(self, ms, cb):
                calls.append(ms)

        task = tasks.BackgroundTask(PollApp(), work=lambda: 1, on_done=lambda r: None)
        task._poll()
        self.assertEqual(calls, [100])

    def test_start_spawns_daemon_thread(self):
        task = tasks.BackgroundTask(FakeApp(), work=lambda: "done", on_done=lambda r: None)
        task.start()
        task._thread.join(timeout=5)
        self.assertTrue(task._done)


if __name__ == "__main__":
    unittest.main()
