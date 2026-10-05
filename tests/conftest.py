"""Shared fixtures. The whole suite is offline: no test talks to the OpenAI API."""

import pytest


def program(body: str, result: str = "RESULT = {'x': 1}") -> str:
    """Wrap a snippet so it satisfies the contract (2 asserts + RESULT)."""
    return f"{body}\nassert True, 'check 1'\nassert True, 'check 2'\n{result}\n"


@pytest.fixture
def make_program():
    return program
