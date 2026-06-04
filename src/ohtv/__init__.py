"""OpenHands Trajectory Viewer - CLI for viewing conversation histories."""

import os as _os

# Silence LiteLLM's eager Bedrock/SageMaker pre-load warnings (Issue #148).
# These fire at `import litellm` time via logging.getLogger("LiteLLM"),
# *before* openhands-sdk has a chance to lower the LiteLLM logger level,
# so we must set LITELLM_LOG via the env var that litellm._logging reads
# at module init. setdefault() preserves any user-provided value
# (e.g. LITELLM_LOG=DEBUG for debugging).
_os.environ.setdefault("LITELLM_LOG", "ERROR")

__version__ = "0.23.0"
