"""ThresholdGuard: margin and grey-zone decisions, escalating verification.

Groups
  A  open_check input validation
  B  read: what counts as a usable measurement
  C  assessment: margin, grey zone, escalation, INCONCLUSIVE
  D  ownership and lifecycle
  E  views

The point of the contract is the decision primitive: not "is it true" but "how
far from the limit is it", with more verification spent only when the evidence
sits near the boundary.
"""

import json

import pytest

from conftest import (
    OWNER, STRANGER,
    URL_A, URL_B, URL_C, URL_D, URL_E, URL_F, URL_G, URL_H, URL_I, URL_J,
    URL_K, URL_L, URL_M,
    open_check, read_all, remock,
)


def state_of(vm, c, cid):
    return json.loads(c.get_check(cid))["state"]


# ---------------------------------------------------------------- A: creation


def test_blank_subject_rejected(guard):
    vm, c = guard
    with pytest.raises(Exception):
        open_check(vm, c, subject="   ")


def test_oversized_subject_rejected(guard):
    vm, c = guard
    with pytest.raises(Exception):
        open_check(vm, c, subject="s" * 400)


def test_blank_field_rejected(guard):
    vm, c = guard
    with pytest.raises(Exception):
        open_check(vm, c, field="  ")


def test_oversized_field_rejected(guard):
    vm, c = guard
    with pytest.raises(Exception):
        open_check(vm, c, field="f" * 200)


def test_blank_unit_rejected(guard):
    vm, c = guard
    with pytest.raises(Exception):
        open_check(vm, c, unit="")


def test_oversized_unit_rejected(guard):
    vm, c = guard
    with pytest.raises(Exception):
        open_check(vm, c, unit="u" * 200)


def test_threshold_must_be_numeric(guard):
    vm, c = guard
    with pytest.raises(Exception):
        open_check(vm, c, threshold="cheap")


def test_direction_must_be_max_or_min(guard):
    vm, c = guard
    with pytest.raises(Exception):
        open_check(vm, c, direction="APPROX")


def test_grey_zone_must_be_a_positive_number(guard):
    vm, c = guard
    for bad in ("wide", "0", "-3"):
        with pytest.raises(Exception):
            open_check(vm, c, grey=bad)


def test_tier_bounds(guard):
    vm, c = guard
    with pytest.raises(Exception):
        open_check(vm, c, tiers=[])
    with pytest.raises(Exception):
        open_check(vm, c, tiers=[[URL_A], [URL_B], [URL_C], [URL_D]])
    with pytest.raises(Exception):
        open_check(vm, c, tiers=[[]])


def test_non_http_source_rejected(guard):
    vm, c = guard
    with pytest.raises(Exception):
        open_check(vm, c, tiers=[["ftp://a.example.com/x", URL_B]])


def test_duplicate_source_within_a_tier_rejected(guard):
    vm, c = guard
    with pytest.raises(Exception):
        open_check(vm, c, tiers=[[URL_A, URL_A]])


def test_duplicate_source_across_tiers_rejected(guard):
    vm, c = guard
    with pytest.raises(Exception):
        open_check(vm, c, tiers=[[URL_A, URL_B], [URL_B, URL_C]], min_agree=[2, 2])


def test_min_agree_must_track_the_tiers(guard):
    vm, c = guard
    with pytest.raises(Exception):
        open_check(vm, c, tiers=[[URL_A, URL_B], [URL_C, URL_D]], min_agree=[2])
    with pytest.raises(Exception):
        open_check(vm, c, tiers=[[URL_A, URL_B]], min_agree=[0])
    with pytest.raises(Exception):
        open_check(vm, c, tiers=[[URL_A, URL_B]], min_agree=[3])
    with pytest.raises(Exception):
        open_check(vm, c, tiers=[[URL_A, URL_B], [URL_C, URL_D]], min_agree=[2, 1])


