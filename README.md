# ThresholdGuard

A GenLayer intelligent contract for checks that **only matter near a limit**. It
reads a measurement off a set of sources, compares it with a posted threshold
through a grey zone, and spends more verification **only when the evidence sits
near the boundary**. A clear reading settles it early; an ambiguous one climbs
the ladder; one that never clears is reported `INCONCLUSIVE` rather than guessed.

Bradbury testnet: `0x3422dA233c38c75d22Baa96b858d43649e177733`

---

## The question it answers is different

Most verification asks *is this true?* This one asks ***how far from the limit is
it?*** Those are not the same question, and the second one is what you actually
need when a false `PASS` is expensive — an SLA cap, a latency budget, a
concentration limit, an emissions ceiling.

| | one-shot assessor | majority oracle | rule-based bounty | **this contract** |
|---|---|---|---|---|
| what it decides | a judgement | which value wins | which rules hold | **which side of a limit, and how far** |
| effort | fixed | fixed | fixed | **scales with ambiguity** |
| near the boundary | guesses | guesses | guesses | **escalates, then reports INCONCLUSIVE** |
| output | verdict | value | score | **verdict + margin + spread + tier reached** |
| money | none | none | escrow | none |
| state | one record | version chain | bounty lifecycle | **a ladder with an early exit** |

## The decision primitive

Readings `v1..vn` from the tier's sources give `low`, `high` and
`spread = high - low`.

```
trustworthy  =  n >= min_agree[tier]  and  spread <= grey
```

The readings are only trusted when enough independent sources agree **and** they
agree tightly enough to be worth anything. Then:

| direction | `PASS` | `FAIL` | otherwise |
|---|---|---|---|
| `MAX` (a cap) | `high <= threshold` | `low > threshold` | straddles → escalate |
| `MIN` (a floor) | `low >= threshold` | `high < threshold` | straddles → escalate |

Notice what that means: `PASS` requires **even the worst reading** to clear the
limit, and `FAIL` requires **even the best reading** to breach it. Anything in
between is genuinely undecided and gets more work, not a coin flip.

`margin` is how far the decision landed from the boundary — `threshold - high`
for a cap pass, `low - threshold` for a cap fail, and so on. A verdict with a
margin of 0.2 is not the same as one with a margin of 40, and the contract says
which.

## The ladder

A check is opened with up to three tiers of sources and a `min_agree` per tier.
The contract reads sources one at a time and **assesses after every read**, so it
settles as soon as the evidence becomes decisive — it never collects more than it
needs.

```
tier 1  read sources one by one   decisive? -> PASS / FAIL (done)
        tier exhausted, undecided -> ESCALATED
tier 2  more sources, a higher bar  decisive? -> PASS / FAIL
        exhausted, undecided      -> ESCALATED
tier 3  the widest set              decisive? -> PASS / FAIL
        exhausted, undecided      -> INCONCLUSIVE
```

`INCONCLUSIVE` is a real answer: *this evidence cannot settle it.* It is what a
cap check should say when the numbers straddle the limit at every tier.

## What counts as a measurement

The model is asked one narrow question — *what value of FIELD, expressed in UNIT,
does this page report?* — and nothing else in the contract calls a model. A
reading is dropped, with a reason, unless all of these hold:

| check | rejects |
|---|---|
| value stated | `not_stated` |
| value parses as a number | `not_numeric` |
| unit matches what the check expects | `wrong_unit` |
| the number occurs in the page **as a whole token** | `not_in_source` |
| the unit is written in the page | `unit_not_in_source` |

Whole-token matching is what stops `50` from being "confirmed" by a page that
says `1500`, and `50` from being claimed when the page says `50.00` — while still
accepting `82.0` for a page that writes `82`.

A rejected reading is not a failure: the tier simply cannot reach its bar from
that source. And a tier that is fully read but still short of usable measurements
**moves on** instead of stalling — the escalation is driven by slots filled, not
by readings accepted.

## Validation

- `subject`, `field`, `unit`: required, length-bounded
- `threshold`, `grey`: numeric; `grey` must be positive
- `direction`: `MAX` or `MIN`
- tiers: 1..3 tiers, 1..5 `http(s)` sources each, **unique within and across tiers**
- `min_agree`: one per tier, between 1 and that tier's size, and never decreasing
- one read per source per tier; reads must target the current tier
- a resolved or closed check accepts no further reads
- only the owner may close a check

## Testing

```
python -m pytest tests/direct -q
```

46 direct-mode tests:

- **creation**: blank and oversized subject / field / unit, non-numeric threshold,
  bad direction, bad grey zone, tier count and size bounds, non-`http` sources,
  duplicates within a tier and **across tiers**, `min_agree` length / range /
  monotonicity
- **evidence**: a usable measurement, HTTP 500, empty body, non-numeric value,
  wrong unit, **a number absent from the page**, a unit absent from the page, an
  unstated value, a `82.0` form still anchored against `82`, malformed extraction,
  duplicate read, out-of-range index, wrong tier, unknown check
- **assessment**: gathering before the bar, **clear pass settles at tier 1 with
  its margin**, clear fail, straddling the cap escalates, a spread wider than the
  grey zone is not trusted, **rejected readings do not stall a tier**,
  `INCONCLUSIVE` after every tier, floor direction both ways, settled checks stop
  taking reads
- **ownership / views**: owner-only close, double close, ordering, unknown keys

## Contract surface

| Method | Kind | Purpose |
|---|---|---|
| `open_check(subject, field, unit, threshold, direction, grey, tiers, min_agree)` | write | register a threshold to watch |
| `read(check_id, tier, source_index)` | write | one fetch, one measurement, then assess |
| `close_check(check_id)` | write | owner retires the check |
| `get_check(check_id)` | view | verdict, margin, spread, tier reached, state |
| `get_reading(check_id, tier, i)` | view | one measurement and why it was accepted or not |
| `get_readings(check_id, tier)` | view | a tier's measurements in order |
| `get_check_count()` | view | counter |
