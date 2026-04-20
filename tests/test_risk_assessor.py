from reliability.risk_assessor import assess_risk


def test_no_fix_is_high_risk():
    risk = assess_risk(
        original_code="print('hi')\n",
        fixed_code="",
        issues=[{"type": "Code Quality", "severity": "Low", "msg": "print"}],
    )
    assert risk["level"] == "high"
    assert risk["should_autofix"] is False
    assert risk["score"] == 0


def test_low_risk_when_minimal_change_and_low_severity():
    original = "import logging\n\ndef add(a, b):\n    return a + b\n"
    fixed = "import logging\n\ndef add(a, b):\n    return a + b\n"
    risk = assess_risk(
        original_code=original,
        fixed_code=fixed,
        issues=[{"type": "Code Quality", "severity": "Low", "msg": "minor"}],
    )
    assert risk["level"] in ("low", "medium")  # depends on scoring rules
    assert 0 <= risk["score"] <= 100


def test_high_severity_issue_drives_score_down():
    original = "def f():\n    try:\n        return 1\n    except:\n        return 0\n"
    fixed = "def f():\n    try:\n        return 1\n    except Exception as e:\n        return 0\n"
    risk = assess_risk(
        original_code=original,
        fixed_code=fixed,
        issues=[{"type": "Reliability", "severity": "High", "msg": "bare except"}],
    )
    assert risk["score"] <= 60
    assert risk["level"] in ("medium", "high")


def test_multiple_low_severity_issues_block_autofix():
    """Multiple issues = larger change surface = no auto-fix even when all are low severity."""
    original = "def f():\n    print('hi')\n    print('bye')\n    return True\n"
    fixed = "import logging\n\ndef f():\n    logging.info('hi')\n    logging.info('bye')\n    return True\n"
    risk = assess_risk(
        original_code=original,
        fixed_code=fixed,
        issues=[
            {"type": "Code Quality", "severity": "Low", "msg": "print statement 1"},
            {"type": "Code Quality", "severity": "Low", "msg": "print statement 2"},
        ],
    )
    assert risk["should_autofix"] is False
    assert any("Multiple" in r for r in risk["reasons"])


def test_single_low_severity_still_autofixes():
    """A single low-severity issue with a clean fix should still auto-apply."""
    original = "def f():\n    print('hi')\n    return True\n"
    fixed = "import logging\n\ndef f():\n    logging.info('hi')\n    return True\n"
    risk = assess_risk(
        original_code=original,
        fixed_code=fixed,
        issues=[{"type": "Code Quality", "severity": "Low", "msg": "print statement"}],
    )
    assert risk["should_autofix"] is True
    assert risk["level"] == "low"


def test_missing_return_is_penalized():
    original = "def f(x):\n    return x + 1\n"
    fixed = "def f(x):\n    x + 1\n"
    risk = assess_risk(
        original_code=original,
        fixed_code=fixed,
        issues=[],
    )
    assert risk["score"] < 100
    assert any("Return" in r or "return" in r for r in risk["reasons"])
