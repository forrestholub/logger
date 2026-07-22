#!/usr/bin/env python3
"""
WFC Handover (HO) Analyzer

Parses Android logcat files to extract Wi‑Fi Calling (WFC) / IMS handover details
between Wi‑Fi and cellular for two vendor styles observed in the provided logs:
- Samsung (e.g., samsung_main_logcat.txt)
- MTK (e.g., logcat_file.txt)

Outputs:
- Command line summary table of detected HO events and key metrics.
- Excel .xlsx (if openpyxl installed) or CSV fallback.

Metrics per HO event:
- Direction: WiFi→Cellular or Cellular→WiFi (best‑effort inference)
- Control‑plane HO start/end timestamps (if markers found) + latency (ms)
- User‑plane HO start/end based on RTP interarrival gap + latency (ms)
- Packet loss (%) and count around HO window (from RTCP RR or PLC hints)
- Jitter stats around HO (from NET_STAT/RTCP)
- RSSI at transition (Wi‑Fi) and cellular signal at transition (best effort)
- Failures detected (timeouts, registration failures, repeated PLC/late discards)
- Handover impact score 0–100 (higher is worse) based on loss, jitter and gap

Assumptions & Notes:
- Log timestamps are in the form "MM-DD HH:MM:SS.mmm" (logcat default). We parse
  leading timestamps from each line when present; otherwise we rely on previous
  timestamp (rare in logcat). Timezone is irrelevant; only relative diffs used.
- Vendor markers vary widely. This script uses a set of regex heuristics that are
  easy to extend: see MARKERS and REGEX sections below.
- If explicit control‑plane markers are missing, control‑plane latency is None.
- User‑plane analysis uses RTP/SAE style lines when present. If not present, it
  falls back to RTCP RR intervals and PLC/late discard markers.
- Signal metrics (Wi‑Fi RSSI, cellular RSRP/RSRQ/SINR) are parsed when present;
  many builds omit them from main logs. Missing values are left None.

Usage:
    python wfc_ho_parser.py \
        --samsung "C:\\path\\to\\samsung_main_logcat.txt" \
        --mtk "C:\\path\\to\\logcat_file.txt" \
        --excel out.xlsx --csv out.csv --window-ms 5000

You can pass one or both logs; the script will auto-detect vendor markers even if
files are swapped.

Extendability:
- Add new regex patterns to VendorPatterns for control/user plane markers.
- Add new signal metric regex if your firmware logs different tags/format.

"""
from __future__ import annotations

import argparse
import csv
import math
import os
import re
import sys
import heapq
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Iterable
from pathlib import Path
# Try optional Excel writer
try:
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter
    HAVE_XLSX = True
except Exception:
    HAVE_XLSX = False

# ----------------------------
# Logging setup
# ----------------------------
def setup_logging(log_file: str, level_name: str = 'INFO') -> None:
    """Configure root logger to log to both console and a file.
    level_name: one of 'DEBUG','INFO','WARNING','ERROR'
    """
    level = getattr(logging, (level_name or 'INFO').upper(), logging.INFO)
    root = logging.getLogger()
    # Clear existing handlers to avoid duplication when main() re-runs
    if root.handlers:
        for h in list(root.handlers):
            root.removeHandler(h)
    root.setLevel(logging.DEBUG)  # capture everything; handlers will filter
    fmt_console = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    fmt_file = logging.Formatter('%(asctime)s %(levelname)s %(name)s:%(lineno)d %(message)s')
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(fmt_console)
    root.addHandler(ch)
    # File handler
    try:
        log_path = Path(log_file)
        if log_path.parent and not log_path.parent.exists():
            log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_path), mode='w', encoding='utf-8')
        fh.setLevel(logging.DEBUG)  # always full detail in file
        fh.setFormatter(fmt_file)
        root.addHandler(fh)
        logging.getLogger(__name__).info(f'File logging initialized: {log_path} (level={level_name})')
    except Exception as e:
        logging.getLogger(__name__).warning(f'Failed to initialize file logging at {log_file}: {e}')

# ----------------------------
# Tunable Parameters (defaults)
# You can adjust these values or override via CLI flags in main()
# ----------------------------
# Samsung W2L success marker clustering window (seconds)
CLUSTER_WINDOW_SEC = 5
# Search window (seconds) to find the nearest attempt trigger before success
W2L_ATTEMPT_SEARCH_SEC = 60
# IKE AUTH pairing window (seconds) to pair request1 with response3
IKE_PAIR_WINDOW_SEC = 60
# Impact window (milliseconds) for max RX inter-arrival gap around HO center
IMPACT_WINDOW_MS = 4000
# Upper bound for valid user-plane latency when bracketing (milliseconds)
MAX_UP_LATENCY_MS = 30000
# OEM KPI (RegiMgr) association window (seconds) around HO center
OEM_KPI_WINDOW_SEC = 30
# OEM packet loss association window (seconds) to find latest OEM loss before HO center
OEM_LOSS_WINDOW_SEC = 30
# Extra margin (seconds) added around KPI windows when collecting RTCP/jitter stats
LOSS_JITTER_MARGIN_SEC = 5
# Time window (seconds) within which a signal KPI is considered "near attempt"
SIGNAL_WINDOW_SEC = 5
# Assumed RTP packet rate (packets per second) for speech (20ms ptime => 50pps)
PKT_RATE_HZ = 50
# Use SSRC change to refine user-plane bracketing
USE_SSRC_FOR_UP = False
# Window for SSRC influence (ms) around HO center (W2L) or after AUTH (L2W)
SSRC_INFLUENCE_WINDOW_MS = IMPACT_WINDOW_MS
# Use CHILD_SA established as CP end stand-in when IMS_WIFI not logged (auxiliary only)
USE_CHILD_SA_AS_CP_END = False
# Association window (seconds) to attach OEM pre-HO latency (HIGH RTP LOSS ... Latency is NNN) before W2L center
OEM_PREHO_ASSOC_SEC = 60


# ----------------------------
# Timestamp parsing utilities
# ----------------------------
# Support multiple common logcat timestamp formats, not necessarily at line start
TS_PATTERNS = [
    # MM-DD HH:MM:SS.mmm (standard logcat)
    re.compile(r"(?P<mm>\d{2})-(?P<dd>\d{2})\s+(?P<hh>\d{2}):(?P<mi>\d{2}):(?P<ss>\d{2})[\.,](?P<ms>\d{3})"),
    # YYYY-MM-DD HH:MM:SS.mmm
    re.compile(r"(?P<yyyy>\d{4})-(?P<mm>\d{2})-(?P<dd>\d{2})\s+(?P<hh>\d{2}):(?P<mi>\d{2}):(?P<ss>\d{2})[\.,](?P<ms>\d{3})"),
    # MM-DD HH:MM:SS (no milliseconds)
    re.compile(r"(?P<mm>\d{2})-(?P<dd>\d{2})\s+(?P<hh>\d{2}):(?P<mi>\d{2}):(?P<ss>\d{2})(?![\.:]\d)"),
]

# Detect and parse the first timestamp-like token anywhere in the line
# If year is absent, infer from file mtime (passed in) or current year

def parse_ts(line: str, year: int = None) -> Optional[datetime]:
    for pat in TS_PATTERNS:
        m = pat.search(line)
        if not m:
            continue
        try:
            if 'yyyy' in m.groupdict() and m.group('yyyy') is not None:
                y = int(m.group('yyyy'))
            else:
                y = year if year else datetime.now().year
            mm = int(m.group('mm'))
            dd = int(m.group('dd'))
            hh = int(m.group('hh'))
            mi = int(m.group('mi'))
            ss = int(m.group('ss'))
            # Milliseconds may be missing
            ms = int(m.group('ms')) if 'ms' in m.groupdict() and m.group('ms') is not None else 0
            return datetime(y, mm, dd, hh, mi, ss, ms * 1000)
        except Exception:
            continue
    return None

# ----------------------------
# Markers & Regex (heuristics)
# ----------------------------
class VendorPatterns:
    """Regex patterns we look for per vendor or generic."""

    # Common RTP/RTCP/SAE-like media path
    RTP_RX_RE = re.compile(r"ProcessRTPPacket.*?ssrc\s*=\s*(?P<ssrc>0x[0-9a-fA-F]+).*?seq_num\s*=\s*(?P<seq>\d+).*?ts\s*=\s*(?P<rtpts>\d+)")
    RTP_TX_RE = re.compile(r"SendAudio.*?seq_num\s*=\s*(?P<seq>\d+).*?ts\s*=\s*(?P<rtpts>\d+)")
    NET_STAT_JITTER_RE = re.compile(r"NET_STAT.*?InterArrivalJitter\s*=\s*(?P<jitter>[\d\.]+)")
    RTCP_RR_RE = re.compile(r"RTCP.*?RR.*?cum_lost\s*\[(?P<lost>\d+)\].*?Jitter\s*\[(?P<jitter>\d+)\]", re.IGNORECASE)
    RTCP_INTERVAL_RE = re.compile(r"Calculated RTCP Interval\s*=\s*(?P<ival>[\d\.]+)")
    LATE_DISCARD_RE = re.compile(r"Late packet discard", re.IGNORECASE)
    PLC_RE = re.compile(r"EVS PLC.*?Lost=(?P<lost>\d+)", re.IGNORECASE)

    # Control plane / path switch indications (generic + OEM)
    # Try a broad set of likely markers across OEMs
    WIFI_UP_RE = re.compile(r"\b(WIFI|Wi-Fi|IWLAN|WLAN|VoWiFi|VoWIFI|VOWIFI)\b.*(Connected|Register|Established)", re.IGNORECASE)
    WIFI_DOWN_RE = re.compile(r"\b(WIFI|Wi-Fi|IWLAN|WLAN|VoWiFi|VoWIFI|VOWIFI)\b.*(Disconnected|Deregister|Tear|Closed)", re.IGNORECASE)
    EPDG_RE = re.compile(r"\b(EPDG|ePDG)\b.*(connect|disconnect|handover|tunnel|IKE)", re.IGNORECASE)
    IMS_REG_WIFI_RE = re.compile(r"IMS.*(registered|voice over wifi|VOWIFI).*", re.IGNORECASE)
    IMS_REG_CELL_RE = re.compile(r"IMS.*(registered).*?(LTE|NR|5G|4G|cell|mobile)", re.IGNORECASE)
    SRVCC_RE = re.compile(r"SRVCC|SRVCC\s+start|SRVCC\s+complete", re.IGNORECASE)
    HANDOVER_RE = re.compile(r"handover|HO\s+(start|end|complete)", re.IGNORECASE)

    # Samsung-specific HO and IKE markers
    SAM_HO_W2L_SUCC_RE = re.compile(r"\bOH_EVENT\]W2L HO success|Handover Result \(HANDOVER_W2L\) : True", re.IGNORECASE)
    SAM_HO_L2W_SUCC_RE = re.compile(r"\bOH_EVENT\]L2W HO Success|Handover Result \(HANDOVER_L2W\) : True", re.IGNORECASE)
    SAM_HO_RESULT_RE = re.compile(r"EpdgHandoverHandler.*mHOResult.*mIsL2WHandover\s*=\s*(?P<l2w>[01]).*mResult\s*=\s*(?P<res>[01])", re.IGNORECASE)
    SAM_IKE_AUTH_REQ1_RE = re.compile(r"eris\s*:.*generating IKE_AUTH request 1", re.IGNORECASE)
    SAM_IKE_AUTH_RESP3_RE = re.compile(r"eris\s*:.*parsed IKE_AUTH response 3 \[ AUTH", re.IGNORECASE)
    SAM_HO_HIGHLOSS_RE = re.compile(r"HIGH RTP LOSS", re.IGNORECASE)
    SAM_HO_CRITERIA_RE = re.compile(r"HO_CRITERIA", re.IGNORECASE)
    # Samsung RTPlossrate OEM metric
    SAM_RTP_LOSS_RE = re.compile(r"RTP loss:.*?RTPlossrate\s*:\s*(?P<loss>[\d\.]+).*?jitter\s*:\s*(?P<jitter>[\d\.]+)", re.IGNORECASE)
    # Samsung HIGH RTP LOSS with latency
    SAM_HI_LOSS_LAT_RE = re.compile(r"HIGH RTP LOSS detected\s*:.*Latency\s+is\s+(?P<lat>\d+)", re.IGNORECASE)
    # IPSEC events and CHILD_SA established
    SAM_IPSEC_EVT_RE = re.compile(r"EPDG\s*--.*IPSEC_CONN_(?P<state>CONNECTED|DISCONNECTED)", re.IGNORECASE)
    SAM_CHILD_SA_EST_RE = re.compile(r"eris\s*:.*CHILD_SA\s+.*\sestablished", re.IGNORECASE)
    # Samsung RegiMgr KPI[0]
    SAM_REGIMGR_KPI0_RE = re.compile(r"RegiMgr\s*:.*?#IMSREGI\s*-\s*KPI\[0\].*?Total Time\s+(?P<total>[\d\.]+)s,\s*<Gap\s+IMS\s+PDN\s+from\s+Request\s+to\s+Connected\s*:\s*(?P<pdn>[\d\.]+)s>.*?<Gap\s+Latch\s+from\s+Data\s+Attch?\s+to\s+PDN\s+Request\s*:\s*(?P<latch>[\d\.]+)s", re.IGNORECASE)
    # RAT corroborators
    ECHOLOCATE_RAT_RE = re.compile(r"Echolocate_Info: getRatType Type:\s*(?P<rat>\w+)")
    TELEPHONY_DISP_RE = re.compile(r"TelephonyDisplayInfo\s+.*\{network=(?P<net>\w+).*\}")

    # MTK/TCL-specific markers
    MTK_HO_ATTEMPT_RE = re.compile(r"VoiceMetrics: all msg = 2102.*call_state=EPDG_HO_STARTED", re.IGNORECASE)
    MTK_HO_SUCCESS_RE = re.compile(r"VoiceMetrics: all msg = 2102.*call_state=EPDG_HO_SUCCESSFUL", re.IGNORECASE)
    # New: MTK VoiceMetrics 2102 in 'data' format (observed variant)
    MTK_VM_2102_DATA_STARTED_RE = re.compile(r"VoiceMetrics:\s*2102\s*data:.*call_state=EPDG_HO_STARTED", re.IGNORECASE)
    MTK_VM_2102_DATA_SUCCESS_RE = re.compile(r"VoiceMetrics:\s*2102\s*data:.*call_state=EPDG_HO_SUCCESSFUL", re.IGNORECASE)
    MTK_VM_2102_DATA_FAILED_RE = re.compile(r"VoiceMetrics:\s*2102\s*data:.*call_state=EPDG_HO_FAILED", re.IGNORECASE)
    MTK_VM_BCAST_STARTED_RE = re.compile(r"VoiceMetrics: send2102Broadcast.*EPDG_HO_STARTED", re.IGNORECASE)
    MTK_VM_BCAST_SUCCESS_RE = re.compile(r"VoiceMetrics: send2102Broadcast.*EPDG_HO_SUCCESSFUL", re.IGNORECASE)
    MTK_PDN_BEGIN_RE = re.compile(r"VT\s*:.*PDN_HANDOVER_BEGIN", re.IGNORECASE)
    MTK_PDN_END_RE = re.compile(r"VT\s*:.*PDN_HANDOVER_END", re.IGNORECASE)
    # MTK L2W Control-plane anchors provided by user
    MTK_L2W_START_RE = re.compile(r"onNotifyPdnHandover.*\+EPDNHANDOVER:\s*0,0,1,2", re.IGNORECASE)
    MTK_L2W_END_RE = re.compile(r"\[\s*WLAN\s*:\s*IWLAN->IWLAN\s*,\s*NOT_REG_SEARCHING->HOME\s*\]", re.IGNORECASE)
    MTK_RTP_LOSS_RE = re.compile(r"VolteNotifier: onRtpLossRateNoti:.*LossRate(?P<loss>[\d\.]+).*Jitter\s+(?P<jitter>[\d\.]+)", re.IGNORECASE)
    MTK_VM_2101_RE = re.compile(r"VoiceMetrics: all msg = 2101.*rtp_downlink_loss_rate=(?P<loss>[\d\.]+).*rtp_downlink_delay=(?P<delay>\d+).*rtp_downlink_jitter=(?P<jitter>\d+)", re.IGNORECASE)
    # IMS 200 OK REGISTER from EDMFAPP
    EDMFAPP_REG_OK_RE = re.compile(r"EDMFAPP:.*\"SIP/2\.0 200 OK\".*\"CSeq:\s*\d+\s*REGISTER\"", re.IGNORECASE)

    # Wi-Fi / Cellular signal metrics
    WIFI_RSSI_RE = re.compile(r"\bRSSI\s*=\s*(?P<rssi>-?\d{1,3})\b|rssi=(?P<rssi2>-?\d{1,3})", re.IGNORECASE)
    RSRP_RE = re.compile(r"\bRSRP\s*=\s*(?P<rsrp>-?\d{1,3})\b", re.IGNORECASE)
    RSRQ_RE = re.compile(r"\bRSRQ\s*=\s*(?P<rsrq>-?\d{1,2})\b", re.IGNORECASE)
    SINR_RE = re.compile(r"\b(SINR|SNR)\s*=\s*(?P<sinr>-?\d{1,2})\b", re.IGNORECASE)

    # Vendor hints
    SAMSUNG_HINT_RE = re.compile(r"SAE|RTP\s+Average|RTCP|EIMS|Samsung|ScanController|EpdgHandoverHandler|IPSECDATACONNSM|eris|RegiMgr", re.IGNORECASE)
    MTK_HINT_RE = re.compile(r"EMDLOGGER|ccci|mtk|hwcomposer|libPerfCtl|VoiceMetrics|VolteNotifier|VT\s*:.*PDN_HANDOVER", re.IGNORECASE)


