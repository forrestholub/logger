#!/usr/bin/env python3
"""
Summarize per-call IMS/SIP call-flow KPIs from an Android logcat dump.

Input:
  - A log file (default: log_all.txt) containing lines like:
      01-15 21:12:03.659 ... +EDMFAPP: 3,2105,"1484...","CallId@[ip]",...

Output:
  - One row per CALL_ID with the requested KPI columns in a CSV.

Notes / assumptions (based on your snippet):
  - We key calls primarily by CALL_ID (the hex-ish token near the end).
  - For +EDMFAPP 2105 (IMS signaling), we infer:
      * direction: 0 = SENT, 1 = RECEIVED
      * SIP line1 is a quoted field (e.g. "INVITE ...", "SIP/2.0 180 Ringing")
      * The tail fields look like: ..., CALL_ID, CELL_ID, PANI, RRC, <int>
  - Call setup time = first 180 Ringing - first INVITE (same CSeq INVITE if available).
  - Answer time = first "SIP/2.0 200 OK" with CSeq containing "INVITE"
  - Transitions are counted from PANI changes:
      * "IEEE-802.11..." = WiFi
      * "3GPP-..."       = Cellular
  - Some columns (like packet-level “LAST_PACKET”) don’t truly exist in logcat;
    this script populates them with the last matching raw log line / a synthesized
    “full packet” string from parsed fields.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple
import os

# ---- Config / parsing helpers ------------------------------------------------

EDMFAPP_RE = re.compile(r"\+EDMFAPP:\s*(.*)$")
TIMESTAMP_RE = re.compile(
    r"^(?P<mm>\d{2})-(?P<dd>\d{2})\s+(?P<hh>\d{2}):(?P<mi>\d{2}):(?P<ss>\d{2})\.(?P<ms>\d{3})"
)

WIFI_PANI_PREFIXES = ("IEEE-802.11",)
CELL_PANI_PREFIXES = ("3GPP-",)
INPUT_FILE_NAME_MATCH = "logall"
INPUT_FILE_NAME_MATCH2 = "radio_log_"


def find_files_with_pattern(directory, pattern):
    matching_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if re.search(pattern, file):
                matching_files.append(os.path.join(root, file))
    return matching_files


def parse_logcat_timestamp(line: str, year: Optional[int]) -> Optional[dt.datetime]:
    """Parse 'MM-DD HH:MM:SS.mmm' at start of logcat line into datetime."""
    m = TIMESTAMP_RE.match(line)
    if not m:
        return None

    mm = int(m.group("mm"))
    dd = int(m.group("dd"))
    hh = int(m.group("hh"))
    mi = int(m.group("mi"))
    ss = int(m.group("ss"))
    ms = int(m.group("ms"))

    y = year if year is not None else dt.datetime.now().year
    try:
        return dt.datetime(y, mm, dd, hh, mi, ss, ms * 1000)
    except ValueError:
        return None


def csv_parse_edmfapp_payload(payload: str) -> List[str]:
    """
    Parse the +EDMFAPP payload as CSV (comma-delimited, quotes allowed).
    """
    # The payload is CSV-like: 3,2105,"1484...","callid",1,"SIP/2.0 ...",...
    reader = csv.reader([payload], delimiter=",", quotechar='"', skipinitialspace=True)
    return next(reader)


def pani_to_network(pani: Optional[str]) -> Optional[str]:
    if not pani:
        return None
    p = pani.strip()
    if p.startswith(WIFI_PANI_PREFIXES):
        return "WiFi"
    if p.startswith(CELL_PANI_PREFIXES):
        return "Cellular"
    return None


def safe_float_seconds(delta: Optional[dt.timedelta]) -> Optional[float]:
    if delta is None:
        return None
    return round(delta.total_seconds(), 3)


# ---- Data model ---------------------------------------------------------------

@dataclasses.dataclass
class SipEvent:
    ts: dt.datetime
    call_id: str
    session_id: Optional[str]
    mo_number: Optional[str]
    direction: Optional[int]          # 0 sent, 1 received
    line1: Optional[str]              # SIP first line / request line
    cseq: Optional[str]
    reason: Optional[str]
    sdp: Optional[str]
    pani: Optional[str]
    rrc: Optional[str]
    raw: str


@dataclasses.dataclass
class CallStateEvent:
    ts: dt.datetime
    call_id: str
    mo_number: Optional[str]
    state_code: Optional[int]
    pani: Optional[str]
    raw: str


@dataclasses.dataclass
class CallAggregate:
    call_id: str
    session_ids: set = dataclasses.field(default_factory=set)
    mo_numbers: set = dataclasses.field(default_factory=set)
    mt_numbers: set = dataclasses.field(default_factory=set)

    sip_events: List[SipEvent] = dataclasses.field(default_factory=list)
    state_events: List[CallStateEvent] = dataclasses.field(default_factory=list)

    def sort_events(self) -> None:
        self.sip_events.sort(key=lambda e: e.ts)
        self.state_events.sort(key=lambda e: e.ts)

    def all_events_sorted(self) -> List[Tuple[dt.datetime, str, Any]]:
        """
        Return (ts, kind, event) for both SIP and call-state events.
        kind: "sip" or "state"
        """
        evs: List[Tuple[dt.datetime, str, Any]] = []
        evs.extend([(e.ts, "sip", e) for e in self.sip_events])
        evs.extend([(e.ts, "state", e) for e in self.state_events])
        evs.sort(key=lambda x: x[0])
        return evs


# ---- EDMFAPP field extraction -------------------------------------------------

def extract_tail_call_id_cell_pani_rrc(fields: List[str]) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Heuristic: many 2105 lines end with:
      ..., CALL_ID, CELL_ID, PANI, RRC, <int>
    So we read from the end.
    """
    if len(fields) < 5:
        return None, None, None, None

    # Last field often "1" or similar.
    rrc = fields[-2] if len(fields) >= 2 else None
    pani = fields[-3] if len(fields) >= 3 else None
    cell_id = fields[-4] if len(fields) >= 4 else None
    call_id = fields[-5] if len(fields) >= 5 else None

    # Normalize
    call_id = call_id.strip() if call_id else None
    cell_id = cell_id.strip() if cell_id else None
    pani = pani.strip() if pani else None
    rrc = rrc.strip() if rrc else None

    # Sometimes cell_id is -1 and call_id is actually earlier; accept best-effort.
    return call_id, cell_id, pani, rrc


