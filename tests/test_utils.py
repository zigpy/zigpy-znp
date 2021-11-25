import asyncio

import pytest

import zigpy_znp.types as t
import zigpy_znp.commands as c
from zigpy_znp.utils import deduplicate_commands, combine_concurrent_calls


def test_command_deduplication_simple():
    c1 = c.SYS.Ping.Rsp(partial=True)
    c2 = c.UTIL.TimeAlive.Rsp(Seconds=12)

    assert deduplicate_commands([]) == ()
    assert deduplicate_commands([c1]) == (c1,)
    assert deduplicate_commands([c1, c1]) == (c1,)
    assert deduplicate_commands([c1, c2]) == (c1, c2)
    assert deduplicate_commands([c2, c1, c2]) == (c2, c1)


def test_command_deduplication_complex():
    result = deduplicate_commands(
        [
            c.SYS.Ping.Rsp(Capabilities=t.MTCapabilities.SYS),
            # Duplicating matching commands shouldn't do anything
            c.SYS.Ping.Rsp(partial=True),
            c.SYS.Ping.Rsp(partial=True),
            # Matching against different command types should also work
            c.UTIL.TimeAlive.Rsp(Seconds=12),
            c.UTIL.TimeAlive.Rsp(Seconds=10),
            c.AppConfig.BDBCommissioningNotification.Callback(
                partial=True, Status=c.app_config.BDBCommissioningStatus.InProgress
            ),
            c.AppConfig.BDBCommissioningNotification.Callback(
                partial=True,
                Status=c.app_config.BDBCommissioningStatus.InProgress,
                Mode=c.app_config.BDBCommissioningMode.NwkFormation,
            ),
            c.AppConfig.BDBCommissioningNotification.Callback(
                partial=True,
                Status=c.app_config.BDBCommissioningStatus.InProgress,
                Mode=c.app_config.BDBCommissioningMode.NwkFormation,
                RemainingModes=c.app_config.BDBCommissioningMode.InitiatorTouchLink,
            ),
            c.AppConfig.BDBCommissioningNotification.Callback(
                partial=True,
                RemainingModes=c.app_config.BDBCommissioningMode.InitiatorTouchLink,
            ),
        ]
    )

    assert set(result) == {
        c.SYS.Ping.Rsp(partial=True),
        c.UTIL.TimeAlive.Rsp(Seconds=12),
        c.UTIL.TimeAlive.Rsp(Seconds=10),
        c.AppConfig.BDBCommissioningNotification.Callback(
            partial=True, Status=c.app_config.BDBCommissioningStatus.InProgress
        ),
        c.AppConfig.BDBCommissioningNotification.Callback(
            partial=True,
            RemainingModes=c.app_config.BDBCommissioningMode.InitiatorTouchLink,
        ),
    }


async def test_combine_concurrent_calls():
    class TestFuncs:
        def __init__(self):
            self.slow_calls = 0
            self.slow_error_calls = 0

        async def slow(self, n=None):
            await asyncio.sleep(0.1)
            self.slow_calls += 1
            return (self.slow_calls, n)

        async def slow_error(self, n=None):
            await asyncio.sleep(0.1)
            self.slow_error_calls += 1
            raise RuntimeError()

        combined_slow = combine_concurrent_calls(slow)
        combined_slow_error = combine_concurrent_calls(slow_error)

    f = TestFuncs()

    assert f.slow_calls == 0

    await f.slow()
    assert f.slow_calls == 1

    await f.combined_slow()
    assert f.slow_calls == 2

    results = await asyncio.gather(*[f.combined_slow() for _ in range(5)])
    assert results == [(3, None)] * 5
    assert f.slow_calls == 3

    results = await asyncio.gather(*[f.combined_slow() for _ in range(5)])
    assert results == [(4, None)] * 5
    assert f.slow_calls == 4

    # Unique keyword arguments
    results = await asyncio.gather(*[f.combined_slow(n=i) for i in range(5)])
    assert results == [(5 + i, 0 + i) for i in range(5)]
    assert f.slow_calls == 9

    # Non-unique keyword arguments
    results = await asyncio.gather(*[f.combined_slow(i // 2) for i in range(5)])
    assert results == [(10, 0), (10, 0), (11, 1), (11, 1), (12, 2)]
    assert f.slow_calls == 12

    # Mixed keyword and non-keyword
    results = await asyncio.gather(
        f.combined_slow(0),
        f.combined_slow(n=0),
        f.combined_slow(1),
        f.combined_slow(n=1),
        f.combined_slow(n=1),
    )
    assert results == [(13, 0), (13, 0), (14, 1), (14, 1), (14, 1)]
    assert f.slow_calls == 14

    assert f.slow_error_calls == 0

    with pytest.raises(RuntimeError):
        await f.slow_error()

    assert f.slow_error_calls == 1

    for coro in asyncio.as_completed([f.combined_slow_error() for _ in range(5)]):
        with pytest.raises(RuntimeError):
            await coro

    assert f.slow_error_calls == 2
