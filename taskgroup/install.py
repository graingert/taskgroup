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
        v = self._abort_func
        # break a reference cycle and only support level cancel
        del self._abort_func
        v()

        # asyncio.Task.cancel calls:
        #
        #     if self._fut_waiter is not None:
        #         if self._fut_waiter.cancel(msg=msg):
        #             # Leave self._fut_waiter; it may be a Task that
        #             # catches and ignores the cancellation so we may have
        #             # to cancel it again later.
        #             return True
        #     # It must be the case that self.__step is already scheduled.
        #     self._must_cancel = True
        #     self._cancel_message = msg
        # fut_waiter (that's us) needs to return True otherwise task._must_cancel
        # is set to True, which means when we wake up the task it will call
        # coro.throw(CancelledError)!
        return True

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


async def get_context():
    context = None

    def abort_func():
        pass

    def add_done_callback(reschedule, context_):
        nonlocal context
        context = context_
        asyncio.current_task().get_loop().call_soon(reschedule, NullFuture())

    await _async_yield(
        WaitTaskRescheduled(add_done_callback=add_done_callback, abort_func=abort_func)
    )
    return context


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

    cancel_scope = timeouts.Timeout(None)
    # Revised 'done' callback: set a Future

    async def asyncio_main(coro):
        async with cancel_scope:
            return await coro

    def add_done_callback(callback, context):
        task = asyncio.current_task()
        loop = task.get_loop()
        new_task = _task_factory(
            loop, asyncio_main(WrapCoro(task.get_coro(), context=context))
        )
        new_task.add_done_callback(callback, context=context)

    # suspend the current task so we can use its coro
    await _async_yield(
        WaitTaskRescheduled(
            add_done_callback=add_done_callback,
            abort_func=lambda: cancel_scope.reschedule(-1),
        )
    )

    try:
        yield
    finally:
        # tell our WrapCoro that trio is done
        await _async_yield(UNCANCEL_DONE)