def test_open_check_is_queryable(guard):
    vm, c = guard
    cid = open_check(vm, c)
    assert cid == "1"
    rec = json.loads(c.get_check(cid))
    assert rec["state"] == "OPEN"
    assert rec["owner"] == OWNER
    assert rec["threshold"] == 100.0 and rec["grey"] == 5.0
    assert rec["direction"] == "MAX"
    assert rec["min_agree"] == [2]
    assert c.get_check_count() == 1


# ---------------------------------------------------------------- B: evidence


def test_a_usable_measurement_is_accepted(guard):
    vm, c = guard
    cid = open_check(vm, c)
    res = json.loads(c.read(cid, 0, 0))
    assert res == {"value": 80.0, "rejected": "", "state": "OPEN"}
    rec = json.loads(c.get_reading(cid, 0, 0))
    assert rec["value"] == 80.0 and rec["rejected"] == ""


def test_http_error_fails_the_read(guard):
    vm, c = guard
    cid = open_check(vm, c, tiers=[["https://metrics-z9.example.com/p99", URL_B]])
    with pytest.raises(Exception):
        c.read(cid, 0, 0)


def test_empty_body_fails_the_read(guard):
    vm, c = guard
    cid = open_check(vm, c, tiers=[["https://metrics-y8.example.com/p99", URL_B]])
    with pytest.raises(Exception):
        c.read(cid, 0, 0)


def test_non_numeric_value_is_not_a_measurement(guard):
    vm, c = guard
    cid = open_check(vm, c, tiers=[[URL_L, URL_B]])
    res = json.loads(c.read(cid, 0, 0))
    assert res["value"] is None and res["rejected"] == "not_numeric"


def test_wrong_unit_is_rejected(guard):
    vm, c = guard
    cid = open_check(vm, c, tiers=[[URL_K, URL_B]])
    res = json.loads(c.read(cid, 0, 0))
    assert res["value"] is None and res["rejected"] == "wrong_unit"


def test_value_absent_from_the_page_is_rejected(guard):
    """The model says 50; the page says 1500. 50 is not a whole token in 1500."""
    vm, c = guard
    cid = open_check(vm, c, tiers=[[URL_E, URL_B]])
    res = json.loads(c.read(cid, 0, 0))
    assert res["value"] is None and res["rejected"] == "not_in_source"


def test_unit_absent_from_the_page_is_rejected(guard):
    vm, c = guard
    cid = open_check(vm, c, tiers=[[URL_F, URL_B]])
    res = json.loads(c.read(cid, 0, 0))
    assert res["value"] is None and res["rejected"] == "unit_not_in_source"


def test_unstated_value_is_not_a_measurement(guard):
    vm, c = guard
    cid = open_check(vm, c, tiers=[[URL_M, URL_B]])
    res = json.loads(c.read(cid, 0, 0))
    assert res["value"] is None and res["rejected"] == "not_stated"


def test_a_percentage_value_is_anchored_before_the_sign(guard):
    """70.8 in '70.8%' must be accepted: % is a unit suffix, not part of the
    number. Without this every percentage reading is thrown away."""
    remock_spec = [("metrics-a.", "SPEC-A1", "SPEC-A1. coverage: 70.8% of the crust.",
                    json.dumps({"value": "70.8", "unit": "%"}))]
    vm, c = guard
    remock(vm, spec=remock_spec)
    cid = open_check(vm, c, field="coverage", unit="%", threshold="80",
                     tiers=[[URL_A, URL_B]])
    res = json.loads(c.read(cid, 0, 0))
    assert res["value"] == 70.8 and res["rejected"] == ""


def test_a_prefix_of_a_decimal_is_still_rejected(guard):
    """70 must not be anchored by 70.8: the dot keeps the number whole."""
    remock_spec = [("metrics-a.", "SPEC-A1", "SPEC-A1. coverage: 70.8% of the crust.",
                    json.dumps({"value": "70", "unit": "%"}))]
    vm, c = guard
    remock(vm, spec=remock_spec)
    cid = open_check(vm, c, field="coverage", unit="%", threshold="80",
                     tiers=[[URL_A, URL_B]])
    res = json.loads(c.read(cid, 0, 0))
    assert res["value"] is None and res["rejected"] == "not_in_source"


