from __future__ import annotations

from _pytest.pytester import Pytester


# a conftest that runs tests in a threadpool. You can think of this as "like pytest-xdist,
# but using threads instead of processes". This is a nice conftest for flushing out
# concurrency bugs in pytest itself.
threaded_conftest = """
import sys
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor

# make thread switches more common
sys.setswitchinterval(0.000001)
n = 3

def pytest_runtestloop(session):
    queue = Queue()
    for item in session.items:
        queue.put(item)

    def worker():
        try:
            item = queue.get_nowait()
        except Empty:
            return

        while item is not None:
            try:
                next_item = queue.get_nowait()
            except Empty:
                next_item = None

            item.config.hook.pytest_runtest_protocol(
                item=item, nextitem=next_item
            )
            item = next_item

    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(worker) for _ in range(n)]
        for future in futures:
            future.result()
    return True
"""


def test_concurrent(pytester: Pytester) -> None:
    pytester.makeconftest(threaded_conftest)
    pytester.makepyfile(
        """
        import pytest

        def do_work():
            # arbitrary moderately-expensive work
            for x in range(500):
                _y = x**x

        def test_1(): do_work()
        def test_2(): do_work()
        def test_3(): do_work()
        def test_4(): do_work()

        @pytest.fixture
        def setup_fixture():
            yield

        def test_with_fixture_1(setup_fixture): do_work()
        def test_with_fixture_2(setup_fixture): do_work()
        def test_with_fixture_3(setup_fixture): do_work()
        def test_with_fixture_4(setup_fixture): do_work()

        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=10)


def test_each_thread_gets_fresh_fixture_value(pytester: Pytester) -> None:
    pytester.makeconftest(threaded_conftest)
    pytester.makepyfile(
        """
        import pytest
        import threading
        from collections import defaultdict

        # obj_id: [thread_id]
        threads_using_object = defaultdict(list)

        @pytest.fixture
        def my_fixture():
            return object()

        def test_1(my_fixture): threads_using_object[id(my_fixture)].append(threading.get_ident())
        def test_2(my_fixture): threads_using_object[id(my_fixture)].append(threading.get_ident())
        def test_3(my_fixture): threads_using_object[id(my_fixture)].append(threading.get_ident())
        def test_4(my_fixture): threads_using_object[id(my_fixture)].append(threading.get_ident())

        def test_verify_isolation():
            for thread_ids in threads_using_object.values():
                assert len(thread_ids) == 1
        """
    )
    result = pytester.runpytest()
    # fixtures should not be shared across threads. ie, each thread should get a
    # fresh value for each fixture.
    result.assert_outcomes(passed=5)
