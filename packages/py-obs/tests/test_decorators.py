"""The decorators are transparent — including to reflection.

Apollo builds the tool schemas it hands to Claude and to GPT by reflecting over
each tool function: ``inspect.signature`` for the parameters, ``__name__`` for
the tool name, ``inspect.getdoc`` for the description and the ``Args:`` block
(``agent/run.py``). A wrapper that lost the signature would not raise anything.
It would build every schema with an empty ``properties`` dict, the models would
call the tools with no arguments, and the failure would surface as an agent that
has become mysteriously stupid. So the signature is asserted here, explicitly,
rather than trusted to ``functools.wraps``.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

import deus_obs


def original(genre: str, limit: int = 5, *, context_variables: dict | None = None) -> str:
    """Pick a track.

    Args:
        genre: The genre folder to pick from.
        limit: How many candidates to consider.
    """
    return f"{genre}:{limit}"


decorated = deus_obs.tool(original)


def test_signature_is_preserved():
    assert inspect.signature(decorated) == inspect.signature(original)
    assert list(inspect.signature(decorated).parameters) == [
        "genre",
        "limit",
        "context_variables",
    ]


def test_name_and_doc_are_preserved():
    assert decorated.__name__ == "original"
    assert decorated.__doc__ == original.__doc__
    assert inspect.getdoc(decorated) == inspect.getdoc(original)


def test_behaviour_is_preserved():
    assert decorated("techno") == "techno:5"
    assert decorated("lofi", 2) == "lofi:2"
    assert decorated(genre="techno", limit=1, context_variables={}) == "techno:1"


def test_exceptions_pass_through_unchanged():
    @deus_obs.tool
    def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        boom()


def test_every_kind_decorates_the_same_way():
    for decorator in (deus_obs.tool, deus_obs.chain, deus_obs.agent):
        wrapped = decorator(original)
        assert inspect.signature(wrapped) == inspect.signature(original)
        assert wrapped("x") == "x:5"


def test_parenthesised_and_named_forms():
    @deus_obs.tool(name="renamed")
    def one(a: int) -> int:
        return a + 1

    @deus_obs.chain("also_renamed")
    def two(a: int) -> int:
        return a + 2

    assert one(1) == 2 and two(1) == 3
    assert one.__name__ == "one" and two.__name__ == "two"


def test_async_functions_stay_async_and_keep_their_signature():
    @deus_obs.tool
    async def fetch(track_id: str) -> str:
        await asyncio.sleep(0)
        return track_id

    assert inspect.iscoroutinefunction(fetch)
    assert list(inspect.signature(fetch).parameters) == ["track_id"]
    assert asyncio.run(fetch("abc")) == "abc"


def test_generator_functions_are_returned_untouched():
    """A span around a generator would time its creation, not its work."""

    def stream(n: int):
        yield from range(n)

    async def astream(n: int):
        for i in range(n):
            yield i

    assert deus_obs.tool(stream) is stream
    assert deus_obs.agent(astream) is astream


def test_decorating_at_import_time_is_safe_before_install():
    """Module-level decoration in a process that never configures telemetry."""
    from conftest import run_python

    run = run_python(
        """
import deus_obs

@deus_obs.tool
def a(x): return x

@deus_obs.chain
def b(x): return a(x) + 1

@deus_obs.agent
def c(x): return b(x) + 1

assert c(1) == 3
print("OK")
"""
    )
    assert run.clean, run
