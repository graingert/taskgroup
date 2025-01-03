import sys
import contextvars
import asyncio
import contextlib
import types
from typing import cast

from .tasks import task_factory as _task_factory, Task as _Task

from typing_extensions import Self, TypeVar

if sys.version_info >= (3, 9):
    from collections.abc import Generator, Coroutine
else:
    from typing import Generator, Coroutine


UNCANCEL_DONE = object()


class WaitTaskRescheduled:
    _asyncio_future_blocking = True

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


_YieldT_co = TypeVar("_YieldT_co", covariant=True)
_SendT_contra = TypeVar("_SendT_contra", contravariant=True, default=None)
_ReturnT_co = TypeVar("_ReturnT_co", covariant=True, default=None)
_SendT_contra_nd = TypeVar("_SendT_contra_nd", contravariant=True)
_ReturnT_co_nd = TypeVar("_ReturnT_co_nd", covariant=True)


class WrapCoro(
    Generator[_YieldT_co, _SendT_contra_nd, _ReturnT_co_nd],
    Coroutine[_YieldT_co, _SendT_contra_nd, _ReturnT_co_nd],
):
    def __init__(
        self,
        coro: Coroutine[_YieldT_co, _SendT_contra_nd, _ReturnT_co_nd],
        context: contextvars.Context,
    ):
        self._coro = coro
        self._context = context

    def __await__(self) -> Self:
        return self

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> _YieldT_co:
        return self.send(cast(_SendT_contra_nd, None))

    def throw(self, *exc_info) -> _YieldT_co:
        result = self._context.run(self._coro.throw, *exc_info)
        if result is UNCANCEL_DONE:
            raise StopIteration
        return result

    def send(self, v: _SendT_contra_nd) -> _YieldT_co:
        result = self._context.run(self._coro.send, v)
        if result is UNCANCEL_DONE:
            raise StopIteration
        return result

    def close(self) -> None:
        super().close()


@contextlib.asynccontextmanager
async def install_uncancel():
    if isinstance(asyncio.current_task(), _Task):
        # already installed
        yield
        return

    context = None

    task = asyncio.current_task()
    assert task is not None

    async def asyncio_main():
        return await WrapCoro(task.get_coro(), context=context)  # type: ignore  # see python/typing#1480

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