@dataclass
class MediaPacket:
    t: datetime
    seq: int
    rx_tx: str  # 'rx' or 'tx'
    rtp_ts: Optional[int] = None
    ssrc: Optional[str] = None

@dataclass
class RtcpStat:
    t: datetime
    cum_lost: int
    jitter: float

@dataclass
class SignalSnapshot:
    t: datetime
    wifi_rssi: Optional[int] = None
    rsrp: Optional[int] = None
    rsrq: Optional[int] = None
    sinr: Optional[int] = None

@dataclass
class ControlMarker:
    t: datetime
    kind: str  # e.g., WIFI_DOWN, WIFI_UP, IMS_WIFI, IMS_CELL, EPDG, SRVCC, HANDOVER
    raw: str

@dataclass
class OemKpi:
    t: datetime
    source: str  # e.g., RegiMgr_KPI0
    total_time_s: Optional[float]
    pdn_req_to_connected_s: Optional[float]
    latch_to_pdn_req_s: Optional[float]
    raw: str

@dataclass
class OemLoss:
    t: datetime
    source: str  # e.g., Samsung_RTP_loss, MTK_VoiceMetrics2101, MTK_VolteNotifier
    loss_rate_pct: Optional[float]  # percentage as float
    jitter_ms: Optional[float]
    raw: str

@dataclass
class OemPreHoLatency:
    t: datetime
    source: str  # e.g., SAM_HI_LOSS
    latency_ms: Optional[int]
    raw: str

@dataclass
class HOEvent:
    vendor: str
    direction: Optional[str]  # "WiFi->Cell" or "Cell->WiFi" or None
    # Attempt/Result
    attempt_ts: Optional[datetime]
    result: Optional[str]  # Success/Failure/Unknown
    # Control plane (primary)
    ctrl_start: Optional[datetime]
    ctrl_end: Optional[datetime]
    ctrl_latency_ms: Optional[float]
    cp_method: Optional[str]
    reason_ctrl: Optional[str]
    # Control plane (PDN-specific)
    cp_pdn_start: Optional[datetime] = None
    cp_pdn_end: Optional[datetime] = None
    cp_pdn_latency_ms: Optional[float] = None
    reason_cp_pdn: Optional[str] = None
    # User plane
    user_start: Optional[datetime] = None
    user_end: Optional[datetime] = None
    user_latency_ms: Optional[float] = None
    up_method: Optional[str] = None
    reason_user: Optional[str] = None
    # KPIs
    pkt_loss_count: Optional[int] = None
    pkt_loss_rate_pct: Optional[float] = None
    reason_loss: Optional[str] = None
    jitter_mean: Optional[float] = None
    reason_jitter: Optional[str] = None
    wifi_rssi_at_ho: Optional[int] = None
    reason_rssi: Optional[str] = None
    rsrp_at_ho: Optional[int] = None
    reason_rsrp: Optional[str] = None
    rsrq_at_ho: Optional[int] = None
    reason_rsrq: Optional[str] = None
    sinr_at_ho: Optional[int] = None
    reason_sinr: Optional[str] = None
    # OEM CP auxiliary metrics
    oem_total_time_s: Optional[float] = None
    oem_pdn_req_to_connected_s: Optional[float] = None
    oem_latch_to_pdn_req_s: Optional[float] = None
    oem_cp_source: Optional[str] = None
    reason_oem_cp: Optional[str] = None
    # OEM Loss auxiliary metrics
    oem_loss_rate_pct: Optional[float] = None
    oem_loss_jitter_ms: Optional[float] = None
    oem_loss_source: Optional[str] = None
    reason_oem_loss: Optional[str] = None
    # New QoE and OEM metrics (optional)
    evs_plc_event_count: Optional[int] = None
    evs_plc_lost_sum: Optional[int] = None
    late_discard_count: Optional[int] = None
    jitter_peak: Optional[float] = None
    reason_plc: Optional[str] = None
    reason_late_discard: Optional[str] = None
    reason_jitter_peak: Optional[str] = None
    ssrc_changed_at_ho: Optional[bool] = None
    ssrc_change_ts: Optional[datetime] = None
    reason_ssrc: Optional[str] = None
    oem_preho_latency_ms: Optional[int] = None
    oem_preho_source: Optional[str] = None
    reason_oem_preho: Optional[str] = None
    ctrl_end_ipsec: Optional[datetime] = None
    cp_method_detail: Optional[str] = None
    reason_cp_detail: Optional[str] = None
    rat_before: Optional[str] = None
    rat_after: Optional[str] = None
    # Failure/Notes/Impact
    failure_cause: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    impact_score: Optional[float] = None
    reason_impact: Optional[str] = None

# ----------------------------
# Core parsing functions
# ----------------------------