def test_a_leading_zero_form_is_still_found(guard):
    """The page writes 82; a model answering 82.0 must still be anchored."""
    remock_spec = [("metrics-a.", "SPEC-A1", "SPEC-A1. latency: 82 ms.",
                    json.dumps({"value": "82.0", "unit": "ms"}))]
    vm, c = guard
    remock(vm, spec=remock_spec)
    cid = open_check(vm, c, tiers=[[URL_A, URL_B]])
    res = json.loads(c.read(cid, 0, 0))
    assert res["value"] == 82.0 and res["rejected"] == ""


def test_malformed_extraction_rejected(guard):
    remock_spec = [("metrics-x7", "SPEC-X7", "SPEC-X7. latency: 80 ms.",
                    json.dumps({"value": "80", "unit": 123}))]
    vm, c = guard
    remock(vm, spec=remock_spec)
    cid = open_check(vm, c, tiers=[["https://metrics-x7.example.com/p99", URL_B]])
    with pytest.raises(Exception):
        c.read(cid, 0, 0)


def test_duplicate_read_rejected(guard):
    vm, c = guard
    cid = open_check(vm, c)
    c.read(cid, 0, 0)
    with pytest.raises(Exception):
        c.read(cid, 0, 0)


def test_read_index_out_of_range_rejected(guard):
    vm, c = guard
    cid = open_check(vm, c)
    for bad in (-1, 2, 99):
        with pytest.raises(Exception):
            c.read(cid, 0, bad)


def test_read_on_the_wrong_tier_rejected(guard):
    vm, c = guard
    cid = open_check(vm, c, tiers=[[URL_A, URL_B], [URL_C, URL_D]], min_agree=[2, 2])
    with pytest.raises(Exception):
        c.read(cid, 1, 0)


def test_read_on_unknown_check_rejected(guard):
    vm, c = guard
    with pytest.raises(Exception):
        c.read("42", 0, 0)


# ------------------------------------------------------------ C: assessment


def test_gathers_before_enough_readings(guard):
    vm, c = guard
    cid = open_check(vm, c)
    c.read(cid, 0, 0)
    rec = json.loads(c.get_check(cid))
    assert rec["state"] == "OPEN" and rec["tier_state"] == "GATHERING"
    assert rec["readings_this_tier"] == 1


def test_clear_pass_settles_at_the_first_tier(guard):
    vm, c = guard
    cid = open_check(vm, c)
    read_all(vm, c, cid, 0, [0, 1])
    rec = json.loads(c.get_check(cid))
    assert rec["state"] == "PASS" and rec["verdict"] == "PASS"
    assert rec["low"] == 80.0 and rec["high"] == 82.0 and rec["spread"] == 2.0
    assert rec["margin"] == 18.0
    assert rec["tier_reached"] == 1 and rec["tier"] == 0
    assert rec["note"] == "settled at tier 1"


def test_clear_fail_settles_at_the_first_tier(guard):
    vm, c = guard
    cid = open_check(vm, c, threshold="70")
    read_all(vm, c, cid, 0, [0, 1])
    rec = json.loads(c.get_check(cid))
    assert rec["state"] == "FAIL"
    assert rec["margin"] == 10.0


def test_straddling_the_cap_escalates(guard):
    vm, c = guard
    cid = open_check(vm, c, tiers=[[URL_C, URL_D], [URL_A, URL_B]], min_agree=[2, 2])
    read_all(vm, c, cid, 0, [0, 1])
    rec = json.loads(c.get_check(cid))
    assert rec["state"] == "OPEN"
    assert rec["tier"] == 1 and rec["tier_state"] == "ESCALATED"
    assert rec["spread"] == 4.0


