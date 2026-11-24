from rfp_agent.llm import _provider_schema
from rfp_agent.schemas import Extraction


def test_provider_schema_removes_unsupported_additional_properties():
    provider_schema = _provider_schema(Extraction)
    assert "additionalProperties" not in str(provider_schema)
    assert provider_schema["type"] == "object"
