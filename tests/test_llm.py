import anthropic
import httpx
import pytest

from harnessforge.agent.llm import (
    LLMClient,
    UnretryableLLMError,
    is_retryable_error,
)


def _status_error(error_type, status: int):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status, request=request)
    return error_type("test error", response=response, body={"error": "test"})


def test_retry_policy_distinguishes_transient_and_permanent_failures():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    assert is_retryable_error(anthropic.APIConnectionError(request=request))
    assert is_retryable_error(anthropic.APITimeoutError(request))
    assert is_retryable_error(_status_error(anthropic.RateLimitError, 429))
    assert is_retryable_error(_status_error(anthropic.InternalServerError, 500))
    assert not is_retryable_error(_status_error(anthropic.BadRequestError, 400))
    assert not is_retryable_error(_status_error(anthropic.AuthenticationError, 401))
    assert not is_retryable_error(_status_error(anthropic.NotFoundError, 404))


class _AlwaysBadRequest:
    def __init__(self):
        self.calls = 0
        self.messages = self

    async def create(self, **_kwargs):
        self.calls += 1
        raise _status_error(anthropic.BadRequestError, 400)


@pytest.mark.asyncio
async def test_bad_request_fails_after_one_attempt_without_backoff():
    fake = _AlwaysBadRequest()
    client = object.__new__(LLMClient)
    client.model = "test-model"
    client.provider = "anthropic"
    client.temperature = None
    client.client = fake
    client.max_attempts = 5
    client.backoff_s = 100

    with pytest.raises(UnretryableLLMError, match="BadRequestError"):
        await client.complete("system", [{"role": "user", "content": "test"}])
    assert fake.calls == 1
