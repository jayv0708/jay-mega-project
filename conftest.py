from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: run async test functions with asyncio")


def pytest_pyfunc_call(pyfuncitem):
    if pyfuncitem.get_closest_marker("asyncio") is None:
        return None
    test_func = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_func):
        return None
    fixture_args = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames
    }
    asyncio.run(test_func(**fixture_args))
    return True