def iter_lines(path: str) -> Iterable[Tuple[Optional[datetime], str]]:
    if not os.path.exists(path):
        return
    # Infer year from file modified time to avoid year rollover issues
    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        inferred_year = mtime.year
    except Exception:
        inferred_year = None
    last_ts = None
    with open(path, 'r', errors='replace', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            ts = parse_ts(line, inferred_year)
            if ts:
                last_ts = ts
            yield last_ts, line


def iter_lines_multi(paths: List[str]) -> Iterable[Tuple[Optional[datetime], str]]:
    """Merge multiple files by timestamp order. Assumes each file individually has
    non-decreasing timestamps. Yields (ts, line) across all files ordered by ts.
    Lines without a parsable timestamp inherit their file's last seen ts via
    iter_lines(). If a file yields None timestamps only, it effectively contributes nothing.
    """
    # Build one iterator per file
    iters = [iter(iter_lines(p)) for p in paths if os.path.exists(p)]
    heap = []  # (ts, idx, line, iterator)
    # Prime each iterator by advancing until we hit the first line that has a timestamp
    for idx, it in enumerate(iters):
        try:
            while True:
                ts, line = next(it)
                if ts is not None:
                    heapq.heappush(heap, (ts, idx, line, it))
                    break
        except StopIteration:
            pass
    while heap:
        ts, idx, line, it = heapq.heappop(heap)
        yield ts, line
        # Advance this iterator until the next line that has a timestamp
        try:
            while True:
                ts2, line2 = next(it)
                if ts2 is not None:
                    heapq.heappush(heap, (ts2, idx, line2, it))
                    break
        except StopIteration:
            pass


def scan_log(path: str) -> Dict[str, List]:
    vp = VendorPatterns
    media: List[MediaPacket] = []
    rtcp: List[RtcpStat] = []
    signals: List[SignalSnapshot] = []
    ctrls: List[ControlMarker] = []
    oem_kpis: List[OemKpi] = []
    oem_losses: List[OemLoss] = []
    oem_preho: List[OemPreHoLatency] = []
    plc_events: List[Tuple[datetime, int]] = []
    late_discards: List[datetime] = []
    rat_snaps: List[Tuple[datetime, str]] = []
    tdisp_snaps: List[Tuple[datetime, str]] = []
    rtcp_intervals: List[Tuple[datetime, float]] = []
    vendor_hint_counts = { 'samsung': 0, 'mtk': 0 }

    for ts, line in iter_lines(path):
        if ts is None:
            continue
        # vendor hints
        if vp.SAMSUNG_HINT_RE.search(line):
            vendor_hint_counts['samsung'] += 1
        if vp.MTK_HINT_RE.search(line):
            vendor_hint_counts['mtk'] += 1

        # RTP RX
        m = vp.RTP_RX_RE.search(line)
        if m:
            try:
                media.append(MediaPacket(ts, int(m.group('seq')), 'rx', int(m.group('rtpts')), m.group('ssrc')))
            except Exception:
                pass
        # RTP TX
        m = vp.RTP_TX_RE.search(line)
        if m:
            try:
                media.append(MediaPacket(ts, int(m.group('seq')), 'tx', int(m.group('rtpts'))))
            except Exception:
                pass
        # RTCP
        m = vp.RTCP_RR_RE.search(line)
        if m:
            try:
                rtcp.append(RtcpStat(ts, int(m.group('lost')), float(m.group('jitter'))))
            except Exception:
                pass
        # Jitter NET_STAT (used as additional source)
        m = vp.NET_STAT_JITTER_RE.search(line)
        if m:
            try:
                rtcp.append(RtcpStat(ts, math.nan, float(m.group('jitter'))))
            except Exception:
                pass

        # Control markers
        if vp.WIFI_DOWN_RE.search(line):
            ctrls.append(ControlMarker(ts, 'WIFI_DOWN', line))
        elif vp.WIFI_UP_RE.search(line):
            ctrls.append(ControlMarker(ts, 'WIFI_UP', line))
        elif vp.EPDG_RE.search(line):
            ctrls.append(ControlMarker(ts, 'EPDG', line))
        elif vp.IMS_REG_WIFI_RE.search(line):
            ctrls.append(ControlMarker(ts, 'IMS_WIFI', line))
        elif vp.IMS_REG_CELL_RE.search(line):
            ctrls.append(ControlMarker(ts, 'IMS_CELL', line))
        elif vp.SRVCC_RE.search(line):
            ctrls.append(ControlMarker(ts, 'SRVCC', line))
        elif vp.HANDOVER_RE.search(line):
            ctrls.append(ControlMarker(ts, 'HANDOVER', line))
        # MTK specific control markers
        if vp.MTK_PDN_BEGIN_RE.search(line):
            ctrls.append(ControlMarker(ts, 'MTK_PDN_BEGIN', line))
        if vp.MTK_PDN_END_RE.search(line):
            ctrls.append(ControlMarker(ts, 'MTK_PDN_END', line))
        # MTK LTE->WiFi anchors (start/end)
        if vp.MTK_L2W_START_RE.search(line):
            ctrls.append(ControlMarker(ts, 'MTK_L2W_START', line))
        if vp.MTK_L2W_END_RE.search(line):
            ctrls.append(ControlMarker(ts, 'MTK_L2W_END', line))
        # MTK 2102 VoiceMetrics variants (attempt/result/failed)
        if (vp.MTK_HO_ATTEMPT_RE.search(line) or 
            vp.MTK_VM_BCAST_STARTED_RE.search(line) or 
            vp.MTK_VM_2102_DATA_STARTED_RE.search(line)):
            ctrls.append(ControlMarker(ts, 'MTK_HO_ATTEMPT', line))
        if (vp.MTK_HO_SUCCESS_RE.search(line) or 
            vp.MTK_VM_BCAST_SUCCESS_RE.search(line) or 
            vp.MTK_VM_2102_DATA_SUCCESS_RE.search(line)):
            ctrls.append(ControlMarker(ts, 'MTK_HO_SUCCESS', line))
        if vp.MTK_VM_2102_DATA_FAILED_RE.search(line):
            ctrls.append(ControlMarker(ts, 'MTK_HO_FAILED', line))
        if vp.EDMFAPP_REG_OK_RE.search(line):
            ctrls.append(ControlMarker(ts, 'IMS_REG_200', line))
        # Samsung HO markers
        if vp.SAM_HO_W2L_SUCC_RE.search(line):
            ctrls.append(ControlMarker(ts, 'SAM_W2L_SUCC', line))
        if vp.SAM_HO_L2W_SUCC_RE.search(line):
            ctrls.append(ControlMarker(ts, 'SAM_L2W_SUCC', line))
        mh = vp.SAM_HO_RESULT_RE.search(line)
        if mh:
            ctrls.append(ControlMarker(ts, 'SAM_HO_RESULT', line))
            # Synthesize explicit success markers from mHOResult to trigger existing branches
            try:
                is_l2w = mh.group('l2w') == '1'
                is_success = mh.group('res') == '1'
                logging.debug('Samsung mHOResult parsed at %s: is_l2w=%s is_success=%s', ts, is_l2w, is_success)
                if is_success:
                    if is_l2w:
                        ctrls.append(ControlMarker(ts, 'SAM_L2W_SUCC', line))
                        logging.debug('Synthesized SAM_L2W_SUCC at %s from mHOResult', ts)
                    else:
                        ctrls.append(ControlMarker(ts, 'SAM_W2L_SUCC', line))
                        logging.debug('Synthesized SAM_W2L_SUCC at %s from mHOResult', ts)
            except Exception as e:
                logging.debug('Failed to synthesize from mHOResult: %s', e)
        # IKE anchors (Samsung strongSwan/eris)
        if vp.SAM_IKE_AUTH_REQ1_RE.search(line):
            ctrls.append(ControlMarker(ts, 'IKE_REQ1', line))
        if vp.SAM_IKE_AUTH_RESP3_RE.search(line):
            ctrls.append(ControlMarker(ts, 'IKE_RESP3', line))
        # Samsung RegiMgr KPI[0]
        m = vp.SAM_REGIMGR_KPI0_RE.search(line)
        if m:
            try:
                total = float(m.group('total')) if m.group('total') is not None else None
                pdn = float(m.group('pdn')) if m.group('pdn') is not None else None
                latch = float(m.group('latch')) if m.group('latch') is not None else None
                oem_kpis.append(OemKpi(ts, 'RegiMgr_KPI0', total, pdn, latch, line))
            except Exception:
                pass
        # Samsung OEM RTP loss rate
        m = vp.SAM_RTP_LOSS_RE.search(line)
        if m:
            try:
                loss = float(m.group('loss'))
                jit = float(m.group('jitter')) if m.group('jitter') is not None else None
                oem_losses.append(OemLoss(ts, 'Samsung_RTP_loss', loss, jit, line))
            except Exception:
                pass
        # Samsung HIGH RTP LOSS with latency (OEM pre-HO)
        m = vp.SAM_HI_LOSS_LAT_RE.search(line)
        if m:
            try:
                lat = int(m.group('lat'))
                oem_preho.append(OemPreHoLatency(ts, 'Samsung_HO_OPTIMIZATION', lat, line))
            except Exception:
                pass
        # MTK OEM RTP loss rate (VolteNotifier)
        m = vp.MTK_RTP_LOSS_RE.search(line)
        if m:
            try:
                loss = float(m.group('loss'))
                jit = float(m.group('jitter')) if m.group('jitter') is not None else None
                oem_losses.append(OemLoss(ts, 'MTK_VolteNotifier', loss, jit, line))
            except Exception:
                pass
        # MTK VoiceMetrics 2101 downlink metrics
        m = vp.MTK_VM_2101_RE.search(line)
        if m:
            try:
                loss = float(m.group('loss'))
                jit = float(m.group('jitter')) if m.group('jitter') is not None else None
                oem_losses.append(OemLoss(ts, 'MTK_VoiceMetrics2101', loss, jit, line))
            except Exception:
                pass

        # Additional control markers (Samsung)
        m = vp.SAM_IPSEC_EVT_RE.search(line)
        if m:
            state = m.group('state').upper()
            ctrls.append(ControlMarker(ts, f'IPSEC_{state}', line))
        if vp.SAM_CHILD_SA_EST_RE.search(line):
            ctrls.append(ControlMarker(ts, 'CHILD_SA_EST', line))

        # PLC and Late discard QoE hints
        m = vp.PLC_RE.search(line)
        if m:
            try:
                plc_events.append((ts, int(m.group('lost'))))
            except Exception:
                plc_events.append((ts, 0))
        if vp.LATE_DISCARD_RE.search(line):
            late_discards.append(ts)

        # RTCP interval capture (optional)
        m = vp.RTCP_INTERVAL_RE.search(line)
        if m:
            try:
                rtcp_intervals.append((ts, float(m.group('ival'))))
            except Exception:
                pass

        # RAT corroborators
        m = vp.ECHOLOCATE_RAT_RE.search(line)
        if m:
            rat_snaps.append((ts, m.group('rat')))
        m = vp.TELEPHONY_DISP_RE.search(line)
        if m:
            tdisp_snaps.append((ts, m.group('net')))

        # Signal metrics
        snap = SignalSnapshot(ts)
        w = vp.WIFI_RSSI_RE.search(line)
        if w:
            rssi = w.group('rssi') or w.group('rssi2')
            try:
                snap.wifi_rssi = int(rssi)
            except Exception:
                pass
        r = vp.RSRP_RE.search(line)
        if r:
            try:
                snap.rsrp = int(r.group('rsrp'))
            except Exception:
                pass
        r = vp.RSRQ_RE.search(line)
        if r:
            try:
                snap.rsrq = int(r.group('rsrq'))
            except Exception:
                pass
        s = vp.SINR_RE.search(line)
        if s:
            try:
                snap.sinr = int(s.group('sinr'))
            except Exception:
                pass
        if any([snap.wifi_rssi is not None, snap.rsrp is not None, snap.rsrq is not None, snap.sinr is not None]):
            signals.append(snap)

        # Failures markers (a small set; extend as needed)
        if 'fail' in line.lower() or 'error' in line.lower() or 'timeout' in line.lower():
            if any(k in line.lower() for k in ['ims', 'epdg', 'wifi', 'wlan', 'rtp', 'rtcp', 'srvcc']):
                ctrls.append(ControlMarker(ts, 'FAIL', line))

    # Decide vendor
    vendor = 'samsung' if vendor_hint_counts['samsung'] >= vendor_hint_counts['mtk'] else 'mtk'
    return {
        'vendor': vendor,
        'media': media,
        'rtcp': rtcp,
        'signals': signals,
        'ctrls': ctrls,
        'oem_kpis': oem_kpis,
        'oem_losses': oem_losses,
        'oem_preho': oem_preho,
        'plc_events': plc_events,
        'late_discards': late_discards,
        'rat_snaps': rat_snaps,
        'tdisp_snaps': tdisp_snaps,
        'rtcp_intervals': rtcp_intervals,
    }


def scan_logs(paths: List[str]) -> Dict[str, List]:
    """Same as scan_log but for multiple files merged chronologically."""
    vp = VendorPatterns
    media: List[MediaPacket] = []
    rtcp: List[RtcpStat] = []
    signals: List[SignalSnapshot] = []
    ctrls: List[ControlMarker] = []
    oem_kpis: List[OemKpi] = []
    oem_losses: List[OemLoss] = []
    oem_preho: List[OemPreHoLatency] = []
    plc_events: List[Tuple[datetime, int]] = []
    late_discards: List[datetime] = []
    rat_snaps: List[Tuple[datetime, str]] = []
    tdisp_snaps: List[Tuple[datetime, str]] = []
    rtcp_intervals: List[Tuple[datetime, float]] = []
    vendor_hint_counts = { 'samsung': 0, 'mtk': 0 }

    for ts, line in iter_lines_multi(paths):
        if ts is None:
            continue
        # vendor hints
        if vp.SAMSUNG_HINT_RE.search(line):
            vendor_hint_counts['samsung'] += 1
        if vp.MTK_HINT_RE.search(line):
            vendor_hint_counts['mtk'] += 1

        # RTP RX
        m = vp.RTP_RX_RE.search(line)
        if m:
            try:
                media.append(MediaPacket(ts, int(m.group('seq')), 'rx', int(m.group('rtpts')), m.group('ssrc')))
            except Exception:
                pass
        # RTP TX
        m = vp.RTP_TX_RE.search(line)
        if m:
            try:
                media.append(MediaPacket(ts, int(m.group('seq')), 'tx', int(m.group('rtpts'))))
            except Exception:
                pass
        # RTCP
        m = vp.RTCP_RR_RE.search(line)
        if m:
            try:
                rtcp.append(RtcpStat(ts, int(m.group('lost')), float(m.group('jitter'))))
            except Exception:
                pass
        # Jitter NET_STAT (used as additional source)
        m = vp.NET_STAT_JITTER_RE.search(line)
        if m:
            try:
                rtcp.append(RtcpStat(ts, math.nan, float(m.group('jitter'))))
            except Exception:
                pass
        # RTCP interval
        m = vp.RTCP_INTERVAL_RE.search(line)
        if m:
            try:
                rtcp_intervals.append((ts, float(m.group('ival'))))
            except Exception:
                pass

        # Control markers
        if vp.WIFI_DOWN_RE.search(line):
            ctrls.append(ControlMarker(ts, 'WIFI_DOWN', line))
        elif vp.WIFI_UP_RE.search(line):
            ctrls.append(ControlMarker(ts, 'WIFI_UP', line))
        elif vp.EPDG_RE.search(line):
            ctrls.append(ControlMarker(ts, 'EPDG', line))
        elif vp.IMS_REG_WIFI_RE.search(line):
            ctrls.append(ControlMarker(ts, 'IMS_WIFI', line))
        elif vp.IMS_REG_CELL_RE.search(line):
            ctrls.append(ControlMarker(ts, 'IMS_CELL', line))
        elif vp.SRVCC_RE.search(line):
            ctrls.append(ControlMarker(ts, 'SRVCC', line))
        elif vp.HANDOVER_RE.search(line):
            ctrls.append(ControlMarker(ts, 'HANDOVER', line))
        # MTK specific control markers
        if vp.MTK_PDN_BEGIN_RE.search(line):
            ctrls.append(ControlMarker(ts, 'MTK_PDN_BEGIN', line))
        if vp.MTK_PDN_END_RE.search(line):
            ctrls.append(ControlMarker(ts, 'MTK_PDN_END', line))
        # MTK LTE->WiFi anchors (start/end)
        if vp.MTK_L2W_START_RE.search(line):
            ctrls.append(ControlMarker(ts, 'MTK_L2W_START', line))
        if vp.MTK_L2W_END_RE.search(line):
            ctrls.append(ControlMarker(ts, 'MTK_L2W_END', line))
        # MTK 2102 VoiceMetrics variants (attempt/result/failed)
        if (vp.MTK_HO_ATTEMPT_RE.search(line) or 
            vp.MTK_VM_BCAST_STARTED_RE.search(line) or 
            vp.MTK_VM_2102_DATA_STARTED_RE.search(line)):
            ctrls.append(ControlMarker(ts, 'MTK_HO_ATTEMPT', line))
        if (vp.MTK_HO_SUCCESS_RE.search(line) or 
            vp.MTK_VM_BCAST_SUCCESS_RE.search(line) or 
            vp.MTK_VM_2102_DATA_SUCCESS_RE.search(line)):
            ctrls.append(ControlMarker(ts, 'MTK_HO_SUCCESS', line))
        if vp.MTK_VM_2102_DATA_FAILED_RE.search(line):
            ctrls.append(ControlMarker(ts, 'MTK_HO_FAILED', line))
        if vp.EDMFAPP_REG_OK_RE.search(line):
            ctrls.append(ControlMarker(ts, 'IMS_REG_200', line))
        # Samsung HO markers
        if vp.SAM_HO_W2L_SUCC_RE.search(line):
            ctrls.append(ControlMarker(ts, 'SAM_W2L_SUCC', line))
        if vp.SAM_HO_L2W_SUCC_RE.search(line):
            ctrls.append(ControlMarker(ts, 'SAM_L2W_SUCC', line))
        mh = vp.SAM_HO_RESULT_RE.search(line)
        if mh:
            ctrls.append(ControlMarker(ts, 'SAM_HO_RESULT', line))
            # Synthesize explicit success markers from mHOResult to trigger existing branches
            try:
                is_l2w = mh.group('l2w') == '1'
                is_success = mh.group('res') == '1'
                logging.debug('Samsung mHOResult parsed at %s: is_l2w=%s is_success=%s', ts, is_l2w, is_success)
                if is_success:
                    if is_l2w:
                        ctrls.append(ControlMarker(ts, 'SAM_L2W_SUCC', line))
                        logging.debug('Synthesized SAM_L2W_SUCC at %s from mHOResult', ts)
                    else:
                        ctrls.append(ControlMarker(ts, 'SAM_W2L_SUCC', line))
                        logging.debug('Synthesized SAM_W2L_SUCC at %s from mHOResult', ts)
            except Exception as e:
                logging.debug('Failed to synthesize from mHOResult: %s', e)
        # IKE anchors (Samsung strongSwan/eris)
        if vp.SAM_IKE_AUTH_REQ1_RE.search(line):
            ctrls.append(ControlMarker(ts, 'IKE_REQ1', line))
        if vp.SAM_IKE_AUTH_RESP3_RE.search(line):
            ctrls.append(ControlMarker(ts, 'IKE_RESP3', line))
        # IPSEC events and CHILD_SA
        m = vp.SAM_IPSEC_EVT_RE.search(line)
        if m:
            state = m.group('state').upper()
            ctrls.append(ControlMarker(ts, f'IPSEC_{state}', line))
        if vp.SAM_CHILD_SA_EST_RE.search(line):
            ctrls.append(ControlMarker(ts, 'CHILD_SA_EST', line))
        # Samsung RegiMgr KPI[0]
        m = vp.SAM_REGIMGR_KPI0_RE.search(line)
        if m:
            try:
                total = float(m.group('total')) if m.group('total') is not None else None
                pdn = float(m.group('pdn')) if m.group('pdn') is not None else None
                latch = float(m.group('latch')) if m.group('latch') is not None else None
                oem_kpis.append(OemKpi(ts, 'RegiMgr_KPI0', total, pdn, latch, line))
            except Exception:
                pass
        # Samsung OEM RTP loss rate
        m = vp.SAM_RTP_LOSS_RE.search(line)
        if m:
            try:
                loss = float(m.group('loss'))
                jit = float(m.group('jitter')) if m.group('jitter') is not None else None
                oem_losses.append(OemLoss(ts, 'Samsung_RTP_loss', loss, jit, line))
            except Exception:
                pass
        # Samsung HIGH RTP LOSS with latency (OEM pre-HO)
        m = vp.SAM_HI_LOSS_LAT_RE.search(line)
        if m:
            try:
                oem_preho.append(OemPreHoLatency(ts, 'Samsung_HO_OPTIMIZATION', int(m.group('lat')), line))
            except Exception:
                pass
        # MTK OEM RTP loss rate (VolteNotifier)
        m = vp.MTK_RTP_LOSS_RE.search(line)
        if m:
            try:
                loss = float(m.group('loss'))
                jit = float(m.group('jitter')) if m.group('jitter') is not None else None
                oem_losses.append(OemLoss(ts, 'MTK_VolteNotifier', loss, jit, line))
            except Exception:
                pass
        # MTK VoiceMetrics 2101 downlink metrics
        m = vp.MTK_VM_2101_RE.search(line)
        if m:
            try:
                loss = float(m.group('loss'))
                jit = float(m.group('jitter')) if m.group('jitter') is not None else None
                oem_losses.append(OemLoss(ts, 'MTK_VoiceMetrics2101', loss, jit, line))
            except Exception:
                pass

        # PLC and Late discard QoE hints
        m = vp.PLC_RE.search(line)
        if m:
            try:
                plc_events.append((ts, int(m.group('lost'))))
            except Exception:
                plc_events.append((ts, 0))
        if vp.LATE_DISCARD_RE.search(line):
            late_discards.append(ts)

        # RAT corroborators
        m = vp.ECHOLOCATE_RAT_RE.search(line)
        if m:
            rat_snaps.append((ts, m.group('rat')))
        m = vp.TELEPHONY_DISP_RE.search(line)
        if m:
            tdisp_snaps.append((ts, m.group('net')))

        # Signal metrics
        snap = SignalSnapshot(ts)
        w = vp.WIFI_RSSI_RE.search(line)
        if w:
            rssi = w.group('rssi') or w.group('rssi2')
            try:
                snap.wifi_rssi = int(rssi)
            except Exception:
                pass
        r = vp.RSRP_RE.search(line)
        if r:
            try:
                snap.rsrp = int(r.group('rsrp'))
            except Exception:
                pass
        r = vp.RSRQ_RE.search(line)
        if r:
            try:
                snap.rsrq = int(r.group('rsrq'))
            except Exception:
                pass
        s = vp.SINR_RE.search(line)
        if s:
            try:
                snap.sinr = int(s.group('sinr'))
            except Exception:
                pass
        if any([snap.wifi_rssi is not None, snap.rsrp is not None, snap.rsrq is not None, snap.sinr is not None]):
            signals.append(snap)

        # Failures markers (a small set; extend as needed)
        if 'fail' in line.lower() or 'error' in line.lower() or 'timeout' in line.lower():
            if any(k in line.lower() for k in ['ims', 'epdg', 'wifi', 'wlan', 'rtp', 'rtcp', 'srvcc']):
                ctrls.append(ControlMarker(ts, 'FAIL', line))

    vendor = 'samsung' if vendor_hint_counts['samsung'] >= vendor_hint_counts['mtk'] else 'mtk'
    return {
        'vendor': vendor,
        'media': media,
        'rtcp': rtcp,
        'signals': signals,
        'ctrls': ctrls,
        'oem_kpis': oem_kpis,
        'oem_losses': oem_losses,
        'oem_preho': oem_preho,
        'plc_events': plc_events,
        'late_discards': late_discards,
        'rat_snaps': rat_snaps,
        'tdisp_snaps': tdisp_snaps,
        'rtcp_intervals': rtcp_intervals,
    }


def detect_user_plane_gaps(media: List[MediaPacket], gap_ms_threshold: 150) -> List[Tuple[datetime, datetime]]:
    """Find intervals where RTP interarrival gap exceeds threshold.
    Returns list of (gap_start_ts, gap_end_ts) per detected gap.
    """
    gaps = []
    if len(media) < 3:
        return gaps
    media_sorted = sorted(media, key=lambda x: x.t)
    prev_t = media_sorted[0].t
    in_gap = False
    gap_start = None
    for pkt in media_sorted[1:]:
        dt = (pkt.t - prev_t).total_seconds() * 1000.0
        if dt >= gap_ms_threshold and not in_gap:
            in_gap = True
            gap_start = prev_t
        elif dt < gap_ms_threshold and in_gap:
            gaps.append((gap_start, pkt.t))
            in_gap = False
            gap_start = None
        prev_t = pkt.t
    if in_gap and gap_start is not None:
        gaps.append((gap_start, media_sorted[-1].t))
    return gaps


def closest_signal(signals: List[SignalSnapshot], t: datetime) -> SignalSnapshot:
    if not signals:
        return SignalSnapshot(t)
    best = min(signals, key=lambda s: abs((s.t - t).total_seconds()))
    return best


def compute_loss_and_jitter(rtcp: List[RtcpStat], window: Tuple[datetime, datetime]) -> Tuple[Optional[int], Optional[float], Optional[float]]:
    if not rtcp:
        return None, None, None
    start, end = window
    window_stats = [r for r in rtcp if start - timedelta(seconds=LOSS_JITTER_MARGIN_SEC) <= r.t <= end + timedelta(seconds=LOSS_JITTER_MARGIN_SEC)]
    if not window_stats:
        return None, None, None
    # cum_lost may be NaN in NET_STAT-based entries; filter them
    lost_vals = [r.cum_lost for r in window_stats if isinstance(r.cum_lost, int)]
    jitter_vals = [r.jitter for r in window_stats if isinstance(r.jitter, (int, float)) and not math.isnan(r.jitter)]
    pkt_loss_count = None
    if len(lost_vals) >= 2:
        pkt_loss_count = max(lost_vals) - min(lost_vals)
    jitter_mean = None
    if jitter_vals:
        jitter_mean = sum(jitter_vals) / len(jitter_vals)
    # Loss rate unknown without packet count; we approximate from RTP rate: use time window * 50 packets/sec (20ms frames)
    duration_s = max(0.02, (end - start).total_seconds())
    approx_pkts = duration_s * PKT_RATE_HZ
    pkt_loss_rate = (pkt_loss_count / approx_pkts * 100.0) if (pkt_loss_count is not None and approx_pkts > 0) else None
    return pkt_loss_count, pkt_loss_rate, jitter_mean


def infer_direction(ctrls: List[ControlMarker], user_window: Tuple[datetime, datetime]) -> Optional[str]:
    if not ctrls:
        return None
    start, end = user_window
    around = [c for c in ctrls if start - timedelta(seconds=10) <= c.t <= end + timedelta(seconds=10)]
    # Heuristic: WIFI_DOWN then IMS_CELL -> WiFi->Cell, WIFI_UP/IMS_WIFI -> Cell->WiFi
    kinds = [c.kind for c in around]
    if 'WIFI_DOWN' in kinds and 'IMS_CELL' in kinds:
        return 'WiFi->Cell'
    if 'WIFI_UP' in kinds and 'IMS_WIFI' in kinds:
        return 'Cell->WiFi'
    # ePDG disconnect near window typically means leaving Wi‑Fi
    if any(c.kind == 'EPDG' and 'disconnect' in c.raw.lower() for c in around):
        return 'WiFi->Cell'
    if any(c.kind == 'EPDG' and 'connect' in c.raw.lower() for c in around):
        return 'Cell->WiFi'
    return None


def infer_control_plane(ctrls: List[ControlMarker], direction: Optional[str]) -> Tuple[Optional[datetime], Optional[datetime], Optional[float]]:
    if not ctrls:
        return None, None, None
    # Prefer more specific anchors when available (MTK + Samsung)
    sorted_ctrls = sorted(ctrls, key=lambda c: c.t)
    start = end = None
    if direction == 'WiFi->Cell':
        # Start priority (W2L): MTK_PDN_BEGIN > EPDG disconnect > WIFI_DOWN > generic HANDOVER
        for c in sorted_ctrls:
            rawl = c.raw.lower()
            if c.kind in ('MTK_PDN_BEGIN',):
                start = c.t
                break
            if (c.kind == 'EPDG' and 'disconnect' in rawl) or c.kind == 'WIFI_DOWN' or (c.kind == 'HANDOVER' and 'start' in rawl):
                start = c.t
                break
        # End priority: MTK_PDN_END > IMS_CELL > IMS_REG_200 > SRVCC complete > generic HANDOVER end
        for c in sorted_ctrls:
            rawl = c.raw.lower()
            if c.t < (start or datetime.min):
                continue
            if c.kind in ('MTK_PDN_END',):
                end = c.t
                break
            if c.kind == 'IMS_CELL':
                end = c.t
                break
            if c.kind == 'IMS_REG_200':
                end = c.t
                break
            if c.kind == 'SRVCC' and 'complete' in rawl:
                end = c.t
                break
            if c.kind == 'HANDOVER' and ('end' in rawl or 'complete' in rawl):
                end = c.t
                break
    elif direction == 'Cell->WiFi':
        # Start priority (L2W): WIFI_UP > EPDG connect > HANDOVER start
        for c in sorted_ctrls:
            rawl = c.raw.lower()
            if c.kind == 'WIFI_UP' or (c.kind == 'EPDG' and 'connect' in rawl) or (c.kind == 'HANDOVER' and 'start' in rawl):
                start = c.t
                break
        # End priority: IMS_WIFI > CHILD_SA_EST > IPSEC_CONNECTED > IMS_REG_200
        for c in sorted_ctrls:
            rawl = c.raw.lower()
            if c.t < (start or datetime.min):
                continue
            if c.kind == 'IMS_WIFI':
                end = c.t
                break
            if c.kind in ('CHILD_SA_EST', 'IPSEC_CONNECTED'):
                end = c.t
                break
            if c.kind == 'IMS_REG_200':
                end = c.t
                break
    else:
        # Fallback: any obvious pair
        for i, c in enumerate(sorted_ctrls):
            if c.kind in ('MTK_PDN_BEGIN', 'WIFI_DOWN', 'WIFI_UP', 'EPDG', 'HANDOVER'):
                start = c.t
                for d in sorted_ctrls[i+1:]:
                    rawl = d.raw.lower()
                    if d.kind in ('MTK_PDN_END', 'IMS_WIFI', 'IMS_CELL', 'SRVCC', 'HANDOVER', 'IMS_REG_200'):
                        end = d.t
                        break
                break
    if start and end and end >= start:
        return start, end, (end - start).total_seconds() * 1000.0
    return start, end, None


def compute_impact_max_gap_ms(media: List[MediaPacket], center: datetime, window_ms: int = 2000) -> Optional[float]:
    """Impact score = maximum RX inter-arrival gap (ms) in ±window around center.
    Only RX RTP packets are considered.
    """
    if not media:
        return None
    start = center - timedelta(milliseconds=window_ms)
    end = center + timedelta(milliseconds=window_ms)
    rx = sorted([m for m in media if m.rx_tx == 'rx' and start <= m.t <= end], key=lambda x: x.t)
    if len(rx) < 2:
        return None
    max_gap = 0.0
    prev = rx[0].t
    for pkt in rx[1:]:
        gap = (pkt.t - prev).total_seconds() * 1000.0
        if gap > max_gap:
            max_gap = gap
        prev = pkt.t
    return round(max_gap, 1)


def _last_rx_before(media: List[MediaPacket], t: datetime) -> Optional[MediaPacket]:
    cand = [m for m in media if m.rx_tx == 'rx' and m.t < t]
    return max(cand, key=lambda x: x.t) if cand else None


def _first_rx_after(media: List[MediaPacket], t: datetime) -> Optional[MediaPacket]:
    cand = [m for m in media if m.rx_tx == 'rx' and m.t > t]
    return min(cand, key=lambda x: x.t) if cand else None


def _last_rx_before_ssrc(media: List[MediaPacket], t: datetime, ssrc: str) -> Optional[MediaPacket]:
    cand = [m for m in media if m.rx_tx == 'rx' and m.t < t and m.ssrc == ssrc]
    return max(cand, key=lambda x: x.t) if cand else None


def _first_rx_after_ssrc(media: List[MediaPacket], t: datetime, ssrc: str) -> Optional[MediaPacket]:
    cand = [m for m in media if m.rx_tx == 'rx' and m.t > t and m.ssrc == ssrc]
    return min(cand, key=lambda x: x.t) if cand else None


def detect_ssrc_switch(media: List[MediaPacket], start: datetime, end: datetime) -> Optional[Tuple[str, str, datetime]]:
    """Detect the first SSRC change in RX packets within [start, end].
    Returns (old_ssrc, new_ssrc, switch_ts) or None.
    """
    rx = [m for m in media if m.rx_tx == 'rx' and m.ssrc is not None and start <= m.t <= end]
    if len(rx) < 2:
        return None
    base = rx[0].ssrc
    for pkt in rx[1:]:
        if pkt.ssrc != base:
            return base, pkt.ssrc, pkt.t
    return None


def qoe_aggregates(plc_events: List[Tuple[datetime, int]], late_discards: List[datetime], rtcp: List[RtcpStat], window: Tuple[datetime, datetime]) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[float]]:
    s, e = window
    plc_in = [p for p in plc_events if s <= p[0] <= e]
    late_in = [t for t in late_discards if s <= t <= e]
    jitter_vals = [r.jitter for r in rtcp if (s - timedelta(seconds=LOSS_JITTER_MARGIN_SEC)) <= r.t <= (e + timedelta(seconds=LOSS_JITTER_MARGIN_SEC)) and isinstance(r.jitter, (int, float)) and not math.isnan(r.jitter)]
    plc_count = len(plc_in) if plc_in else None
    plc_sum = sum(v for _, v in plc_in) if plc_in else None
    late_count = len(late_in) if late_in else None
    jitter_peak = max(jitter_vals) if jitter_vals else None
    return plc_count, plc_sum, late_count, jitter_peak