def parse_2105(fields: List[str], ts: dt.datetime, raw_line: str) -> Optional[SipEvent]:
    """
    +EDMFAPP 2105 (IMS signaling) parser based on your snippet.
    Example (shortened):
      3,2105,"1484...","CallId@[ip]",0,"INVITE ...","CSeq: 138 INVITE","", "<sdp>", ... ,"6d86...",-1,"IEEE-802.11n","CONNECTIONSETUPCOMPLETE",1
    """
    # Minimal sanity:
    if len(fields) < 8:
        return None

    mo_number = fields[2] if len(fields) > 2 else None
    session_id = fields[3] if len(fields) > 3 else None

    # Direction is usually fields[4] after mo_number and session_id.
    direction: Optional[int] = None
    if len(fields) > 4:
        try:
            direction = int(fields[4])
        except ValueError:
            direction = None

    line1 = fields[5] if len(fields) > 5 else None
    cseq = fields[6] if len(fields) > 6 else None
    reason = fields[7] if len(fields) > 7 else None
    sdp = fields[9] if len(fields) > 9 else None  # often empty or SDP-ish

    call_id, _cell_id, pani, rrc = extract_tail_call_id_cell_pani_rrc(fields)
    if not call_id:
        return None

    return SipEvent(
        ts=ts,
        call_id=call_id,
        session_id=session_id,
        mo_number=mo_number,
        direction=direction,
        line1=line1,
        cseq=cseq,
        reason=reason,
        sdp=sdp,
        pani=pani,
        rrc=rrc,
        raw=raw_line.rstrip("\n"),
    )


