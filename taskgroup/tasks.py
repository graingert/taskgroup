import asyncio
import collections.abc


@collections.abc.Coroutine.register
class _Interceptor:
    def __init__(self, coro, context):
        self.__coro = coro
        self.__context = context

    def send(self, v):
        return self.__context.run(self.__coro.send, v)

    def throw(self, e):
        return self.__context.run(self.__coro.throw, e)

    def __getattr__(self, name):
        return getattr(self.__coro, name)


class Task(asyncio.Task):
    def __init__(self, coro, *args, context=None, **kwargs):
        self._num_cancels_requested = 0
        if context is not None:
            coro = _Interceptor(coro, context)
        super().__init__(coro, *args, **kwargs)

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

    def get_coro(self):
        coro = super().get_coro()
        if isinstance(coro, _Interceptor):
            return coro._Interceptor__coro
        return coro

def task_factory(loop, coro, **kwargs):
    return Task(coro, loop=loop, **kwargs)
