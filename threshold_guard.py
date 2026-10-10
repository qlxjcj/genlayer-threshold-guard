# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
import json
from genlayer import *

MAX_SUBJECT = 120
MAX_FIELD = 40
MAX_UNIT = 20
MAX_VALUE_LEN = 60
MAX_TIERS = 3
MAX_PER_TIER = 5
MAX_BODY_CHARS = 6000

OPEN = "OPEN"
PASS = "PASS"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"
CLOSED = "CLOSED"

CAP = "MAX"
FLOOR = "MIN"


class ThresholdGuard(gl.Contract):
    """Some checks only matter near a limit. This reads a measurement off a set of
    sources, compares it with a posted threshold through a grey zone, and spends
    more verification only when the evidence sits near the boundary. A clear
    reading settles it early; an ambiguous one climbs the ladder; one that never
    clears is reported INCONCLUSIVE rather than guessed."""

    checks: TreeMap[str, str]
    reads: TreeMap[str, str]
    check_count: u256

    def __init__(self):
        self.check_count = 0

    def _addr_hex(self, a) -> str:
        if isinstance(a, str):
            return a
        h = getattr(a, "as_hex", None)
        return h if isinstance(h, str) else str(a)

    def _iso_to_epoch(self, s: str) -> int:
        s = s.strip()
        if len(s) < 19:
            return 0
        off = 0
        tail = s[19:]
        if tail.endswith("Z"):
            tail = tail[:-1]
        if len(tail) >= 6 and (tail[0] == "+" or tail[0] == "-"):
            try:
                off = (1 if tail[0] == "+" else -1) * (int(tail[1:3]) * 3600 + int(tail[4:6]) * 60)
            except (ValueError, IndexError):
                off = 0
        try:
            y, mo, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
            hh, mm, ss = int(s[11:13]), int(s[14:16]), int(s[17:19])
        except (ValueError, IndexError):
            return 0
        if not (1 <= mo <= 12 and 1 <= d <= 31 and hh < 24 and mm < 60 and ss < 61):
            return 0
        yy = y - 1 if mo <= 2 else y
        era = yy // 400
        yoe = yy - era * 400
        doy = (153 * (mo + (-3 if mo > 2 else 9)) + 2) // 5 + d - 1
        return (era * 146097 + yoe * 365 + yoe // 4 - yoe // 100 + doy - 719468) * 86400 \
            + hh * 3600 + mm * 60 + ss - off

    def _now(self) -> int:
        raw = getattr(gl, "message_raw", None)
        d = None
        if raw is not None:
            try:
                d = raw["datetime"]
            except Exception:
                d = None
        return self._iso_to_epoch(str(d)) if d is not None else 0

    def _decode_body(self, content) -> str:
        body = getattr(content, "body", None)
        if body is None:
            return str(content)
        return body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)

    def _to_num(self, s):
        if not isinstance(s, str):
            return None
        t = s.strip().replace(",", "")
        if not t:
            return None
        for ch in t:
            if not ("0" <= ch <= "9") and ch not in "+-.":
                return None
        try:
            return float(t)
        except (ValueError, OverflowError):
            return None

    def _numeric_token(self, body: str, token: str) -> bool:
        """The number must occur in the page as a whole token, so 50 is not
        satisfied by 500 nor by 1500."""
        if not token or not body:
            return False
        n = len(token)
        i = body.find(token)
        while i >= 0:
            before = body[i - 1] if i > 0 else ""
            after = body[i + n] if i + n < len(body) else ""
            if not self._word_char(before) and not self._word_char(after):
                return True
            i = body.find(token, i + 1)
        return False

    def _word_char(self, c: str) -> bool:
        if not c:
            return False        # "" in "._%" is True in Python; an edge is a boundary
        return ("a" <= c <= "z") or ("A" <= c <= "Z") or ("0" <= c <= "9") or c in "._%"

    def _num_forms(self, s: str) -> list:
        out = [s.strip()]
        t = s.strip()
        if "." in t:
            z = t.rstrip("0").rstrip(".")
            if z and z not in out:
                out.append(z)
        return out

    def _anchored_number(self, body: str, value: str) -> bool:
        for form in self._num_forms(value):
            if self._numeric_token(body, form):
                return True
        return False

    # ---------------- input validation ----------------

    def _url_list(self, v, what: str) -> list:
        if not isinstance(v, list) or len(v) == 0 or len(v) > MAX_PER_TIER:
            raise gl.vm.UserError(what + " must be 1.." + str(MAX_PER_TIER) + " urls")
        out = []
        for u in v:
            if not isinstance(u, str) or not (u.startswith("http://") or u.startswith("https://")):
                raise gl.vm.UserError(what + " must be http(s)")
            if u in out:
                raise gl.vm.UserError(what + " must be unique")
            if len(u) > MAX_VALUE_LEN * 4:
                raise gl.vm.UserError(what + " url too long")
            out.append(u)
        return out

    # ---------------- the model's only job ----------------

    def _extract(self, url: str, field: str, unit: str) -> dict:
        """One narrow question: what measurement does this page report? The answer
        is then checked against the page text and against the stated unit."""
        def check() -> dict:
            body = ""
            try:
                body = self._decode_body(gl.nondet.web.render(url))
            except Exception:
                body = ""
            if not body.strip():
                return {"retrieved": False, "body": "", "value": "", "unit": ""}
            task = (
                "What value of " + field + ", expressed in " + unit + ", does this SOURCE report? "
                'Copy the number exactly as written. Answer JSON only: {"value": "<number>", "unit": "<unit>"}. '
                'Use "" for value when the SOURCE does not state it.\nSOURCE:\n' + body[:2000]
            )
            result = gl.nondet.exec_prompt(task)
            if isinstance(result, str):
                result = json.loads(result.replace("```json", "").replace("```", ""))
            if not isinstance(result, dict):
                raise gl.vm.UserError("[LLM_ERROR] non-dict result")
            return {"retrieved": True, "body": body,
                    "value": result.get("value", ""), "unit": result.get("unit", "")}

        principle = "Equivalent if retrieved matches and the reported value and unit are identical."
        return gl.eq_principle.prompt_comparative(check, principle)

    # ---------------- deterministic assessment ----------------

    def _assess(self, c: dict) -> dict:
        """Pure computation over the readings already stored. Decides whether the
        evidence is trustworthy and, if so, which side of the threshold it falls
        on. Otherwise it escalates, or gives up without inventing an answer."""
        tier = int(c["tier"])
        names = c["tiers"][tier]
        vals = []
        filled = 0
        for i in range(len(names)):
            raw = self.reads.get(self._rkey(c["check_id"], tier, i), "")
            if raw:
                filled += 1
                rec = json.loads(raw)
                if rec.get("value") is not None:
                    vals.append(float(rec["value"]))
        need = int(c["min_agree"][tier])
        n = len(vals)
        c["readings_this_tier"] = n
        c["filled_this_tier"] = filled

        if n < need:
            # A tier that is fully read but still short of usable measurements can
            # never decide, so it must move on rather than stall here.
            if filled < len(names):
                c["tier_state"] = "GATHERING"
                return c
            return self._escalate(c, tier)

        low, high = min(vals), max(vals)
        spread = high - low
        c["low"], c["high"], c["spread"] = low, high, spread

        threshold = float(c["threshold"])
        grey = float(c["grey"])
        cap = c["direction"] == CAP

        verdict = ""
        margin = 0.0
        if spread > grey:
            verdict = ""                       # sources disagree too much to trust
        elif cap and high <= threshold:
            verdict, margin = PASS, threshold - high
        elif cap and low > threshold:
            verdict, margin = FAIL, low - threshold
        elif (not cap) and low >= threshold:
            verdict, margin = PASS, low - threshold
        elif (not cap) and high < threshold:
            verdict, margin = FAIL, threshold - high

        if verdict:
            c["state"] = verdict
            c["verdict"] = verdict
            c["margin"] = margin
            c["tier_reached"] = tier + 1
            c["note"] = "settled at tier " + str(tier + 1)
            c["resolved_at"] = str(self._now())
            return c

        if filled >= len(names):
            return self._escalate(c, tier)
        c["tier_state"] = "GATHERING"
        return c

    def _escalate(self, c: dict, tier: int) -> dict:
        if tier + 1 < len(c["tiers"]):
            c["tier"] = tier + 1
            c["tier_state"] = "ESCALATED"
            c["note"] = "escalated to tier " + str(tier + 2)
        else:
            c["state"] = INCONCLUSIVE
            c["verdict"] = INCONCLUSIVE
            c["tier_reached"] = tier + 1
            c["note"] = "no tier settled it"
            c["resolved_at"] = str(self._now())
        return c

    # ---------------- lifecycle ----------------

    @gl.public.write
    def open_check(self, subject: str, field: str, unit: str, threshold: str,
                   direction: str, grey: str, tiers: list, min_agree: list) -> str:
        if not isinstance(subject, str) or not subject.strip() or len(subject) > MAX_SUBJECT:
            raise gl.vm.UserError("Subject required and short")
        if not isinstance(field, str) or not field.strip() or len(field) > MAX_FIELD:
            raise gl.vm.UserError("Field required")
        if not isinstance(unit, str) or not unit.strip() or len(unit) > MAX_UNIT:
            raise gl.vm.UserError("Unit required")
        if self._to_num(threshold) is None:
            raise gl.vm.UserError("Threshold must be numeric")
        if direction != CAP and direction != FLOOR:
            raise gl.vm.UserError("Direction must be MAX or MIN")
        grey_n = self._to_num(grey)
        if grey_n is None or grey_n <= 0:
            raise gl.vm.UserError("Grey zone must be numeric and positive")
        if not isinstance(tiers, list) or len(tiers) == 0 or len(tiers) > MAX_TIERS:
            raise gl.vm.UserError("Tiers must be 1.." + str(MAX_TIERS))
        tiers = [self._url_list(t, "tier") for t in tiers]
        seen = []
        for t in tiers:
            for u in t:
                if u in seen:
                    raise gl.vm.UserError("Sources must be unique across tiers")
                seen.append(u)
        if not isinstance(min_agree, list) or len(min_agree) != len(tiers):
            raise gl.vm.UserError("min_agree must match the tier count")
        agreed = []
        for idx, t in enumerate(tiers):
            k = min_agree[idx]
            if not isinstance(k, int) or k < 1 or k > len(t):
                raise gl.vm.UserError("min_agree must be 1..tier size")
            if agreed and k < agreed[-1]:
                raise gl.vm.UserError("min_agree must not decrease")
            agreed.append(k)

        self.check_count += 1
        cid = str(self.check_count)
        self.checks[cid] = json.dumps({
            "check_id": cid,
            "subject": subject.strip(),
            "field": field.strip(),
            "unit": unit.strip(),
            "threshold": self._to_num(threshold),
            "direction": direction,
            "grey": grey_n,
            "tiers": tiers,
            "min_agree": agreed,
            "owner": self._addr_hex(gl.message.sender_address),
            "state": OPEN,
            "tier": 0,
            "tier_state": "GATHERING",
            "tier_reached": 0,
            "readings_this_tier": 0,
            "low": None,
            "high": None,
            "spread": None,
            "margin": None,
            "verdict": "",
            "note": "",
            "created_at": str(self._now()),
            "resolved_at": "",
        })
        return cid

    @gl.public.write
    def read(self, check_id: str, tier: int, source_index: int) -> str:
        """One fetch, one measurement. The assessment runs on what is already
        stored and settles early as soon as the evidence is decisive."""
        cid = str(check_id)
        c = json.loads(self.checks.get(cid, "{}"))
        if not c:
            raise gl.vm.UserError("Check not found")
        if c["state"] != OPEN:
            raise gl.vm.UserError("Check already resolved")
        t = int(tier)
        if t != int(c["tier"]):
            raise gl.vm.UserError("Not the current tier")
        idx = int(source_index)
        names = c["tiers"][t]
        if idx < 0 or idx >= len(names):
            raise gl.vm.UserError("source_index out of range")
        if self.reads.get(self._rkey(cid, t, idx), ""):
            raise gl.vm.UserError("Source already read for this tier")

        ex = self._extract(names[idx], c["field"], c["unit"])
        if not isinstance(ex, dict) or not isinstance(ex.get("retrieved"), bool):
            raise gl.vm.UserError("Invalid extraction")
        if not ex.get("retrieved"):
            raise gl.vm.UserError("Source could not be retrieved")

        body = ex["body"][:MAX_BODY_CHARS]
        value = ex.get("value", "")
        unit = ex.get("unit", "")
        if not isinstance(value, str) or len(value) > MAX_VALUE_LEN:
            raise gl.vm.UserError("Extracted value is invalid")
        if not isinstance(unit, str) or len(unit) > MAX_UNIT:
            raise gl.vm.UserError("Extracted unit is invalid")

        value = value.strip().replace(",", "")
        num = self._to_num(value) if value else None
        reason = ""
        if not value:
            reason = "not_stated"
        elif num is None:
            reason = "not_numeric"
        elif unit.strip().lower() != str(c["unit"]).strip().lower():
            reason = "wrong_unit"
        elif not self._anchored_number(body, value):
            reason = "not_in_source"
        elif str(c["unit"]).strip().lower() not in body.lower():
            reason = "unit_not_in_source"

        self.reads[self._rkey(cid, t, idx)] = json.dumps({
            "check_id": cid, "tier": t, "source_index": idx, "url": names[idx],
            "value": num if not reason else None,
            "raw_value": value, "raw_unit": unit, "rejected": reason,
            "read_at": str(self._now()),
        })

        c = self._assess(c)
        self.checks[cid] = json.dumps(c)
        return json.dumps({"value": num if not reason else None,
                           "rejected": reason, "state": c["state"]})

    @gl.public.write
    def close_check(self, check_id: str) -> str:
        cid = str(check_id)
        c = json.loads(self.checks.get(cid, "{}"))
        if not c:
            raise gl.vm.UserError("Check not found")
        if c["state"] == CLOSED:
            raise gl.vm.UserError("Already closed")
        if self._addr_hex(gl.message.sender_address).lower() != str(c["owner"]).lower():
            raise gl.vm.UserError("Only the owner can close")
        c["state"] = CLOSED
        c["note"] = "closed by owner"
        self.checks[cid] = json.dumps(c)
        return CLOSED

    def _rkey(self, cid: str, tier: int, idx: int) -> str:
        return str(cid) + "|" + str(tier) + "|" + str(idx)

    # ---------------- views ----------------

    @gl.public.view
    def get_check(self, check_id: str) -> str:
        return self.checks.get(str(check_id), "{}")

    @gl.public.view
    def get_reading(self, check_id: str, tier: int, source_index: int) -> str:
        return self.reads.get(self._rkey(str(check_id), int(tier), int(source_index)), "{}")

    @gl.public.view
    def get_readings(self, check_id: str, tier: int) -> list:
        c = json.loads(self.checks.get(str(check_id), "{}"))
        if not c:
            return []
        t = int(tier)
        if t < 0 or t >= len(c["tiers"]):
            return []
        out = []
        for i in range(len(c["tiers"][t])):
            raw = self.reads.get(self._rkey(str(check_id), t, i), "")
            if raw:
                out.append(json.loads(raw))
        return out

    @gl.public.view
    def get_check_count(self) -> int:
        return self.check_count