def test_a_spread_wider_than_the_grey_zone_is_not_trusted(guard):
    vm, c = guard
    cid = open_check(vm, c, tiers=[[URL_A, URL_D], [URL_B, URL_C]], min_agree=[2, 2])
    read_all(vm, c, cid, 0, [0, 1])
    rec = json.loads(c.get_check(cid))
    assert rec["state"] == "OPEN" and rec["tier"] == 1
    assert rec["spread"] == 22.0


def test_rejected_readings_do_not_stall_a_tier(guard):
    """Source 0's claim is unverifiable, so the tier can never reach min_agree.
    It must move on instead of waiting forever."""
    vm, c = guard
    cid = open_check(vm, c, tiers=[[URL_E, URL_A], [URL_B, URL_C]], min_agree=[2, 2])
    first = json.loads(c.read(cid, 0, 0))
    assert first["rejected"] == "not_in_source"
    read_all(vm, c, cid, 0, [1])
    rec = json.loads(c.get_check(cid))
    assert rec["state"] == "OPEN" and rec["tier"] == 1
    assert rec["readings_this_tier"] == 1 and rec["filled_this_tier"] == 2


def test_no_tier_settling_it_is_inconclusive(guard):
    vm, c = guard
    cid = open_check(vm, c,
                     tiers=[[URL_C, URL_D], [URL_G, URL_H], [URL_I, URL_J]],
                     min_agree=[2, 2, 2])
    read_all(vm, c, cid, 0, [0, 1])
    assert json.loads(c.get_check(cid))["tier"] == 1
    read_all(vm, c, cid, 1, [0, 1])
    assert json.loads(c.get_check(cid))["tier"] == 2
    read_all(vm, c, cid, 2, [0, 1])
    rec = json.loads(c.get_check(cid))
    assert rec["state"] == "INCONCLUSIVE" and rec["verdict"] == "INCONCLUSIVE"
    assert rec["tier_reached"] == 3
    assert rec["note"] == "no tier settled it"


def test_floor_direction_pass(guard):
    vm, c = guard
    cid = open_check(vm, c, threshold="75", direction="MIN")
    read_all(vm, c, cid, 0, [0, 1])
    rec = json.loads(c.get_check(cid))
    assert rec["state"] == "PASS"
    assert rec["margin"] == 5.0


def test_floor_direction_fail(guard):
    vm, c = guard
    cid = open_check(vm, c, threshold="85", direction="MIN")
    read_all(vm, c, cid, 0, [0, 1])
    rec = json.loads(c.get_check(cid))
    assert rec["state"] == "FAIL"
    assert rec["margin"] == 3.0


def test_settling_stops_further_reads(guard):
    vm, c = guard
    cid = open_check(vm, c)
    read_all(vm, c, cid, 0, [0, 1])
    assert state_of(vm, c, cid) == "PASS"
    with pytest.raises(Exception):
        c.read(cid, 0, 1)


# ---------------------------------------------------------------- D: ownership


def test_owner_closes_a_check(guard):
    vm, c = guard
    cid = open_check(vm, c)
    vm.sender = OWNER
    assert c.close_check(cid) == "CLOSED"
    assert state_of(vm, c, cid) == "CLOSED"


def test_stranger_cannot_close(guard):
    vm, c = guard
    cid = open_check(vm, c)
    vm.sender = STRANGER
    with pytest.raises(Exception):
        c.close_check(cid)


def test_closing_twice_rejected(guard):
    vm, c = guard
    cid = open_check(vm, c)
    c.close_check(cid)
    with pytest.raises(Exception):
        c.close_check(cid)


def test_closing_an_unknown_check_rejected(guard):
    vm, c = guard
    with pytest.raises(Exception):
        c.close_check("77")


# -------------------------------------------------------------------- E: views


