# -*- coding: utf-8 -*-
"""
금속 식각 공정 FDC 모니터링 대시보드 (현장 엔지니어용)
=====================================================
이 화면은 "AI가 불량명을 맞히는 화면"이 아닙니다.
MPCA Q statistic 으로 이상 신호를 감지하고, Contribution / FDC 해석으로
'확인이 필요한 센서'와 '조치 방향'을 제시하는 금속 식각 공정 모니터링 화면입니다.

실행:
    streamlit run dashboard_process_monitoring_final.py

필요 패키지: streamlit, pandas, plotly
"""

import os
import re
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# 0. 경로 / 상수
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

Q_TRAJ_FILE   = os.path.join(BASE_DIR, "streaming_q_trajectory.csv")
DETECT_FILE   = os.path.join(BASE_DIR, "streaming_detection_results.csv")
FDC_FILE      = os.path.join(BASE_DIR, "mpca_fault_fdc_interpretation.csv")
REVIEW_FILE   = os.path.join(BASE_DIR, "operator_review_status.csv")  # 운영자 처리상태 저장

# 원본 센서 CSV (조회/시각화 전용 — 새 이상탐지/threshold/score 계산에 사용하지 않음)
RAW_FILES = {
    "EV":  os.path.join(BASE_DIR, "ev_data(1).csv"),
    "OES": os.path.join(BASE_DIR, "oes_data(1).csv"),
    "RFM": os.path.join(BASE_DIR, "rfm_data (1).csv"),
}

# 색상 (UI 표시용 — 색상 규칙: 기본=회색/남색, 주의=주황, 초과=빨강은 marker 에만)
C_Q        = "#2563eb"                # Q statistic (파란 선)
C_THR      = "#98a2b3"                # Adaptive 99% Threshold (회색 점선)
C_EXCEED   = "#d92d20"                # threshold 초과 marker (빨강)
C_BAND     = "rgba(245,158,11,0.13)"  # 초과 구간 배경 (연한 주황)
C_RISE     = "#f59e0b"                # q_delta 상승 (주의 amber)
C_FALL     = "#cbd5e1"                # q_delta 하강 (회색)

# FDC 계열별 "작업 지시형" 확인 가이드 (suspected_family 기반, 모델 예측값 아님)
FDC_INSTRUCTION = {
    "rf":       "RF 전력 공급, Bias Power, RF Load 변동 여부를 먼저 확인한다.",
    "tcp":      "TCP Source Power, TCP Load, TCP Tuner 변화를 확인한다.",
    "matching": "Impedance, Phase Error, Reflected Power 변화를 함께 확인한다.",
    "gas":      "BCl3 또는 Cl2 공급 조건과 유량(Flow) 안정성을 확인한다.",
    "he":       "Backside He Pressure와 wafer chucking 상태를 확인한다.",
    "pressure": "Chamber Pressure와 Vat Valve Position 변화를 확인한다.",
    "oes":      "플라즈마 반응 강도와 endpoint(OES) 신호 변화를 확인한다.",
    "generic":  "점검 센서의 trend와 공정 조건 변화를 함께 확인한다.",
}

# 계열별 관련 센서 묶음 (FDC_INSTRUCTION 과 동일한 내용을 태그로 표시하기 위한 UI 데이터)
FAMILY_SENSORS = {
    "rf":       ["RF 전력", "Bias Power", "RF Load"],
    "tcp":      ["TCP Source Power", "TCP Load", "TCP Tuner"],
    "matching": ["Impedance", "Phase Error", "Reflected Power"],
    "gas":      ["BCl3 Flow", "Cl2 Flow", "유량 안정성"],
    "he":       ["Backside He Press", "Wafer Chucking"],
    "pressure": ["Chamber Pressure", "Vat Valve"],
    "oes":      ["플라즈마 강도", "Endpoint(OES)"],
    "generic":  ["점검 센서"],
}


# ---------------------------------------------------------------------------
# 1. 컬럼 자동 매핑 (컬럼명이 조금 달라도 동작하도록 후보 탐색)
# ---------------------------------------------------------------------------
def find_col(df, candidates, contains=None):
    """후보 목록에서 실제 존재하는 컬럼을 찾아 반환. 없으면 contains(부분일치)로 탐색."""
    cols = list(df.columns)
    lower = {c.lower().strip(): c for c in cols}
    # 1) 정확 일치 (대소문자 무시)
    for cand in candidates:
        key = cand.lower().strip()
        if key in lower:
            return lower[key]
    # 2) 부분 일치
    needles = contains if contains else candidates
    for c in cols:
        cl = c.lower()
        for n in needles:
            if n.lower() in cl:
                return c
    return None


def col_map(df, spec):
    """spec = {표준이름: ([후보들], [contains후보])}. 매핑 결과 dict 반환(없으면 None)."""
    out = {}
    for std, val in spec.items():
        cands, contains = (val if isinstance(val, tuple) else (val, None))
        out[std] = find_col(df, cands, contains)
    return out


# ---------------------------------------------------------------------------
# 2. 데이터 로드 + 표준화
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_data():
    q   = pd.read_csv(Q_TRAJ_FILE)
    det = pd.read_csv(DETECT_FILE)
    fdc = pd.read_csv(FDC_FILE)

    # --- Q trajectory ---
    qm = col_map(q, {
        "wafer_id":     (["wafer_id", "wafer", "id"], ["wafer"]),
        "progress_pct": (["progress_pct", "progress", "pct", "step"], ["progress", "pct"]),
        "Q_score":      (["Q_score", "q_score", "qstat", "q"], ["q_score", "qstat"]),
        "Q_threshold":  (["Q_threshold", "q_threshold", "threshold", "thr"], ["threshold", "thr"]),
        "pred_anomaly": (["pred_anomaly", "pred", "anomaly"], ["anomaly", "pred"]),
        "fault_name":   (["fault_name", "fault", "label"], ["fault", "label"]),
        "is_fault":     (["is_fault", "fault_flag"], ["is_fault"]),
    })
    q = q.rename(columns={v: k for k, v in qm.items() if v})
    q["wafer_id"] = q["wafer_id"].astype(int)
    q = q.sort_values(["wafer_id", "progress_pct"]).reset_index(drop=True)
    # q_delta : 현재 Q − 직전 progress Q (보조 시각화용, 새 판정 기준 아님)
    q["q_delta"] = q.groupby("wafer_id")["Q_score"].diff()
    q["exceed"]  = q["Q_score"] > q["Q_threshold"]

    # --- Detection results ---
    dm = col_map(det, {
        "wafer_id":              (["wafer_id", "wafer", "id"], ["wafer"]),
        "first_detect_progress": (["first_detect_progress", "first_detect", "detect_progress"], ["first_detect"]),
        "lead_time_pct":         (["lead_time_pct", "lead_time", "lead"], ["lead"]),
        "detected_at_pct":       (["detected_at_pct", "detected_at"], ["detected_at"]),
        "detected":              (["detected", "detect_flag"], ["detected"]),
        "fault_name":            (["fault_name", "fault", "label"], ["fault", "label"]),
        "is_fault":              (["is_fault", "fault_flag"], ["is_fault"]),
    })
    det = det.rename(columns={v: k for k, v in dm.items() if v})
    det["wafer_id"] = det["wafer_id"].astype(int)
    det["detected"] = det["detected"].astype(bool)

    # --- FDC interpretation ---
    fm = col_map(fdc, {
        "wafer_id":           (["wafer_id", "wafer", "id"], ["wafer"]),
        "top_block":          (["top_block", "block"], ["block"]),
        "top_sensor":         (["top_sensor", "sensor"], ["sensor"]),
        "top_sensor_pct":     (["top_sensor_pct"], ["sensor_pct"]),
        "top_time":           (["top_time"], ["time"]),
        "suspected_family":   (["suspected_family", "family", "suspect"], ["family", "suspect"]),
        "fdc_interpretation": (["fdc_interpretation", "interpretation", "fdc"], ["interpret", "fdc"]),
    })
    fdc = fdc.rename(columns={v: k for k, v in fm.items() if v})
    fdc["wafer_id"] = fdc["wafer_id"].astype(int)

    return q, det, fdc


# ---------------------------------------------------------------------------
# 3. 해석형 문구 변환 (숫자 → 현장 언어)
# ---------------------------------------------------------------------------
def progress_phrase(pct):
    """progress_pct → 공정 초기/중반/후반 해석"""
    if pct is None or pd.isna(pct):
        return "구간 정보 없음"
    p = int(round(float(pct)))
    if p <= 30:
        return f"공정 초기({p}% 구간)"
    if p <= 70:
        return f"공정 중반({p}% 구간)"
    return f"공정 후반({p}% 구간)"


def leadtime_phrase(lt):
    """Lead Time → 조기 인지 여유 해석"""
    if lt is None or pd.isna(lt):
        return "조기 인지 정보 없음"
    v = int(round(float(lt)))
    if v <= 0:
        return "조기 인지 여유 없음 (종료 시점 단발 감지)"
    if v >= 70:
        return f"공정 종료 전 {v}% 구간에서 조기 인지"
    if v >= 40:
        return f"공정 중반 이전 조기 인지({v}%)"
    return f"공정 후반부 탐지({v}%)"


def progress_token(pct):
    """테이블용 짧은 토큰 (초기/중반/후반 + %)"""
    if pct is None or pd.isna(pct):
        return "—"
    p = int(round(float(pct)))
    if p <= 30:
        return f"초기 {p}%"
    if p <= 70:
        return f"중반 {p}%"
    return f"후반 {p}%"


def lead_token(lt):
    """테이블용 짧은 토큰 (조기 인지 여유)"""
    if lt is None or pd.isna(lt):
        return "—"
    v = int(round(float(lt)))
    return "여유 없음" if v <= 0 else f"여유 {v}%"


def family_key(fam):
    """suspected_family 문자열 → 계열 key (작업 지시 매핑용). 매칭 계열 우선 판별."""
    f = str(fam)
    if "RF/TCP" in f or "매칭" in f:
        return "matching"
    if "OES" in f or "플라즈마" in f:
        return "oes"
    if "He" in f or "Chuck" in f or "척" in f:
        return "he"
    if ("Cl2" in f) or ("BCl3" in f) or ("가스" in f) or ("Gas" in f):
        return "gas"
    if ("제어" in f) or ("장비" in f) or ("Pressure" in f) or ("압력" in f) or ("Valve" in f):
        return "pressure"
    if "TCP" in f:
        return "tcp"
    if "RF" in f:
        return "rf"
    return "generic"


def family_instruction(fam):
    return FDC_INSTRUCTION.get(family_key(fam), FDC_INSTRUCTION["generic"])


def family_short(fam):
    """테이블용 짧은 계열명 ('RF 계열 이상 의심' → 'RF 계열')."""
    return str(fam).replace(" 이상 의심", "").replace("이상 의심", "").strip()


# --- 예지보전 표현: Lead Time(계산값) → '남은 구간' 문구 (계산 자체는 변경 없음) ---
def remain_phrase(lt):
    if lt is None or pd.isna(lt):
        return "—"
    v = int(round(float(lt)))
    if v <= 0:
        return "남은 구간 없음 (종료 시점 감지)"
    return f"공정 종료 전 {v}% 구간"


def remain_token(lt):
    if lt is None or pd.isna(lt):
        return "—"
    v = int(round(float(lt)))
    return "여유 없음" if v <= 0 else f"종료 전 {v}%"


# --- 점검 우선순위: 기존 Q_score/Q_threshold 비율만 사용 (새 score/threshold 아님) ---
def priority_label(max_ratio):
    if max_ratio is None or pd.isna(max_ratio):
        return "관찰"
    if max_ratio >= 2.0:
        return "긴급"
    if max_ratio >= 1.2:
        return "위험"
    return "관찰"


def priority_cls(label):
    return {"긴급": "urgent", "위험": "high", "관찰": "watch"}.get(label, "watch")


# 화면 표시용: 우선순위 라벨 → 점검 단계 문구 (정렬/계산은 기존 긴급/위험/관찰 그대로 사용)
PRIO_PHRASE = {"긴급": "긴급 점검", "위험": "주의 점검", "관찰": "관찰"}

# 상태별 색상 매핑 — UI 표시 전용 (판정 로직 변경 없음)
STATUS_COLOR  = {"긴급 점검": "#dc2626", "주의 점검": "#f59e0b", "관찰": "#16a34a", "정상": "#2563eb", "완료": "#2563eb"}
STATUS_BG     = {"긴급 점검": "#fef2f2", "주의 점검": "#fff7ed", "관찰": "#f0fdf4",  "정상": "#ffffff",  "완료": "#ffffff"}
STATUS_BORDER = {"긴급 점검": "#fca5a5", "주의 점검": "#fdba74", "관찰": "#86efac",  "정상": "#94a3b8",  "완료": "#94a3b8"}


