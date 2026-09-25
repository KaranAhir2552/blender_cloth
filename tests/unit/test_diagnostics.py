from ai_garment.core.diagnostics import analyze_penetration, analyze_settling, analyze_stability


def test_clean_penetration():
    d = analyze_penetration([0.01] * 1000)
    assert d.ok and d.issues == []


def test_penetration_detected_with_canonical_message():
    d = analyze_penetration([0.01] * 900 + [-0.01] * 100)
    assert not d.ok
    issue = d.issues[0]
    assert issue.code == "COLLISION_ISSUE"
    assert issue.message == "Potential collision issue detected."
    assert "increase collision margin" in issue.suggestions
    assert "increase simulation quality" in issue.suggestions
    assert d.data["penetrating_fraction"] == 0.1


def test_tiny_penetration_tolerated():
    d = analyze_penetration([0.01] * 999 + [-0.01])
    assert d.ok


def test_settling_converges():
    d = analyze_settling([0.05, 0.02, 0.01, 0.0009, 0.0005, 0.0004, 0.0003], threshold=0.001, window=3)
    assert d.data["settled"] is True
    assert d.data["settled_at"] == 5


def test_settling_not_converged():
    d = analyze_settling([0.1] * 10, threshold=0.001, window=3)
    assert d.data["settled"] is False
    assert any("frames" in s for i in d.issues for s in i.suggestions)


def test_stability():
    avatar_bbox = ((-0.3, -0.2, 0.0), (0.3, 0.2, 1.8))
    assert analyze_stability(((-0.35, -0.25, 0.8), (0.35, 0.25, 1.5)), avatar_bbox).ok
    bad = analyze_stability(((-30, -30, -30), (30, 30, 30)), avatar_bbox)
    assert not bad.ok and bad.issues[0].code == "SIMULATION_UNSTABLE"
    nan = analyze_stability(((-0.3, -0.2, 0.0), (0.3, 0.2, 1.8)), avatar_bbox, has_nan=True)
    assert not nan.ok
