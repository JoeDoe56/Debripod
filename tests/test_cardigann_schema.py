import pytest
import yaml

from debripod.Services.indexers.cardigann.schema import CardigannDefinition


def test_public_definition_eligibility_and_unknown_keys_preserved():
    definition = CardigannDefinition.from_dict({"id": "public", "name": "Public", "type": "public", "links": ["https://example"], "search": {"paths": []}, "futureKey": 42})
    assert definition.eligible
    assert definition.extra["futureKey"] == 42


def test_required_settings_are_preserved_and_require_setup():
    definition = CardigannDefinition.from_dict({"id": "private", "name": "Private", "type": "private", "links": ["https://example"], "search": {"paths": []}, "settings": [{"name": "password", "type": "password", "required": True, "future": "x"}]})
    assert definition.requires_setup and not definition.eligible
    assert definition.settings[0].extra["future"] == "x"


def test_safe_yaml_rejects_python_tags():
    with pytest.raises(yaml.constructor.ConstructorError):
        CardigannDefinition.from_yaml("!!python/object/apply:os.system ['echo bad']")
