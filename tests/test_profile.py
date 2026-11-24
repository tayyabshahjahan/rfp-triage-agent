from rfp_agent.profile import IDIAZ_BUILD_SCOPE, IDIAZ_PROFILE
from rfp_agent.prompts import extract_prompt


def test_company_profile_is_verbatim_and_is_the_prompt_source():
    assert IDIAZ_PROFILE == (
        "A US-registered, AI-native engineering studio with a small senior team. "
        "What we build: automation platforms, compliance tooling, AI-integrated ops "
        "software, web and mobile apps."
    )
    assert IDIAZ_BUILD_SCOPE in extract_prompt("[[PAGE 1]]\nExample")