def parse_2102(fields: List[str], ts: dt.datetime, raw_line: str) -> Optional[CallStateEvent]:
    """
    +EDMFAPP 2102 (call state / metrics) parser.
    Your snippet shows:
      3,2102,"1484...", 1, -1, 1, "-57", ... ,"6d86...", 0,0,-1
    The state_code appears early (fields[3]).
    CALL_ID is near the end in many variants.
    """
    if len(fields) < 5:
        return None

    mo_number = fields[2] if len(fields) > 2 else None

    state_code: Optional[int] = None
    try:
        state_code = int(fields[3])
    except (ValueError, TypeError):
        state_code = None

    # CALL_ID often appears as a hex token somewhere near the end.
    call_id: Optional[str] = None
    pani: Optional[str] = None

    # Try tail heuristic first:
    tail_call_id, _cell_id, tail_pani, _rrc = extract_tail_call_id_cell_pani_rrc(fields)
    if tail_call_id and re.fullmatch(r"[0-9a-fA-F]{10,}", tail_call_id):
        call_id = tail_call_id
        pani = tail_pani
    else:
        # Fallback: search last 20 fields for a hex-ish id
        for token in reversed(fields[-25:]):
            t = token.strip()
            if re.fullmatch(r"[0-9a-fA-F]{10,}", t):
                call_id = t
                break

    if not call_id:
        return None

    return CallStateEvent(
        ts=ts,
        call_id=call_id,
        mo_number=mo_number,
        state_code=state_code,
        pani=pani,
        raw=raw_line.rstrip("\n"),
    )


# ---- KPI computation ----------------------------------------------------------

def find_first_sip_event(call: CallAggregate, predicate) -> Optional[SipEvent]:
    for e in call.sip_events:
        if predicate(e):
            return e
    return None


def find_last_sip_event(call: CallAggregate, predicate) -> Optional[SipEvent]:
    for e in reversed(call.sip_events):
        if predicate(e):
            return e
    return None


def compute_transitions(call: CallAggregate) -> Tuple[int, int, Optional[str], Optional[str]]:
    """
    Count PANI transitions across the merged ordered events.
    Returns:
      (cell_to_wifi, wifi_to_cell, start_network, end_network)
    """
    events = call.all_events_sorted()

    # Build a PANI timeline (collapse consecutive duplicates)
    pani_seq: List[str] = []
    for _ts, kind, ev in events:
        pani = None
        if kind == "sip":
            pani = ev.pani
        else:
            pani = ev.pani

        if not pani:
            continue

        if not pani_seq or pani_seq[-1] != pani:
            pani_seq.append(pani)

    networks: List[str] = []
    for p in pani_seq:
        n = pani_to_network(p)
        if n:
            networks.append(n)
        else:
            networks.append("Unknown")

    cell_to_wifi = 0
    wifi_to_cell = 0
    for prev, cur in zip(networks, networks[1:]):
        if prev == "Cellular" and cur == "WiFi":
            cell_to_wifi += 1
        elif prev == "WiFi" and cur == "Cellular":
            wifi_to_cell += 1

    start_network = networks[0] if networks else None
    end_network = networks[-1] if networks else None
    return cell_to_wifi, wifi_to_cell, start_network, end_network


def summarize_rat(call: CallAggregate) -> str:
    """
    Simple summary: most common network based on PANI.
    """
    counts: Dict[str, int] = defaultdict(int)
    for _ts, kind, ev in call.all_events_sorted():
        pani = ev.pani if kind == "sip" else ev.pani
        n = pani_to_network(pani)
        if n:
            counts[n] += 1

    if not counts:
        return "Unknown"
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    parts = [f"{k}:{v}" for k, v in ordered]
    return " | ".join(parts)


