"""Tests for v2.3.2 — Editor + Critic prompts include the USER PREFERENCES SIGNAL block.

Pure assertions on the system prompt strings: a regression here would
mean the agent loses its rating-awareness guidance. We also check that
the new user-context tools are registered on the editor and critic
tool lists in pipeline.py.
"""

from __future__ import annotations


def test_editor_system_prompt_contains_user_preferences_section():
    from agent.run import _EDITOR_SYSTEM
    assert "USER PREFERENCES SIGNAL" in _EDITOR_SYSTEM
    # Mentions both the favor-favorites and avoid-dislikes rules.
    assert "★4" in _EDITOR_SYSTEM or "rated 4" in _EDITOR_SYSTEM.lower()
    assert "★1" in _EDITOR_SYSTEM or "rated 1" in _EDITOR_SYSTEM.lower()


def test_critic_system_prompt_contains_user_preferences_section():
    from agent.run import _CRITIC_SYSTEM
    assert "USER PREFERENCES SIGNAL" in _CRITIC_SYSTEM
    # Mentions the structured_problem expectation so the LLM doesn't drop the format.
    assert "structured_problem" in _CRITIC_SYSTEM


def test_editor_tools_register_user_context_tools():
    from agent.run import _EDITOR_TOOLS
    names = {fn.__name__ for fn in _EDITOR_TOOLS}
    assert "get_user_ratings" in names
    assert "get_favorite_tracks" in names
    assert "get_user_playlists" in names
    assert "get_playlist_tracks" in names


def test_pipeline_web_editor_tools_register_user_context_tools():
    from web.backend.pipeline import _WEB_EDITOR_TOOLS
    names = {fn.__name__ for fn in _WEB_EDITOR_TOOLS}
    assert "get_user_ratings" in names
    assert "get_favorite_tracks" in names
    assert "get_user_playlists" in names
    assert "get_playlist_tracks" in names


def test_pipeline_critic_tools_register_user_context_tools():
    from web.backend.pipeline import _CRITIC_TOOLS
    names = {fn.__name__ for fn in _CRITIC_TOOLS}
    assert "get_user_ratings" in names
    assert "get_favorite_tracks" in names
