"""Reviewed fixtures: these are the only programs the local demo executes."""

ORIGINAL = "def total(subtotal, discount):\n    return subtotal - discount\n"
FIX = "def total(subtotal, discount):\n    return max(0, subtotal - discount)\n"
WRONG_FIX = "def total(subtotal, discount):\n    return 0\n"
REGRESSION = """from pricing import total

def test_excess_discount():
    assert total(100, 150) == 0
"""
EXISTING = """from pricing import total

def test_normal_discount():
    assert total(100, 20) == 80
"""
INDEPENDENT = """from pricing import total

def test_boundaries():
    for subtotal, discount, expected in [(0, 0, 0), (50, 50, 0), (75, 0, 75), (10, 11, 0)]:
        assert total(subtotal, discount) == expected
"""
CASES = {
    "repair": {
        "title": "Excess discount",
        "issue": "An excess discount makes the total negative. The specified behavior is to clamp the total to zero.",
        "patches": [FIX],
    },
    "reject": {
        "title": "Catch a plausible bad fix",
        "issue": "Clamp excess discounts to zero while preserving normal order totals.",
        "patches": [WRONG_FIX, FIX],
    },
    "unresolved": {
        "title": "Exhaust the repair budget",
        "issue": "Clamp excess discounts to zero while preserving normal order totals.",
        "patches": [WRONG_FIX, WRONG_FIX],
    },
    "ambiguous": {
        "title": "Clarify expected behavior",
        "issue": "The order total goes negative when the discount exceeds the subtotal.",
        "patches": [],
    },
}
