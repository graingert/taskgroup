# backported from cpython 3.12.8 2dc476bcb9142cd25d7e1d52392b73a3dcdf1756
# Copyright © 2001 Python Software Foundation; All Rights Reserved
# modified to support working on 3.9, differences applied in the TaskGroup
# subclass, type annotations and assertions added

from __future__ import annotations

__all__ = ["TaskGroup"]
import sys
from types import TracebackType
from asyncio import events
from asyncio import exceptions
from asyncio import tasks
from asyncio import futures
import asyncio
import contextvars
from typing import Optional, Type
from . import install as _install
from . import tasks as _tasks

from exceptiongroup import BaseExceptionGroup
from typing import Any, Union
from typing_extensions import Self, TypeAlias, Literal, TypeVar
import contextlib

if sys.version_info >= (3, 9):
    from collections.abc import Generator, Coroutine, Awaitable
else:
    from typing import Generator, Coroutine, Awaitable


_T = TypeVar("_T")

_YieldT_co = TypeVar("_YieldT_co", covariant=True)
_SendT_contra = TypeVar("_SendT_contra", contravariant=True, default=None)
_ReturnT_co = TypeVar("_ReturnT_co", covariant=True, default=None)
_SendT_contra_nd = TypeVar("_SendT_contra_nd", contravariant=True)
_ReturnT_co_nd = TypeVar("_ReturnT_co_nd", covariant=True)

_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)
_TaskYieldType: TypeAlias = "futures.Future[object] | None"

if sys.version_info >= (3, 12):
    _TaskCompatibleCoro: TypeAlias = Coroutine[Any, Any, _T_co]
elif sys.version_info >= (3, 9):
    _TaskCompatibleCoro: TypeAlias = Union[
        Generator[_TaskYieldType, None, _T_co],
        Coroutine[Any, Any, _T_co],
    ]
else:
    _TaskCompatibleCoro: TypeAlias = (
        "Generator[_TaskYieldType, None, _T_co] | Awaitable[_T_co]"
    )