def test_readings_are_returned_in_order(guard):
    vm, c = guard
    cid = open_check(vm, c)
    read_all(vm, c, cid, 0, [1, 0])
    got = json.loads(c.get_readings(cid, 0))
    assert [r["source_index"] for r in got] == [0, 1]
    assert [r["value"] for r in got] == [80.0, 82.0]


def test_unknown_keys_read_as_empty(guard):
    vm, c = guard
    assert c.get_check("42") == "{}"
    assert c.get_reading("42", 0, 0) == "{}"
    assert json.loads(c.get_readings("42", 0)) == []
    assert json.loads(c.get_readings("1", 9)) == []
    assert c.get_check_count() == 0


def test_views_never_return_a_bare_float(guard):
    """GenVM calldata cannot encode float. Every view must hand back text, or
    the call fails on chain while direct-mode tests stay green."""
    vm, c = guard
    cid = open_check(vm, c)
    read_all(vm, c, cid, 0, [0, 1])
    assert isinstance(c.get_check(cid), str)
    assert isinstance(c.get_reading(cid, 0, 0), str)
    assert isinstance(c.get_readings(cid, 0), str)
    assert json.loads(c.get_check(cid))["margin"] == 18.0


def test_full_lifecycle_end_to_end(guard):
    vm, c = guard
    cid = open_check(vm, c, tiers=[[URL_C, URL_D], [URL_A, URL_B], [URL_G, URL_H]],
                     min_agree=[2, 2, 2])
    read_all(vm, c, cid, 0, [0, 1])          # straddles -> escalate
    read_all(vm, c, cid, 1, [0, 1])          # tight and clear -> settle
    rec = json.loads(c.get_check(cid))
    assert rec["state"] == "PASS"
    assert rec["tier_reached"] == 2
    assert rec["margin"] == 18.0
    assert len(json.loads(c.get_readings(cid, 0))) == 2
    assert len(json.loads(c.get_readings(cid, 1))) == 2


def test_policy_must_be_open_or_curated(guard):
    vm, c = guard
    with pytest.raises(Exception):
        open_check(vm, c, policy="ANYONE")


# ------------------------- G: no verdict on a partial tier (early settlement)


def test_a_tier_is_not_judged_before_it_is_fully_read(guard):
    """Reading two of three sources must not settle anything: the unread source
    is exactly the one that could widen the spread and force an escalation."""
    vm, c = guard
    cid = open_check(vm, c, tiers=[[URL_A, URL_B, URL_C]], min_agree=[2])
    read_all(vm, c, cid, 0, [0, 1])          # 80 and 82, tempting to call PASS
    rec = json.loads(c.get_check(cid))
    assert rec["state"] == "OPEN"
    assert rec["tier_state"] == "GATHERING"
    assert rec["tier_reached"] == 0
    assert rec["verdict"] == ""


def test_the_third_source_is_considered_before_any_verdict(guard):
    """98 widens the spread past the grey zone, so the tier that looked settled
    has to escalate instead."""
    vm, c = guard
    cid = open_check(vm, c, tiers=[[URL_A, URL_B, URL_C], [URL_D, URL_E, URL_F]],
                     min_agree=[2, 2])
    read_all(vm, c, cid, 0, [0, 1])
    assert json.loads(c.get_check(cid))["state"] == "OPEN"
    read_all(vm, c, cid, 0, [2])
    rec = json.loads(c.get_check(cid))
    assert rec["state"] == "OPEN"
    assert rec["tier"] == 1 and rec["tier_state"] == "ESCALATED"


def test_a_complete_tier_still_settles(guard):
    vm, c = guard
    cid = open_check(vm, c, tiers=[[URL_A, URL_B, URL_G]], min_agree=[2], grey="20")
    read_all(vm, c, cid, 0, [0, 1, 2])       # 80, 82, 96 -> spread 16 <= grey 20
    rec = json.loads(c.get_check(cid))
    assert rec["state"] == "PASS"
    assert rec["low"] == 80.0 and rec["high"] == 96.0 and rec["spread"] == 16.0
    assert rec["tier_reached"] == 1 and rec["margin"] == 4.0


