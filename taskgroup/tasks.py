import asyncio

class Task(asyncio.Task):
    def __init__(self, *args, **kwargs):
        self._num_cancels_requested = 0
        super().__init__(*args, **kwargs)

    def cancel(self, *args, **kwargs):
        if not self.done():
            self._num_cancels_requested += 1
        return super().cancel(*args, **kwargs)

    def cancelling(self):
        return self._num_cancels_requested

    def uncancel(self):
        if self._num_cancels_requested > 0:
            self._num_cancels_requested -= 1
        return self._num_cancels_requested


def task_factory(loop, coro, **kwargs):
    return Task(coro, loop=loop, **kwargs)