def analyze_file(path: str, gap_ms_threshold: int, vendor_hint: Optional[str]) -> List[HOEvent]:
    """Analyze a single file by delegating to the multi-file pipeline to reuse logic."""
    return analyze_files([path], gap_ms_threshold, vendor_hint)


def analyze_files(paths: List[str], gap_ms_threshold: int, vendor_hint: Optional[str]) -> List[HOEvent]:
    """Analyze multiple files merged by timestamp as a single logical log."""
    data = scan_logs(paths)
    vendor = data['vendor']
    if vendor_hint in ('samsung', 'mtk'):
        vendor = vendor_hint

    media = data['media']
    rtcp = data['rtcp']
    signals = data['signals']
    ctrls = data['ctrls']
    oem_kpis: List[OemKpi] = data.get('oem_kpis', [])
    oem_losses: List[OemLoss] = data.get('oem_losses', [])
    oem_preho: List[OemPreHoLatency] = data.get('oem_preho', [])
    plc_events: List[Tuple[datetime, int]] = data.get('plc_events', [])
    late_discards: List[datetime] = data.get('late_discards', [])
    rat_snaps: List[Tuple[datetime, str]] = data.get('rat_snaps', [])
    tdisp_snaps: List[Tuple[datetime, str]] = data.get('tdisp_snaps', [])

    logging.info('analyze_files: vendor=%s files=%d media=%d rtcp=%d signals=%d ctrls=%d plc=%d late_discards=%d',
                 vendor, len(paths), len(media), len(rtcp), len(signals), len(ctrls), len(plc_events), len(late_discards))
    if logging.getLogger().isEnabledFor(logging.DEBUG):
        kinds = {}
        for c in ctrls:
            kinds[c.kind] = kinds.get(c.kind, 0) + 1
        logging.debug('Control kinds: %s', kinds)

    events: List[HOEvent] = []

    # Helper: choose pre-trigger signal (closest BEFORE t if possible)
    def pre_signal(signals_list: List[SignalSnapshot], t: datetime) -> SignalSnapshot:
        prev = [s for s in signals_list if s.t <= t]
        if prev:
            return max(prev, key=lambda s: s.t)
        return closest_signal(signals_list, t)

    # Helper: signal KPIs with window and reason strings per metric
    def signal_values_with_reason(signals_list: List[SignalSnapshot], t: datetime):
        def pick(metric_getter, name: str):
            # find latest snapshot at or before t that has this metric
            prior = [s for s in signals_list if s.t <= t and metric_getter(s) is not None]
            if not prior:
                return None, f'N/A - no {name} near attempt (no prior samples)'
            latest = max(prior, key=lambda s: s.t)
            age_s = (t - latest.t).total_seconds()
            val = metric_getter(latest)
            if age_s <= SIGNAL_WINDOW_SEC:
                return val, None
            else:
                # outside window: still report last value but explain
                age_str = f'{age_s:.1f}' if age_s >= 0.1 else f'{int(age_s)}'
                return val, f'N/A - no {name} near attempt, last recorded value was {val} {age_str} seconds before HO trigger'
        wifi_rssi, reason_rssi = pick(lambda s: s.wifi_rssi, 'WiFi RSSI')
        rsrp, reason_rsrp = pick(lambda s: s.rsrp, 'RSRP')
        rsrq, reason_rsrq = pick(lambda s: s.rsrq, 'RSRQ')
        sinr, reason_sinr = pick(lambda s: s.sinr, 'SINR')
        return wifi_rssi, reason_rssi, rsrp, reason_rsrp, rsrq, reason_rsrq, sinr, reason_sinr

    # Helper: pair MTK PDN BEGIN/END around a center time for CP_PDN latency
    def pair_mtk_pdn(center: datetime) -> Tuple[Optional[datetime], Optional[datetime], Optional[float], Optional[str]]:
        begins = [c for c in ctrls if c.kind == 'MTK_PDN_BEGIN' and c.t <= center and (center - c.t) <= timedelta(seconds=W2L_ATTEMPT_SEARCH_SEC)]
        if not begins:
            return None, None, None, 'No MTK_PDN_BEGIN within search window'
        begin = max(begins, key=lambda x: x.t)
        ends = [c for c in ctrls if c.kind == 'MTK_PDN_END' and c.t >= begin.t and (c.t - begin.t) <= timedelta(seconds=120)]
        if not ends:
            return begin.t, None, None, 'No MTK_PDN_END within 120s after PDN_BEGIN'
        end = min(ends, key=lambda x: x.t)
        lat = (end.t - begin.t).total_seconds() * 1000.0 if end.t >= begin.t else None
        return begin.t, end.t, lat, None

    # MTK WiFi->Cell synthesis from VoiceMetrics/VT markers (per user request)
    if vendor == 'mtk':
        # Cluster MTK successes to avoid duplicates
        mtk_succ = sorted([c for c in ctrls if c.kind == 'MTK_HO_SUCCESS'], key=lambda x: x.t)
        m_clusters: List[List[ControlMarker]] = []
        for mark in mtk_succ:
            if not m_clusters:
                m_clusters.append([mark])
            else:
                last = m_clusters[-1]
                if (mark.t - last[-1].t) <= timedelta(seconds=CLUSTER_WINDOW_SEC):
                    last.append(mark)
                else:
                    m_clusters.append([mark])
        for group in m_clusters:
            succ = group[0]
            # Attempt: prefer MTK_HO_ATTEMPT or MTK_PDN_BEGIN within backsearch window
            attempts = [c for c in ctrls if c.t <= succ.t and (succ.t - c.t) <= timedelta(seconds=W2L_ATTEMPT_SEARCH_SEC) and c.kind in ('MTK_HO_ATTEMPT','MTK_PDN_BEGIN')]
            attempt_ts = max(attempts, key=lambda x: x.t).t if attempts else succ.t
            # Direction inference from network_state_type
            direction = 'WiFi->Cell'
            raw_up = succ.raw.upper()
            net_type = None
            m_net = re.search(r"network_state_type=([A-Z0-9_]+)", raw_up)
            if m_net:
                net_type = m_net.group(1)
            if 'NETWORK_STATE_TYPE=' in raw_up:
                if any(k in raw_up for k in ['WFC', 'WFC2', 'IWLAN', 'WIFI']):
                    direction = 'Cell->WiFi'
                elif any(k in raw_up for k in ['LTE', 'NR', '4G', '5G']):
                    direction = 'WiFi->Cell'
            logging.debug('MTK VM2102: inferred direction=%s (network_state_type=%s) at %s', direction, (net_type or 'N/A'), succ.t.isoformat(sep=' '))
            # Primary control plane defaults for MTK: Attempt→Success
            ctrl_start = attempt_ts
            ctrl_end = succ.t
            ctrl_lat = (ctrl_end - ctrl_start).total_seconds() * 1000.0 if (ctrl_end and ctrl_start and ctrl_end >= ctrl_start) else None
            cp_method = 'MTK_VM2102_Attempt_to_Success'
            reason_ctrl = None if ctrl_lat is not None else 'N/A - missing attempt/success anchors'
            # If this is inferred as L2W, try to use L2W anchors for CP
            if direction == 'Cell->WiFi':
                ends_l2w = [c for c in ctrls if c.kind == 'MTK_L2W_END' and abs((c.t - succ.t).total_seconds()) <= W2L_ATTEMPT_SEARCH_SEC]
                if ends_l2w:
                    endm = min(ends_l2w, key=lambda x: abs((x.t - succ.t).total_seconds()))
                    starts_l2w = [c for c in ctrls if c.kind == 'MTK_L2W_START' and c.t <= endm.t and (endm.t - c.t) <= timedelta(seconds=W2L_ATTEMPT_SEARCH_SEC)]
                    startm = max(starts_l2w, key=lambda x: x.t) if starts_l2w else None
                    if startm:
                        ctrl_start = startm.t
                        ctrl_end = endm.t
                        ctrl_lat = (ctrl_end - ctrl_start).total_seconds() * 1000.0 if ctrl_end >= ctrl_start else None
                        cp_method = 'MTK_PDN_onNotify_to_WLAN_Home'
                        reason_ctrl = None if ctrl_lat is not None else 'N/A - MTK_L2W_START after L2W_END'
                        logging.debug('MTK L2W CP pairing (via VM2102 path): start=%s end=%s lat_ms=%s', ctrl_start.isoformat(sep=' '), ctrl_end.isoformat(sep=' '), ctrl_lat)
                    else:
                        reason_ctrl = 'Fallback to Attempt→Success; missing MTK_L2W_START before WLAN HOME'
            # CP_PDN latency using VT markers
            cp_pdn_start, cp_pdn_end, cp_pdn_lat, reason_cp_pdn = pair_mtk_pdn(succ.t)
            if direction == 'Cell->WiFi' and cp_pdn_start is None and cp_pdn_end is None and reason_cp_pdn is None:
                reason_cp_pdn = 'N/A - no VT PDN anchors for L2W'
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                logging.debug('MTK CP_PDN pairing: begin=%s end=%s lat_ms=%s reason=%s',
                              (cp_pdn_start.isoformat(sep=' ') if cp_pdn_start else 'N/A'),
                              (cp_pdn_end.isoformat(sep=' ') if cp_pdn_end else 'N/A'),
                              cp_pdn_lat, reason_cp_pdn)
            # User-plane impact (Option 2) centered at ctrl_end
            impact = compute_impact_max_gap_ms(media, ctrl_end, IMPACT_WINDOW_MS)
            reason_impact = None if impact is not None else f'N/A - insufficient RX RTP packets in ±{IMPACT_WINDOW_MS/1000:.1f}s window'
            user_start = None
            user_end = None
            if impact is not None:
                user_lat = impact
                up_method = f'MaxGap_Op2_±{int(IMPACT_WINDOW_MS/1000)}s_around_CP_end'
                reason_user = 'Fallback Option2; no IKE anchors on MTK path'
            else:
                user_lat = None
                up_method = f'MaxGap_Op2_±{int(IMPACT_WINDOW_MS/1000)}s_around_CP_end'
                reason_user = f'N/A - insufficient RX RTP packets in ±{IMPACT_WINDOW_MS/1000:.1f}s window to compute UserLatency'
            # KPIs window around ctrl_end
            k_start = ctrl_end - timedelta(seconds=IMPACT_WINDOW_MS/1000.0)
            k_end = ctrl_end + timedelta(seconds=IMPACT_WINDOW_MS/1000.0)
            loss_count, loss_pct, jitter_mean = compute_loss_and_jitter(rtcp, (k_start, k_end))
            reason_loss = None if (loss_count is not None or loss_pct is not None) else f'N/A - no RTCP/NET_STAT entries in ±{IMPACT_WINDOW_MS/1000:.1f}s window'
            reason_jitter = None if jitter_mean is not None else 'N/A - no jitter stats in window'
            # Signals near attempt
            wifi_rssi, reason_rssi, rsrp, reason_rsrp, rsrq, reason_rsrq, sinr, reason_sinr = signal_values_with_reason(signals, attempt_ts)
            # Extract call_id if present for traceability
            call_id = None
            m_cid = re.search(r"call_id=\"([0-9a-f]+)\"", succ.raw)
            if m_cid:
                call_id = m_cid.group(1)
            notes = [f"MTK success clustered: {len(group)} marker(s)"]
            if call_id:
                notes.append(f"call_id={call_id}")
            ev = HOEvent(
                vendor=vendor,
                direction=direction,
                attempt_ts=attempt_ts,
                result='Success',
                ctrl_start=ctrl_start,
                ctrl_end=ctrl_end,
                ctrl_latency_ms=ctrl_lat,
                cp_method=cp_method,
                reason_ctrl=reason_ctrl,
                # CP_PDN
                cp_pdn_start=cp_pdn_start,
                cp_pdn_end=cp_pdn_end,
                cp_pdn_latency_ms=cp_pdn_lat,
                reason_cp_pdn=reason_cp_pdn,
                # User plane
                user_start=user_start,
                user_end=user_end,
                user_latency_ms=user_lat,
                up_method=up_method,
                reason_user=reason_user,
                # Loss/jitter
                pkt_loss_count=loss_count,
                pkt_loss_rate_pct=loss_pct,
                reason_loss=reason_loss,
                jitter_mean=jitter_mean,
                reason_jitter=reason_jitter,
                # Signals
                wifi_rssi_at_ho=wifi_rssi,
                reason_rssi=reason_rssi,
                rsrp_at_ho=rsrp,
                reason_rsrp=reason_rsrp,
                rsrq_at_ho=rsrq,
                reason_rsrq=reason_rsrq,
                sinr_at_ho=sinr,
                reason_sinr=reason_sinr,
                # OEM auxiliary
                oem_total_time_s=None,
                oem_pdn_req_to_connected_s=None,
                oem_latch_to_pdn_req_s=None,
                oem_cp_source=None,
                reason_oem_cp=None,
                # Failure/Impact
                failure_cause=None,
                notes=notes,
                impact_score=impact,
                reason_impact=reason_impact,
            )
            # Append for both directions (WiFi->Cell and Cell->WiFi)
            events.append(ev)
        # MTK LTE->WiFi (Cell->WiFi) CP using provided anchors: onNotifyPdnHandover +EPDNHANDOVER... -> [WLAN: IWLAN->IWLAN, NOT_REG_SEARCHING->HOME]
        mtk_l2w_end = sorted([c for c in ctrls if c.kind == 'MTK_L2W_END'], key=lambda x: x.t)
        l_clusters: List[List[ControlMarker]] = []
        for mark in mtk_l2w_end:
            if not l_clusters:
                l_clusters.append([mark])
            else:
                last = l_clusters[-1]
                if (mark.t - last[-1].t) <= timedelta(seconds=CLUSTER_WINDOW_SEC):
                    last.append(mark)
                else:
                    l_clusters.append([mark])
        for group in l_clusters:
            endm = group[0]
            # Start = nearest MTK_L2W_START within backsearch window
            starts = [c for c in ctrls if c.kind == 'MTK_L2W_START' and c.t <= endm.t and (endm.t - c.t) <= timedelta(seconds=W2L_ATTEMPT_SEARCH_SEC)]
            startm = max(starts, key=lambda x: x.t) if starts else None
            attempt_ts = (startm.t if startm else endm.t)
            ctrl_start = (startm.t if startm else None)
            ctrl_end = endm.t
            ctrl_lat = (ctrl_end - ctrl_start).total_seconds() * 1000.0 if (ctrl_start and ctrl_end and ctrl_end >= ctrl_start) else None
            cp_method = 'MTK_PDN_onNotify_to_WLAN_Home'
            reason_ctrl = None if ctrl_lat is not None else 'N/A - missing MTK_L2W_START anchor before WLAN HOME'
            # User-plane impact around L2W end (fallback Option2)
            impact = compute_impact_max_gap_ms(media, ctrl_end, IMPACT_WINDOW_MS)
            reason_impact = None if impact is not None else f'N/A - insufficient RX RTP packets in ±{IMPACT_WINDOW_MS/1000:.1f}s window'
            user_start = None
            user_end = None
            user_lat = impact if impact is not None else None
            up_method = f'MaxGap_Op2_±{int(IMPACT_WINDOW_MS/1000)}s_around_L2W_end'
            reason_user = None if impact is not None else f'N/A - insufficient RX RTP packets in ±{IMPACT_WINDOW_MS/1000:.1f}s window to compute UserLatency'
            # KPIs window
            k_start = ctrl_end - timedelta(seconds=IMPACT_WINDOW_MS/1000.0)
            k_end = ctrl_end + timedelta(seconds=IMPACT_WINDOW_MS/1000.0)
            loss_count, loss_pct, jitter_mean = compute_loss_and_jitter(rtcp, (k_start, k_end))
            reason_loss = None if (loss_count is not None or loss_pct is not None) else f'N/A - no RTCP/NET_STAT entries in ±{IMPACT_WINDOW_MS/1000:.1f}s window'
            reason_jitter = None if jitter_mean is not None else 'N/A - no jitter stats in window'
            # Signals near attempt
            wifi_rssi, reason_rssi, rsrp, reason_rsrp, rsrq, reason_rsrq, sinr, reason_sinr = signal_values_with_reason(signals, attempt_ts)
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                logging.debug('MTK L2W CP pairing: start=%s end=%s lat_ms=%s (reason=%s)',
                              (startm.t.isoformat(sep=' ') if startm else 'N/A'),
                              endm.t.isoformat(sep=' '), ctrl_lat, reason_ctrl)
            ev_l2w = HOEvent(
                vendor=vendor,
                direction='Cell->WiFi',
                attempt_ts=attempt_ts,
                result='Success',
                ctrl_start=ctrl_start,
                ctrl_end=ctrl_end,
                ctrl_latency_ms=ctrl_lat,
                cp_method=cp_method,
                reason_ctrl=reason_ctrl,
                # CP_PDN (not applicable for this MTK L2W path unless VT anchors exist separately)
                cp_pdn_start=None,
                cp_pdn_end=None,
                cp_pdn_latency_ms=None,
                reason_cp_pdn='N/A - MTK L2W PDN CP uses different anchors',
                # User plane
                user_start=user_start,
                user_end=user_end,
                user_latency_ms=user_lat,
                up_method=up_method,
                reason_user=reason_user,
                # Loss/jitter
                pkt_loss_count=loss_count,
                pkt_loss_rate_pct=loss_pct,
                reason_loss=reason_loss,
                jitter_mean=jitter_mean,
                reason_jitter=reason_jitter,
                # Signals
                wifi_rssi_at_ho=wifi_rssi,
                reason_rssi=reason_rssi,
                rsrp_at_ho=rsrp,
                reason_rsrp=reason_rsrp,
                rsrq_at_ho=rsrq,
                reason_rsrq=reason_rsrq,
                sinr_at_ho=sinr,
                reason_sinr=reason_sinr,
                # Failure/Impact
                failure_cause=None,
                notes=[f"MTK L2W end clustered: {len(group)} marker(s) merged", 'MTK L2W PDN anchors used'],
                impact_score=impact,
                reason_impact=reason_impact,
            )
            events.append(ev_l2w)
        if events:
            return events

    # Helper: nearest OEM KPI within OEM_KPI_WINDOW_SEC around a center time
    def nearest_oem_kpi(center: datetime) -> Optional[OemKpi]:
        if not oem_kpis:
            return None
        candidates = [k for k in oem_kpis if abs((k.t - center).total_seconds()) <= OEM_KPI_WINDOW_SEC]
        if not candidates:
            return None
        return min(candidates, key=lambda k: abs((k.t - center).total_seconds()))

    # Helper: latest OEM loss BEFORE center within window
    def latest_oem_loss_before(center: datetime) -> Optional[OemLoss]:
        if not oem_losses:
            return None
        candidates = [l for l in oem_losses if l.t <= center and (center - l.t) <= timedelta(seconds=OEM_LOSS_WINDOW_SEC)]
        if not candidates:
            return None
        return max(candidates, key=lambda l: l.t)

    # 0) Samsung W2L via explicit success markers (ensure we don't miss W2L)
    sam_w2l_succ = sorted([c for c in ctrls if c.kind == 'SAM_W2L_SUCC'], key=lambda x: x.t)
    # De-duplicate: cluster success markers that occur within a short window into one HO
    clusters: List[List[ControlMarker]] = []
    for mark in sam_w2l_succ:
        if not clusters:
            clusters.append([mark])
        else:
            last_cluster = clusters[-1]
            if (mark.t - last_cluster[-1].t) <= timedelta(seconds=CLUSTER_WINDOW_SEC):
                last_cluster.append(mark)
            else:
                clusters.append([mark])
    for group in clusters:
        succ = group[0]  # canonical success time = first in cluster
        # Attempt: prefer preceding HIGH RTP LOSS/CRITERIA within W2L_ATTEMPT_SEARCH_SEC; else EPDG disconnect/WIFI_DOWN; else succ time
        candidates = [c for c in ctrls if c.t <= succ.t and (succ.t - c.t) <= timedelta(seconds=W2L_ATTEMPT_SEARCH_SEC) and (
            c.kind in ('HANDOVER', 'WIFI_DOWN', 'EPDG') or
            ('disconnect' in c.raw.lower() and c.kind == 'EPDG') or
            VendorPatterns.SAM_HO_HIGHLOSS_RE.search(c.raw) or VendorPatterns.SAM_HO_CRITERIA_RE.search(c.raw)
        )]
        attempt = max(candidates, key=lambda x: x.t).t if candidates else succ.t
        # Control plane approximation for W2L
        cp_start_marker = next((c for c in reversed(sorted([c for c in ctrls if c.t <= succ.t], key=lambda x: x.t)) if (c.kind == 'EPDG' and 'disconnect' in c.raw.lower()) or c.kind == 'WIFI_DOWN'), None)
        cp_end_marker = next((c for c in ctrls if c.t >= succ.t and (c.kind == 'IMS_CELL' or c.kind == 'SRVCC')), None)
        ctrl_start = cp_start_marker.t if cp_start_marker else None
        ctrl_end = cp_end_marker.t if cp_end_marker else succ.t
        cp_method = 'EPDG_to_IMS_CELL' if (cp_start_marker and cp_end_marker) else ('EPDG_or_WIFI_DOWN_to_OH_EVENT' if cp_start_marker else 'OH_EVENT_only')
        ctrl_lat = (ctrl_end - ctrl_start).total_seconds() * 1000.0 if (ctrl_start and ctrl_end and ctrl_end >= ctrl_start) else None
        reason_ctrl = None if ctrl_lat is not None else 'N/A - missing CP anchors (EPDG disconnect/IMS_CELL) in Samsung logs'
        # User plane for W2L: Option2 max RX gap around success (±IMPACT_WINDOW_MS)
        impact = compute_impact_max_gap_ms(media, succ.t, IMPACT_WINDOW_MS)
        reason_impact = None if impact is not None else f'N/A - insufficient RX RTP packets in ±{IMPACT_WINDOW_MS/1000:.1f}s window'
        user_start = None
        user_end = None
        if impact is not None:
            user_lat = impact
            up_method = f'MaxGap_Op2_±{int(IMPACT_WINDOW_MS/1000)}s_around_success'
            reason_user = f'Fallback Option2 used; UserLatency equals ImpactScore (max RX inter-arrival gap ±{IMPACT_WINDOW_MS/1000:.1f}s around success)'
        else:
            user_lat = None
            up_method = f'MaxGap_Op2_±{int(IMPACT_WINDOW_MS/1000)}s_around_success'
            reason_user = f'N/A - insufficient RX RTP packets in ±{IMPACT_WINDOW_MS/1000:.1f}s window to compute UserLatency'
        # KPIs window
        k_start = succ.t - timedelta(seconds=IMPACT_WINDOW_MS/1000.0)
        k_end = succ.t + timedelta(seconds=IMPACT_WINDOW_MS/1000.0)
        loss_count, loss_pct, jitter_mean = compute_loss_and_jitter(rtcp, (k_start, k_end))
        reason_loss = None if (loss_count is not None or loss_pct is not None) else f'N/A - no RTCP/NET_STAT entries in ±{IMPACT_WINDOW_MS/1000:.1f}s window'
        reason_jitter = None if jitter_mean is not None else 'N/A - no jitter stats in window'
        # Signal KPIs near attempt with windowed reasoning
        wifi_rssi, reason_rssi, rsrp, reason_rsrp, rsrq, reason_rsrq, sinr, reason_sinr = signal_values_with_reason(signals, attempt)
        # OEM KPI association around success (center)
        oem = nearest_oem_kpi(succ.t)
        oem_reason = None if oem else f'No RegiMgr KPI[0] within ±{OEM_KPI_WINDOW_SEC}s of HO center'
        # OEM Loss association: latest before center within window
        oem_loss = latest_oem_loss_before(succ.t)
        oem_loss_reason = None if oem_loss else f'No OEM RTP loss within {OEM_LOSS_WINDOW_SEC}s before HO center'
        cluster_notes = f"Samsung W2L success clustered: {len(group)} marker(s) merged"
        ev = HOEvent(
            vendor=vendor,
            direction='WiFi->Cell',
            attempt_ts=attempt,
            result='Success',
            ctrl_start=ctrl_start,
            ctrl_end=ctrl_end,
            ctrl_latency_ms=ctrl_lat,
            cp_method=cp_method,
            reason_ctrl=reason_ctrl,
            user_start=user_start,
            user_end=user_end,
            user_latency_ms=user_lat,
            up_method=up_method,
            reason_user=reason_user,
            pkt_loss_count=loss_count,
            pkt_loss_rate_pct=loss_pct,
            reason_loss=reason_loss,
            jitter_mean=jitter_mean,
            reason_jitter=reason_jitter,
            wifi_rssi_at_ho=wifi_rssi,
            reason_rssi=reason_rssi,
            rsrp_at_ho=rsrp,
            reason_rsrp=reason_rsrp,
            rsrq_at_ho=rsrq,
            reason_rsrq=reason_rsrq,
            sinr_at_ho=sinr,
            reason_sinr=reason_sinr,
            # OEM CP auxiliary
            oem_total_time_s=(oem.total_time_s if oem else None),
            oem_pdn_req_to_connected_s=(oem.pdn_req_to_connected_s if oem else None),
            oem_latch_to_pdn_req_s=(oem.latch_to_pdn_req_s if oem else None),
            oem_cp_source=(oem.source if oem else None),
            reason_oem_cp=oem_reason,
            # OEM Loss auxiliary
            oem_loss_rate_pct=(oem_loss.loss_rate_pct if oem_loss else None),
            oem_loss_jitter_ms=(oem_loss.jitter_ms if oem_loss else None),
            oem_loss_source=(oem_loss.source if oem_loss else None),
            reason_oem_loss=oem_loss_reason,
            failure_cause=None,
            notes=[cluster_notes, "OH_EVENT/HandoverResult used as HO result"],
            impact_score=impact,
            reason_impact=reason_impact,
        )
        events.append(ev)

    # 1) Preferred L2W path using IKE anchors and RX RTP per user's rule
    ike_req = [c for c in ctrls if c.kind == 'IKE_REQ1']
    ike_resp = [c for c in ctrls if c.kind == 'IKE_RESP3']
    ike_req.sort(key=lambda c: c.t)
    ike_resp.sort(key=lambda c: c.t)
    used_resp_ts = set()
    for req in ike_req:
        # find the first response after req within 60s
        resp = next((r for r in ike_resp if r.t >= req.t and r.t not in used_resp_ts and (r.t - req.t) <= timedelta(seconds=IKE_PAIR_WINDOW_SEC)), None)
        if not resp:
            continue
        used_resp_ts.add(resp.t)
        # CP latency
        ctrl_start, ctrl_end = req.t, resp.t
        ctrl_lat = (ctrl_end - ctrl_start).total_seconds() * 1000.0
        # UP latency per new rule: last RX before req1, first RX after resp3
        rx_before = _last_rx_before(media, ctrl_start)
        rx_after = _first_rx_after(media, ctrl_end)
        user_start = rx_before.t if rx_before else None
        user_end = rx_after.t if rx_after else None
        user_lat = (user_end - user_start).total_seconds() * 1000.0 if (user_start and user_end) else None
        # guard against unrealistic values due to sparse packets
        reason_user = None
        if user_lat is not None and user_lat > MAX_UP_LATENCY_MS:
            reason_user = f'Discarded computed RX gap {int(user_lat)}ms >{int(MAX_UP_LATENCY_MS/1000)}s; likely sparse/missing RTP around AUTH'
            user_lat = None
        up_method = 'L2W_IKE_RX' if user_lat is not None else f'MaxGap_Op2_±{int(IMPACT_WINDOW_MS/1000)}s_around_AUTH'
        if user_lat is None and reason_user is None:
            reason_user = 'No RX RTP before/after AUTH; using max gap as proxy'
        # Loss/jitter around UP window
        w_start = (user_start or ctrl_start)
        w_end = (user_end or ctrl_end)
        loss_count, loss_pct, jitter_mean = compute_loss_and_jitter(rtcp, (w_start, w_end))
        reason_loss = None if (loss_count is not None or loss_pct is not None) else 'N/A - no RTCP/NET_STAT in window'
        reason_jitter = None if jitter_mean is not None else 'N/A - no jitter stats in window'
        # Signal snapshot near attempt
        # Signal KPIs near attempt with windowed reasoning
        wifi_rssi, reason_rssi, rsrp, reason_rsrp, rsrq, reason_rsrq, sinr, reason_sinr = signal_values_with_reason(signals, ctrl_start)
        # Impact score: max RX inter-arrival gap ±2s centered at AUTH resp
        impact = compute_impact_max_gap_ms(media, ctrl_end, IMPACT_WINDOW_MS)
        reason_impact = None if impact is not None else f'N/A - insufficient RX RTP packets in ±{IMPACT_WINDOW_MS/1000:.1f}s window'
        # OEM KPI association around AUTH response (center)
        oem = nearest_oem_kpi(ctrl_end)
        oem_reason = None if oem else f'No RegiMgr KPI[0] within ±{OEM_KPI_WINDOW_SEC}s of HO center'
        # OEM Loss association: latest before AUTH response
        oem_loss = latest_oem_loss_before(ctrl_end)
        oem_loss_reason = None if oem_loss else f'No OEM RTP loss within {OEM_LOSS_WINDOW_SEC}s before HO center'
        ev = HOEvent(
            vendor=vendor,
            direction='Cell->WiFi',
            attempt_ts=ctrl_start,
            result='Success',
            ctrl_start=ctrl_start,
            ctrl_end=ctrl_end,
            ctrl_latency_ms=ctrl_lat,
            cp_method='IKE_AUTH_req1_to_resp3',
            reason_ctrl=None,
            user_start=user_start,
            user_end=user_end,
            user_latency_ms=user_lat,
            up_method=up_method,
            reason_user=reason_user,
            pkt_loss_count=loss_count,
            pkt_loss_rate_pct=loss_pct,
            reason_loss=reason_loss,
            jitter_mean=jitter_mean,
            reason_jitter=reason_jitter,
            wifi_rssi_at_ho=wifi_rssi,
            reason_rssi=reason_rssi,
            rsrp_at_ho=rsrp,
            reason_rsrp=reason_rsrp,
            rsrq_at_ho=rsrq,
            reason_rsrq=reason_rsrq,
            sinr_at_ho=sinr,
            reason_sinr=reason_sinr,
            # OEM CP auxiliary
            oem_total_time_s=(oem.total_time_s if oem else None),
            oem_pdn_req_to_connected_s=(oem.pdn_req_to_connected_s if oem else None),
            oem_latch_to_pdn_req_s=(oem.latch_to_pdn_req_s if oem else None),
            oem_cp_source=(oem.source if oem else None),
            reason_oem_cp=oem_reason,
            # Failure/Impact
            failure_cause=None,
            notes=[],
            impact_score=impact,
            reason_impact=reason_impact,
        )
        events.append(ev)

    if events:
        # If we built events from explicit markers, return them to avoid duplicates
        return events

    # 2) Fallback: Detect user-plane gaps as candidates for HO (legacy method)
    gaps = detect_user_plane_gaps(media, gap_ms_threshold)
    if not gaps:
        # If no media lines or gaps, try control-plane only inference
        if ctrls:
            ctrl_start, ctrl_end, ctrl_lat = infer_control_plane(ctrls, None)
            direction = None
            if ctrl_start and ctrl_end:
                direction = 'WiFi->Cell' if 'WIFI_DOWN' in [c.kind for c in ctrls] else None
            center = ctrl_end or ctrl_start or ctrls[0].t
            sig = pre_signal(signals, center)
            # OEM KPI association near center
            oem = nearest_oem_kpi(center)
            oem_reason = None if oem else f'No RegiMgr KPI[0] within ±{OEM_KPI_WINDOW_SEC}s of HO center'
            # OEM Loss association near center
            oem_loss = latest_oem_loss_before(center)
            oem_loss_reason = None if oem_loss else f'No OEM RTP loss within {OEM_LOSS_WINDOW_SEC}s before HO center'
            ev = HOEvent(
                vendor=vendor,
                direction=direction,
                attempt_ts=ctrl_start or ctrl_end or ctrls[0].t,
                result='Unknown',
                ctrl_start=ctrl_start,
                ctrl_end=ctrl_end,
                ctrl_latency_ms=ctrl_lat,
                cp_method='Heuristic',
                reason_ctrl=None if ctrl_lat is not None else 'N/A - insufficient control-plane markers',
                user_start=None,
                user_end=None,
                user_latency_ms=None,
                up_method=None,
                reason_user='N/A - no media gap detected',
                pkt_loss_count=None,
                pkt_loss_rate_pct=None,
                reason_loss='N/A - no RTCP/NET_STAT in window',
                jitter_mean=None,
                reason_jitter='N/A - no jitter stats in window',
                wifi_rssi_at_ho=sig.wifi_rssi,
                reason_rssi=None if sig.wifi_rssi is not None else 'N/A - no WiFi RSSI near attempt',
                rsrp_at_ho=sig.rsrp,
                reason_rsrp=None if sig.rsrp is not None else 'N/A - no RSRP near attempt',
                rsrq_at_ho=sig.rsrq,
                reason_rsrq=None if sig.rsrq is not None else 'N/A - no RSRQ near attempt',
                sinr_at_ho=sig.sinr,
                reason_sinr=None if sig.sinr is not None else 'N/A - no SINR near attempt',
                # OEM CP auxiliary
                oem_total_time_s=(oem.total_time_s if oem else None),
                oem_pdn_req_to_connected_s=(oem.pdn_req_to_connected_s if oem else None),
                oem_latch_to_pdn_req_s=(oem.latch_to_pdn_req_s if oem else None),
                oem_cp_source=(oem.source if oem else None),
                reason_oem_cp=oem_reason,
                # OEM Loss auxiliary
                oem_loss_rate_pct=(oem_loss.loss_rate_pct if oem_loss else None),
                oem_loss_jitter_ms=(oem_loss.jitter_ms if oem_loss else None),
                oem_loss_source=(oem_loss.source if oem_loss else None),
                reason_oem_loss=oem_loss_reason,
                failure_cause=None,
                notes=['Control-plane only inference'],
                impact_score=None,
                reason_impact='N/A - no RX RTP center to compute max gap',
            )
            events.append(ev)
        return events

    for window in gaps:
        ustart, uend = window
        user_lat = (uend - ustart).total_seconds() * 1000.0
        direction = infer_direction(ctrls, window)
        ctrl_start, ctrl_end, ctrl_lat = infer_control_plane(ctrls, direction)
        loss_count, loss_pct, jitter_mean = compute_loss_and_jitter(rtcp, window)
        # Signal KPIs near attempt with windowed reasoning
        wifi_rssi, reason_rssi, rsrp, reason_rsrq, rsrq, reason_rsrq2, sinr, reason_sinr = signal_values_with_reason(signals, ustart)
        # Fix naming from tuple order
        reason_rsrp = reason_rsrq
        reason_rsrq = reason_rsrq2
        impact = compute_impact_max_gap_ms(media, uend, IMPACT_WINDOW_MS)
        # OEM KPI association near the end of gap (as proxy HO center for fallback cases)
        center = ctrl_end or uend
        oem = nearest_oem_kpi(center)
        oem_reason = None if oem else f'No RegiMgr KPI[0] within ±{OEM_KPI_WINDOW_SEC}s of HO center'
        # OEM Loss association near center
        oem_loss = latest_oem_loss_before(center)
        oem_loss_reason = None if oem_loss else f'No OEM RTP loss within {OEM_LOSS_WINDOW_SEC}s before HO center'
        ev = HOEvent(
            vendor=vendor,
            direction=direction,
            attempt_ts=ustart,
            result='Unknown',
            ctrl_start=ctrl_start,
            ctrl_end=ctrl_end,
            ctrl_latency_ms=ctrl_lat,
            cp_method='Heuristic',
            reason_ctrl=None if ctrl_lat is not None else 'N/A - insufficient control-plane markers',
            user_start=ustart,
            user_end=uend,
            user_latency_ms=user_lat,
            up_method='MaxGap_Op2',
            reason_user=None,
            pkt_loss_count=loss_count,
            pkt_loss_rate_pct=loss_pct,
            reason_loss=None if (loss_count is not None or loss_pct is not None) else 'N/A - no RTCP/NET_STAT in window',
            jitter_mean=jitter_mean,
            reason_jitter=None if jitter_mean is not None else 'N/A - no jitter stats in window',
            wifi_rssi_at_ho=wifi_rssi,
            reason_rssi=reason_rssi if reason_rssi else (None if wifi_rssi is not None else 'N/A - no WiFi RSSI near attempt'),
            rsrp_at_ho=rsrp,
            reason_rsrp=reason_rsrp if reason_rsrp else (None if rsrp is not None else 'N/A - no RSRP near attempt'),
            rsrq_at_ho=rsrq,
            reason_rsrq=reason_rsrq if reason_rsrq else (None if rsrq is not None else 'N/A - no RSRQ near attempt'),
            sinr_at_ho=sinr,
            reason_sinr=reason_sinr if reason_sinr else (None if sinr is not None else 'N/A - no SINR near attempt'),
            # OEM CP auxiliary
            oem_total_time_s=(oem.total_time_s if oem else None),
            oem_pdn_req_to_connected_s=(oem.pdn_req_to_connected_s if oem else None),
            oem_latch_to_pdn_req_s=(oem.latch_to_pdn_req_s if oem else None),
            oem_cp_source=(oem.source if oem else None),
            reason_oem_cp=oem_reason,
            # OEM Loss auxiliary
            oem_loss_rate_pct=(oem_loss.loss_rate_pct if oem_loss else None),
            oem_loss_jitter_ms=(oem_loss.jitter_ms if oem_loss else None),
            oem_loss_source=(oem_loss.source if oem_loss else None),
            reason_oem_loss=oem_loss_reason,
            failure_cause=None,
            notes=['User-plane gap detected'],
            impact_score=impact,
            reason_impact=None if impact is not None else f'N/A - insufficient RX RTP packets in ±{IMPACT_WINDOW_MS/1000:.1f}s window',
        )
        events.append(ev)

    return events

    media = data['media']
    rtcp = data['rtcp']
    signals = data['signals']
    ctrls = data['ctrls']
    oem_kpis: List[OemKpi] = data.get('oem_kpis', [])
    oem_losses: List[OemLoss] = data.get('oem_losses', [])

    events: List[HOEvent] = []

    # Helper: choose pre-trigger signal (closest BEFORE t if possible)
    def pre_signal(signals_list: List[SignalSnapshot], t: datetime) -> SignalSnapshot:
        prev = [s for s in signals_list if s.t <= t]
        if prev:
            return max(prev, key=lambda s: s.t)
        return closest_signal(signals_list, t)

    # Helper: signal KPIs with window and reason strings per metric
    def signal_values_with_reason(signals_list: List[SignalSnapshot], t: datetime):
        def pick(metric_getter, name: str):
            # find latest snapshot at or before t that has this metric
            prior = [s for s in signals_list if s.t <= t and metric_getter(s) is not None]
            if not prior:
                return None, f'N/A - no {name} near attempt (no prior samples)'
            latest = max(prior, key=lambda s: s.t)
            age_s = (t - latest.t).total_seconds()
            val = metric_getter(latest)
            if age_s <= SIGNAL_WINDOW_SEC:
                return val, None
            else:
                # outside window: still report last value but explain
                age_str = f'{age_s:.1f}' if age_s >= 0.1 else f'{int(age_s)}'
                return val, f'N/A - no {name} near attempt, last recorded value was {val} {age_str} seconds before HO trigger'
        wifi_rssi, reason_rssi = pick(lambda s: s.wifi_rssi, 'WiFi RSSI')
        rsrp, reason_rsrp = pick(lambda s: s.rsrp, 'RSRP')
        rsrq, reason_rsrq = pick(lambda s: s.rsrq, 'RSRQ')
        sinr, reason_sinr = pick(lambda s: s.sinr, 'SINR')
        return wifi_rssi, reason_rssi, rsrp, reason_rsrp, rsrq, reason_rsrq, sinr, reason_sinr

    # Helper: nearest OEM KPI within OEM_KPI_WINDOW_SEC around a center time
    def nearest_oem_kpi(center: datetime) -> Optional[OemKpi]:
        if not oem_kpis:
            return None
        candidates = [k for k in oem_kpis if abs((k.t - center).total_seconds()) <= OEM_KPI_WINDOW_SEC]
        if not candidates:
            return None
        return min(candidates, key=lambda k: abs((k.t - center).total_seconds()))

    # Helper: latest OEM loss BEFORE center within window
    def latest_oem_loss_before(center: datetime) -> Optional[OemLoss]:
        if not oem_losses:
            return None
        candidates = [l for l in oem_losses if l.t <= center and (center - l.t) <= timedelta(seconds=OEM_LOSS_WINDOW_SEC)]
        if not candidates:
            return None
        return max(candidates, key=lambda l: l.t)

    # 0) Samsung W2L via explicit success markers (ensure we don't miss W2L)
    sam_w2l_succ = sorted([c for c in ctrls if c.kind == 'SAM_W2L_SUCC'], key=lambda x: x.t)
    # De-duplicate: cluster success markers that occur within a short window into one HO
    clusters: List[List[ControlMarker]] = []
    for mark in sam_w2l_succ:
        if not clusters:
            clusters.append([mark])
        else:
            last_cluster = clusters[-1]
            if (mark.t - last_cluster[-1].t) <= timedelta(seconds=CLUSTER_WINDOW_SEC):
                last_cluster.append(mark)
            else:
                clusters.append([mark])
    for group in clusters:
        succ = group[0]  # canonical success time = first in cluster
        # Attempt: prefer preceding HIGH RTP LOSS/CRITERIA within W2L_ATTEMPT_SEARCH_SEC; else EPDG disconnect/WIFI_DOWN; else succ time
        candidates = [c for c in ctrls if c.t <= succ.t and (succ.t - c.t) <= timedelta(seconds=W2L_ATTEMPT_SEARCH_SEC) and (
            c.kind in ('HANDOVER', 'WIFI_DOWN', 'EPDG') or
            ('disconnect' in c.raw.lower() and c.kind == 'EPDG') or
            VendorPatterns.SAM_HO_HIGHLOSS_RE.search(c.raw) or VendorPatterns.SAM_HO_CRITERIA_RE.search(c.raw)
        )]
        attempt = max(candidates, key=lambda x: x.t).t if candidates else succ.t
        # Control plane approximation for W2L
        cp_start_marker = next((c for c in reversed(sorted([c for c in ctrls if c.t <= succ.t], key=lambda x: x.t)) if (c.kind == 'EPDG' and 'disconnect' in c.raw.lower()) or c.kind == 'WIFI_DOWN'), None)
        cp_end_marker = next((c for c in ctrls if c.t >= succ.t and (c.kind == 'IMS_CELL' or c.kind == 'SRVCC')), None)
        ctrl_start = cp_start_marker.t if cp_start_marker else None
        ctrl_end = cp_end_marker.t if cp_end_marker else succ.t
        cp_method = 'EPDG_to_IMS_CELL' if (cp_start_marker and cp_end_marker) else ('EPDG_or_WIFI_DOWN_to_OH_EVENT' if cp_start_marker else 'OH_EVENT_only')
        ctrl_lat = (ctrl_end - ctrl_start).total_seconds() * 1000.0 if (ctrl_start and ctrl_end and ctrl_end >= ctrl_start) else None
        reason_ctrl = None if ctrl_lat is not None else 'N/A - missing CP anchors (EPDG disconnect/IMS_CELL) in Samsung logs'
        # User plane for W2L: Option2 max RX gap around success (±IMPACT_WINDOW_MS)
        impact = compute_impact_max_gap_ms(media, succ.t, IMPACT_WINDOW_MS)
        reason_impact = None if impact is not None else f'N/A - insufficient RX RTP packets in ±{IMPACT_WINDOW_MS/1000:.1f}s window'
        user_start = None
        user_end = None
        if impact is not None:
            user_lat = impact
            up_method = f'MaxGap_Op2_±{int(IMPACT_WINDOW_MS/1000)}s_around_success'
            reason_user = f'Fallback Option2 used; UserLatency equals ImpactScore (max RX inter-arrival gap ±{IMPACT_WINDOW_MS/1000:.1f}s around success)'
        else:
            user_lat = None
            up_method = f'MaxGap_Op2_±{int(IMPACT_WINDOW_MS/1000)}s_around_success'
            reason_user = f'N/A - insufficient RX RTP packets in ±{IMPACT_WINDOW_MS/1000:.1f}s window to compute UserLatency'
        # KPIs window
        k_start = succ.t - timedelta(seconds=IMPACT_WINDOW_MS/1000.0)
        k_end = succ.t + timedelta(seconds=IMPACT_WINDOW_MS/1000.0)
        loss_count, loss_pct, jitter_mean = compute_loss_and_jitter(rtcp, (k_start, k_end))
        reason_loss = None if (loss_count is not None or loss_pct is not None) else f'N/A - no RTCP/NET_STAT entries in ±{IMPACT_WINDOW_MS/1000:.1f}s window'
        reason_jitter = None if jitter_mean is not None else 'N/A - no jitter stats in window'
        # Signal KPIs near attempt with windowed reasoning
        wifi_rssi, reason_rssi, rsrp, reason_rsrp, rsrq, reason_rsrq, sinr, reason_sinr = signal_values_with_reason(signals, attempt)
        # OEM KPI association around success (center)
        oem = nearest_oem_kpi(succ.t)
        oem_reason = None if oem else f'No RegiMgr KPI[0] within ±{OEM_KPI_WINDOW_SEC}s of HO center'
        # OEM Loss association: latest before center within window
        oem_loss = latest_oem_loss_before(succ.t)
        oem_loss_reason = None if oem_loss else f'No OEM RTP loss within {OEM_LOSS_WINDOW_SEC}s before HO center'
        cluster_notes = f"Samsung W2L success clustered: {len(group)} marker(s) merged"
        ev = HOEvent(
            vendor=vendor,
            direction='WiFi->Cell',
            attempt_ts=attempt,
            result='Success',
            ctrl_start=ctrl_start,
            ctrl_end=ctrl_end,
            ctrl_latency_ms=ctrl_lat,
            cp_method=cp_method,
            reason_ctrl=reason_ctrl,
            user_start=user_start,
            user_end=user_end,
            user_latency_ms=user_lat,
            up_method=up_method,
            reason_user=reason_user,
            pkt_loss_count=loss_count,
            pkt_loss_rate_pct=loss_pct,
            reason_loss=reason_loss,
            jitter_mean=jitter_mean,
            reason_jitter=reason_jitter,
            wifi_rssi_at_ho=wifi_rssi,
            reason_rssi=reason_rssi,
            rsrp_at_ho=rsrp,
            reason_rsrp=reason_rsrp,
            rsrq_at_ho=rsrq,
            reason_rsrq=reason_rsrq,
            sinr_at_ho=sinr,
            reason_sinr=reason_sinr,
            # OEM CP auxiliary
            oem_total_time_s=(oem.total_time_s if oem else None),
            oem_pdn_req_to_connected_s=(oem.pdn_req_to_connected_s if oem else None),
            oem_latch_to_pdn_req_s=(oem.latch_to_pdn_req_s if oem else None),
            oem_cp_source=(oem.source if oem else None),
            reason_oem_cp=oem_reason,
            # OEM Loss auxiliary
            oem_loss_rate_pct=(oem_loss.loss_rate_pct if oem_loss else None),
            oem_loss_jitter_ms=(oem_loss.jitter_ms if oem_loss else None),
            oem_loss_source=(oem_loss.source if oem_loss else None),
            reason_oem_loss=oem_loss_reason,
            failure_cause=None,
            notes=[cluster_notes, "OH_EVENT/HandoverResult used as HO result"],
            impact_score=impact,
            reason_impact=reason_impact,
        )
        events.append(ev)

    # 1) Preferred L2W path using IKE anchors and RX RTP per user's rule
    ike_req = [c for c in ctrls if c.kind == 'IKE_REQ1']
    ike_resp = [c for c in ctrls if c.kind == 'IKE_RESP3']
    ike_req.sort(key=lambda c: c.t)
    ike_resp.sort(key=lambda c: c.t)
    used_resp_ts = set()
    for req in ike_req:
        # find the first response after req within 60s
        resp = next((r for r in ike_resp if r.t >= req.t and r.t not in used_resp_ts and (r.t - req.t) <= timedelta(seconds=IKE_PAIR_WINDOW_SEC)), None)
        if not resp:
            continue
        used_resp_ts.add(resp.t)
        # CP latency
        ctrl_start, ctrl_end = req.t, resp.t
        ctrl_lat = (ctrl_end - ctrl_start).total_seconds() * 1000.0
        # UP latency per new rule: last RX before req1, first RX after resp3
        rx_before = _last_rx_before(media, ctrl_start)
        rx_after = _first_rx_after(media, ctrl_end)
        user_start = rx_before.t if rx_before else None
        user_end = rx_after.t if rx_after else None
        user_lat = (user_end - user_start).total_seconds() * 1000.0 if (user_start and user_end) else None
        # guard against unrealistic values due to sparse packets
        reason_user = None
        if user_lat is not None and user_lat > MAX_UP_LATENCY_MS:
            reason_user = f'Discarded computed RX gap {int(user_lat)}ms >{int(MAX_UP_LATENCY_MS/1000)}s; likely sparse/missing RTP around AUTH'
            user_lat = None
        up_method = 'L2W_IKE_RX' if user_lat is not None else f'MaxGap_Op2_±{int(IMPACT_WINDOW_MS/1000)}s_around_AUTH'
        if user_lat is None and reason_user is None:
            reason_user = 'No RX RTP before/after AUTH; using max gap as proxy'
        # Loss/jitter around UP window
        w_start = (user_start or ctrl_start)
        w_end = (user_end or ctrl_end)
        loss_count, loss_pct, jitter_mean = compute_loss_and_jitter(rtcp, (w_start, w_end))
        reason_loss = None if (loss_count is not None or loss_pct is not None) else 'N/A - no RTCP/NET_STAT in window'
        reason_jitter = None if jitter_mean is not None else 'N/A - no jitter stats in window'
        # Signal snapshot near attempt
        # Signal KPIs near attempt with windowed reasoning
        wifi_rssi, reason_rssi, rsrp, reason_rsrp, rsrq, reason_rsrq, sinr, reason_sinr = signal_values_with_reason(signals, ctrl_start)
        # Impact score: max RX inter-arrival gap ±2s centered at AUTH resp
        impact = compute_impact_max_gap_ms(media, ctrl_end, IMPACT_WINDOW_MS)
        reason_impact = None if impact is not None else f'N/A - insufficient RX RTP packets in ±{IMPACT_WINDOW_MS/1000:.1f}s window'
        # OEM KPI association around AUTH response (center)
        oem = nearest_oem_kpi(ctrl_end)
        oem_reason = None if oem else f'No RegiMgr KPI[0] within ±{OEM_KPI_WINDOW_SEC}s of HO center'
        # OEM Loss association: latest before AUTH response
        oem_loss = latest_oem_loss_before(ctrl_end)
        oem_loss_reason = None if oem_loss else f'No OEM RTP loss within {OEM_LOSS_WINDOW_SEC}s before HO center'
        ev = HOEvent(
            vendor=vendor,
            direction='Cell->WiFi',
            attempt_ts=ctrl_start,
            result='Success',
            ctrl_start=ctrl_start,
            ctrl_end=ctrl_end,
            ctrl_latency_ms=ctrl_lat,
            cp_method='IKE_AUTH_req1_to_resp3',
            reason_ctrl=None,
            user_start=user_start,
            user_end=user_end,
            user_latency_ms=user_lat,
            up_method=up_method,
            reason_user=reason_user,
            pkt_loss_count=loss_count,
            pkt_loss_rate_pct=loss_pct,
            reason_loss=reason_loss,
            jitter_mean=jitter_mean,
            reason_jitter=reason_jitter,
            wifi_rssi_at_ho=wifi_rssi,
            reason_rssi=reason_rssi,
            rsrp_at_ho=rsrp,
            reason_rsrp=reason_rsrp,
            rsrq_at_ho=rsrq,
            reason_rsrq=reason_rsrq,
            sinr_at_ho=sinr,
            reason_sinr=reason_sinr,
            # OEM CP auxiliary
            oem_total_time_s=(oem.total_time_s if oem else None),
            oem_pdn_req_to_connected_s=(oem.pdn_req_to_connected_s if oem else None),
            oem_latch_to_pdn_req_s=(oem.latch_to_pdn_req_s if oem else None),
            oem_cp_source=(oem.source if oem else None),
            reason_oem_cp=oem_reason,
            # Failure/Impact
            failure_cause=None,
            notes=[],
            impact_score=impact,
            reason_impact=reason_impact,
        )
        events.append(ev)

    if events:
        # If we built events from explicit markers, return them to avoid duplicates
        return events

    # 2) Fallback: Detect user-plane gaps as candidates for HO (legacy method)
    gaps = detect_user_plane_gaps(media, gap_ms_threshold)
    if not gaps:
        # If no media lines or gaps, try control-plane only inference
        if ctrls:
            ctrl_start, ctrl_end, ctrl_lat = infer_control_plane(ctrls, None)
            direction = None
            if ctrl_start and ctrl_end:
                direction = 'WiFi->Cell' if 'WIFI_DOWN' in [c.kind for c in ctrls] else None
            center = ctrl_end or ctrl_start or ctrls[0].t
            sig = pre_signal(signals, center)
            # OEM KPI association near center
            oem = nearest_oem_kpi(center)
            oem_reason = None if oem else f'No RegiMgr KPI[0] within ±{OEM_KPI_WINDOW_SEC}s of HO center'
            # OEM Loss association near center
            oem_loss = latest_oem_loss_before(center)
            oem_loss_reason = None if oem_loss else f'No OEM RTP loss within {OEM_LOSS_WINDOW_SEC}s before HO center'
            ev = HOEvent(
                vendor=vendor,
                direction=direction,
                attempt_ts=ctrl_start or ctrl_end or ctrls[0].t,
                result='Unknown',
                ctrl_start=ctrl_start,
                ctrl_end=ctrl_end,
                ctrl_latency_ms=ctrl_lat,
                cp_method='Heuristic',
                reason_ctrl=None if ctrl_lat is not None else 'N/A - insufficient control-plane markers',
                user_start=None,
                user_end=None,
                user_latency_ms=None,
                up_method=None,
                reason_user='N/A - no media gap detected',
                pkt_loss_count=None,
                pkt_loss_rate_pct=None,
                reason_loss='N/A - no RTCP/NET_STAT in window',
                jitter_mean=None,
                reason_jitter='N/A - no jitter stats in window',
                wifi_rssi_at_ho=sig.wifi_rssi,
                reason_rssi=None if sig.wifi_rssi is not None else 'N/A - no WiFi RSSI near attempt',
                rsrp_at_ho=sig.rsrp,
                reason_rsrp=None if sig.rsrp is not None else 'N/A - no RSRP near attempt',
                rsrq_at_ho=sig.rsrq,
                reason_rsrq=None if sig.rsrq is not None else 'N/A - no RSRQ near attempt',
                sinr_at_ho=sig.sinr,
                reason_sinr=None if sig.sinr is not None else 'N/A - no SINR near attempt',
                # OEM CP auxiliary
                oem_total_time_s=(oem.total_time_s if oem else None),
                oem_pdn_req_to_connected_s=(oem.pdn_req_to_connected_s if oem else None),
                oem_latch_to_pdn_req_s=(oem.latch_to_pdn_req_s if oem else None),
                oem_cp_source=(oem.source if oem else None),
                reason_oem_cp=oem_reason,
                # OEM Loss auxiliary
                oem_loss_rate_pct=(oem_loss.loss_rate_pct if oem_loss else None),
                oem_loss_jitter_ms=(oem_loss.jitter_ms if oem_loss else None),
                oem_loss_source=(oem_loss.source if oem_loss else None),
                reason_oem_loss=oem_loss_reason,
                failure_cause=None,
                notes=['Control-plane only inference'],
                impact_score=None,
                reason_impact='N/A - no RX RTP center to compute max gap',
            )
            events.append(ev)
        return events

    for window in gaps:
        ustart, uend = window
        user_lat = (uend - ustart).total_seconds() * 1000.0
        direction = infer_direction(ctrls, window)
        ctrl_start, ctrl_end, ctrl_lat = infer_control_plane(ctrls, direction)
        loss_count, loss_pct, jitter_mean = compute_loss_and_jitter(rtcp, window)
        # Signal KPIs near attempt with windowed reasoning
        wifi_rssi, reason_rssi, rsrp, reason_rsrp, rsrq, reason_rsrq, sinr, reason_sinr = signal_values_with_reason(signals, ustart)
        impact = compute_impact_max_gap_ms(media, uend, IMPACT_WINDOW_MS)
        # OEM KPI association near the end of gap (as proxy HO center for fallback cases)
        center = ctrl_end or uend
        oem = nearest_oem_kpi(center)
        oem_reason = None if oem else f'No RegiMgr KPI[0] within ±{OEM_KPI_WINDOW_SEC}s of HO center'
        # OEM Loss association near center
        oem_loss = latest_oem_loss_before(center)
        oem_loss_reason = None if oem_loss else f'No OEM RTP loss within {OEM_LOSS_WINDOW_SEC}s before HO center'
        ev = HOEvent(
            vendor=vendor,
            direction=direction,
            attempt_ts=ustart,
            result='Unknown',
            ctrl_start=ctrl_start,
            ctrl_end=ctrl_end,
            ctrl_latency_ms=ctrl_lat,
            cp_method='Heuristic',
            reason_ctrl=None if ctrl_lat is not None else 'N/A - insufficient control-plane markers',
            user_start=ustart,
            user_end=uend,
            user_latency_ms=user_lat,
            up_method='MaxGap_Op2',
            reason_user=None,
            pkt_loss_count=loss_count,
            pkt_loss_rate_pct=loss_pct,
            reason_loss=None if (loss_count is not None or loss_pct is not None) else 'N/A - no RTCP/NET_STAT in window',
            jitter_mean=jitter_mean,
            reason_jitter=None if jitter_mean is not None else 'N/A - no jitter stats in window',
            wifi_rssi_at_ho=wifi_rssi,
            reason_rssi=reason_rssi if reason_rssi else (None if wifi_rssi is not None else 'N/A - no WiFi RSSI near attempt'),
            rsrp_at_ho=rsrp,
            reason_rsrp=reason_rsrp if reason_rsrp else (None if rsrp is not None else 'N/A - no RSRP near attempt'),
            rsrq_at_ho=rsrq,
            reason_rsrq=reason_rsrq if reason_rsrq else (None if rsrq is not None else 'N/A - no RSRQ near attempt'),
            sinr_at_ho=sinr,
            reason_sinr=reason_sinr if reason_sinr else (None if sinr is not None else 'N/A - no SINR near attempt'),
            # OEM CP auxiliary
            oem_total_time_s=(oem.total_time_s if oem else None),
            oem_pdn_req_to_connected_s=(oem.pdn_req_to_connected_s if oem else None),
            oem_latch_to_pdn_req_s=(oem.latch_to_pdn_req_s if oem else None),
            oem_cp_source=(oem.source if oem else None),
            reason_oem_cp=oem_reason,
            # OEM Loss auxiliary
            oem_loss_rate_pct=(oem_loss.loss_rate_pct if oem_loss else None),
            oem_loss_jitter_ms=(oem_loss.jitter_ms if oem_loss else None),
            oem_loss_source=(oem_loss.source if oem_loss else None),
            reason_oem_loss=oem_loss_reason,
            failure_cause=None,
            notes=['User-plane gap detected'],
            impact_score=impact,
            reason_impact=None if impact is not None else f'N/A - insufficient RX RTP packets in ±{IMPACT_WINDOW_MS/1000:.1f}s window',
        )
        events.append(ev)

    return events


