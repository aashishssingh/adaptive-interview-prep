"""Errors raised by the LLM gateway. Messages never include credentials."""


class LLMError(RuntimeError):
    pass


class LLMUnavailableError(LLMError):
    """No provider configured (LLM_PROVIDER=none) or the provider package is missing."""


class LLMAuthError(LLMError):
    pass


class LLMResponseError(LLMError):
    """The model's output could not be parsed or validated, even after one repair retry."""


class LLMRefusalError(LLMError):
    pass


class LLMTruncatedError(LLMError):
    pass


ANTHROPIC_AUTH_HELP = (
    "Could not authenticate with Anthropic. Run `ant auth login` (Anthropic CLI sign-in) "
    "or set ANTHROPIC_API_KEY in .env."
)