# -------------------------------------------------- H: trust policy on evidence


def test_open_policy_accepts_any_reader(guard):
    vm, c = guard
    cid = open_check(vm, c, policy="OPEN")
    vm.sender = STRANGER
    assert json.loads(c.read(cid, 0, 0))["value"] == 80.0


def test_curated_policy_rejects_an_unlisted_reader(guard):
    vm, c = guard
    cid = open_check(vm, c, policy="CURATED")
    vm.sender = STRANGER
    with pytest.raises(Exception):
        c.read(cid, 0, 0)


def test_curated_policy_accepts_a_listed_reader(guard):
    vm, c = guard
    cid = open_check(vm, c, policy="CURATED")
    vm.sender = OWNER
    c.set_reader(cid, STRANGER, True)
    vm.sender = STRANGER
    assert json.loads(c.read(cid, 0, 0))["value"] == 80.0


def test_a_reader_can_be_withdrawn(guard):
    vm, c = guard
    cid = open_check(vm, c, policy="CURATED")
    vm.sender = OWNER
    c.set_reader(cid, STRANGER, True)
    c.set_reader(cid, STRANGER, False)
    vm.sender = STRANGER
    with pytest.raises(Exception):
        c.read(cid, 0, 0)


def test_only_the_owner_sets_readers(guard):
    vm, c = guard
    cid = open_check(vm, c, policy="CURATED")
    vm.sender = STRANGER
    with pytest.raises(Exception):
        c.set_reader(cid, STRANGER, True)


def test_reader_management_rejects_bad_input(guard):
    vm, c = guard
    cid = open_check(vm, c, policy="CURATED")
    vm.sender = OWNER
    with pytest.raises(Exception):
        c.set_reader(cid, "not-an-address", True)
    with pytest.raises(Exception):
        c.set_reader(cid, STRANGER, False)        # not on the list
    c.set_reader(cid, STRANGER, True)
    with pytest.raises(Exception):
        c.set_reader(cid, STRANGER, True)         # already there


def test_every_reading_records_who_supplied_it(guard):
    vm, c = guard
    cid = open_check(vm, c)
    vm.sender = STRANGER
    c.read(cid, 0, 0)
    rec = json.loads(c.get_reading(cid, 0, 0))
    assert rec["reader"] == STRANGER.lower()


def test_only_the_owner_can_strike_a_reading(guard):
    vm, c = guard
    cid = open_check(vm, c, tiers=[[URL_A, URL_B, URL_G]], min_agree=[2])
    read_all(vm, c, cid, 0, [0])             # still gathering, so rejection is legal
    assert json.loads(c.get_check(cid))["state"] == "OPEN"
    vm.sender = STRANGER
    with pytest.raises(Exception):
        c.reject_reading(cid, 0, 0, "wrong metric")


def test_striking_a_reading_removes_it_from_the_evidence(guard):
    vm, c = guard
    cid = open_check(vm, c, tiers=[[URL_A, URL_B, URL_G]], min_agree=[2])
    read_all(vm, c, cid, 0, [0])
    vm.sender = OWNER
    with pytest.raises(Exception):
        c.reject_reading(cid, 0, 5, "no such reading")
    with pytest.raises(Exception):
        c.reject_reading(cid, 0, 0, "")
    c.reject_reading(cid, 0, 0, "wrong metric")
    rec = json.loads(c.get_reading(cid, 0, 0))
    assert rec["value"] is None and rec["rejected"] == "owner_rejected"
    assert rec["reject_reason"] == "wrong metric"
    with pytest.raises(Exception):
        c.reject_reading(cid, 0, 0, "again")
    assert json.loads(c.get_check(cid))["filled_this_tier"] == 1