# ---------------------------------------------------------------------------
# 화면 표시명 통일 매핑 (단일 소스 — 같은 의미는 코드 전체에서 같은 문구로)
#   * 표시 문구만 변환. 계산/판정 값(긴급/위험/관찰, detected, Q_score 등)은 바꾸지 않는다.
# ---------------------------------------------------------------------------
def normalize_status_label(s):
    """점검 단계 / 확인 상태 표시명 통일."""
    return {"바로 확인 필요": "긴급 점검", "우선 확인 필요": "주의 점검",
            "추이 관찰": "관찰", "추이 관찰 필요": "관찰", "정상 범위": "정상",
            "처리 완료": "완료"}.get(str(s).strip(), str(s).strip())


def normalize_column_label(c):
    """표 컬럼 / 항목 표시명 통일."""
    return {"확인 센서": "점검 센서", "우선 점검 센서": "점검 센서", "확인 방향": "점검 방향",
            "권장 확인": "점검 방향", "먼저 볼 계열": "점검 계열", "먼저 볼 장비/계열": "점검 계열",
            "같이 볼 센서": "같이 점검할 센서"}.get(str(c).strip(), str(c).strip())


def normalize_compare_label(s):
    """센서 비교 결과 표시명 통일 (정상 평균 대비)."""
    return {"정상과 유사": "정상 범위 안", "정상보다 높음": "정상 범위 이탈",
            "정상보다 낮음": "정상 범위 이탈"}.get(s, "비교 데이터 부족")


def qrise_interval(wqx):
    """q_delta 최대 상승 구간 'A% → B%' (보조 시각화용, 새 판정 아님)."""
    g = wqx.sort_values("progress_pct")
    progs = g["progress_pct"].tolist()
    qdv = g["q_delta"].tolist()
    best_i, best_v = None, None
    for i, d in enumerate(qdv):
        if d is None or pd.isna(d):
            continue
        if best_v is None or d > best_v:
            best_v, best_i = d, i
    if not best_i:
        return None
    return f"{progs[best_i - 1]}% → {progs[best_i]}%"


def threshold_approach_phrase(wqx):
    """기존 Q_score/Q_threshold 만 사용. 첫 초과 직전 '기준선 접근' 구간을 구간 기반으로 표현."""
    g = wqx.sort_values("progress_pct")
    progs = g["progress_pct"].tolist()
    gap = (g["Q_threshold"] - g["Q_score"]).tolist()   # >0: 기준선 아래, <=0: 초과
    first_ex = next((p for p, gp in zip(progs, gap) if gp <= 0), None)
    if first_ex is None:
        return None
    if first_ex == progs[0]:
        return "공정 초기 구간부터 기준선 초과"
    idx = progs.index(first_ex)
    return f"{progs[idx - 1]}~{first_ex}% 구간에서 기준선 접근 후 초과"


def exceed_segments(progress, mask):
    """threshold 초과가 연속되는 구간 [(start,end), ...] 반환 (음영용)."""
    segs, start, prev = [], None, None
    for p, m in zip(progress, mask):
        if m and start is None:
            start = p
        elif (not m) and start is not None:
            segs.append((start, prev))
            start = None
        prev = p
    if start is not None:
        segs.append((start, prev))
    return segs


# ---------------------------------------------------------------------------
# 4. 운영자 처리상태 저장/로드 (operator_review_status.csv)
# ---------------------------------------------------------------------------
def load_review():
    """{wafer_id: {'handled': bool, 'memo': str}} 형태로 로드."""
    if not os.path.exists(REVIEW_FILE):
        return {}
    try:
        r = pd.read_csv(REVIEW_FILE)
    except Exception:
        return {}
    out = {}
    for row in r.itertuples(index=False):
        d = row._asdict()
        wid = int(d.get("wafer_id"))
        handled = str(d.get("handled", False)).strip().lower() in {"true", "1", "yes"}
        memo = "" if pd.isna(d.get("memo", "")) else str(d.get("memo", ""))
        # 확인 상태: 미확인 / 확인 중 / 완료 (status 없으면 handled 로 유도, 레거시 '처리 완료'→'완료')
        raw = d.get("status", None)
        if raw is None or (isinstance(raw, float) and pd.isna(raw)) or str(raw).strip() == "":
            status = "완료" if handled else "미확인"
        else:
            status = str(raw).strip()
            if status == "처리 완료":
                status = "완료"
        updated = "" if pd.isna(d.get("updated_at", "")) else str(d.get("updated_at", ""))
        out[wid] = {"handled": handled, "memo": memo, "status": status, "updated": updated}
    return out


