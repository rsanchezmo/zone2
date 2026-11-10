import os

# Pydantic AI prints an observability banner on the first run otherwise
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
