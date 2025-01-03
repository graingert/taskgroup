[![PyPI - Version](https://img.shields.io/pypi/v/taskgroup)](https://pypi.org/project/taskgroup/)

# taskgroup

a backport of asyncio.TaskGroup, asyncio.Runner and asyncio.timeout

## background

This is a backport of the TaskGroup, Runner and timeout code from
Python 3.12.8 to Python 3.8, Python 3.9, Python 3.10 and Python 3.11.

## operation

This project works by temporarily swapping the current task of a coroutine to a
subclass of asyncio.Task with uncancel and context setting support.
The advantage of this approach means that most of the operation of
asyncio.Task will continue to be c-accelerated.

## example

```python
if sys.python_version >= (3, 11):
    from asyncio import run, TaskGroup, timeout
else:
    from taskgroup import run, TaskGroup, timeout

async def main():
    async with TaskGroup() as group:
        group.create_task(task1())
        group.create_task(task2())

run(main())
```

# changelog
## 0.2.2
### What's Changed
* update note about which version we backported from by @graingert in https://github.com/graingert/taskgroup/pull/27
* [pre-commit.ci] pre-commit autoupdate by @pre-commit-ci in https://github.com/graingert/taskgroup/pull/28
* restore support for 3.8 by @graingert in https://github.com/graingert/taskgroup/pull/30

### New Contributors
* @pre-commit-ci made their first contribution in https://github.com/graingert/taskgroup/pull/28

**Full Changelog**: https://github.com/graingert/taskgroup/compare/0.2.1...0.2.2

## 0.2.1
### What's Changed
* make _Interceptor not abstract by @graingert in https://github.com/graingert/taskgroup/pull/25


**Full Changelog**: https://github.com/graingert/taskgroup/compare/0.2.0...0.2.1

## 0.2.0
### What's Changed
* add readme and changelog by @graingert in https://github.com/graingert/taskgroup/pull/21
* Add link to PyPI by @graingert in https://github.com/graingert/taskgroup/pull/22
* changes from 3.12.8, add a smoke test, make uncancel installation simpler by @graingert in https://github.com/graingert/taskgroup/pull/23


**Full Changelog**: https://github.com/graingert/taskgroup/compare/0.1.1...0.2.0

## 0.1.1
### What's Changed
* Alter typing to support Python3.9 by @pgjones in https://github.com/graingert/taskgroup/pull/18
* bump to 0.1.1 by @graingert in https://github.com/graingert/taskgroup/pull/19

### New Contributors
* @pgjones made their first contribution in https://github.com/graingert/taskgroup/pull/18

**Full Changelog**: https://github.com/graingert/taskgroup/compare/0.1.0...0.1.1

## 0.1.0
### What's Changed
* bump version to 0.1.0 by @graingert in https://github.com/graingert/taskgroup/pull/16


**Full Changelog**: https://github.com/graingert/taskgroup/compare/0.0.0a6...0.1.0

## 0.0.0a6
### What's Changed
* configure pre-commit by @graingert in https://github.com/graingert/taskgroup/pull/13
* bump to 0.0.0a5 by @graingert in https://github.com/graingert/taskgroup/pull/14
* bump version by @graingert in https://github.com/graingert/taskgroup/pull/15


**Full Changelog**: https://github.com/graingert/taskgroup/compare/0.0.0a5...0.0.0a6

## 0.0.0a5
### What's Changed
* Typehint the public API by @Gobot1234 in https://github.com/graingert/taskgroup/pull/1
* Fix more type issues by @Gobot1234 in https://github.com/graingert/taskgroup/pull/2
* Backport 3.11/12 changes by @Gobot1234 in https://github.com/graingert/taskgroup/pull/3
* Fix support for python 3.9 by @danielnelson in https://github.com/graingert/taskgroup/pull/5
* fix ci by @graingert in https://github.com/graingert/taskgroup/pull/11
* Add publish script by @graingert in https://github.com/graingert/taskgroup/pull/12

### New Contributors
* @Gobot1234 made their first contribution in https://github.com/graingert/taskgroup/pull/1
* @danielnelson made their first contribution in https://github.com/graingert/taskgroup/pull/5

**Full Changelog**: https://github.com/graingert/taskgroup/commits/0.0.0a5