def save_review(records):
    """records = [{wafer_id, handled, memo}]. 변경분 저장 + 타임스탬프."""
    df = pd.DataFrame(records)
    df["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df.to_csv(REVIEW_FILE, index=False)


def save_review_dict(review):
    """review dict 전체 저장. status(미확인/확인 중/완료) + handled(하위호환)."""
    save_review([{"wafer_id": w,
                  "status": v.get("status", "미확인"),
                  "handled": v.get("status", "미확인") == "완료",
                  "memo": v.get("memo", "")}
                 for w, v in review.items()])


# ---------------------------------------------------------------------------
# 5. 원본 센서 CSV 로드 (EV/OES/RFM) — 조회/시각화 전용
#    * 기존 MPCA Q/threshold/Lead Time/FDC 결과는 변경하지 않는다.
#    * 여기서 읽는 원본 센서값으로 새 score/threshold/이상탐지를 만들지 않는다.
# ---------------------------------------------------------------------------
RAW_EXCLUDE_COLS = {"wafer_names", "fault_name", "Step Number", "wafer_id", "progress"}


@st.cache_data(show_spinner=False)
def load_raw_block(block):
    """블록(EV/OES/RFM) 원본 CSV 로드 + wafer_id / progress(0~100%) 부여."""
    df = pd.read_csv(RAW_FILES[block])
    wn_col = find_col(df, ["wafer_names", "wafer_name", "wafer_id", "wafer"], ["wafer"])
    # 'l2901.txm' / 's2901.int' / 'r2901.txt' → 2901
    df["wafer_id"] = pd.to_numeric(
        df[wn_col].astype(str).str.extract(r"(\d+)")[0], errors="coerce")
    df = df.dropna(subset=["wafer_id"]).copy()
    df["wafer_id"] = df["wafer_id"].astype(int)
    # 시간 컬럼이 있으면 시간순 정렬 (OES 는 시간 컬럼이 없어 파일 순서를 진행순으로 사용)
    tcol = find_col(df, ["Time", "TIME", "timestamp"], ["time"])
    if tcol:
        df = df.sort_values(["wafer_id", tcol]).reset_index(drop=True)
    # wafer 내 진행률 0~100% (원본 표본 순서 기준) — Q progress_pct 축과 정렬하기 위함
    n = df.groupby("wafer_id")["wafer_id"].transform("size")
    rank = df.groupby("wafer_id").cumcount()
    df["progress"] = (rank / (n - 1).clip(lower=1) * 100.0).where(n > 1, 0.0)
    return df


def raw_sensor_cols(df):
    """블록 DataFrame 에서 센서(수치) 컬럼 목록만 반환."""
    tcol = find_col(df, ["Time", "TIME", "timestamp"], ["time"])
    exclude = set(RAW_EXCLUDE_COLS) | ({tcol} if tcol else set())
    return [c for c in df.columns
            if c not in exclude and pd.api.types.is_numeric_dtype(df[c])]


@st.cache_data(show_spinner=False)
def normal_trend(block, sensor, normal_ids, grid=60):
    """정상(미감지) wafer 들의 sensor trend 를 공통 progress 그리드에 보간 후 평균/표준편차.
    'normal'=기존 Q 알람에서 미감지(detected=False)인 wafer (새 판정 아님)."""
    df = load_raw_block(block)
    if sensor not in df.columns:
        return None
    xs = np.linspace(0, 100, grid)
    mats = []
    sub_all = df[df["wafer_id"].isin(set(normal_ids))]
    for _, sub in sub_all.groupby("wafer_id"):
        s = sub[["progress", sensor]].dropna()
        if len(s) < 2:
            continue
        mats.append(np.interp(xs, s["progress"].to_numpy(), s[sensor].to_numpy()))
    if not mats:
        return None
    M = np.vstack(mats)
    return xs, M.mean(axis=0), M.std(axis=0), len(mats)


# ---------------------------------------------------------------------------
# 6. 표시용 헬퍼 (기존 결과를 현장 문구로 변환 — 새 모델/threshold/score 아님)
# ---------------------------------------------------------------------------
def segment_name(pct):
    # wafer별 공정 신호를 0~100%로 정렬한 상대 진행 구간 (실제 recipe step명 아님)
    if pct is None or pd.isna(pct):
        return "구간 정보 없음"
    p = float(pct)
    if p <= 20:
        return "식각 시작 구간"
    if p <= 40:
        return "식각 초반 구간"
    if p <= 60:
        return "식각 중반 구간"
    if p <= 80:
        return "식각 후반 구간"
    return "식각 종료 접근 구간"


def segment_with_pct(pct):
    if pct is None or pd.isna(pct):
        return "이상 없음"
    return f"{segment_name(pct)} / {int(round(float(pct)))}%"


def segment_short(pct):
    if pct is None or pd.isna(pct):
        return "—"
    return f"{segment_name(pct).replace(' 구간', '')} {int(round(float(pct)))}%"


# 점검 계열 표시명
FAMILY_VIEW = {"rf": "RF/TCP 매칭", "matching": "RF/TCP 매칭", "tcp": "RF/TCP 매칭", "gas": "Gas 공급",
               "pressure": "Pressure 제어", "oes": "OES/플라즈마", "he": "He Chuck", "generic": "장비 조건"}


def family_view(fam):
    return FAMILY_VIEW.get(family_key(fam), "—")


# 점검 방향 (표/패널용 현장 문구)
CHECK_DIRECTION = {"rf": "RF/TCP 매칭 계열 확인", "matching": "RF/TCP 매칭 계열 확인",
                   "tcp": "RF/TCP 매칭 계열 확인", "gas": "Gas 공급 상태 확인",
                   "pressure": "Pressure 제어 상태 확인", "oes": "OES/플라즈마 반응 확인",
                   "he": "He Chuck 상태 확인", "generic": "장비 조건 변화 확인"}


def check_direction(fam, detected=True):
    if not detected or not str(fam).strip():
        return "장비 조건 변화 확인"
    return CHECK_DIRECTION.get(family_key(fam), "장비 조건 변화 확인")


# 같이 점검할 센서 (계열별 — 함께 점검할 센서)
COSEE_SENSORS = {
    "rf":       ["RF 전력", "RF Load", "Bias Power", "Reflected Power", "TCP Load"],
    "matching": ["RF 전력", "RF Load", "Bias Power", "Reflected Power", "TCP Load"],
    "tcp":      ["TCP Power", "TCP Load", "RF 전력", "플라즈마 세기", "Reflected Power"],
    "gas":      ["BCl3 Flow", "Cl2 Flow", "MFC 응답", "RF 전력", "OES 신호"],
    "pressure": ["Chamber Pressure", "Vat Valve", "배기 상태", "RF 전력", "OES 신호"],
    "he":       ["Backside He", "Chuck 상태", "냉각 상태", "인접 wafer He"],
    "oes":      ["플라즈마 발광", "Gas 신호", "RF 전력", "endpoint 신호"],
    "generic":  ["RF 전력", "RF Load", "Chamber Pressure", "Gas Flow"],
}


def cosee_sensors(fam):
    return COSEE_SENSORS.get(family_key(fam), COSEE_SENSORS["generic"])


def sensor_direction(block, sensor, wid, normal_ids):
    """선택 wafer 센서 평균 vs 정상 wafer 평균 → '정상보다 높음/낮음/유사'. 표시 보조(새 판정 아님)."""
    try:
        df = load_raw_block(block)
    except Exception:
        return None
    if sensor not in df.columns:
        return None
    s = df[df["wafer_id"] == wid][sensor].dropna()
    if s.empty:
        return None
    nt = normal_trend(block, sensor, tuple(sorted(normal_ids)))
    if nt is None:
        return None
    sel_mean, nmean, nstd = float(s.mean()), float(np.mean(nt[1])), float(np.mean(nt[2]))
    tol = max(nstd, abs(nmean) * 0.005)
    if sel_mean > nmean + tol:
        return "정상보다 높음"
    if sel_mean < nmean - tol:
        return "정상보다 낮음"
    return "정상과 유사"


# ---------------------------------------------------------------------------
# 캐릭터 이미지 헬퍼 (character 폴더 — 인터넷 다운로드 없음, 로컬 전용)
# ---------------------------------------------------------------------------
def get_character_images():
    """BASE_DIR/character 폴더에서 유효한 이미지 경로 목록 반환. 폴더 없으면 []."""
    char_dir = os.path.join(BASE_DIR, "character")
    if not os.path.isdir(char_dir):
        return []
    exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    return sorted(
        os.path.join(char_dir, f) for f in os.listdir(char_dir)
        if os.path.splitext(f)[1].lower() in exts
    )


def first_character_image():
    """transparent 우선, 없으면 첫 번째 이미지 경로 반환. 이미지가 없으면 None."""
    imgs = get_character_images()
    if not imgs:
        return None
    return next((p for p in imgs if "transparent" in os.path.basename(p).lower()), imgs[0])


def render_character_image(position="sidebar"):
    """캐릭터 이미지를 st.image() 로 안전하게 렌더링. 이미지 없으면 아무것도 표시하지 않음."""
    img_path = first_character_image()
    if not img_path:
        return
    width = 100 if position == "sidebar" else 70
    try:
        st.image(img_path, width=width)
    except Exception:
        pass


# ===========================================================================
#  PAGE  (3페이지 · 블록 분리/색상/현장 문구 재정리)
# ===========================================================================
st.set_page_config(page_title="금속 식각 FDC 모니터링", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
<style>
  .stApp { background:#e4e9f1; }
  header[data-testid="stHeader"] { visibility:hidden; background:transparent; }
  [data-testid="stExpandSidebarButton"] { visibility:visible !important; z-index:1000000 !important; }
  [data-testid="stSidebarCollapseButton"] { visibility:visible !important; }
  #MainMenu, footer { visibility:hidden; }
  .block-container { padding:0.5rem 1.4rem 0.9rem 1.4rem; max-width:1500px; }
  div[data-testid="stVerticalBlock"] { gap:0.65rem; }
  [data-testid="stElementToolbar"] { display:none; }

  section[data-testid="stSidebar"] { background:#ffffff; border-right:1px solid #d0d7e2; }
  section[data-testid="stSidebar"] .block-container { padding-top:1rem; }
  section[data-testid="stSidebar"] div[role="radiogroup"] { gap:3px; }
  section[data-testid="stSidebar"] div[role="radiogroup"] > label {
      padding:9px 11px; border-radius:6px; margin:0; width:100%; border:1px solid transparent; font-size:0.86rem; }
  section[data-testid="stSidebar"] div[role="radiogroup"] > label:hover { background:#f1f5fb; }
  section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {
      background:#e6effc; border-color:#c5dcf7; color:#1d4ed8; font-weight:600; }

  /* 주요 블록 = 흰색 카드 (st.container(border=True) — Streamlit 기본 스타일을 이기도록 !important) */
  div[data-testid="stVerticalBlockBorderWrapper"] {
      background:#ffffff !important;
      border:1.5px solid #94a3b8 !important;
      border-radius:12px !important;
      box-shadow:0 3px 10px rgba(15,23,42,0.12) !important;
  }
  /* 카드 내부 컨텐츠 영역도 흰색 + 충분한 padding (배경색이 비치지 않도록) */
  div[data-testid="stVerticalBlockBorderWrapper"] > div {
      padding:16px 18px !important;
      background:#ffffff !important;
      border-radius:12px !important;
  }

  div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalBlock"] {
      background:#ffffff !important;
  }

  /* === 카드 색상은 key 기반 class(.st-key-*)로 확실히 적용 (data-testid 선택자는 보조) === */
  .st-key-filter_card,
  .st-key-selected_wafer_card,
  .st-key-wafer_table_card,
  .st-key-summary_card,
  .st-key-sensor_chip_card,
  .st-key-sensor_result_card,
  .st-key-review_table_card,
  .st-key-review_input_card,
  .st-key-page1_header,
  .st-key-p2_header,
  .st-key-check_guide_card,
  .st-key-page_header {
      background-color: #ffffff !important;
      border: 1.5px solid #94a3b8 !important;
      border-radius: 12px !important;
      box-shadow: 0 3px 10px rgba(15,23,42,0.12) !important;
      padding: 22px 26px !important;
      margin-bottom: 18px !important;
  }
  .st-key-page_header { min-height: 110px !important; padding: 18px 24px !important; margin-bottom: 14px !important; }
  .st-key-sensor_chart_card,
  .st-key-sensor_result_card,
  .st-key-sensor_chip_card,
  .st-key-check_guide_card { margin-bottom: 10px !important; }

  /* 차트 카드: 패딩 최소화 + 내부 여백 제거 */
  .st-key-chart_card,
  .st-key-sensor_chart_card {
      background-color: #ffffff !important;
      border: 1.5px solid #94a3b8 !important;
      border-radius: 12px !important;
      box-shadow: 0 3px 10px rgba(15,23,42,0.12) !important;
      padding: 10px 12px 4px 12px !important;
      margin-bottom: 18px !important;
  }
  .st-key-chart_card > div,
  .st-key-sensor_chart_card > div { gap: 0 !important; }
  .st-key-chart_card [data-testid="stPlotlyChart"],
  .st-key-sensor_chart_card [data-testid="stPlotlyChart"] {
      margin-bottom: 0 !important; padding-bottom: 0 !important;
  }
  .st-key-chart_card [data-testid="stPlotlyChart"] > div,
  .st-key-sensor_chart_card [data-testid="stPlotlyChart"] > div {
      margin-bottom: 0 !important; padding-bottom: 0 !important;
  }
  .st-key-chart_card iframe,
  .st-key-sensor_chart_card iframe { display: block; margin-bottom: 0 !important; }

  /* Page 2: 센서 차트 카드 ↔ 센서 점검 해석 카드 높이 균형 */
  .st-key-sensor_chart_card,
  .st-key-sensor_result_card {
      min-height: 390px !important;
      box-sizing: border-box !important;
  }
  .st-key-sensor_chart_card > div,
  .st-key-sensor_result_card > div { box-sizing: border-box !important; }
  .st-key-sensor_result_card { padding: 18px 22px !important; }

  /* Page 2 lower row: related-sensor card ↔ guide card height matching */
  .st-key-sensor_chip_card,
  .st-key-check_guide_card {
      min-height: 150px !important;
      box-sizing: border-box !important;
  }
  .st-key-sensor_chip_card > div,
  .st-key-check_guide_card > div { box-sizing: border-box !important; }

  /* Page 1 lower row: wafer list card height — left only, do not shrink .sumcard */
  .st-key-wafer_table_card {
      min-height: 430px !important;
      box-sizing: border-box !important;
  }
  .st-key-wafer_table_card > div { box-sizing: border-box !important; }

  /* 카드 내부 자식은 배경 투명 → 카드 흰색이 그대로 비치도록 */
  .st-key-filter_card *,
  .st-key-selected_wafer_card *,
  .st-key-wafer_table_card *,
  .st-key-chart_card *,
  .st-key-sensor_chart_card *,
  .st-key-summary_card *,
  .st-key-sensor_chip_card *,
  .st-key-sensor_result_card *,
  .st-key-review_table_card *,
  .st-key-review_input_card *,
  .st-key-page1_header *,
  .st-key-p2_header *,
  .st-key-check_guide_card *,
  .st-key-page_header * {
      background-color: transparent;
  }

  /* 헤더 이미지 아이콘 */
  .header-icon-wrap img { border-radius:18px; box-shadow:0 4px 14px rgba(15,23,42,0.18); }
  .main-title-wrap { display:flex; flex-direction:column; justify-content:center; min-height:88px; }
  .main-title { font-size:2.1rem; font-weight:900; color:#0f172a; line-height:1.15; margin:0; }
  .main-subtitle { font-size:1.05rem; color:#64748b; margin-top:8px; margin-bottom:0; }
  /* === 전 페이지 공통 헤더 클래스 === */
  .unified-header-text {
    display:flex;
    flex-direction:column;
    justify-content:center;
    align-items:flex-start;
    text-align:left;
    min-height:100px;
    padding-top:15px;
    box-sizing:border-box;}
  .unified-header-title { font-size:2.1rem; font-weight:900; color:#0f172a; line-height:1.15;
      margin:0; text-align:left; }
  .unified-header-subtitle { font-size:1.05rem; color:#64748b; margin-top:8px; margin-bottom:0;
      text-align:left; }
  .unified-header-icon { width:64px; height:64px; border-radius:18px; flex:0 0 auto; color:#fff;
      background:linear-gradient(135deg,#1d4ed8,#1e3a8a); font-size:2rem;
      display:flex; align-items:center; justify-content:center;
      box-shadow:0 4px 12px rgba(29,78,216,0.50); }

  /* === 이미지형 헤더 / KPI / 요약 카드 (신규 표시 컴포넌트) === */
  .hdr-id { display:flex; align-items:center; gap:22px; }
  .hdr-id .logo { width:68px; height:68px; border-radius:18px; flex:0 0 auto; color:#fff !important;
      background:linear-gradient(135deg,#1d4ed8,#1e3a8a) !important; font-size:2.2rem;
      display:flex; align-items:center; justify-content:center;
      box-shadow:0 4px 12px rgba(29,78,216,0.50); }
  .hdr-id .t-title { font-size:1.85rem; font-weight:900; color:#0f172a; line-height:1.2; }
  .hdr-id .t-sub { font-size:1.02rem; color:#64748b; margin-top:3px; }

  .topbar { display:flex; align-items:center; gap:13px; background:#ffffff; border:1.5px solid #94a3b8;
      border-radius:14px; padding:11px 18px; box-shadow:0 3px 10px rgba(15,23,42,0.10); margin-bottom:6px; }
  .topbar .logo { width:38px; height:38px; border-radius:10px; flex:0 0 auto; color:#fff;
      background:linear-gradient(135deg,#2563eb,#1e40af); font-size:1.2rem;
      display:flex; align-items:center; justify-content:center; box-shadow:0 2px 6px rgba(37,99,235,0.40); }
  .topbar .t-title { font-size:1.06rem; font-weight:800; color:#0f172a; }
  .topbar .t-sub { font-size:0.72rem; color:#64748b; }

  /* === 사이드바 브랜드 카드 === */
  .st-key-sidebar_brand_card {
      background: #ffffff !important;
      border: 1.5px solid #d0d7e2 !important;
      border-radius: 16px !important;
      padding: 0 !important;
      margin: 0 0 18px 0 !important;
      text-align: center;
  }
  .st-key-sidebar_brand_card > div {
      padding: 16px 14px !important;
      text-align: center !important;
      background: #ffffff !important;
      border-radius: 16px !important;
  }
  .st-key-sidebar_brand_card [data-testid="stImage"] {
      text-align: center !important;
  }
  .st-key-sidebar_brand_card [data-testid="stImage"] img {
      display: inline-block !important;
      margin: 0 auto !important;
  }
  .st-key-sidebar_brand_card [data-testid="stMarkdownContainer"] {
      text-align: center !important;
  }
  .sidebar-brand-title { font-size:1.05rem; font-weight:800; color:#0f172a; line-height:1.2; }
  .sidebar-brand-subtitle { font-size:0.78rem; color:#64748b; margin-top:6px; }

  .kpi { background:#ffffff; border:1.5px solid #94a3b8; border-radius:14px; padding:16px 18px;
      box-shadow:0 3px 10px rgba(15,23,42,0.12); height:100%; }
  .kpi-top { display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }
  .kpi-label { font-size:0.80rem; color:#64748b; font-weight:700; }
  .kpi-big { font-size:2.15rem; font-weight:800; color:#0f172a; line-height:1.1; margin-top:2px; }
  .kpi-unit { font-size:1.0rem; font-weight:700; color:#2563eb; margin-left:2px; }
  .kpi-spark { padding-top:8px; }
  .kpi-sub { font-size:0.78rem; color:#475467; margin-top:8px; }
  .kpi-foot { display:flex; align-items:center; gap:8px; margin-top:12px; padding-top:10px; flex-wrap:wrap;
      border-top:1px dashed #e2e8f0; font-size:0.80rem; }
  .kpi-foot-l { color:#64748b; font-weight:700; }
  .kpi-wid { font-weight:800; color:#0f172a; }

  /* 상단 KPI 4종 (이미지형 카드 그리드) */
  .kpi-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:2px; }
  .kpi2 { background:#ffffff; border:1.5px solid #94a3b8; border-radius:14px; padding:15px 18px;
      box-shadow:0 3px 10px rgba(15,23,42,0.12); }
  .kpi2 .k2-label { font-size:0.74rem; color:#64748b; font-weight:700; }
  .kpi2 .k2-val { font-size:1.7rem; font-weight:800; color:#2563eb; line-height:1.15; margin-top:6px;
      white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .kpi2 .k2-sub { font-size:0.76rem; color:#64748b; margin-top:6px; }
  /* 이상 예측 원인 카드 동적 색상은 inline style 로 처리 — 별도 클래스 불필요 */
  @media (max-width:1100px) { .kpi-grid { grid-template-columns:repeat(2,1fr); } }

  .sumcard { background:#ffffff; border:1.5px solid #94a3b8; border-radius:14px; padding:16px 18px;
      box-shadow:0 3px 10px rgba(15,23,42,0.12); }
  .sum-row { display:flex; justify-content:space-between; align-items:center; gap:10px;
      padding:6px 0; font-size:0.84rem; border-bottom:1px solid #f1f5f9; }
  .sum-row:last-child { border-bottom:none; }
  .sum-k { color:#64748b; } .sum-v { color:#0f172a; font-weight:600; text-align:right; }
  .sum-sep { height:1px; background:#cbd5e1; margin:7px 0; }

  .appbar { display:flex; align-items:baseline; gap:12px; background:linear-gradient(90deg,#1e293b,#334155);
            color:#e2e8f0; padding:9px 16px; border-radius:9px; margin:0 0 8px 0; }
  .appbar .a-title { font-size:1.0rem; font-weight:700; color:#fff; }
  .appbar .a-sub { font-size:0.74rem; color:#9fb0c4; }
  .page-title { font-size:1.40rem; font-weight:800; color:#101828; margin:2px 0 8px 0; }

  /* 카드 제목 영역 */
  .sec-title { font-size:1.15rem; font-weight:800; color:#111827; margin-bottom:10px; }
  .oneline { font-size:0.81rem; color:#64748b; margin:-2px 0 10px 1px; }

  /* 선택 wafer 요약 패널 */
  .wpanel { background:#fff; border:1.5px solid #94a3b8; border-left:5px solid #94a3b8; border-radius:12px;
            padding:18px 20px; box-shadow:0 3px 10px rgba(15,23,42,0.12); }
  .wpanel.red { border-left-color:#d92d20; } .wpanel.amber { border-left-color:#f59e0b; }
  .wpanel.blue { border-left-color:#2563eb; } .wpanel.gray { border-left-color:#94a3b8; }
  .wpanel.green { border-left-color:#1a9e54; }
  .wpanel .w-head { display:flex; align-items:center; gap:12px; margin-bottom:10px; }
  .wpanel .w-id { font-size:1.32rem; font-weight:800; color:#101828; }
  .wpanel .w-grid { display:flex; flex-wrap:wrap; gap:6px 30px; font-size:0.87rem; color:#475467; }
  .wpanel .w-grid b { color:#101828; font-weight:700; }
  .wpanel .w-rec { margin-top:10px; font-size:0.85rem; color:#475467; background:#f4f7fb;
                   border-radius:6px; padding:8px 12px; }

  .bdg-lg { display:inline-block; padding:3px 14px; border-radius:7px; font-size:0.88rem; font-weight:700; }
  .bdg-lg.red { background:#fee4e2; color:#b42318; } .bdg-lg.amber { background:#fef0c7; color:#b54708; }
  .bdg-lg.blue { background:#e6effc; color:#1d4ed8; } .bdg-lg.gray { background:#eef2f6; color:#475467; }
  .bdg-lg.green { background:#e7f4ec; color:#1a7f37; }

  .bdg { display:inline-block; padding:1px 9px; border-radius:6px; font-size:0.73rem; font-weight:600; white-space:nowrap; }
  .bdg.red { background:#fee4e2; color:#b42318; border:1px solid #fecdca; }
  .bdg.amber { background:#fef0c7; color:#b54708; border:1px solid #fedf89; }
  .bdg.blue { background:#e6effc; color:#1d4ed8; border:1px solid #c5dcf7; }
  .bdg.gray { background:#eef2f6; color:#475467; border:1px solid #dde3ea; }
  .bdg.green { background:#e7f4ec; color:#1a7f37; border:1px solid #cce8d6; }
  .bdg.wait { background:#f2f4f7; color:#98a2b3; border:1px solid #e4e7ec; }
  .pill { display:inline-block; padding:2px 10px; border-radius:12px; font-size:0.74rem;
          background:#eef2f6; color:#1f4a73; border:1px solid #d6e1ee; margin:2px 5px 2px 0; white-space:nowrap; }
  /* 센서 이동 버튼 — pill 스타일 */
  div[data-testid="stButton"].sensor-nav-btn > button {
      background:#e0f0ff; color:#1e3a8a; border:1.5px solid #93c5fd;
      border-radius:18px; font-size:0.80rem; font-weight:600;
      padding:3px 14px; min-height:28px; }
  div[data-testid="stButton"].sensor-nav-btn > button:hover {
      background:#bfdbfe; border-color:#3b82f6; color:#1e3a8a; }

  table.mon { width:100%; border-collapse:collapse; font-size:0.82rem; }
  table.mon thead th { background:#93c5fd; color:#0f172a; font-weight:700; text-align:left;
                       padding:7px 11px; border-bottom:1px solid #60a5fa; position:sticky; top:0; }
  table.mon tbody td { padding:7px 11px; border-bottom:1px solid #cbd5e1; color:#1f2937; }
  table.mon tbody tr:nth-child(odd) { background:#ffffff; }
  table.mon tbody tr:nth-child(even) { background:#f1f5f9; }
  table.mon tbody tr.st-red td:first-child   { box-shadow: inset 4px 0 0 #dc2626; } /* 긴급 점검 */
  table.mon tbody tr.st-amber td:first-child { box-shadow: inset 4px 0 0 #f59e0b; } /* 주의 점검 */
  table.mon tbody tr.st-green td:first-child { box-shadow: inset 4px 0 0 #16a34a; } /* 관찰 */
  table.mon tbody tr.st-blue td:first-child  { box-shadow: inset 4px 0 0 #2563eb; } /* 정상 */
  table.mon tbody tr:hover { background:#eff6ff; }
  table.mon tbody tr.sel { background:#dbeafe !important; }
  table.mon td.wid { font-weight:700; color:#101828; }
  table.mon td.memo { color:#667085; max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .tbl-wrap { max-height:380px; overflow-y:auto; background:#ffffff; border:1.5px solid #64748b;
             border-radius:10px; box-shadow:0 3px 10px rgba(15,23,42,0.12); }

  .gcard .g-h { font-size:1.02rem; font-weight:800; color:#111827; margin:12px 0 6px 0; }
  .gcard .g-h:first-child { margin-top:0; }
  .gcard ul, .gcard ol { margin:2px 0 0 0; padding-left:18px; font-size:0.83rem; color:#344054; line-height:1.6; }
  .gcard .tiny { color:#98a2b3; font-size:0.74rem; margin-top:8px; }
  .gcard .muted { color:#98a2b3; font-size:0.82rem; }
  .mini { background:#fff; border:1.5px solid #94a3b8; border-radius:12px; padding:16px 18px;
          box-shadow:0 3px 10px rgba(15,23,42,0.12); }
  .mini .m-l { font-size:0.72rem; color:#667085; } .mini .m-v { font-size:1.2rem; font-weight:700; color:#101828; }
  /* 입력창 / selectbox — 카드 안에서 묻히지 않게 */
  .stSelectbox label, .stTextInput label, .stToggle label {
      color:#1f2937 !important; font-weight:700 !important; }
  div[data-testid="stMain"] .stTextInput div[data-baseweb="input"],
  div[data-testid="stMain"] div[data-baseweb="select"] > div {
      background:#f8fafc !important; border-color:#cbd5e1 !important; }
  div[data-testid="stMain"] .stTextInput input { color:#111827 !important; }
  div[data-testid="stForm"] { border:none; padding:0; }
/* 1페이지: Q 차트 카드 / 점검 해석 카드 높이 맞춤 */
.st-key-chart_card,
.st-key-selected_wafer_card {
    min-height: 500px !important;
    box-sizing: border-box !important;
}

/* 내부 wrapper에는 높이를 주지 말고 여백만 정리 */
.st-key-chart_card > div,
.st-key-selected_wafer_card > div {
    box-sizing: border-box !important;
}

/* Q 차트 제목만 크게 */
.q-chart-title {
    font-size: 1.35rem;
    font-weight: 900;
    color: #111827;
    line-height: 1.25;
    margin-bottom: 8px;
}
.st-key-sensor_chip_card {
    min-height: 165px !important;
    box-sizing: border-box !important;
}
/* 1페이지 확인 상태 · 메모 입력 저장 버튼: 평시에도 빨간색 */
.st-key-review_input_card div[data-testid="stFormSubmitButton"] button {
    background-color: #ef4444 !important;
    color: #ffffff !important;
    border: 1.5px solid #ef4444 !important;
    border-radius: 10px !important;
    font-weight: 800 !important;
    min-height: 42px !important;
    padding: 0 18px !important;
}

/* hover 상태 */
.st-key-review_input_card div[data-testid="stFormSubmitButton"] button:hover {
    background-color: #dc2626 !important;
    color: #ffffff !important;
    border-color: #dc2626 !important;
}

/* 클릭/포커스 상태 */
.st-key-review_input_card div[data-testid="stFormSubmitButton"] button:focus,
.st-key-review_input_card div[data-testid="stFormSubmitButton"] button:active {
    background-color: #b91c1c !important;
    color: #ffffff !important;
    border-color: #b91c1c !important;
    box-shadow: none !important;
}

/* 3페이지: 선택 wafer 조치 내용 입력 영역 — 흰색 카드 통일 */
.st-key-review_input_section {
    background: #ffffff !important;
    border: 1.5px solid #94a3b8 !important;
    border-radius: 14px !important;
    box-shadow: 0 3px 10px rgba(15,23,42,0.12) !important;
    box-sizing: border-box !important;
    padding: 16px 18px !important;
}
.st-key-review_input_section details,
.st-key-review_input_section div[data-testid="stExpander"] {
    background: #ffffff !important;
}
.st-key-review_input_section * { background-color: transparent; }

/* 전역: 모든 form 저장 버튼 — 평시에도 빨간색 (page 1 · page 3 공통) */
div[data-testid="stFormSubmitButton"] button,
button[data-testid="stBaseButton-primaryFormSubmit"] {
    background: #ef4444 !important;
    background-color: #ef4444 !important;
    color: #ffffff !important;
    border: 1.5px solid #ef4444 !important;
    border-radius: 10px !important;
    font-weight: 800 !important;
    min-height: 42px !important;
    padding: 0 18px !important;
}

div[data-testid="stFormSubmitButton"] button:hover,
button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
    background: #dc2626 !important;
    background-color: #dc2626 !important;
    color: #ffffff !important;
    border-color: #dc2626 !important;
}

div[data-testid="stFormSubmitButton"] button:focus,
div[data-testid="stFormSubmitButton"] button:active,
button[data-testid="stBaseButton-primaryFormSubmit"]:focus,
button[data-testid="stBaseButton-primaryFormSubmit"]:active {
    background: #b91c1c !important;
    background-color: #b91c1c !important;
    color: #ffffff !important;
    border-color: #b91c1c !important;
    box-shadow: none !important;
}

div[data-testid="stFormSubmitButton"] button *,
button[data-testid="stBaseButton-primaryFormSubmit"] * {
    color: #ffffff !important;
}
</style>
""", unsafe_allow_html=True)

# --------------------------- 데이터 로드 (기존 로직 그대로) ---------------------------
q, det, fdc = load_data()
all_ids = sorted(q["wafer_id"].unique().tolist())
n_total = len(all_ids)
fdc_map = fdc.set_index("wafer_id").to_dict("index")
det_map = det.set_index("wafer_id").to_dict("index")
detected_ids = sorted(det.loc[det["detected"], "wafer_id"].tolist()) if "detected" in det.columns else []
genuine_ids = [w for w in detected_ids if w in fdc_map]
nonspecific_ids = [w for w in detected_ids if w not in fdc_map]
n_detect, n_genuine, n_nonspecific = len(detected_ids), len(genuine_ids), len(nonspecific_ids)
normal_ids = [w for w in all_ids if w not in detected_ids]
ratio_max = (q.assign(_r=q["Q_score"] / q["Q_threshold"]).groupby("wafer_id")["_r"].max().to_dict())
review = load_review()

STAGE_RANK = {"긴급 점검": 0, "주의 점검": 1, "관찰": 2, "정상": 3, "완료": 4}


def wafer_stage(wid):
    """(점검 단계, 정렬순위, 색상cls). 완료=review완료 / 정상=미감지 / 그 외 기존 비율 라벨 매핑.
    색상cls: red=긴급점검 / amber=주의점검 / green=관찰·완료 / blue=정상"""
    if review.get(wid, {}).get("status") == "완료":
        return ("완료", 4, "blue")
    if wid not in detected_ids:
        return ("정상", 3, "blue")   # 정상 → 파란색
    p = priority_label(ratio_max.get(wid))
    if p == "긴급":
        return ("긴급 점검", 0, "red")
    if p == "위험":
        return ("주의 점검", 1, "amber")
    return ("관찰", 2, "green")     # 관찰 → 초록색


def wfields(wid):
    fi = fdc_map.get(wid)
    if fi:
        return (str(fi.get("top_sensor", "")).strip() or "센서 미특정",
                str(fi.get("suspected_family", "")).strip())
    return ("센서 미특정", "")


def rev_cls(status):
    return {"미확인": "wait", "확인 중": "amber", "완료": "green"}.get(status, "wait")


# 같이 점검할 센서 — 실제 raw 컬럼(block,col) 기준 (2페이지에서 클릭 가능하도록)
RELATED_REAL = {
    "rf":       [("EV", "RF Load"), ("EV", "RF Pwr"), ("EV", "RF Btm Pwr"), ("EV", "RF Btm Rfl Pwr"), ("EV", "TCP Load")],
    "matching": [("EV", "RF Load"), ("EV", "RF Pwr"), ("EV", "RF Btm Pwr"), ("EV", "RF Btm Rfl Pwr"), ("EV", "TCP Load")],
    "tcp":      [("EV", "TCP Top Pwr"), ("EV", "TCP Rfl Pwr"), ("EV", "TCP Load"), ("EV", "RF Load"), ("EV", "RF Pwr")],
    "gas":      [("EV", "BCl3 Flow"), ("EV", "Cl2 Flow"), ("EV", "RF Load")],
    "pressure": [("EV", "Pressure"), ("EV", "Vat Valve"), ("EV", "RF Load")],
    "he":       [("EV", "He Press"), ("EV", "Pressure")],
    "oes":      [],
    "generic":  [("EV", "RF Load"), ("EV", "Pressure"), ("EV", "BCl3 Flow")],
}


def related_real_sensors(wid):
    """(block, column) 실제 존재하는 센서 목록. 첫 항목은 우선 점검 센서(top_sensor)."""
    out, fk = [], "generic"
    fi = fdc_map.get(wid)
    if fi:
        tb, ts = str(fi.get("top_block", "")).strip(), str(fi.get("top_sensor", "")).strip()
        if tb in RAW_FILES and ts:
            out.append((tb, ts))
        fk = family_key(fi.get("suspected_family", ""))
    for blk, col in RELATED_REAL.get(fk, RELATED_REAL["generic"]):
        if (blk, col) not in out:
            out.append((blk, col))
    valid = []
    for blk, col in out:
        try:
            if col in load_raw_block(blk).columns:
                valid.append((blk, col))
        except Exception:
            pass
    return valid[:6]


_MANUAL_TEXT = {
    "rf": ("RF 계열", [
        "RF Power 공급값과 실제 출력값이 일치하는지 확인",
        "RF Load / RF Bias Power 변동 여부 확인",
        "RF Reflected Power가 증가했는지 확인",
        "RF Generator 상태 로그와 알람 이력 확인",
        "반복 발생 시 RF Matching 계열과 함께 점검",
    ]),
    "tcp": ("TCP 계열", [
        "TCP Source Power 출력 안정성 확인",
        "TCP Load / TCP Tuner 위치 변화 확인",
        "TCP Reflected Power 상승 여부 확인",
        "TCP Phase Error 또는 Impedance 변동 확인",
        "반복 발생 시 RF/TCP Matching 상태를 함께 점검",
    ]),
    "matching": ("RF/TCP Matching 계열", [
        "Impedance 변동 여부 확인",
        "Phase Error가 튀는 구간 확인",
        "Reflected Power 상승 여부 확인",
        "RF Load, TCP Load가 같은 구간에서 흔들리는지 확인",
        "Matching network 또는 tuner 상태 로그 확인",
    ]),
    "gas": ("Gas 공급 계열", [
        "BCl3 / Cl2 유량 setpoint와 실제 flow 비교",
        "MFC 응답 지연 또는 순간 흔들림 확인",
        "Gas 공급 압력과 valve 상태 확인",
        "같은 Lot 내 인접 wafer에서도 같은 flow 패턴이 반복되는지 확인",
        "반복 발생 시 gas line, MFC, recipe 조건 변경 이력 확인",
    ]),
    "pressure": ("Pressure / 제어 계열", [
        "Chamber Pressure 안정성 확인",
        "Vat Valve Position 변동 여부 확인",
        "Pressure 제어 응답 지연 여부 확인",
        "Gas flow 변화와 pressure 변화가 같은 구간에서 발생했는지 확인",
        "반복 발생 시 throttle valve / pressure control loop 상태 확인",
    ]),
    "he": ("He Chuck 계열", [
        "Backside He Pressure 변동 여부 확인",
        "Wafer chucking 상태 확인",
        "He leak 또는 pressure drop 여부 확인",
        "ESC / chuck 관련 장비 로그 확인",
        "반복 발생 시 wafer contact 상태와 thermal 안정성 확인",
    ]),
    "oes": ("OES / 플라즈마 반응 계열", [
        "해당 파장 intensity가 정상 wafer 대비 상승/저하했는지 확인",
        "Endpoint 신호 변화 구간 확인",
        "Gas flow, RF/TCP power 변화와 같은 구간에서 발생했는지 확인",
        "Plasma 안정성 관련 알람 또는 recipe step 변경 여부 확인",
        "반복 발생 시 chamber condition 또는 plasma 상태 점검",
    ]),
    "generic": ("장비 조건 일반", [
        "선택 wafer의 이상 신호 발생 구간과 센서 변화 구간 비교",
        "동일 Lot / 인접 wafer에서도 같은 패턴이 있는지 확인",
        "장비 로그와 recipe 변경 이력 확인",
        "RF/TCP, gas, pressure, He Chuck 순서로 확대 점검",
        "반복 발생 시 해당 공정 step의 장비 상태 점검",
    ]),
}

_SENSOR_TO_FAMILY = {
    "RF Load": "rf", "RF Pwr": "rf", "RF Btm Pwr": "rf",
    "RF Btm Rfl Pwr": "rf", "RF Bias": "rf", "RF Generator": "rf",
    "TCP Load": "tcp", "TCP Top Pwr": "tcp", "TCP Tuner": "tcp",
    "TCP Rfl Pwr": "tcp", "TCP Source": "tcp", "TCP Phase": "tcp",
    "S3I2": "matching", "S1I3": "matching", "S312": "matching",
    "Impedance": "matching", "Phase Error": "matching",
    "Reflected Power": "matching", "Rfl Pwr": "matching", "Matching": "matching",
    "BCl3 Flow": "gas", "Cl2 Flow": "gas", "MFC": "gas",
    "Pressure": "pressure", "Vat Valve": "pressure",
    "Throttle": "pressure", "Valve": "pressure",
    "He Press": "he", "Backside He": "he", "Chuck": "he", "ESC": "he",
    "OES": "oes", "Endpt A": "oes", "Endpoint": "oes",
}


def _fk_to_label(fk):
    return _MANUAL_TEXT.get(fk, _MANUAL_TEXT["generic"])[0]


def classify_sensor_family_for_manual(sensor_name, top_block=""):
    """센서 이름 → 표시용 계열 레이블 (매뉴얼 라우팅 전용, FDC 재계산 없음)."""
    sn = str(sensor_name).strip()
    if top_block == "OES" or any(k in sn for k in ("OES", "Endpt A", "Endpoint", "intensity")):
        return "oes"
    for kw, mapped in _SENSOR_TO_FAMILY.items():
        if kw.lower() in sn.lower():
            return mapped
    # 파장 패턴 (예: 644.9, 643.2) → OES
    import re
    if re.search(r"\d{3}\.\d", sn):
        return "oes"
    return "generic"


def field_action_manual_items(wid, selected_sensor="", selected_block=""):
    """현장 조치 매뉴얼 카테고리와 항목 반환.

    반환: (fdc_label, sensor_label, manual_label, items)
    - fdc_label: FDC/Contribution 기반 계열 (항상 표시)
    - sensor_label: 현재 선택 센서 기반 계열
    - manual_label: 실제 매뉴얼 표시 계열 (센서 기반 우선, fallback → FDC)
    - items: 5개 조치 항목 리스트
    확정 원인이 아니라 도메인 기반 점검 우선순서."""
    fi = fdc_map.get(wid, {})
    top_sensor = str(fi.get("top_sensor", "")).strip()
    top_block = str(fi.get("top_block", "")).strip()
    suspected = str(fi.get("suspected_family", "")).strip()

    # FDC 기반 계열 (항상 유지)
    fk_fdc = family_key(suspected) if suspected else "generic"
    if top_block == "OES":
        fk_fdc = "oes"
    if fk_fdc == "generic" and top_sensor:
        for kw, mapped in _SENSOR_TO_FAMILY.items():
            if kw.lower() in top_sensor.lower():
                fk_fdc = mapped
                break
    fdc_label = _fk_to_label(fk_fdc)

    # 현재 선택 센서 기반 계열
    fk_sensor = classify_sensor_family_for_manual(selected_sensor, selected_block)
    sensor_label = _fk_to_label(fk_sensor)

    # 매뉴얼 표시 계열: 선택 센서가 specific하면 우선, 아니면 FDC 기반
    fk_manual = fk_sensor if fk_sensor != "generic" else fk_fdc
    manual_label, items = _MANUAL_TEXT.get(fk_manual, _MANUAL_TEXT["generic"])

    return fdc_label, sensor_label, manual_label, items


PAGES = ["1. 공정 이상 감지 현황", "2. 센서 점검 화면", "3. 조치 기록 공유"]

# 세션 상태 초기화 — selected_wafer 는 위젯 키와 분리된 앱 상태 전용 변수
if "selected_wafer" not in st.session_state:
    _init_cands = sorted(detected_ids, key=lambda w: (wafer_stage(w)[1], -(ratio_max.get(w) or 0), w))
    st.session_state["selected_wafer"] = (
        _init_cands[0] if _init_cands else (all_ids[0] if all_ids else None)
    )
if "active_page" not in st.session_state:
    st.session_state["active_page"] = PAGES[0]

# pending 네비게이션 처리 (버튼 클릭 → st.rerun() 시 이 블록에서 적용)
# page_radio_widget 도 함께 pre-set → radio 가 index= 없이 세션값만 참조하도록
if "pending_page" in st.session_state:
    _pp = st.session_state.pop("pending_page")
    if _pp in PAGES:
        st.session_state["active_page"] = _pp
        st.session_state["page_radio_widget"] = _pp  # widget pre-set (index= 없으므로 경고 없음)
if "pending_wafer" in st.session_state:
    _pw = st.session_state.pop("pending_wafer")
    if _pw in set(all_ids):
        st.session_state["selected_wafer"] = _pw
if "pending_block" in st.session_state:
    st.session_state["sv_block"] = st.session_state.pop("pending_block")
if "pending_sensor" in st.session_state:
    st.session_state["sv_sensor"] = st.session_state.pop("pending_sensor")

# page_radio_widget 미초기화 시 active_page 와 동기화
if "page_radio_widget" not in st.session_state:
    st.session_state["page_radio_widget"] = st.session_state["active_page"]

with st.sidebar:
    _char_img = first_character_image()

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

    if _char_img:
        try:
            _l, _m, _r = st.columns([1, 2, 1])
            with _m:
                st.image(_char_img, width=80)
        except Exception:
            st.markdown("<div style='font-size:2rem;text-align:center'>🔧</div>", unsafe_allow_html=True)
    else:
        st.markdown("<div style='font-size:2rem;text-align:center'>🔧</div>", unsafe_allow_html=True)

    st.markdown(
    """
    <div style="
        width:100%;
        text-align:center;
        margin-top:8px;
        margin-bottom:22px;
    ">
        <div style="
            font-size:1.05rem;
            font-weight:800;
            color:#0f172a;
            line-height:1.2;
            text-align:center;
        ">
            FDC 모니터링
        </div>
        <div style="
            font-size:0.78rem;
            color:#64748b;
            margin-top:6px;
            text-align:center;
        ">
            금속 식각 공정 · 현장 점검
        </div>
    </div>
    """,
    unsafe_allow_html=True
)

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    # index= 제거 — 세션 상태(page_radio_widget)만으로 선택값을 제어해 경고 방지
    page = st.radio("화면", PAGES, key="page_radio_widget", label_visibility="collapsed")
    st.session_state["active_page"] = page

def fmt_wafer(wid):
    cls = wafer_stage(wid)[2]
    sym = {"red": "🔴", "amber": "🟠", "green": "🟢", "blue": "🔵"}.get(cls, "·")
    return f"{sym} {wid}"


def filtered_ids():
    flt = st.session_state.get("wf_filter", "전체")
    bflt = st.session_state.get("batch_filter", "전체 Batch")
    ids = list(all_ids)
    if flt in STAGE_RANK:
        ids = [w for w in ids if wafer_stage(w)[0] == flt]
    if bflt != "전체 Batch":
        try:
            b_num = int(bflt.replace("Batch_", ""))
            ids = [w for w in ids if batch_of(w) == b_num]
        except ValueError:
            pass
    return sorted(ids, key=lambda w: (wafer_stage(w)[1], -(ratio_max.get(w) or 0), w))


def body_wafer_selector():
    """본문 상단 wafer 선택 (점검 상태 필터 + 드롭다운). 전체 wafer 포함 토글 없음 — 기본 전체 표시."""
    with st.container(border=True, key="filter_card"):
        c1, c2 = st.columns([1.3, 3])
        c1.selectbox("점검 상태 필터", ["전체", "긴급 점검", "주의 점검", "관찰", "정상", "완료"], key="wf_filter")
        cand = filtered_ids() or sorted(all_ids)
        cur = st.session_state.get("selected_wafer")
        if cur not in cand:
            if cur in set(all_ids):
                cand = [cur] + cand
            else:
                st.session_state["selected_wafer"] = cand[0] if cand else None
        if st.session_state.get("wafer_table_widget") not in cand:
            st.session_state["wafer_table_widget"] = st.session_state.get("selected_wafer")
        sel = c2.selectbox("점검 wafer 선택", cand, format_func=fmt_wafer, key="wafer_table_widget")
        st.session_state["selected_wafer"] = sel
        return sel


def summary_panel(sel):
    label, _, cls = wafer_stage(sel)
    detected = sel in detected_ids
    sensor, fam = wfields(sel)
    di = det_map.get(sel, {})
    fd = di.get("first_detect_progress")
    if detected and fam:
        ilsa, psens, pfam = segment_with_pct(fd), sensor, family_view(fam)
        pdir = f"{sensor}와 같은 {family_view(fam)} 계열 센서를 우선 확인"
    elif detected:
        ilsa, psens, pfam, pdir = segment_with_pct(fd), "센서 미특정", "장비 조건", "장비 조건 변화 확인"
    else:
        ilsa, psens, pfam, pdir = "이상 없음", "—", "—", "정상 — 별도 확인 불필요"
    st.html(
        f"<div class='wpanel {cls}'>"
        f"<div class='w-head'><span class='w-id'>선택 wafer {sel}</span>"
        f"<span class='bdg-lg {cls}'>{normalize_status_label(label)}</span></div>"
        f"<div class='w-grid'><span>이탈 시작: <b>{ilsa}</b></span>"
        f"<span>점검 센서: <b>{psens}</b></span>"
        f"<span>점검 계열: <b>{pfam}</b></span></div>"
        f"<div class='w-rec'>점검 방향: {pdir}</div></div>"
    )


def ialike_chart(sel):
    """선택 wafer 이상 정도 변화 (y=기존 Q_score / 기준선=기존 Q_threshold, 비율 미사용)."""
    wq = q[q["wafer_id"] == sel].sort_values("progress_pct").reset_index(drop=True)
    prog, qs, th = wq["progress_pct"].tolist(), wq["Q_score"].tolist(), wq["Q_threshold"].tolist()
    exmask = (wq["Q_score"] > wq["Q_threshold"]).tolist()
    fd = det_map.get(sel, {}).get("first_detect_progress")
    fig = go.Figure()
    for s, e in exceed_segments(prog, exmask):
        fig.add_vrect(x0=s - 5, x1=e + 5, fillcolor=C_BAND, line_width=0)
    fig.add_trace(go.Scatter(x=prog, y=qs, name="선택 wafer 이탈 정도", mode="lines+markers",
                             line=dict(color=C_Q, width=3.5), marker=dict(size=7)))
    fig.add_trace(go.Scatter(x=prog, y=th, name="정상 기준선", mode="lines",
                             line=dict(color=C_THR, width=2.4, dash="dash")))
    ex_x = [p for p, m in zip(prog, exmask) if m]
    ex_y = [v for v, m in zip(qs, exmask) if m]
    if ex_x:
        fig.add_trace(go.Scatter(x=ex_x, y=ex_y, name="기준선 초과 지점", mode="markers",
                                 marker=dict(color=C_EXCEED, size=12, line=dict(color="white", width=1.5))))
    if sel in detected_ids and fd is not None and not pd.isna(fd):
        fdv = float(fd)
        fig.add_vline(x=fdv, line=dict(color=C_EXCEED, width=2.0, dash="dot"))
        _xa = "left" if fdv <= 20 else ("right" if fdv >= 90 else "center")
        fig.add_annotation(x=fdv, xref="x", yref="paper", y=0.98, yanchor="top", xanchor=_xa,
                           text=f"이탈 시작 · {segment_name(fdv)}", showarrow=False,
                           font=dict(color=C_EXCEED, size=12), bgcolor="rgba(255,255,255,0.78)")
    fig.update_layout(height=420, margin=dict(l=10, r=12, t=30, b=18),
                      plot_bgcolor="white", paper_bgcolor="white", hovermode="x unified",
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0,
                                  font=dict(size=12), bgcolor="rgba(0,0,0,0)"), font=dict(size=13))
    fig.update_xaxes(title_text="식각 진행률 (%)", tickvals=prog, ticksuffix="%",
                     gridcolor="#eef1f5", showline=True, linecolor="#e4e7ec",
                     title_font=dict(size=15), tickfont=dict(size=13))
    fig.update_yaxes(title_text="이탈 정도", gridcolor="#eef1f5", zeroline=False,
                     title_font=dict(size=15), tickfont=dict(size=13))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def interp_card(sel):
    """점검 해석: 이상 감지 요약 / 점검 우선순서 / 같이 점검할 센서."""
    detected = sel in detected_ids
    sensor, fam = wfields(sel)
    di = det_map.get(sel, {})
    seg = segment_short(di.get("first_detect_progress"))
    cosee = [c for _, c in related_real_sensors(sel)]
    # 카드 상단: 제목(좌) + 캐릭터 이미지(우)
    _ic_title, _ic_img = st.columns([5, 1])
    _ic_title.markdown("<div class='sec-title'>🧭 점검 해석</div>", unsafe_allow_html=True)
    with _ic_img:
        render_character_image("summary")
    if not detected:
        st.html("<div class='gcard'>"
                "<div class='muted'>정상 범위입니다. 별도 확인 항목이 없습니다.</div></div>")
        return
    if fam:
        summ = (f"<ul><li>선택 wafer는 <b>{seg} 구간</b>부터 정상 기준선을 벗어났습니다.</li>"
                f"<li>{sensor}가 이상 신호와 함께 크게 반응했습니다.</li></ul>")
        steps = (f"<ol><li>{sensor} 변화에서 이탈 시작 구간과 같은 시간대에 흔들림이 있는지 확인</li>"
                 f"<li>{sensor}와 같은 {family_view(fam)} 계열 센서도 함께 확인</li>"
                 f"<li>{', '.join(cosee[:5]) if cosee else sensor} 순서로 추가 확인</li></ol>")
    else:
        summ = (f"<ul><li>선택 wafer는 <b>{seg} 구간</b>부터 정상 기준선을 벗어났습니다.</li>"
                "<li>특정 센서가 두드러지게 반응하지는 않았습니다.</li></ul>")
        steps = ("<ol><li>이탈 시작 구간의 센서 흔들림이 있는지 확인</li>"
                 "<li>장비 조건 변화가 있었는지 확인</li>"
                 f"<li>{', '.join(cosee[:5]) if cosee else '관련 계열 센서'} 순서로 추가 확인</li></ol>")
    st.html("<div class='gcard'>"
            "<div class='g-h'>🔎 이상 감지 요약</div>" + summ +
            "<div class='g-h'>🛠️ 점검 우선순서</div>" + steps +
            "<div class='g-h'>🔬 같이 점검할 센서</div>"
            "</div>")
    # 클릭 가능한 센서 버튼 (pending 방식으로 페이지 전환)
    chips_data = related_real_sensors(sel)
    _btn_targets = chips_data if chips_data else []
    if _btn_targets:
        n_per_row = 3
        for _rs in range(0, len(_btn_targets), n_per_row):
            _row = _btn_targets[_rs:_rs + n_per_row]
            _bcols = st.columns(len(_row))
            for _bi, (_blk, _col) in enumerate(_row):
                _lbl = f"⭐ {_col}" if (_rs == 0 and _bi == 0) else _col
                if _bcols[_bi].button(_lbl, key=f"snav_{sel}_{_rs + _bi}_{_col}",
                                      use_container_width=True):
                    st.session_state["pending_page"] = PAGES[1]
                    st.session_state["pending_wafer"] = sel
                    st.session_state["pending_block"] = _blk
                    st.session_state["pending_sensor"] = _col
                    st.rerun()
    else:
        st.html(f"<div><span class='pill'>{sensor}</span></div>")


# ---------------------------------------------------------------------------
# 7. 이미지형 UI 컴포넌트 (신규 — 표시 전용. 계산/판정/데이터 로드는 변경하지 않음)
# ---------------------------------------------------------------------------
def batch_of(wid):
    """표시용 Batch 그룹 = wafer_id // 100 (wafer ID 구간 기반 그룹 — 실제 lot 판정/계산 아님)."""
    return int(wid) // 100


def batch_stats(b):
    """해당 Batch 그룹의 (전체 wafer 수, 이상 감지 wafer 수). 기존 detected 결과만 집계."""
    tot = sum(1 for w in all_ids if batch_of(w) == b)
    det = sum(1 for w in detected_ids if batch_of(w) == b)
    return tot, det


def mark_page1_filter_changed():
    """페이지 1 헤더 필터를 사용자가 직접 변경했을 때 호출되는 콜백."""
    st.session_state["page1_filter_changed"] = True


def render_page_header(title, subtitle, show_filters=False,
                       show_sensor_filters=False, sensor_block_opts=None):
    """전 페이지 공통 헤더 카드 — 캐릭터 이미지 + 제목/부제목 + 페이지별 필터.
    show_sensor_filters=True 시 (block, sensor) 튜플 반환. 그 외 None 반환."""
    _char_img = first_character_image()

    def render_header_identity():
        """1,2,3페이지가 공통으로 쓰는 아이콘 + 제목 + 부제목 영역."""
        _icon_col, _title_col = st.columns([0.48, 2.52])

        with _icon_col:
            if _char_img:
                try:
                    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
                    st.markdown("<div class='header-icon-wrap'>", unsafe_allow_html=True)
                    st.image(_char_img, width=100)
                    st.markdown("</div>", unsafe_allow_html=True)
                except Exception:
                    st.html("<div class='unified-header-icon'>📈</div>")
            else:
                st.html("<div class='unified-header-icon'>📈</div>")

        with _title_col:
            st.markdown(
                f"""
                <div class='unified-header-text'>
                    <div class='unified-header-title'>{title}</div>
                    <div class='unified-header-subtitle'>{subtitle}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

    with st.container(border=True, key="page_header"):
        if show_filters:
            # 1페이지: 왼쪽 제목 영역 + 오른쪽 필터
            _batch_opts = ["전체 Batch"] + [
                f"Batch_{b}" for b in sorted(set(batch_of(w) for w in all_ids))
            ]

            # 총합 6.4 기준: 왼쪽 제목 영역 4.0
            _c_left, _c_f1, _c_f2 = st.columns([4.0, 1.2, 1.2])

            with _c_left:
                render_header_identity()

            _wf_dot = {
                "전체": "#94a3b8",
                "긴급 점검": "#dc2626",
                "주의 점검": "#f59e0b",
                "관찰": "#16a34a",
                "정상": "#2563eb",
                "완료": "#2563eb",
            }.get(st.session_state.get("wf_filter", "전체"), "#94a3b8")

            _FILTER_TOP_GAP = 10

            with _c_f1:
                st.markdown(f"<div style='height:{_FILTER_TOP_GAP}px'></div>", unsafe_allow_html=True)
                st.markdown(
                    f"""
                    <div style='
                        font-size:0.72rem;
                        color:#64748b;
                        font-weight:700;
                        margin-bottom:4px;
                        line-height:1.2;
                        '>
                        <span style='
                            display:inline-block;
                            width:9px;
                            height:9px;
                            border-radius:50%;
                            background:{_wf_dot};
                            vertical-align:middle;
                            margin-right:5px;
                        '></span>
                        점검 상태
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.selectbox(
                    "점검 상태",
                    ["전체", "긴급 점검", "주의 점검", "관찰", "정상", "완료"],
                    key="wf_filter",
                    label_visibility="collapsed",
                    on_change=mark_page1_filter_changed,
                )

            with _c_f2:
                st.markdown(f"<div style='height:{_FILTER_TOP_GAP}px'></div>", unsafe_allow_html=True)
                st.markdown(
                    """
                    <div style='
                        font-size:0.72rem;
                        color:#64748b;
                        font-weight:700;
                        margin-bottom:4px;
                        line-height:1.2;
                    '>
                        Batch 필터
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.selectbox(
                    "Batch 필터",
                    _batch_opts,
                    key="batch_filter",
                    label_visibility="collapsed",
                    on_change=mark_page1_filter_changed,
                )

        elif show_sensor_filters:
            # 2페이지: 왼쪽 제목 + 오른쪽 데이터 구분 / 점검 센서 드롭다운
            _blk_opts = sensor_block_opts or list(RAW_FILES.keys())
            _c_left, _c_f1, _c_f2 = st.columns([4.0, 1.2, 2.0])

            with _c_left:
                render_header_identity()

            with _c_f1:
                st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                _block = st.selectbox("데이터 구분", _blk_opts, key="sv_block",
                                      label_visibility="visible")

            # sv_block 위젯 생성 후, sv_sensor 위젯 생성 전에 sensors 계산 + 사전 보정
            try:
                _raw_for_opts = load_raw_block(_block)
                _sensors = raw_sensor_cols(_raw_for_opts)
            except Exception:
                _sensors = []
            if st.session_state.get("sv_sensor") not in _sensors:
                st.session_state["sv_sensor"] = _sensors[0] if _sensors else None

            with _c_f2:
                st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                _sensor = st.selectbox("점검 센서", _sensors, key="sv_sensor",
                                       label_visibility="visible")

            return _block, _sensor

        else:
            # 3페이지: 왼쪽 제목 영역, 오른쪽 빈 공간
            _c_left, _ = st.columns([4.0, 2.4])

            with _c_left:
                render_header_identity()

    return None


def kpi_row(sel):
    """상단 KPI 4종 (이미지형 카드) — 불량률 / 이상 예측 원인 / 선택 WAFER / 선택 BATCH.
    기존 집계·FDC 해석값만 사용 (새 score/threshold/판정 없음)."""
    label, _, cls = wafer_stage(sel)
    detected = sel in detected_ids
    sensor, fam = wfields(sel)
    if detected and fam:
        cause_v, cause_s = (sensor or "센서 미특정"), family_view(fam)
    elif detected:
        cause_v, cause_s = (sensor or "센서 미특정"), "장비 조건"
    else:
        cause_v, cause_s = "정상", "이상 없음"
    b = batch_of(sel)
    btot, bdet = batch_stats(b)
    cards = [
        ("불량률", f"{n_detect} / {n_total}장", f"이상 감지 {n_detect}장 · 전체 {n_total}장"),
        ("이상 예측 원인", cause_v, cause_s),
        ("선택 WAFER", f"{sel}", f"점검 단계: {normalize_status_label(label)}"),
        ("선택 BATCH", f"Batch_{b}", f"Batch 이상 {bdet}장 / {btot}장"),
    ]
    _slabel = normalize_status_label(label)
    _sc = STATUS_COLOR.get(_slabel, "#2563eb")
    _sb = STATUS_BORDER.get(_slabel, "#94a3b8")
    html = ""
    for lab, val, sub in cards:
        if lab in ("이상 예측 원인", "선택 WAFER"):
            html += (f"<div class='kpi2' style='border-color:{_sb}'>"
                     f"<div class='k2-label'>{lab}</div>"
                     f"<div class='k2-val' style='color:{_sc}'>{val}</div>"
                     f"<div class='k2-sub'>{sub}</div></div>")
        else:
            html += (f"<div class='kpi2'><div class='k2-label'>{lab}</div>"
                     f"<div class='k2-val'>{val}</div><div class='k2-sub'>{sub}</div></div>")
    st.html(f"<div class='kpi-grid'>{html}</div>")


def process_summary_panel(sel):
    """공정 요약 정보 — 선택 wafer 요약 + 전체 집계 (표시용, 계산 변경 없음)."""
    label, _, cls = wafer_stage(sel)
    detected = sel in detected_ids
    sensor, fam = wfields(sel)
    di = det_map.get(sel, {})
    seg = segment_with_pct(di.get("first_detect_progress")) if detected else "이상 없음"
    famv = family_view(fam) if (detected and fam) else ("장비 조건" if detected else "—")
    pdir = check_direction(fam, detected) if detected else "정상 — 별도 확인 불필요"
    ratio = ratio_max.get(sel)
    ratio_s = f"{ratio:.2f}" if (ratio is not None and not pd.isna(ratio)) else "—"
    n_done = sum(1 for w in all_ids if review.get(w, {}).get("status") == "완료")
    rows = [
        ("선택 wafer", f"<b>{sel}</b> &nbsp;<span class='bdg {cls}'>{normalize_status_label(label)}</span>"),
        ("이탈 시작", seg),
        ("점검 센서", sensor if detected else "—"),
        ("점검 계열", famv),
        ("점검 방향", pdir),
        ("__sep__", ""),
        ("전체 wafer", f"{n_total}장"),
        ("이상 감지", f"<b style='color:#b42318'>{n_detect}장</b>"),
        ("우선 점검(FDC)", f"{n_genuine}장"),
        ("처리 완료", f"{n_done}장"),
        ("선택 wafer Q 최대비", ratio_s),
    ]
    body = ""
    for k, v in rows:
        if k == "__sep__":
            body += "<div class='sum-sep'></div>"
        else:
            body += f"<div class='sum-row'><span class='sum-k'>{k}</span><span class='sum-v'>{v}</span></div>"
    st.html(f"<div class='sumcard'><div class='sec-title'>공정 요약 정보</div>{body}</div>")


# ===========================================================================
# 1페이지 : 공정 이상 감지 현황
# ===========================================================================
if page == PAGES[0]:
    # ── 이미지형 상단 헤더(로고+제목) + 점검 상태 필터 ──
    render_page_header("공정 이상 감지 현황", "MPCA 기반 이상 감지 · 금속 식각 공정", show_filters=True)

    # ── 사용자가 필터를 직접 바꾼 경우에만 selected_wafer 동기화 ─────────────
    _cur_filter_sig = (
        st.session_state.get("wf_filter", "전체"),
        st.session_state.get("batch_filter", "전체 Batch"),
    )

    if "prev_page1_filter_sig" not in st.session_state:
        st.session_state["prev_page1_filter_sig"] = _cur_filter_sig

    _cand_after_filter = filtered_ids()
    _filter_changed_by_user = st.session_state.pop("page1_filter_changed", False)

    if _filter_changed_by_user:
        st.session_state["prev_page1_filter_sig"] = _cur_filter_sig
        if _cand_after_filter:
            st.session_state["selected_wafer"] = _cand_after_filter[0]
            st.rerun()

    sel = st.session_state["selected_wafer"]

    # ── 상단 KPI 4종 (이미지형 카드) — 불량률 / 이상 예측 원인 / 선택 WAFER / 선택 BATCH ──
    kpi_row(sel)

    # ── Q statistic 차트(좌) + 선택 wafer 해석 패널(우) ──
    gcol, icol = st.columns([65, 35], gap="small")
    with gcol:
        with st.container(border=True, key="chart_card"):
            sel = st.session_state["selected_wafer"]
            st.markdown("<div class='sec-title'>선택 wafer 공정 이탈 흐름</div>",
                        unsafe_allow_html=True)
            ialike_chart(sel)
    with icol:
        with st.container(border=True, key="selected_wafer_card"):
            interp_card(sel)

    # ── 점검 대상 wafer 목록(좌) + 공정 요약 정보(우) ──
    tcol, scol = st.columns([2.4, 1], gap="small")
    with tcol:
        with st.container(border=True, key="wafer_table_card"):
            st.markdown("<div class='sec-title'>점검 대상 wafer 목록</div>", unsafe_allow_html=True)
            st.markdown(
                f"<div class='oneline'>전체 {n_total}장 · 확인 필요 {n_detect}장 · 우선 점검(FDC) {n_genuine}장 · "
                f"일시 관찰 {n_nonspecific}장 · 완료 {sum(1 for w in all_ids if review.get(w, {}).get('status') == '완료')}장</div>",
                unsafe_allow_html=True)
            _tbl_records = []
            for wid in filtered_ids():
                label, _, _ = wafer_stage(wid)
                sensor, fam = wfields(wid)
                di = det_map.get(wid, {})
                rstat = review.get(wid, {}).get("status", "미확인")
                detected = wid in detected_ids
                _tbl_records.append({
                    "선택": "✓" if wid == sel else "",
                    "확인 상태": normalize_status_label(rstat),
                    "Wafer ID": wid,
                    "점검 단계": normalize_status_label(label),
                    "이탈 시작": segment_short(di.get("first_detect_progress")) if detected else "—",
                    "점검 센서": sensor if detected else "—",
                    "점검 계열": family_view(fam) if (detected and fam) else ("장비 조건" if detected else "—"),
                    "점검 방향": check_direction(fam, detected) if detected else "—",
                })
            if _tbl_records:
                _tbl_df = pd.DataFrame(_tbl_records)
                _tbl_event = st.dataframe(
                    _tbl_df,
                    use_container_width=True,
                    hide_index=True,
                    height=330,
                    selection_mode="single-row",
                    on_select="rerun",
                    key="wafer_table_selection",
                    column_config={
                        "선택":     st.column_config.TextColumn("", width="small"),
                        "확인 상태": st.column_config.TextColumn("확인 상태", width="small"),
                        "Wafer ID": st.column_config.NumberColumn("Wafer ID", width="small"),
                        "점검 단계": st.column_config.TextColumn("점검 단계", width="small"),
                        "이탈 시작": st.column_config.TextColumn("이탈 시작", width="medium"),
                        "점검 센서": st.column_config.TextColumn("점검 센서", width="small"),
                        "점검 계열": st.column_config.TextColumn("점검 계열", width="medium"),
                        "점검 방향": st.column_config.TextColumn("점검 방향", width="large"),
                    },
                )
                if _tbl_event.selection.rows:
                    _clicked_wid = int(_tbl_df.iloc[_tbl_event.selection.rows[0]]["Wafer ID"])
                    if _clicked_wid != st.session_state["selected_wafer"]:
                        st.session_state["selected_wafer"] = _clicked_wid
                        st.rerun()
            else:
                st.caption("필터 조건에 해당하는 wafer가 없습니다.")
    with scol:
        process_summary_panel(sel)

    # ── 확인 상태 · 메모 입력 (기존 유지) ──
    with st.container(border=True, key="review_input_card"):
        st.markdown(f"<div class='sec-title'>확인 상태 · 메모 입력 — wafer {sel}</div>", unsafe_allow_html=True)
        cur = review.get(sel, {"status": "미확인", "memo": ""})
        opts = ["미확인", "확인 중", "완료"]
        with st.form(f"rev_{sel}", border=False):
            fc1, fc2, fc3 = st.columns([1.3, 3, 0.8])
            new_status = fc1.selectbox("확인 상태", opts, index=opts.index(cur.get("status", "미확인")),
                                       label_visibility="collapsed")
            new_memo = fc2.text_input("메모", value=cur.get("memo", ""),
                                      placeholder="확인 내용·조치 결과 입력", label_visibility="collapsed")
            ok = fc3.form_submit_button("저장", type="primary")
        if ok:
            review[sel] = {"status": new_status, "memo": new_memo or "", "handled": new_status == "완료"}
            save_review_dict(review)
            st.rerun()

# ===========================================================================
# 2페이지 : 센서 정상 범위 비교
# ===========================================================================
elif page == PAGES[1]:
    sel = st.session_state["selected_wafer"]

    # ── sv_block / sv_sensor 초기화 (pending 으로 설정된 값 우선 유지) ──
    sensor0, fam0 = wfields(sel)
    fi = fdc_map.get(sel)
    default_block = (str(fi.get("top_block", "")).strip() if fi else "")
    if default_block not in RAW_FILES:
        default_block = "EV"
    try:
        default_sensors = raw_sensor_cols(load_raw_block(default_block))
    except Exception:
        default_sensors = []
    default_sensor = sensor0 if sensor0 in default_sensors else (default_sensors[0] if default_sensors else None)

    if st.session_state.get("sv_wafer") != sel:
        st.session_state["sv_wafer"] = sel
        if st.session_state.get("sv_block") not in RAW_FILES:
            st.session_state["sv_block"] = default_block
        try:
            _cur_blk_sensors = raw_sensor_cols(load_raw_block(st.session_state["sv_block"]))
        except Exception:
            _cur_blk_sensors = []
        if st.session_state.get("sv_sensor") not in _cur_blk_sensors:
            st.session_state["sv_sensor"] = default_sensor

    # ── 헤더 카드 (제목 + 데이터 구분 / 점검 센서 드롭다운 통합) ─────────
    block_opts = list(RAW_FILES.keys())
    if st.session_state.get("sv_block") not in block_opts:
        st.session_state["sv_block"] = default_block
    block, sensor = render_page_header(
        "센서 점검 화면", "정상 wafer 기준과 선택 wafer 센서 흐름 비교",
        show_sensor_filters=True, sensor_block_opts=block_opts,
    )
    raw_df = load_raw_block(block)

    di = det_map.get(sel, {})
    fd = di.get("first_detect_progress")
    sub = raw_df[raw_df["wafer_id"] == sel].sort_values("progress")
    has_data = not (sub.empty or sensor is None or sub[sensor].dropna().empty)
    nt = normal_trend(block, sensor, tuple(sorted(normal_ids))) if has_data else None
    direction = sensor_direction(block, sensor, sel, normal_ids) if has_data else None
    cmp_txt = normalize_compare_label(direction)

    # ── KPI 요약 행 (4 카드) ────────────────────────────────────────────
    _stage_lbl2, _, _ = wafer_stage(sel)
    _slabel2 = normalize_status_label(_stage_lbl2)
    _sc2 = STATUS_COLOR.get(_slabel2, "#2563eb")
    _sb2 = STATUS_BORDER.get(_slabel2, "#94a3b8")
    _cmp_color = ("#b42318" if direction in ("정상보다 높음", "정상보다 낮음")
                  else ("#1a7f37" if direction == "정상과 유사" else "#64748b"))
    _kpi2_html = (
        f"<div class='kpi2' style='border-color:{_sb2}'><div class='k2-label'>선택 WAFER</div>"
        f"<div class='k2-val' style='color:{_sc2}'>{sel}</div>"
        f"<div class='k2-sub'>점검 단계: {_slabel2}</div></div>"
        f"<div class='kpi2'><div class='k2-label'>선택 센서</div>"
        f"<div class='k2-val' style='font-size:1.2rem'>{sensor or '—'}</div>"
        f"<div class='k2-sub'>데이터 구분: {block}</div></div>"
        f"<div class='kpi2'><div class='k2-label'>센서 상태</div>"
        f"<div class='k2-val' style='font-size:1.1rem;color:{_cmp_color}'>{cmp_txt}</div>"
        f"<div class='k2-sub'>정상 wafer 흐름 기준</div></div>"
        f"<div class='kpi2'><div class='k2-label'>이탈 시작</div>"
        f"<div class='k2-val' style='font-size:1.1rem'>{segment_short(di.get('first_detect_progress')) if sel in detected_ids else '—'}</div>"
        f"<div class='k2-sub'>{'이상 감지 wafer' if sel in detected_ids else '정상 범위'}</div></div>"
    )
    st.html(f"<div class='kpi-grid'>{_kpi2_html}</div>")

    # ── 중간 행: 차트(좌) + 센서 점검 해석(우) ──────────────────────────
    gcol, icol = st.columns([65, 35], gap="small")
    with gcol:
        with st.container(border=True, key="sensor_chart_card"):
            st.markdown(f"<div class='sec-title'>선택 센서 원본 시계열 — wafer {sel} · {sensor}</div>",
                        unsafe_allow_html=True)
            if not has_data:
                st.info(f"이 구분({block})에 wafer {sel}의 센서 데이터가 없습니다.")
            else:
                fig = go.Figure()
                if nt is not None:
                    xs, mean, std, kk = nt
                    fig.add_trace(go.Scatter(
                        x=np.concatenate([xs, xs[::-1]]),
                        y=np.concatenate([mean + std, (mean - std)[::-1]]),
                        fill="toself", fillcolor="rgba(148,163,184,0.15)",
                        line=dict(width=0), hoverinfo="skip", name="정상 범위"))
                    fig.add_trace(go.Scatter(x=xs, y=mean, mode="lines", name="정상 평균",
                                             line=dict(color="#94a3b8", width=1.8, dash="dot")))
                fig.add_trace(go.Scatter(x=sub["progress"], y=sub[sensor], mode="lines+markers",
                                         name="선택 wafer", line=dict(color=C_Q, width=2.2),
                                         marker=dict(size=4)))
                if sel in detected_ids and fd is not None and not pd.isna(fd):
                    fig.add_vline(x=float(fd), line=dict(color=C_EXCEED, width=1.3, dash="dot"))
                    fig.add_annotation(x=float(fd), xref="x", yref="paper", y=0.98,
                                       yanchor="top", xanchor="center",
                                       text=f"이탈 시작", showarrow=False,
                                       font=dict(color=C_EXCEED, size=10),
                                       bgcolor="rgba(255,255,255,0.78)")
                fig.update_layout(height=330, margin=dict(l=6, r=10, t=20, b=4),
                                  plot_bgcolor="white", paper_bgcolor="white",
                                  hovermode="x unified",
                                  legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0,
                                              font=dict(size=10), bgcolor="rgba(0,0,0,0)"),
                                  font=dict(size=11))
                fig.update_xaxes(title_text="식각 진행률 (%)", range=[0, 100], ticksuffix="%",
                                 gridcolor="#eef1f5", showline=True, linecolor="#e4e7ec")
                fig.update_yaxes(title_text=sensor, gridcolor="#eef1f5", zeroline=False)
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    with icol:
        with st.container(border=True, key="sensor_result_card"):
            st.markdown("<div class='sec-title'>센서 점검 해석</div>", unsafe_allow_html=True)
            _fam2 = wfields(sel)[1]
            _pdir2 = (f"{family_view(_fam2)} 계열 센서와 함께 확인" if _fam2 else "장비 조건 변화 확인")
            _rel2 = "평균 기준 차이 있음" if direction in ("정상보다 높음", "정상보다 낮음") else "구간별 추가 확인 필요"
            st.html(
                f"<div style='font-size:0.92rem;line-height:2.0'>"
                f"<div><span class='pill'>선택 센서</span> <b>{sensor}</b></div>"
                f"<div><span class='pill'>센서 상태</span> {cmp_txt}</div>"
                f"<div><span class='pill'>이탈 구간</span> {_rel2}</div>"
                f"<div><span class='pill'>점검 방향</span> {_pdir2}</div></div>"
            )

    # ── 하단 행: 같이 점검할 센서(좌) + 점검 기준(우) ─────────────────
    bot_l, bot_r = st.columns([55, 45], gap="small")
    with bot_l:
        with st.container(border=True, key="sensor_chip_card"):
            st.markdown("<div class='sec-title'>🔬 같이 점검할 센서</div>", unsafe_allow_html=True)
            st.markdown("<div class='oneline'>클릭하면 이 화면의 차트가 바뀝니다. 다른 페이지로 이동하지 않습니다.</div>",
                        unsafe_allow_html=True)
            _chips2 = related_real_sensors(sel)
            if _chips2:
                _n = min(len(_chips2), 6)
                _chip_cols = st.columns(_n)
                for _ci, (_cblk, _ccol) in enumerate(_chips2[:_n]):
                    _ctag = "⭐ " if _ci == 0 else ""
                    if _chip_cols[_ci].button(f"{_ctag}{_ccol}",
                                              key=f"chip2_{sel}_{_cblk}_{_ccol}",
                                              use_container_width=True):
                        st.session_state["pending_block"] = _cblk
                        st.session_state["pending_sensor"] = _ccol
                        st.session_state["pending_wafer"] = sel   # 현재 wafer 유지
                        st.rerun()
            else:
                st.caption("이 wafer에 연계된 센서 정보가 없습니다.")

    with bot_r:
        with st.container(border=True, key="check_guide_card"):
            _cur_sensor = sensor or st.session_state.get("sv_sensor", "")
            _cur_block = block or st.session_state.get("sv_block", "")
            _fdc_lbl, _sensor_lbl, _manual_lbl, _manual_items = field_action_manual_items(
                sel, selected_sensor=_cur_sensor, selected_block=_cur_block
            )
            st.markdown("<div class='sec-title'>📋 현장 조치 매뉴얼</div>", unsafe_allow_html=True)
            st.html(
                "<div style='font-size:0.90rem;line-height:1.8;color:#334155'>"
                f"<div><span style='color:#64748b'>FDC 기준 점검 계열:</span> <b>{_fdc_lbl}</b></div>"
                f"<div><span style='color:#64748b'>현재 확인 센서:</span> <b>{_cur_sensor or '—'}</b></div>"
                f"<div><span style='color:#64748b'>센서 기준 계열:</span> <b>{_sensor_lbl}</b></div>"
                "<div style='font-size:0.78rem;line-height:1.5;color:#64748b;"
                "margin-top:4px;margin-bottom:8px'>"
                "현재 확인 센서는 관련 센서 원본 흐름 확인용이며, 기본 조치 방향은 FDC 기준 점검 계열을 우선합니다."
                "</div>"
                f"<div style='font-weight:800;color:#0f172a;margin-bottom:2px'>표시 매뉴얼: {_manual_lbl}</div>"
                + "".join(f"<div>{i + 1}) {item}</div>" for i, item in enumerate(_manual_items))
                + "</div>"
            )

# ===========================================================================
# 3페이지 : 조치 기록 공유
# ===========================================================================
elif page == PAGES[2]:
    render_page_header("조치 기록 공유", "확인 상태와 조치 내용 공유")

    n_done = sum(1 for w in detected_ids if review.get(w, {}).get("status") == "완료")
    n_prog = sum(1 for w in detected_ids if review.get(w, {}).get("status") == "확인 중")
    n_unseen = max(0, n_detect - n_done - n_prog)
    upds = [review[w]["updated"] for w in review if review.get(w, {}).get("updated")]
    last_upd = max(upds) if upds else "—"
    m1, m2, m3, m4 = st.columns(4)
    m1.html(f"<div class='mini'><div class='m-l'>미확인</div><div class='m-v'>{n_unseen}</div></div>")
    m2.html(f"<div class='mini'><div class='m-l'>확인 중</div><div class='m-v'>{n_prog}</div></div>")
    m3.html(f"<div class='mini'><div class='m-l'>완료</div><div class='m-v'>{n_done}</div></div>")
    m4.html(f"<div class='mini'><div class='m-l'>최근 업데이트</div><div class='m-v' style='font-size:0.84rem'>{last_upd}</div></div>")

    with st.expander("⚠️ 조치기록 초기화", expanded=False):
        st.caption(
            "operator_review_status.csv의 처리 상태, 메모, 업데이트 시간을 초기화합니다. "
            "원본 센서 데이터와 MPCA 결과 파일은 변경하지 않습니다."
        )
        _do_reset = st.checkbox("초기화를 진행합니다", key="reset_review_confirm")
        if st.button("초기화 실행", key="reset_review_btn", disabled=not _do_reset):
            _reset_records = [
                {"wafer_id": w, "status": "미확인", "handled": False, "memo": "", "updated_at": ""}
                for w in all_ids
            ]
            pd.DataFrame(_reset_records).to_csv(REVIEW_FILE, index=False)
            st.success("조치 기록이 초기화되었습니다.")
            st.rerun()

    with st.container(border=True, key="review_table_card"):
        st.markdown("<div class='sec-title'>조치 기록</div>", unsafe_allow_html=True)
        rows = ""
        for wid in sorted(detected_ids, key=lambda w: (wafer_stage(w)[1], -(ratio_max.get(w) or 0), w)):
            label, _, cls = wafer_stage(wid)
            sensor, fam = wfields(wid)
            rv = review.get(wid, {})
            rstat = rv.get("status", "미확인")
            memo = str(rv.get("memo", "") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            upd = rv.get("updated", "") or "—"
            rows += (
                f"<tr><td class='wid'>{wid}</td>"
                f"<td><span class='bdg {cls}'>{normalize_status_label(label)}</span></td>"
                f"<td>{sensor}</td><td>{family_view(fam) if fam else '장비 조건'}</td>"
                f"<td><span class='bdg {rev_cls(rstat)}'>{normalize_status_label(rstat)}</span></td>"
                f"<td class='memo'>{memo or '—'}</td><td>{upd}</td></tr>"
            )
        st.html(
            "<div class='tbl-wrap'><table class='mon'><thead><tr>"
            "<th>Wafer ID</th><th>점검 단계</th><th>점검 센서</th><th>점검 계열</th>"
            "<th>확인 상태</th><th>메모</th><th>업데이트 시간</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div>"
        )

    with st.container(border=False, key="review_input_section"):
        with st.expander("선택 wafer 조치 내용 입력", expanded=False):
            cur_ids = sorted(detected_ids, key=lambda w: (wafer_stage(w)[1], -(ratio_max.get(w) or 0), w)) or sorted(all_ids)
            _cur_sel3 = st.session_state.get("selected_wafer")
            _p3_last = st.session_state.get("_p3_last_seen_wafer")
            # Sync widget only when selected_wafer changed externally (navigated from another page)
            if _cur_sel3 != _p3_last:
                if _cur_sel3 in cur_ids:
                    st.session_state["wafer_p3_widget"] = _cur_sel3
                elif st.session_state.get("wafer_p3_widget") not in cur_ids:
                    st.session_state["wafer_p3_widget"] = cur_ids[0] if cur_ids else None
            st.session_state["_p3_last_seen_wafer"] = _cur_sel3
            sel = st.selectbox("wafer 선택", cur_ids, format_func=fmt_wafer, key="wafer_p3_widget")
            # Update selected_wafer only when user explicitly changes the selectbox,
            # and only when selected_wafer was already a detected wafer (in cur_ids)
            if sel != _cur_sel3 and _cur_sel3 in cur_ids:
                st.session_state["selected_wafer"] = sel
                st.rerun()
            cur = review.get(sel, {"status": "미확인", "memo": ""})
            opts = ["미확인", "확인 중", "완료"]
            with st.form(f"rev3_{sel}", border=False):
                fc1, fc2, fc3 = st.columns([1.3, 3, 0.8])
                new_status = fc1.selectbox("확인 상태", opts, index=opts.index(cur.get("status", "미확인")),
                                           label_visibility="collapsed")
                new_memo = fc2.text_input("메모", value=cur.get("memo", ""),
                                          placeholder="확인 내용·조치 결과 입력", label_visibility="collapsed")
                ok = fc3.form_submit_button("저장", type="primary")
            if ok:
                review[sel] = {"status": new_status, "memo": new_memo or "", "handled": new_status == "완료"}
                save_review_dict(review)
                st.rerun()