# ----------------------------
# Output helpers
# ----------------------------

def to_rows(events: List[HOEvent]) -> List[List]:
    # Non-OEM columns first; OEM-specific columns at the end (per request)
    hdr = [
        # Basic identification
        'Vendor', 'Direction', 'AttemptTS', 'Result',
        # Control plane (primary)
        'CtrlStart', 'CtrlEnd', 'CtrlLatency(ms)', 'CP_Method', 'CP_Method_Detail', 'CtrlEnd_IPSEC', 'Reason(CP)', 'Reason(CP_Detail)',
        # Control plane (PDN-specific)
        'CP_PDN_Start', 'CP_PDN_End', 'CP_PDN_Latency(ms)', 'Reason(CP_PDN)',
        # User plane
        'UserStart', 'UserEnd', 'UserLatency(ms)', 'UP_Method', 'Reason(UP)',
        # SSRC influence
        'SSRC_Changed_At_HO', 'SSRC_Change_TS', 'Reason(SSRC)',
        # Packet loss and jitter (primary)
        'PktLossCount', 'PktLossRate(%)', 'Reason(Loss)',
        'JitterMean', 'Jitter_Peak', 'Reason(Jitter)', 'Reason(Jitter_Peak)',
        # Signals
        'WiFiRSSI', 'Reason(RSSI)', 'RSRP', 'Reason(RSRP)', 'RSRQ', 'Reason(RSRQ)', 'SINR', 'Reason(SINR)',
        # QoE hints
        'EVS_PLC_Event_Count', 'EVS_PLC_Lost_Sum', 'Reason(PLC)', 'LateDiscard_Count', 'Reason(LateDiscard)',
        # Impact and outcome
        'FailureCause', 'Notes', 'ImpactScore(ms)', 'Reason(Impact)',
        # RAT corroboration
        'RAT_Before', 'RAT_After',
        # OEM metrics (auxiliary, at the end)
        'OEM_TotalTime_s', 'OEM_IMS_PDN_Req_to_Connected_s', 'OEM_Latch_to_PDN_Req_s', 'OEM_CP_Source', 'Reason(OEM_CP)',
        'OEM_LossRate(%)', 'OEM_Loss_Jitter', 'OEM_Loss_Source', 'Reason(OEM_Loss)',
        'OEM_PreHO_Latency_ms', 'OEM_PreHO_Source', 'Reason(OEM_PreHO)'
    ]
    def tsfmt(t: Optional[datetime]) -> str:
        return t.isoformat(sep=' ') if t else 'N/A'
    def numfmt(v: Optional[float]) -> str:
        return str(round(v, 2)) if isinstance(v, (int, float)) and v is not None else 'N/A'
    rows = [hdr]
    for e in events:
        notes = '; '.join(e.notes) if e.notes else ''
        rows.append([
            # Basic identification
            e.vendor,
            e.direction or 'N/A',
            tsfmt(e.attempt_ts),
            e.result or 'Unknown',
            # Control plane
            tsfmt(e.ctrl_start),
            tsfmt(e.ctrl_end),
            numfmt(e.ctrl_latency_ms),
            e.cp_method or 'N/A',
            e.cp_method_detail or '',
            tsfmt(e.ctrl_end_ipsec),
            e.reason_ctrl or '',
            e.reason_cp_detail or '',
            # CP_PDN
            tsfmt(e.cp_pdn_start),
            tsfmt(e.cp_pdn_end),
            numfmt(e.cp_pdn_latency_ms),
            (e.reason_cp_pdn or ''),
            # User plane
            tsfmt(e.user_start),
            tsfmt(e.user_end),
            numfmt(e.user_latency_ms),
            e.up_method or 'N/A',
            e.reason_user or '',
            # SSRC
            ('Yes' if e.ssrc_changed_at_ho else ('No' if e.ssrc_changed_at_ho is not None else 'N/A')),
            tsfmt(e.ssrc_change_ts),
            e.reason_ssrc or '',
            # Loss/jitter
            (e.pkt_loss_count if e.pkt_loss_count is not None else 'N/A'),
            numfmt(e.pkt_loss_rate_pct),
            e.reason_loss or '',
            numfmt(e.jitter_mean),
            numfmt(e.jitter_peak),
            e.reason_jitter or '',
            e.reason_jitter_peak or '',
            # Signals
            (e.wifi_rssi_at_ho if e.wifi_rssi_at_ho is not None else 'N/A'),
            e.reason_rssi or '',
            (e.rsrp_at_ho if e.rsrp_at_ho is not None else 'N/A'),
            e.reason_rsrp or '',
            (e.rsrq_at_ho if e.rsrq_at_ho is not None else 'N/A'),
            e.reason_rsrq or '',
            (e.sinr_at_ho if e.sinr_at_ho is not None else 'N/A'),
            e.reason_sinr or '',
            # QoE
            (e.evs_plc_event_count if e.evs_plc_event_count is not None else 'N/A'),
            (e.evs_plc_lost_sum if e.evs_plc_lost_sum is not None else 'N/A'),
            e.reason_plc or '',
            (e.late_discard_count if e.late_discard_count is not None else 'N/A'),
            e.reason_late_discard or '',
            # Impact & outcome
            e.failure_cause or '',
            notes,
            numfmt(e.impact_score),
            e.reason_impact or '',
            # RAT corroboration
            (e.rat_before or ''),
            (e.rat_after or ''),
            # OEM auxiliary
            numfmt(e.oem_total_time_s),
            numfmt(e.oem_pdn_req_to_connected_s),
            numfmt(e.oem_latch_to_pdn_req_s),
            (e.oem_cp_source or ''),
            (e.reason_oem_cp or ''),
            numfmt(e.oem_loss_rate_pct),
            numfmt(e.oem_loss_jitter_ms),
            (e.oem_loss_source or ''),
            (e.reason_oem_loss or ''),
            (e.oem_preho_latency_ms if e.oem_preho_latency_ms is not None else 'N/A'),
            (e.oem_preho_source or ''),
            (e.reason_oem_preho or ''),
        ])
    return rows


