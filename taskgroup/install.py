import contextvars
import asyncio
import collections.abc
import types
from typing import cast, Optional, Type

from .tasks import task_factory as _task_factory, Task as _Task

from typing_extensions import Self, TypeVar


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
    collections.abc.Generator[_YieldT_co, _SendT_contra_nd, _ReturnT_co_nd],
    collections.abc.Coroutine[_YieldT_co, _SendT_contra_nd, _ReturnT_co_nd],
):
    def __init__(
        self,
        coro: collections.abc.Coroutine[_YieldT_co, _SendT_contra_nd, _ReturnT_co_nd],
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


MISNESTING_ADVICE = """
This is probably a bug in your code, that has caused taskgroup's internal state to
become corrupted.

Typically this is caused by one of the following:
  - yielding within a generator or async generator that's opened a Timeout
    or TaskGroup (unless the generator is a @contextmanager or
    @asynccontextmanager); see https://github.com/python-trio/trio/issues/638
  - manually calling __aenter__ or __aexit__ on the TaskGroup or Timeout object
    doing so correctly is difficult and you should use @[async]contextmanager
    instead, or maybe [Async]ExitStack
  - using [Async]ExitStack to interleave the entries/exits of Timeouts
    and/or TaskGroups in a way that couldn't be achieved by some nesting of
    'with' and 'async with' blocks
  - using the low-level coroutine object protocol to execute some parts of
    an async function in a different Timeout TaskGroup context than
    other parts
"""


class install_uncancel:
    def __init__(self):
        self._loop = None
        self._new_task = None

    async def __aenter__(self) -> None:
        self._loop = loop = asyncio.get_running_loop()
        task = asyncio.current_task(loop)

        if task is None or isinstance(task, _Task):
            return

        context = None

        async def asyncio_main():
            return await WrapCoro(task.get_coro(), context=context)  # type: ignore  # see python/typing#1480

        self._new_task = new_task = _task_factory(loop, asyncio_main())

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

    async def __aexit__(
        self,
        et: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[types.TracebackType],
    ) -> Optional[bool]:
        new_task = self._new_task
        if new_task is None:
            return

        if asyncio.current_task(self._loop) is new_task:
            # tell our WrapCoro that we are done
            await _async_yield(UNCANCEL_DONE)
            return

        raise RuntimeError(MISNESTING_ADVICE)
