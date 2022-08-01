import contextlib

import asyncio
import collections.abc
import contextlib
import functools
import types

from .tasks import task_factory as _task_factory, Task as _Task
from . import timeouts


UNCANCEL_DONE = object()


class WaitTaskRescheduled:
    _asyncio_future_blocking = True
    _add_done_callback = None
    _abort_func = None

    def __init__(self, add_done_callback, abort_func):
        self._add_done_callback = add_done_callback
        self._abort_func = abort_func

    def cancel(self, *args, **kwargs):
        return self._abort_func(*args, **kwargs)

    def get_loop(self):
        return asyncio.get_running_loop()

    def add_done_callback(self, fn, *, context):
        v = self._add_done_callback
        # break a reference cycle and detect multiple add_done_callbacks
        del self._add_done_callback
        if v is None:
            raise AssertionError("only one task can listen to a Future at a time")

        v(fn, context)


@types.coroutine
def _async_yield(v):
    return (yield v)


@collections.abc.Coroutine.register
class WrapCoro:
    def __init__(self, coro, context):
        self._coro = coro
        self._context = context

    def __await__(self):
        return self

    def __iter__(self):
        return self

    def __next__(self):
        return self.send(None)

    def throw(self, *exc_info):
        result = self._context.run(self._coro.throw, *exc_info)
        if result is UNCANCEL_DONE:
            raise StopIteration
        return result

    def send(self, v):
        result = self._context.run(self._coro.send, v)
        if result is UNCANCEL_DONE:
            raise StopIteration
        return result


class NullFuture:
    def result(self):
        return None


@contextlib.asynccontextmanager
async def install_uncancel():
    if isinstance(asyncio.current_task(), _Task):
        # already installed
        yield
        return

    context = None

    async def asyncio_main():
        return await WrapCoro(task.get_coro(), context=context)

    task = asyncio.current_task()
    loop = task.get_loop()
    new_task = _task_factory(loop, asyncio_main())

    def add_done_callback(callback, context_):
        nonlocal context
        context = context_
        new_task.add_done_callback(callback, context=context_)

    # suspend the current task so we can use its coro
    await _async_yield(
        WaitTaskRescheduled(
            add_done_callback=add_done_callback,
            abort_func=new_task.cancel,
        )
    )

    try:
        yield
    finally:
        # tell our WrapCoro that trio is done
        await _async_yield(UNCANCEL_DONE)