def print_cli(events: List[HOEvent]) -> None:
    rows = to_rows(events)
    # Pretty print to CLI as a minimal fixed-width table
    col_widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    def fmt_row(r):
        return ' | '.join(str(v).ljust(col_widths[i]) for i, v in enumerate(r))
    print(fmt_row(rows[0]))
    print('-+-'.join('-' * w for w in col_widths))
    for r in rows[1:]:
        print(fmt_row(r))


def save_csv(events: List[HOEvent], path: str) -> None:
    rows = to_rows(events)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        for r in rows:
            writer.writerow(r)


def save_xlsx(events: List[HOEvent], path: str) -> None:
    if not HAVE_XLSX:
        raise RuntimeError('openpyxl not available')
    wb = Workbook()
    ws = wb.active
    ws.title = 'WFC HO'
    rows = to_rows(events)
    for r in rows:
        ws.append(r)
    # autosize columns
    for i, _ in enumerate(rows[0], start=1):
        max_len = 10
        for r in rows:
            max_len = max(max_len, len(str(r[i-1])))
        ws.column_dimensions[get_column_letter(i)].width = min(60, max_len + 2)
    wb.save(path)


# ----------------------------
# Main
# ----------------------------

def discover_logs(directory: str) -> List[Tuple[str, Optional[str]]]:
    """Discover Samsung/MTK main log files in a directory.
    Returns list of (path, vendor_hint).
    """
    patterns = [
        # Samsung
        ('samsung', ['samsung_main*.txt', '*samsung*main*logcat*.txt']),
        # MTK (various names seen)
        ('mtk', ['mtk_main*.txt', '*logcat_file*.txt', '*tcl_main*.txt', '*mtk*main*logcat*.txt']),
    ]
    found: List[Tuple[str, Optional[str]]] = []
    try:
        names = os.listdir(directory)
    except Exception:
        return found
    import fnmatch
    for vendor, globs in patterns:
        for pat in globs:
            for name in names:
                if fnmatch.fnmatch(name.lower(), pat.lower()):
                    full = os.path.join(directory, name)
                    if os.path.isfile(full):
                        found.append((full, vendor))
    return found


