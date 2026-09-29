"""Environment isolation for the whole test suite.

This file must shadow the developer's real credentials *before* any test module
is imported, because :mod:`backend.main` builds an app at import time and
``Settings`` reads ``.env`` via ``SettingsConfigDict(env_file=".env")``.

pydantic-settings gives environment variables precedence over the dotenv file,
so assigning an empty value here wins over a populated local ``.env`` without
reading, modifying or disabling it. Production and local runs are untouched:
this only affects the pytest process.

Tests that assert a credential is absent therefore assert a property of the
test process rather than of the developer's machine.
"""

import os

#: Every credential the backend can hold. Tests must never see a real value.
CREDENTIAL_ENV_VARS = (
    "ASSEMBLYAI_API_KEY",
    "LLM_GATEWAY_API_KEY",
    "SEARCH_API_KEY",
)

# Remove inherited values first so a key exported into the shell cannot leak in
# either, then pin every name to "" so the .env file can never be consulted.
for _name in CREDENTIAL_ENV_VARS:
    os.environ.pop(_name, None)
    os.environ[_name] = ""
del _name
