import asyncio
import contextlib
import taskgroup
import exceptiongroup

class ConnectionClosedError(Exception):
    pass


async def poll_database(database):
    raise ConnectionClosedError


async def close_connection():
    raise ConnectionClosedError


@contextlib.asynccontextmanager
async def database():
    try:
        yield
    finally:
        await close_connection()


async def main():
    async with taskgroup.timeout(None):
        with exceptiongroup.catch({ConnectionClosedError: lambda _: print("done!")}):
            async with taskgroup.TaskGroup() as tg:
                task = asyncio.current_task()
                async with database() as db:
                    tg.create_task(poll_database(db))
                    await asyncio.sleep(1)

        assert task
        print(f"{task.cancelling()=} should be 0")

        try:
            async with taskgroup.timeout(0.1):
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            print(f"got cancelled incorrectly!")
            raise
        except TimeoutError:
            print("timeout as expected")


asyncio.run(main())
