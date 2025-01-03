from __future__ import annotations

import asyncio
import contextvars
from typing import Any, Union, TYPE_CHECKING, Generic
from typing_extensions import TypeAlias, TypeVar, Self
import sys

if sys.version_info >= (3, 9):
    from collections.abc import Generator, Coroutine, Awaitable
else:
    from typing import Generator, Coroutine, Awaitable

_YieldT_co = TypeVar("_YieldT_co", covariant=True)
_SendT_contra = TypeVar("_SendT_contra", contravariant=True, default=None)
_ReturnT_co = TypeVar("_ReturnT_co", covariant=True, default=None)
_SendT_contra_nd = TypeVar("_SendT_contra_nd", contravariant=True)
_ReturnT_co_nd = TypeVar("_ReturnT_co_nd", covariant=True)

_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)
_TaskYieldType: TypeAlias = "asyncio.Future[object] | None"

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


class _Interceptor(
    Generator[_YieldT_co, _SendT_contra_nd, _ReturnT_co_nd],
    Coroutine[_YieldT_co, _SendT_contra_nd, _ReturnT_co_nd],
):
    def __init__(
        self,
        coro: (
            Coroutine[_YieldT_co, _SendT_contra_nd, _ReturnT_co_nd]
            | Generator[_YieldT_co, _SendT_contra_nd, _ReturnT_co_nd]
        ),
        context: contextvars.Context,
    ):
        self.__coro = coro
        self.__context = context

    def send(self, v: _SendT_contra_nd) -> _YieldT_co:
        return self.__context.run(self.__coro.send, v)

    def throw(self, *exc_info) -> _YieldT_co:
        return self.__context.run(self.__coro.throw, *exc_info)

    def __getattr__(self, name):
        return getattr(self.__coro, name)

    def __await__(self) -> Self:
        return self

    def close(self) -> None:
        super().close()


if TYPE_CHECKING:

    class _Task(asyncio.Task[_T_co]):
        pass


elif sys.version_info >= (3, 9):
    _Task = asyncio.Task
else:

    class _Task(asyncio.Task, Generic[_T_co]):
        pass


class Task(_Task[_T_co]):
    def __init__(
        self, coro: _TaskCompatibleCoro[_T_co], *args, context=None, **kwargs
    ) -> None:
        self._num_cancels_requested = 0
        if context is not None:
            coro = _Interceptor(coro, context)
        super().__init__(coro, *args, **kwargs)  # type: ignore

    def cancel(self, *args: Any, **kwargs: Any) -> bool:
        if not self.done():
            self._num_cancels_requested += 1
        return super().cancel(*args, **kwargs)

    def cancelling(self) -> int:
        return self._num_cancels_requested

    def uncancel(self) -> int:
        if self._num_cancels_requested > 0:
            self._num_cancels_requested -= 1
        return self._num_cancels_requested

    def get_coro(self) -> _TaskCompatibleCoro[_T_co] | None:
        coro = super().get_coro()
        if isinstance(coro, _Interceptor):
            return coro._Interceptor__coro  # type: ignore
        return coro


def task_factory(
    loop: asyncio.AbstractEventLoop, coro: _TaskCompatibleCoro[_T_co], **kwargs: Any
) -> Task[_T_co]:
    return Task(coro, loop=loop, **kwargs)