def build_sip_call_flow(call: CallAggregate, max_items: int = 80) -> str:
    """
    Build a compact call-flow string from SIP line1 + direction.
    """
    items: List[str] = []
    for e in call.sip_events:
        if not e.line1:
            continue
        dir_txt = "S>" if e.direction == 0 else "R<" if e.direction == 1 else "?"
        msg = e.line1.strip()
        items.append(f"{dir_txt}{msg}")

    if len(items) > max_items:
        head = items[: max_items // 2]
        tail = items[-max_items // 2 :]
        items = head + ["..."] + tail

    return " -> ".join(items)


def infer_call_type(call: CallAggregate) -> str:
    """
    Rough: WiFi call if first network is WiFi and INVITE includes PANI WiFi; else LTE/Cellular.
    """
    _c2w, _w2c, start_net, _end_net = compute_transitions(call)
    if start_net == "WiFi":
        return "WFC/WiFi IMS"
    if start_net == "Cellular":
        return "Cellular IMS"
    return "Unknown"


def infer_voice_call_result(call: CallAggregate) -> str:
    """
    Success if we see 200 OK to INVITE + ACK, otherwise failure/unknown.
    """
    ok_invite = find_first_sip_event(
        call,
        lambda e: (e.line1 or "").startswith("SIP/2.0 200 OK")
        and "INVITE" in (e.cseq or ""),
    )
    ack = find_first_sip_event(call, lambda e: (e.line1 or "").startswith("ACK "))
    bye = find_first_sip_event(call, lambda e: (e.line1 or "").startswith("BYE "))
    if ok_invite and ack:
        # If it ended with BYE/200 OK to BYE, treat as normal success.
        if bye:
            return "Success (BYE)"
        return "Success"
    # Look for common failure responses to INVITE
    fail = find_first_sip_event(
        call,
        lambda e: (e.line1 or "").startswith("SIP/2.0")
        and any(code in (e.line1 or "") for code in [" 4", " 5", " 6"])
        and "INVITE" in (e.cseq or ""),
    )
    if fail:
        return f"Fail ({fail.line1})"
    return "Unknown"


def infer_failure_reason(call: CallAggregate) -> Optional[str]:
    """
    Use the first non-empty 'Reason:' header found on INVITE-related failure responses.
    """
    for e in call.sip_events:
        if not e.reason:
            continue
        if "INVITE" in (e.cseq or ""):
            r = e.reason.strip()
            if r:
                return r
    return None


def infer_bye_cause(call: CallAggregate) -> Optional[str]:
    """
    Best-effort:
      - If we see BYE with a Reason header, capture it.
      - Or capture Reason on 200 OK to BYE.
    """
    for e in call.sip_events:
        if (e.line1 or "").startswith("BYE ") and e.reason:
            return e.reason.strip() or None

    for e in call.sip_events:
        if (e.line1 or "").startswith("SIP/2.0 200 OK") and "BYE" in (e.cseq or "") and e.reason:
            return e.reason.strip() or None

    return None


def compute_times(call: CallAggregate) -> Dict[str, Any]:
    """
    Compute timestamps and elapsed times.
    """
    events = call.all_events_sorted()

    call_start = min((t for (t, _kind, _ev) in events), default=None)
    call_end = max((t for (t, _kind, _ev) in events), default=None)

    invite = find_first_sip_event(call, lambda e: (e.line1 or "").startswith("INVITE ") and e.direction == 0)
    ringing_180 = find_first_sip_event(call, lambda e: (e.line1 or "") == "SIP/2.0 180 Ringing")
    prog_183 = find_first_sip_event(call, lambda e: (e.line1 or "") == "SIP/2.0 183 Session Progress")

    ok_invite = find_first_sip_event(
        call,
        lambda e: (e.line1 or "").startswith("SIP/2.0 200 OK") and "INVITE" in (e.cseq or ""),
    )

    setup_td = None
    if invite and ringing_180:
        setup_td = ringing_180.ts - invite.ts

    answer_elapsed_td = None
    if invite and ok_invite:
        answer_elapsed_td = ok_invite.ts - invite.ts

    traffic_td = None
    if ok_invite and call_end:
        traffic_td = call_end - ok_invite.ts

    return {
        "CALL_START_TIME": call_start,
        "SIP_183_SESSION_PROGRESS_TIMESTAMP": prog_183.ts if prog_183 else None,
        "VOICE_CALL_SETUP_TIMESTAMP": ringing_180.ts if ringing_180 else None,
        "VOICE_CALL_SETUP_TIMESTAMP_DEVICE": ringing_180.ts if ringing_180 else None,
        "VOICE_CALL_SETUP": safe_float_seconds(setup_td),
        "VOICE_CALL_SETUP_DEVICE": safe_float_seconds(setup_td),
        "VOICE_CALL_ANSWER_TIME": ok_invite.ts if ok_invite else None,
        "VOICE_CALL_ANSWER_ELAPSED_TIME": safe_float_seconds(answer_elapsed_td),
        "VOICE_CALL_ANSWER_ELAPSED_TIME_DEVICE": safe_float_seconds(answer_elapsed_td),
        "TRAFFIC_ELAPSED_TIME": safe_float_seconds(traffic_td),
        "TRAFFIC_ELAPSED_TIME_DEVICE": safe_float_seconds(traffic_td),
        "CALL_END_TIME": call_end,
        "INVITE_TS": invite.ts if invite else None,
    }



# ---- Main parse / output ------------------------------------------------------

def parse_calls_from_log(path: str, year: Optional[int]) -> Dict[str, CallAggregate]:
    calls: Dict[str, CallAggregate] = {}

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            ts = parse_logcat_timestamp(line, year=year)
            if ts is None:
                continue

            m = EDMFAPP_RE.search(line)
            if not m:
                continue

            payload = m.group(1).strip()
            try:
                fields = csv_parse_edmfapp_payload(payload)
            except Exception:
                continue

            if len(fields) < 2:
                continue

            # fields[0] is usually "3"
            msg_id = fields[1].strip()

            if msg_id == "2105":
                ev = parse_2105(fields, ts, line)
                if not ev:
                    continue
                agg = calls.get(ev.call_id)
                if agg is None:
                    agg = CallAggregate(call_id=ev.call_id)
                    calls[ev.call_id] = agg
                agg.sip_events.append(ev)
                if ev.session_id:
                    agg.session_ids.add(ev.session_id)
                if ev.mo_number:
                    agg.mo_numbers.add(ev.mo_number)

            elif msg_id == "2102":
                ev2 = parse_2102(fields, ts, line)
                if not ev2:
                    continue
                agg2 = calls.get(ev2.call_id)
                if agg2 is None:
                    agg2 = CallAggregate(call_id=ev2.call_id)
                    calls[ev2.call_id] = agg2
                agg2.state_events.append(ev2)
                if ev2.mo_number:
                    agg2.mo_numbers.add(ev2.mo_number)

            else:
                # Ignore other EDMFAPP message IDs for now (2107 etc.),
                # but you can add parsers later.
                continue

    for agg in calls.values():
        agg.sort_events()

    return calls


def dt_to_str(ts: Optional[dt.datetime]) -> str:
    if ts is None:
        return ""
    return ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="logall.txt", help="Input logcat file (default: log_all.txt)")
    parser.add_argument("--output", default="call_summary.csv", help="Output CSV path")
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Year to apply to timestamps (logcat lacks year). Default: current year.",
    )
    args = parser.parse_args()
    input_file = args.input

    # Find files matching the input pattern
    matching_files_logall = find_files_with_pattern('.', INPUT_FILE_NAME_MATCH)
    matching_files_radio = find_files_with_pattern('.', INPUT_FILE_NAME_MATCH2)

    if matching_files_logall:
        input_file = matching_files_logall[0]
    elif matching_files_radio:
        input_file = matching_files_radio[0]
    else:
        print("no files found")
        exit(1)

    calls = parse_calls_from_log(input_file, year=args.year)

    # Output columns exactly as you listed:
    columns = [
        "CALL_ID",
        "SESSION_ID",
        "CALL_TYPE",
        "VOICE_CALL_RESULT",
        "RAT_SUMMARY",
        "VOICE_CALL_ANALYSIS",
        "SIP_BYE_CAUSE",
        "SIP_FAILURE_REASON",
        "SIP_CALL_FLOW",
        "SIP_LAST_MSG",
        "SIP_LAST_PACKET",
        "SIP_LAST_FULL_PACKET",
        "VOICE_CALL_EVENT",
        "CALL_START_TIME",
        "SIP_183_SESSION_PROGRESS_TIMESTAMP",
        "VOICE_CALL_SETUP_TIMESTAMP",
        "VOICE_CALL_SETUP_TIMESTAMP_DEVICE",
        "VOICE_CALL_SETUP",
        "VOICE_CALL_SETUP_DEVICE",
        "VOICE_CALL_ANSWER_TIME",
        "VOICE_CALL_ANSWER_ELAPSED_TIME",
        "VOICE_CALL_ANSWER_ELAPSED_TIME_DEVICE",
        "TRAFFIC_ELAPSED_TIME",
        "TRAFFIC_ELAPSED_TIME_DEVICE",
        "CALL_END_TIME",
        "CALL_MO_NUMBER",
        "CALL_MT_NUMBER",
        "CALL_START_NETWORK",
        "CALL_END_NETWORK",
        "NUM_CELLULAR_TO_WIFI_TRANSITIONS",
        "NUM_WIFI_TO_CELLULAR_TRANSITIONS",
    ]

    with open(args.output, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=columns)
        writer.writeheader()

        for call_id, call in sorted(calls.items(), key=lambda kv: kv[0]):
            # Core inferences
            call_type = infer_call_type(call)
            result = infer_voice_call_result(call)
            rat_summary = summarize_rat(call)
            failure_reason = infer_failure_reason(call)
            bye_cause = infer_bye_cause(call)
            sip_flow = build_sip_call_flow(call)

            # Times
            times = compute_times(call)

            # Networks + transitions
            c2w, w2c, start_net, end_net = compute_transitions(call)

            # SIP last message
            last_sip = call.sip_events[-1] if call.sip_events else None
            sip_last_msg = last_sip.line1 if last_sip and last_sip.line1 else ""
            sip_last_packet = last_sip.raw if last_sip else ""
            sip_last_full_packet = ""
            if last_sip:
                # "Full packet" proxy: line1 + CSeq + Reason + SDP
                parts = []
                if last_sip.line1:
                    parts.append(last_sip.line1)
                if last_sip.cseq:
                    parts.append(last_sip.cseq)
                if last_sip.reason:
                    parts.append(last_sip.reason)
                if last_sip.sdp:
                    parts.append(last_sip.sdp)
                sip_last_full_packet = " | ".join([p for p in parts if p])

            # Session ID: pick the main one (most common) if multiple
            session_id = ""
            if call.session_ids:
                # Prefer the session_id that appears most in SIP events
                counts: Dict[str, int] = defaultdict(int)
                for e in call.sip_events:
                    if e.session_id:
                        counts[e.session_id] += 1
                session_id = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

            # MO/MT numbers
            mo_number = sorted(call.mo_numbers)[0] if call.mo_numbers else ""
            mt_number = sorted(call.mt_numbers)[0] if call.mt_numbers else ""  # not extracted from snippet

            # Voice call analysis (lightweight, you can expand)
            analysis_parts = []
            if times.get("INVITE_TS") and times.get("VOICE_CALL_SETUP"):
                analysis_parts.append(f"INVITE->180={times['VOICE_CALL_SETUP']}s")
            if times.get("VOICE_CALL_ANSWER_ELAPSED_TIME") is not None:
                analysis_parts.append(f"INVITE->200OK={times['VOICE_CALL_ANSWER_ELAPSED_TIME']}s")
            if c2w or w2c:
                analysis_parts.append(f"Transitions C2W={c2w}, W2C={w2c}")
            if failure_reason:
                analysis_parts.append(f"FailureReason={failure_reason}")
            voice_call_analysis = "; ".join(analysis_parts)

            row = {
                "CALL_ID": call_id,
                "SESSION_ID": session_id,
                "CALL_TYPE": call_type,
                "VOICE_CALL_RESULT": result,
                "RAT_SUMMARY": rat_summary,
                "VOICE_CALL_ANALYSIS": voice_call_analysis,
                "SIP_BYE_CAUSE": bye_cause or "",
                "SIP_FAILURE_REASON": failure_reason or "",
                "SIP_CALL_FLOW": sip_flow,
                "SIP_LAST_MSG": sip_last_msg,
                "SIP_LAST_PACKET": sip_last_packet,
                "SIP_LAST_FULL_PACKET": sip_last_full_packet,
                "VOICE_CALL_EVENT": "",  # placeholder: extend if you map 2102 state codes -> labels
                "CALL_START_TIME": dt_to_str(times["CALL_START_TIME"]),
                "SIP_183_SESSION_PROGRESS_TIMESTAMP": dt_to_str(times["SIP_183_SESSION_PROGRESS_TIMESTAMP"]),
                "VOICE_CALL_SETUP_TIMESTAMP": dt_to_str(times["VOICE_CALL_SETUP_TIMESTAMP"]),
                "VOICE_CALL_SETUP_TIMESTAMP_DEVICE": dt_to_str(times["VOICE_CALL_SETUP_TIMESTAMP_DEVICE"]),
                "VOICE_CALL_SETUP": "" if times["VOICE_CALL_SETUP"] is None else str(times["VOICE_CALL_SETUP"]),
                "VOICE_CALL_SETUP_DEVICE": "" if times["VOICE_CALL_SETUP_DEVICE"] is None else str(times["VOICE_CALL_SETUP_DEVICE"]),
                "VOICE_CALL_ANSWER_TIME": dt_to_str(times["VOICE_CALL_ANSWER_TIME"]),
                "VOICE_CALL_ANSWER_ELAPSED_TIME": "" if times["VOICE_CALL_ANSWER_ELAPSED_TIME"] is None else str(times["VOICE_CALL_ANSWER_ELAPSED_TIME"]),
                "VOICE_CALL_ANSWER_ELAPSED_TIME_DEVICE": "" if times["VOICE_CALL_ANSWER_ELAPSED_TIME_DEVICE"] is None else str(times["VOICE_CALL_ANSWER_ELAPSED_TIME_DEVICE"]),
                "TRAFFIC_ELAPSED_TIME": "" if times["TRAFFIC_ELAPSED_TIME"] is None else str(times["TRAFFIC_ELAPSED_TIME"]),
                "TRAFFIC_ELAPSED_TIME_DEVICE": "" if times["TRAFFIC_ELAPSED_TIME_DEVICE"] is None else str(times["TRAFFIC_ELAPSED_TIME_DEVICE"]),
                "CALL_END_TIME": dt_to_str(times["CALL_END_TIME"]),
                "CALL_MO_NUMBER": mo_number,
                "CALL_MT_NUMBER": mt_number,
                "CALL_START_NETWORK": start_net or "",
                "CALL_END_NETWORK": end_net or "",
                "NUM_CELLULAR_TO_WIFI_TRANSITIONS": str(c2w),
                "NUM_WIFI_TO_CELLULAR_TRANSITIONS": str(w2c),
            }

            writer.writerow(row)

    print(f"Wrote {len(calls)} call rows -> {args.output}")


if __name__ == "__main__":
    main()
