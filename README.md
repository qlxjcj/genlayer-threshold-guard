# ThresholdGuard

A GenLayer intelligent contract for checks that **only matter near a limit**. It
reads a measurement off a set of sources, compares it with a posted threshold
through a grey zone, and spends more verification **only when the evidence sits
near the boundary**. A clear reading settles it early; an ambiguous one climbs
the ladder; one that never clears is reported `INCONCLUSIVE` rather than guessed.

Bradbury testnet: `0x5520149D1E0F1d0172ed0F42b4faaA4702FA5898`

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
The contract reads sources one at a time and **judges a tier only once every
source in it has been read**. Settling on a partial tier would silently ignore
the unread sources, and those are exactly the ones that could widen the spread
and force an escalation.

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

62 direct-mode tests:

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

## Live on chain

Two checks were run end to end on Bradbury against two real Wikipedia sources
(`Earth` and `Ocean`, both publishing `70.8%`), with `grey = 1`:

```
cap 80%   PASS   low 70.8  high 70.8  spread 0   margin 9.2   "settled at tier 1"
cap 60%   FAIL   low 70.8  high 70.8  spread 0   margin 10.8  "settled at tier 1"
```

Both sources yielded `70.8`, accepted as a whole token in front of the `%` sign,
so the spread is zero and the check settles on the first tier without spending a
second one. The margin is how far the verdict landed from the boundary — 9.2
clearance for the loose cap, 10.8 over the line for the tight one.

Eleven input-validation gates were exercised live and every one of them reverted
as designed:

```
zero grey · bad direction · non-numeric threshold · duplicate across tiers
min_agree decreasing · min_agree too big · non-http source · duplicate within tier
read unknown check · close unknown check   (close by owner accepted)
```

The ladder itself was demonstrated live too. A third check asked for **three**
agreeing sources (`min_agree = 3`) over `Earth`, `Ocean` and `Mars`, then `Venus`,
`Mercury` and `Sun`:

```
tier 0   src0 70.8 accepted   src1 70.8 accepted   src2 not_stated
         n=2 < min_agree=3, slots full -> ESCALATED
tier 1   src0 not_stated      src1 not_stated      src2 not_stated
         n=0, last tier exhausted -> INCONCLUSIVE
```

```
state INCONCLUSIVE  tier_reached 2  note "no tier settled it"
```

Two things are worth noticing. `Mars` does not state an ocean coverage at all,
so its reading is **rejected rather than counted** — and because escalation is
driven by slots filled rather than readings accepted, the tier moves on instead
of waiting forever for a third measurement that will never come. And at the end
the contract says `INCONCLUSIVE` rather than averaging two readings and calling
it three.


## Trust policy over the evidence

Two weaknesses are closed here.

**Who may supply evidence.** A check is opened with `policy` set to `OPEN` or
`CURATED`. Under `CURATED` only the addresses the owner has listed may call
`read`, and the owner can withdraw one at any time while the check is open. The
owner is always allowed.

**Who did supply it.** Every reading records the `reader` address that produced
it, so the evidence carries an audit trail.

**What counts.** While the check is still open the owner may
`reject_reading(check_id, tier, i, reason)` to strike a reading that should not
count — a source that turned out to be unreliable, or a measurement that was
misread. The tier is then re-assessed from what is left, and the reading keeps
the reason it was struck.

None of this can be used to manufacture a verdict: the checks that decide the
outcome are the same as before (whole-token presence, unit match, `min_agree`,
grey zone), and `INCONCLUSIVE` remains the answer when the evidence does not
settle the question.


### The two gates are enforced on chain

Both were exercised live and refused exactly as designed:

```
read by an unlisted reader  -> FINISHED_WITH_ERROR   "Not an authorised reader"
reject_reading by a non-owner -> FINISHED_WITH_ERROR "Owner only"
after 2 of 3 sources        -> state OPEN, tier_state GATHERING   not judged
```

The third line is the early-settlement fix working: with sources still unread the
check stays `GATHERING` and carries no verdict, so a partial tier can never
become a verdict by accident.

## Contract surface

| Method | Kind | Purpose |
|---|---|---|
| `open_check(subject, field, unit, threshold, direction, grey, tiers, min_agree)` | write | register a threshold to watch |
| `read(check_id, tier, source_index)` | write | one fetch, one measurement, then assess a complete tier |
| `set_reader(check_id, addr, allowed)` | write | trust policy: who may supply evidence |
| `reject_reading(check_id, tier, i, reason)` | write | trust policy: strike a reading that should not count |
| `close_check(check_id)` | write | owner retires the check |
| `get_check(check_id)` | view | verdict, margin, spread, tier reached, state |
| `get_reading(check_id, tier, i)` | view | one measurement and why it was accepted or not |
| `get_readings(check_id, tier)` | view | a tier's measurements in order |
| `get_check_count()` | view | counter |
