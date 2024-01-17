from __future__ import annotations

import asyncio
import collections.abc
import contextvars
from typing import Any, Awaitable, TypeVar, cast

_YieldT = TypeVar("_YieldT")
_SendT = TypeVar("_SendT")
_ReturnT = TypeVar("_ReturnT", covariant=True)

class _Interceptor(collections.abc.Coroutine[_YieldT, _SendT, _ReturnT]):
    def __init__(
        self,
        coro: (
            collections.abc.Coroutine[_YieldT, _SendT, _ReturnT]
            | collections.abc.Generator[_YieldT, _SendT, _ReturnT]
        ),
        context: contextvars.Context,
    ):
        self.__coro = coro
        self.__context = context

    def send(self, v: _SendT):
        return self.__context.run(self.__coro.send, v)

    def throw(self, e: BaseException):
        return self.__context.run(self.__coro.throw, e)

    def __getattr__(self, name):
        return getattr(self.__coro, name)


class Task(asyncio.Task[_ReturnT]):
    def __init__(
        self,
        coro: (
            Awaitable[_ReturnT]
            | collections.abc.Coroutine[_YieldT, _SendT, _ReturnT]
            | collections.abc.Generator[_YieldT, _SendT, _ReturnT]
        ),
        *args,
        context=None,
        **kwargs
    ) -> None:
        self._num_cancels_requested = 0
        if context is not None:
            assert isinstance(coro, (collections.abc.Coroutine, collections.abc.Generator))
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

    def get_coro(self) -> collections.abc.Generator[Any, Any, _ReturnT] | collections.abc.Awaitable[_ReturnT]:
        coro = super().get_coro()
        if isinstance(coro, _Interceptor):
            return coro._Interceptor__coro  # type: ignore
        return coro

def task_factory(loop: asyncio.AbstractEventLoop, coro: collections.abc.Coroutine[Any, Any, _ReturnT] | collections.abc.Generator[Any, Any, _ReturnT], **kwargs: Any) -> Task[_ReturnT]:
    return Task(coro, loop=loop, **kwargs)
