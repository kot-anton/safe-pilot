"""Generic back/forward navigation for FSM wizards.

Every step transition goes through `goto()`, which records the state being left onto a
history stack kept in FSM data. `go_back()` pops that stack and re-renders the previous
step, so a pilot who fat-fingers a value is never stuck -- they can always back up and
re-answer instead of cancelling the whole wizard.

For loop-based flows (the same state revisited once per station/tank), the lower-level
`push_checkpoint`/`pop_checkpoint` let a handler store a richer marker than a bare state
name -- e.g. `{"type": "load", "index": 2}` -- and dispatch on it itself.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import Message

from app.database.models import User

RenderFn = Callable[[Message, FSMContext, User], Awaitable[None]]

_HISTORY_KEY = "_nav_history"


async def push_checkpoint(state: FSMContext, checkpoint: Any) -> None:
    data = await state.get_data()
    history = list(data.get(_HISTORY_KEY, []))
    history.append(checkpoint)
    await state.update_data(**{_HISTORY_KEY: history})


async def pop_checkpoint(state: FSMContext) -> Any | None:
    data = await state.get_data()
    history = list(data.get(_HISTORY_KEY, []))
    if not history:
        return None
    checkpoint = history.pop()
    await state.update_data(**{_HISTORY_KEY: history})
    return checkpoint


async def goto(
    message: Message,
    state: FSMContext,
    user: User,
    target: State,
    render: RenderFn,
    *,
    record_history: bool = True,
) -> None:
    """Move forward to `target`, remembering the current step so Back can return to it."""
    if record_history:
        current = await state.get_state()
        if current is not None:
            await push_checkpoint(state, current)
    await state.set_state(target)
    await render(message, state, user)


async def go_back(
    message: Message,
    state: FSMContext,
    user: User,
    renderers: dict[str, RenderFn],
    on_empty: RenderFn,
) -> None:
    """Pop the history stack (expects plain state-name strings) and re-render that step.
    If there's nothing to go back to, calls `on_empty` (typically: a friendly no-op)."""
    previous = await pop_checkpoint(state)
    if previous is None:
        await on_empty(message, state, user)
        return
    await state.set_state(previous)
    renderer = renderers.get(previous)
    if renderer is not None:
        await renderer(message, state, user)
    else:
        await on_empty(message, state, user)
