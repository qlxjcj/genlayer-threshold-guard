"""Fixtures for ThresholdGuard direct-mode tests.

The contract has no payable entry points. What matters here is the split of
responsibility: ``read()`` does one fetch plus one narrow measurement extraction,
while the margin / grey-zone / escalation decision is deterministic code that
never calls the model.

Mocks are keyed per source (URL for the fetch, body marker for the extraction).
Markers must not be substrings of one another: mocks are first-match-wins.
"""

import json
import os

import pytest

CONTRACT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "threshold_guard.py",
)

OWNER = "0x" + "aa" * 20
STRANGER = "0x" + "44" * 20

FIELD = "latency"
UNIT = "ms"

URL_A = "https://metrics-a.example.com/p99"
URL_B = "https://metrics-b.example.com/p99"
URL_C = "https://metrics-c.example.com/p99"
URL_D = "https://metrics-d.example.com/p99"
URL_E = "https://metrics-e.example.com/p99"
URL_F = "https://metrics-f.example.com/p99"
URL_G = "https://metrics-g.example.com/p99"
URL_H = "https://metrics-h.example.com/p99"
URL_I = "https://metrics-i.example.com/p99"
URL_J = "https://metrics-j.example.com/p99"
URL_K = "https://metrics-k.example.com/p99"
URL_L = "https://metrics-l.example.com/p99"
URL_M = "https://metrics-m.example.com/p99"

# 80 and 82 agree tightly and sit well under the cap.
BODY_A = "SPEC-A1. latency: 80 ms."
BODY_B = "SPEC-B2. latency: 82 ms."
# 98 and 102 straddle a 100ms cap while staying inside the grey zone.
BODY_C = "SPEC-C3. latency: 98 ms."
BODY_D = "SPEC-D4. latency: 102 ms."
# 1500: the 50 inside it is not a whole token.
BODY_E = "SPEC-E5. latency: 1500 ms."
# the unit is never written out
BODY_F = "SPEC-F6. latency: 80"
# 96 and 104 disagree by more than the grey zone
BODY_G = "SPEC-G7. latency: 96 ms."
BODY_H = "SPEC-H8. latency: 104 ms."
# 99 and 101 straddle the cap inside the grey zone
BODY_I = "SPEC-I9. latency: 99 ms."
BODY_J = "SPEC-J0. latency: 101 ms."
# rejection shapes
BODY_K = "SPEC-K1. latency: 80 s."
BODY_L = "SPEC-L2. latency: fast."
BODY_M = "SPEC-M3. latency: unknown."


def _m(value, unit=UNIT):
    return json.dumps({"value": value, "unit": unit})


SPEC_DEFAULT = [
    ("metrics-a.", "SPEC-A1", BODY_A, _m("80")),
    ("metrics-b.", "SPEC-B2", BODY_B, _m("82")),
    ("metrics-c.", "SPEC-C3", BODY_C, _m("98")),
    ("metrics-d.", "SPEC-D4", BODY_D, _m("102")),
    ("metrics-e.", "SPEC-E5", BODY_E, _m("50")),
    ("metrics-f.", "SPEC-F6", BODY_F, _m("80")),
    ("metrics-g.", "SPEC-G7", BODY_G, _m("96")),
    ("metrics-h.", "SPEC-H8", BODY_H, _m("104")),
    ("metrics-i.", "SPEC-I9", BODY_I, _m("99")),
    ("metrics-j.", "SPEC-J0", BODY_J, _m("101")),
    ("metrics-k.", "SPEC-K1", BODY_K, _m("80", "s")),
    ("metrics-l.", "SPEC-L2", BODY_L, _m("fast")),
    ("metrics-m.", "SPEC-M3", BODY_M, _m("")),
]


def remock(vm, spec=None, error_marker="metrics-z9", empty_marker="metrics-y8"):
    if spec is None:
        spec = SPEC_DEFAULT
    vm.clear_mocks()
    for url_marker, body_marker, body, resp in spec:
        vm.mock_web(".*" + url_marker + ".*", {"method": "GET", "status": 200, "body": body})
        if resp is not None:
            vm.mock_llm(".*" + body_marker + ".*", resp)
    vm.mock_web(".*" + error_marker + ".*", {"method": "GET", "status": 500, "body": "boom"})
    vm.mock_web(".*" + empty_marker + ".*", {"method": "GET", "status": 200, "body": ""})
    vm.mock_web(".*metrics-x7.*", {"method": "GET", "status": 200, "body": "SPEC-X7. latency: 80 ms."})
    vm.mock_llm(".*SPEC-X7.*", json.dumps({"value": "80"}))


@pytest.fixture
def guard(direct_vm, direct_deploy):
    vm = direct_vm
    remock(vm)
    c = direct_deploy(CONTRACT)
    vm.sender = OWNER
    return vm, c


def open_check(vm, c, subject="Is the p99 latency under the SLA cap?", field=FIELD,
               unit=UNIT, threshold="100", direction="MAX", grey="5",
               tiers=None, min_agree=None):
    if tiers is None:
        tiers = [[URL_A, URL_B]]
    if min_agree is None:
        min_agree = [2]
    vm.sender = OWNER
    return c.open_check(subject, field, unit, threshold, direction, grey, tiers, min_agree)


def read_all(vm, c, cid, tier, indices):
    out = []
    for i in indices:
        out.append(c.read(cid, tier, i))
    return out


def values_of(vm, c, cid, tier):
    out = []
    for r in c.get_readings(cid, tier):
        out.append(r.get("value"))
    return out
