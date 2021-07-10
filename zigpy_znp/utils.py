from __future__ import annotations

import typing
import asyncio
import inspect
import logging
import functools
import dataclasses

import zigpy_znp.types as t

LOGGER = logging.getLogger(__name__)


def deduplicate_commands(
    commands: typing.Iterable[t.CommandBase],
) -> tuple[t.CommandBase]:
    """
    Deduplicates an iterable of commands by folding more-specific commands into less-
    specific commands. Used to avoid triggering callbacks multiple times per packet.
    """

    # We essentially need to find the "maximal" commands, if you treat the relationship
    # between two commands as a partial order.
    maximal_commands = []

    # Command matching as a relation forms a partially ordered set.
    for command in commands:
        for index, other_command in enumerate(maximal_commands):
            if other_command.matches(command):
                # If the other command matches us, we are redundant
                break
            elif command.matches(other_command):
                # If we match another command, we replace it
                maximal_commands[index] = command
                break
            else:
                # Otherwise, we keep looking
                continue  # pragma: no cover
        else:
            # If we matched nothing and nothing matched us, we extend the list
            maximal_commands.append(command)

    # The start of each chain is the maximal element
    return tuple(maximal_commands)


@dataclasses.dataclass(frozen=True)
class BaseResponseListener:
    matching_commands: tuple[t.CommandBase]

    def __post_init__(self):
        commands = deduplicate_commands(self.matching_commands)

        if not commands:
            raise ValueError("Cannot create a listener without any matching commands")

        # We're frozen so __setattr__ is disallowed
        object.__setattr__(self, "matching_commands", commands)

    def matching_headers(self) -> set[t.CommandHeader]:
        """
        Returns the set of Z-Stack MT command headers for all the matching commands.
        """

        return {response.header for response in self.matching_commands}

    def resolve(self, response: t.CommandBase) -> bool:
        """
        Attempts to resolve the listener with a given response. Can be called with any
        command as an argument, including ones we don't match.
        """

        if not any(c.matches(response) for c in self.matching_commands):
            return False

        return self._resolve(response)

    def _resolve(self, response: t.CommandBase) -> bool:
        """
        Implemented by subclasses to handle matched commands.

        Return value indicates whether or not the listener has actually resolved,
        which can sometimes be unavoidable.
        """

        raise NotImplementedError()  # pragma: no cover

    def cancel(self):
        """
        Implement by subclasses to cancel the listener.

        Return value indicates whether or not the listener is cancelable.
        """

        raise NotImplementedError()  # pragma: no cover


@dataclasses.dataclass(frozen=True)
class OneShotResponseListener(BaseResponseListener):
    """
    A response listener that resolves a single future exactly once.
    """

    future: asyncio.Future = dataclasses.field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )

    def _resolve(self, response: t.CommandBase) -> bool:
        if self.future.done():
            # This happens if the UART receives multiple packets during the same
            # event loop step and all of them match this listener. Our Future's
            # add_done_callback will not fire synchronously and thus the listener
            # is never properly removed. This isn't going to break anything.
            LOGGER.debug("Future already has a result set: %s", self.future)
            return False

        self.future.set_result(response)
        return True

    def cancel(self):
        if not self.future.done():
            self.future.cancel()

        return True


@dataclasses.dataclass(frozen=True)
class CallbackResponseListener(BaseResponseListener):
    """
    A response listener with a sync or async callback that is never resolved.
    """

    callback: typing.Callable[[t.CommandBase], typing.Any]

    def _resolve(self, response: t.CommandBase) -> bool:
        try:
            result = self.callback(response)

            # Run coroutines in the background
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
        except Exception:
            LOGGER.warning(
                "Caught an exception while executing callback", exc_info=True
            )

        # Callbacks are always resolved
        return True

    def cancel(self):
        # You can't cancel a callback
        return False


def combine_concurrent_calls(function):
    """
    Decorator that allows concurrent calls to expensive coroutines to share a result.
    """

    futures = {}
    signature = inspect.signature(function)

    @functools.wraps(function)
    async def replacement(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()

        # XXX: all args and kwargs are assumed to be hashable
        key = tuple(bound.arguments.items())

        if key in futures:
            return await futures[key]

        future = futures[key] = asyncio.get_running_loop().create_future()

        try:
            result = await function(*args, **kwargs)
        except Exception as e:
            future.set_exception(e)
            raise
        else:
            future.set_result(result)
            return result
        finally:
            del futures[key]

    return replacement
