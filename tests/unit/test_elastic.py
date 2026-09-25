import pytest

from ai_garment.core.elastic import ELASTIC_STRENGTHS, ElasticSpec, combine_elastics, validate_elastic_params
from ai_garment.core.errors import GarmentError


def test_strength_presets():
    for s in ("light", "medium", "strong"):
        assert s in ELASTIC_STRENGTHS
    e = ElasticSpec.from_params(target="left_sleeve_cuff", strength="medium")
    assert e.tension == pytest.approx(ELASTIC_STRENGTHS["medium"]["tension"])
    assert e.width == pytest.approx(0.03)
    assert e.stiffness_multiplier > 1.0
    assert ELASTIC_STRENGTHS["light"]["tension"] < ELASTIC_STRENGTHS["medium"]["tension"] < ELASTIC_STRENGTHS["strong"]["tension"]


def test_explicit_values_from_brief():
    e = ElasticSpec.from_params(target="sleeve_cuff", strength="medium", width=0.03, tension=0.15)
    assert e.tension == 0.15 and e.width == 0.03


def test_numeric_strength():
    e = ElasticSpec.from_params(target="waistband", strength=0.5)
    assert ELASTIC_STRENGTHS["light"]["tension"] <= e.tension <= ELASTIC_STRENGTHS["strong"]["tension"]


@pytest.mark.parametrize("params,code", [
    ({"strength": "medium", "tension": 0.9}, "ELASTIC_TENSION_RANGE"),
    ({"strength": "medium", "width": 0.5}, "ELASTIC_WIDTH_RANGE"),
    ({"strength": "mega"}, "INVALID_PARAM"),
    ({"strength": 2.0}, "INVALID_PARAM"),
])
def test_validation(params, code):
    issues = validate_elastic_params(params)
    assert code in [i.code for i in issues]
    with pytest.raises(GarmentError):
        ElasticSpec.from_params(target="x", **params)


def test_combine_shrink_groups():
    a = ElasticSpec.from_params(target="a", strength="light", tension=0.1)
    b = ElasticSpec.from_params(target="b", strength="strong", tension=0.2)
    combined = combine_elastics([a, b])
    assert combined.shrink_max == pytest.approx(0.2)
    assert combined.weights["a"] == pytest.approx(0.5)
    assert combined.weights["b"] == pytest.approx(1.0)
    assert combine_elastics([]).shrink_max == 0.0


def test_drawstring_does_not_stiffen():
    d = ElasticSpec.from_params(target="hood", strength="light", kind="drawstring")
    assert d.kind == "drawstring"
    assert d.stiffness_multiplier == 1.0
    assert d.tension > 0