def group_logmain(files: List[Tuple[str, Optional[str]]]) -> Tuple[List[Tuple[str, Optional[str]]], Optional[List[str]]]:
    """If there are multiple files whose basename starts with 'logall_', return a new
    list where those entries are removed and a grouped list of their paths is returned
    separately. Otherwise grouped paths is None.
    """
    logmain_files = [p for p, _ in files if os.path.basename(p).lower().startswith('logall_')]
    if len(logmain_files) >= 2:
        remaining = [(p, v) for (p, v) in files if os.path.basename(p).lower() not in {os.path.basename(x).lower() for x in logmain_files}]
        return remaining, logmain_files
    return files, None


def main(argv=None):
    # Declare globals before any in-function reference (used in help strings below)
    global RTP_GAP_THRESHOLD_MS, CLUSTER_WINDOW_SEC, W2L_ATTEMPT_SEARCH_SEC, IKE_PAIR_WINDOW_SEC, IMPACT_WINDOW_MS, MAX_UP_LATENCY_MS, OEM_KPI_WINDOW_SEC, OEM_LOSS_WINDOW_SEC, LOSS_JITTER_MARGIN_SEC, SIGNAL_WINDOW_SEC
    ap = argparse.ArgumentParser(description='Parse WFC HO details from Android logcats and output CLI + Excel/CSV.')
    ap.add_argument('--samsung', help='Path to Samsung main logcat', default=None)
    ap.add_argument('--mtk', help='Path to MTK logcat', default=None)
    ap.add_argument('--dir', help='Directory to auto-discover log files (defaults to current working directory).', default='.')
    ap.add_argument('--excel', help='Output .xlsx path (requires openpyxl). If not provided or openpyxl missing, skipped.', default=None)
    ap.add_argument('--csv', help='Output .csv path (always supported). If auto-discovery finds multiple files, per-file defaults are used.', default=None)
    # Logging controls
    ap.add_argument('--log-file', default='log.txt', help='Path to write detailed debug log (default: ./log.txt)')
    ap.add_argument('--log-level', choices=['DEBUG','INFO','WARNING','ERROR'], default='INFO', help='Base console log level (default: INFO)')
    ap.add_argument('--verbose', action='store_true', help='Shortcut for --log-level INFO')
    ap.add_argument('--debug', action='store_true', help='Shortcut for --log-level DEBUG')
    ap.add_argument('--window-ms', type=int, default=150, help='User-plane gap threshold in ms to consider a handover (default: 150)')
    ap.add_argument('--vendor-hint', choices=['samsung', 'mtk'], default=None, help='Force vendor for analysis of provided file(s)')
    # Parameter overrides
    ap.add_argument('--cluster-window-sec', type=int, default=None, help=f'Cluster window for Samsung W2L success markers (default: {CLUSTER_WINDOW_SEC}s)')
    ap.add_argument('--w2l-attempt-search-sec', type=int, default=None, help=f'Backsearch window to find W2L attempt trigger (default: {W2L_ATTEMPT_SEARCH_SEC}s)')
    ap.add_argument('--ike-pair-window-sec', type=int, default=None, help=f'Max time between IKE_AUTH req1 and resp3 (default: {IKE_PAIR_WINDOW_SEC}s)')
    ap.add_argument('--impact-window-ms', type=int, default=None, help=f'Window for ImpactScore (±window/2 around center) (default: {IMPACT_WINDOW_MS}ms)')
    ap.add_argument('--max-up-latency-ms', type=int, default=None, help=f'Upper bound for valid user-plane latency (default: {MAX_UP_LATENCY_MS}ms)')
    ap.add_argument('--oem-kpi-window-sec', type=int, default=None, help=f'Association window for RegiMgr KPI near HO (default: {OEM_KPI_WINDOW_SEC}s)')
    ap.add_argument('--loss-jitter-margin-sec', type=int, default=None, help=f'Extra margin around KPI window when computing loss/jitter (default: {LOSS_JITTER_MARGIN_SEC}s)')
    ap.add_argument('--signal-window-sec', type=int, default=None, help=f'Time window to consider signal KPIs (WiFi RSSI/RSRP/RSRQ/SINR) near attempt (default: {SIGNAL_WINDOW_SEC}s)')
    args = ap.parse_args(argv)

    # Apply parameter overrides to globals
    if args.cluster_window_sec is not None:
        CLUSTER_WINDOW_SEC = args.cluster_window_sec
    if args.w2l_attempt_search_sec is not None:
        W2L_ATTEMPT_SEARCH_SEC = args.w2l_attempt_search_sec
    if args.ike_pair_window_sec is not None:
        IKE_PAIR_WINDOW_SEC = args.ike_pair_window_sec
    if args.impact_window_ms is not None:
        IMPACT_WINDOW_MS = args.impact_window_ms
    if args.max_up_latency_ms is not None:
        MAX_UP_LATENCY_MS = args.max_up_latency_ms
    if args.oem_kpi_window_sec is not None:
        OEM_KPI_WINDOW_SEC = args.oem_kpi_window_sec
    if args.loss_jitter_margin_sec is not None:
        LOSS_JITTER_MARGIN_SEC = args.loss_jitter_margin_sec
    if args.signal_window_sec is not None:
        SIGNAL_WINDOW_SEC = args.signal_window_sec

    # Initialize logging
    effective_level = ('DEBUG' if args.debug else ('INFO' if args.verbose else (args.log_level or 'INFO')))
    try:
        setup_logging(args.log_file, effective_level)
    except Exception:
        # As a fallback, ensure logging at least doesn't crash
        pass
    logging.info('WFC HO Parser starting')
    logging.info('Effective logging: file=%s level=%s', args.log_file, effective_level)
    logging.info('Tunables: CLUSTER_WINDOW_SEC=%s W2L_ATTEMPT_SEARCH_SEC=%s IKE_PAIR_WINDOW_SEC=%s IMPACT_WINDOW_MS=%s MAX_UP_LATENCY_MS=%s OEM_KPI_WINDOW_SEC=%s OEM_LOSS_WINDOW_SEC=%s LOSS_JITTER_MARGIN_SEC=%s SIGNAL_WINDOW_SEC=%s',
                 CLUSTER_WINDOW_SEC, W2L_ATTEMPT_SEARCH_SEC, IKE_PAIR_WINDOW_SEC, IMPACT_WINDOW_MS, MAX_UP_LATENCY_MS, OEM_KPI_WINDOW_SEC, OEM_LOSS_WINDOW_SEC, LOSS_JITTER_MARGIN_SEC, SIGNAL_WINDOW_SEC)

    inputs: List[Tuple[str, Optional[str]]] = []

    # Explicit files first
    if args.samsung and os.path.exists(args.samsung):
        inputs.append((args.samsung, args.vendor_hint or 'samsung'))
    if args.mtk and os.path.exists(args.mtk):
        inputs.append((args.mtk, args.vendor_hint or 'mtk'))

    # If none provided, try auto-discovery in directory
    if not inputs:
        directory = args.dir or '.'
        discovered = discover_logs(directory)
        if discovered:
            # Apply logmain_ grouping
            discovered, grouped_logmain = group_logmain(discovered)
            inputs.extend(discovered)
            if grouped_logmain:
                # Represent grouped input as a tuple with vendor_hint None and special handling later
                inputs.append((grouped_logmain, None))  # type: ignore
        else:
            # As a last resort, include any *main_logcat.txt in dir
            try:
                for name in os.listdir(directory):
                    if name.lower().startswith('logall_'):
                        inputs.append((os.path.join(directory, name), None))
            except Exception:
                pass

    if not inputs:
        print('No input files found. Provide --samsung/--mtk or run with --dir pointing to a folder containing samsung_main*.txt or mtk_main/logcat_file*.txt.')
        return 2

    multiple = len(inputs) > 1
    overall_status = 0

    for path, vh in inputs:
        # Grouped case: path can be a List[str] when grouping logmain_ files
        if isinstance(path, list):
            grouped_paths: List[str] = path
            print(f'Analyzing grouped logmain_ files ({len(grouped_paths)} files) (vendor_hint={vh or "auto"})')
            logging.info('Analyzing grouped logmain_ files (%d files) (vendor_hint=%s)', len(grouped_paths), (vh or 'auto'))
            events = analyze_files(grouped_paths, args.window_ms, vh)
            # Output naming: use directory base + 'logmain__combined'
            dir_base = os.path.abspath(args.dir or '.')
            out_base = os.path.join(dir_base, 'logmain__combined')
        else:
            print(f'Analyzing: {path} (vendor_hint={vh or "auto"})')
            logging.info('Analyzing file: %s (vendor_hint=%s)', path, (vh or 'auto'))
            events = analyze_file(path, args.window_ms, vh)
            out_base, _ = os.path.splitext(path)
        if not events:
            print('  No HO events detected in this file.')
            logging.warning('No HO events detected for %s', ('grouped logmain_' if isinstance(path, list) else path))
            overall_status = max(overall_status, 1)
        else:
            logging.info('Detected %d HO events for %s', len(events), ('grouped logmain_' if isinstance(path, list) else path))
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                for idx, e in enumerate(events, 1):
                    logging.debug('Event #%d: vendor=%s dir=%s result=%s ctrl_lat_ms=%s user_lat_ms=%s impact_ms=%s attempt=%s',
                                  idx, e.vendor, e.direction, e.result, e.ctrl_latency_ms, e.user_latency_ms, e.impact_score,
                                  (e.attempt_ts.isoformat(sep=' ') if e.attempt_ts else 'N/A'))
            print_cli(events)
        # Save outputs
        if args.csv and not multiple and not isinstance(path, list):
            out_csv = args.csv
        else:
            out_csv = f'{out_base}_wfc_ho_results.csv'
        try:
            save_csv(events, out_csv)
            print(f'  CSV saved: {out_csv}')
            logging.info('CSV saved: %s', out_csv)
        except Exception as e:
            print(f'  Failed to save CSV: {e}')
            logging.error('Failed to save CSV %s: %s', out_csv, e)
            overall_status = max(overall_status, 1)
        # Excel only if single input and explicitly requested
        if args.excel and not multiple and not isinstance(path, list):
            try:
                save_xlsx(events, args.excel)
                print(f'  Excel saved: {args.excel}')
                logging.info('Excel saved: %s', args.excel)
            except Exception as e:
                print(f'  Failed to save Excel: {e}')
                logging.error('Failed to save Excel %s: %s', args.excel, e)
                overall_status = max(overall_status, 1)

    print(f'  Log saved: {args.log_file}')
    logging.info('Log saved: %s', args.log_file)
    return overall_status


if __name__ == '__main__':
    sys.exit(main())
