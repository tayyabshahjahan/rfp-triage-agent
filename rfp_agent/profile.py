"""The only allowed source of facts about idiaz.io."""

IDIAZ_PROFILE = (
    "A US-registered, AI-native engineering studio with a small senior team. "
    "What we build: automation platforms, compliance tooling, AI-integrated ops "
    "software, web and mobile apps."
)

# Derived from the verbatim profile so prompt text never duplicates company facts.
IDIAZ_BUILD_SCOPE = IDIAZ_PROFILE.partition("What we build: ")[2].rstrip(".")