class _TaskGroup:
    """Asynchronous context manager for managing groups of tasks.

    Example use:

        async with asyncio.TaskGroup() as group:
            task1 = group.create_task(some_coroutine(...))
            task2 = group.create_task(other_coroutine(...))
        print("Both tasks have completed now.")

    All tasks are awaited when the context manager exits.

    Any exceptions other than `asyncio.CancelledError` raised within
    a task will cancel all remaining tasks and wait for them to exit.
    The exceptions are then combined and raised as an `ExceptionGroup`.
    """

    def __init__(self) -> None:
        self._entered = False
        self._exiting = False
        self._aborting = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._parent_task: tasks.Task[object] | None = None
        self._parent_cancel_requested = False
        self._tasks: set[tasks.Task[object]] = set()
        self._errors: list[BaseException] | None = []
        self._base_error: BaseException | None = None
        self._on_completed_fut: futures.Future[Literal[True]] | None = None

    def __repr__(self) -> str:
        info = [""]
        if self._tasks:
            info.append(f"tasks={len(self._tasks)}")
        if self._errors:
            info.append(f"errors={len(self._errors)}")
        if self._aborting:
            info.append("cancelling")
        elif self._entered:
            info.append("entered")

        info_str = " ".join(info)
        return f"<TaskGroup{info_str}>"

    async def __aenter__(self) -> Self:
        if self._entered:
            raise RuntimeError(f"TaskGroup {self!r} has already been entered")
        if self._loop is None:
            self._loop = events.get_running_loop()
        self._parent_task = tasks.current_task(self._loop)
        if self._parent_task is None:
            raise RuntimeError(f"TaskGroup {self!r} cannot determine the parent task")
        self._entered = True

        return self

    async def __aexit__(
        self,
        et: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> Optional[bool]:
        tb = None  # noqa: F841
        try:
            return await self._aexit(et, exc)
        finally:
            # Exceptions are heavy objects that can have object
            # cycles (bad for GC); let's not keep a reference to
            # a bunch of them. It would be nicer to use a try/finally
            # in __aexit__ directly but that introduced some diff noise
            self._parent_task = None
            self._errors = None
            self._base_error = None
            exc = None

    async def _aexit(
        self,
        et: Optional[Type[BaseException]],
        exc: Optional[BaseException],
    ) -> Optional[bool]:
        assert self._parent_task is not None
        assert self._loop is not None
        assert self._errors is not None
        self._exiting = True

        if exc is not None and self._is_base_error(exc) and self._base_error is None:
            self._base_error = exc

        propagate_cancellation_error = exc if et is exceptions.CancelledError else None
        if self._parent_cancel_requested:
            # If this flag is set we *must* call uncancel().
            if self._parent_task.uncancel() == 0:
                # If there are no pending cancellations left,
                # don't propagate CancelledError.
                propagate_cancellation_error = None

        if et is not None:
            if not self._aborting:
                # Our parent task is being cancelled:
                #
                #    async with TaskGroup() as g:
                #        g.create_task(...)
                #        await ...  # <- CancelledError
                #
                # or there's an exception in "async with":
                #
                #    async with TaskGroup() as g:
                #        g.create_task(...)
                #        1 / 0
                #
                self._abort()

        # We use while-loop here because "self._on_completed_fut"
        # can be cancelled multiple times if our parent task
        # is being cancelled repeatedly (or even once, when
        # our own cancellation is already in progress)
        while self._tasks:
            if self._on_completed_fut is None:
                self._on_completed_fut = self._loop.create_future()

            try:
                await self._on_completed_fut
            except exceptions.CancelledError as ex:
                if not self._aborting:
                    # Our parent task is being cancelled:
                    #
                    #    async def wrapper():
                    #        async with TaskGroup() as g:
                    #            g.create_task(foo)
                    #
                    # "wrapper" is being cancelled while "foo" is
                    # still running.
                    propagate_cancellation_error = ex
                    self._abort()

            self._on_completed_fut = None

        assert not self._tasks

        if self._base_error is not None:
            try:
                raise self._base_error
            finally:
                exc = None

        # Propagate CancelledError if there is one, except if there
        # are other errors -- those have priority.
        try:
            if propagate_cancellation_error and not self._errors:
                try:
                    raise propagate_cancellation_error
                finally:
                    exc = None
        finally:
            propagate_cancellation_error = None

        if et is not None and et is not exceptions.CancelledError:
            assert exc is not None
            self._errors.append(exc)

        if self._errors:
            try:
                raise BaseExceptionGroup(
                    "unhandled errors in a TaskGroup",
                    self._errors,
                ) from None
            finally:
                exc = None

    def create_task(
        self,
        coro: _TaskCompatibleCoro[_T_co],
        *,
        name: str | None = None,
        context: contextvars.Context | None = None,
    ) -> tasks.Task[_T_co]:
        """Create a new task in this group and return it.

        Similar to `asyncio.create_task`.
        """
        if not self._entered:
            raise RuntimeError(f"TaskGroup {self!r} has not been entered")
        if self._exiting and not self._tasks:
            raise RuntimeError(f"TaskGroup {self!r} is finished")
        if self._aborting:
            raise RuntimeError(f"TaskGroup {self!r} is shutting down")
        assert self._loop is not None
        if context is None:
            task = self._loop.create_task(coro)
        else:
            task = self._loop.create_task(coro, context=context)
        tasks._set_task_name(task, name)  # type: ignore
        # optimization: Immediately call the done callback if the task is
        # already done (e.g. if the coro was able to complete eagerly),
        # and skip scheduling a done callback
        if task.done():
            self._on_task_done(task)
        else:
            self._tasks.add(task)
            task.add_done_callback(self._on_task_done)
        return task

    # Since Python 3.8 Tasks propagate all exceptions correctly,
    # except for KeyboardInterrupt and SystemExit which are
    # still considered special.

    def _is_base_error(self, exc: BaseException) -> bool:
        assert isinstance(exc, BaseException)
        return isinstance(exc, (SystemExit, KeyboardInterrupt))

    def _abort(self) -> None:
        self._aborting = True

        for t in self._tasks:
            if not t.done():
                t.cancel()

    def _on_task_done(self, task: tasks.Task[object]) -> None:
        assert self._errors is not None
        assert self._parent_task is not None
        assert self._loop is not None
        self._tasks.discard(task)

        if self._on_completed_fut is not None and not self._tasks:
            if not self._on_completed_fut.done():
                self._on_completed_fut.set_result(True)

        if task.cancelled():
            return

        exc = task.exception()
        if exc is None:
            return

        self._errors.append(exc)
        if self._is_base_error(exc) and self._base_error is None:
            self._base_error = exc

        if self._parent_task.done():
            # Not sure if this case is possible, but we want to handle
            # it anyways.
            self._loop.call_exception_handler(
                {
                    "message": f"Task {task!r} has errored out but its parent "
                    f"task {self._parent_task} is already completed",
                    "exception": exc,
                    "task": task,
                }
            )
            return

        if not self._aborting and not self._parent_cancel_requested:
            # If parent task *is not* being cancelled, it means that we want
            # to manually cancel it to abort whatever is being run right now
            # in the TaskGroup.  But we want to mark parent task as
            # "not cancelled" later in __aexit__.  Example situation that
            # we need to handle:
            #
            #    async def foo():
            #        try:
            #            async with TaskGroup() as g:
            #                g.create_task(crash_soon())
            #                await something  # <- this needs to be canceled
            #                                 #    by the TaskGroup, e.g.
            #                                 #    foo() needs to be cancelled
            #        except Exception:
            #            # Ignore any exceptions raised in the TaskGroup
            #            pass
            #        await something_else     # this line has to be called
            #                                 # after TaskGroup is finished.
            self._abort()
            self._parent_cancel_requested = True
            self._parent_task.cancel()


class TaskGroup(_TaskGroup):
    __stack: contextlib.AsyncExitStack

    def create_task(
        self,
        coro: _TaskCompatibleCoro[_T_co],
        *,
        name: str | None = None,
        context: contextvars.Context | None = None,
    ) -> _tasks.Task[_T_co]:
        """Create a new task in this group and return it.

        Similar to `asyncio.create_task`.
        """
        if not self._entered:
            raise RuntimeError(f"TaskGroup {self!r} has not been entered")
        if self._exiting and not self._tasks:
            raise RuntimeError(f"TaskGroup {self!r} is finished")
        if self._aborting:
            raise RuntimeError(f"TaskGroup {self!r} is shutting down")
        assert self._loop is not None
        if context is None:
            task = _tasks.task_factory(self._loop, coro)
        else:
            task = _tasks.task_factory(self._loop, coro, context=context)
        tasks._set_task_name(task, name)  # type: ignore
        # optimization: Immediately call the done callback if the task is
        # already done (e.g. if the coro was able to complete eagerly),
        # and skip scheduling a done callback
        if task.done():
            self._on_task_done(task)
        else:
            self._tasks.add(task)
            task.add_done_callback(self._on_task_done)
        return task

    async def __aenter__(self) -> Self:
        async with contextlib.AsyncExitStack() as stack:
            await stack.enter_async_context(_install.install_uncancel())
            await super().__aenter__()
            stack.push_async_exit(super().__aexit__)
            self.__stack = stack.pop_all()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Optional[bool]:
        return await self.__stack.__aexit__(exc_type, exc_val, exc_tb)
