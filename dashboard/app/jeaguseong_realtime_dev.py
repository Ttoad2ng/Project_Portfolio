# -*- coding: utf-8 -*-
"""
금속 식각 공정 FDC 모니터링 대시보드 - 실시간 재생 개발 버전
=============================================================
원본 발표용 대시보드(dashboard/reference/jeaguseong.py)를 수정하지 않고,
별도 dev 버전으로 분리한 파일입니다.

추가 기능:
  - 원시 데이터(EV/OES/RFM) 기반 세밀 진행률 MPCA Q 재계산 (5%/3%/1%)
  - SPC Rule 기반 상태 모니터링 (정상/관찰/주의/경고/긴급 경고)
  - 블링킹 경고 램프 (CSS animation)
  - 느린 실시간 재생 모드 (1.0~1.5 초/점)

주의사항:
  - 보간(interpolation) 없음 — 모든 Q 점수는 원시 데이터에서 직접 계산
  - 원본 발표용 파일 수정 없음
  - 원본 CSV 파일 수정 없음
  - 기존 카드 크기/레이아웃 변경 없음
  - "불량 확정"/"원인 확정" 표현 사용 안 함

실행:
    streamlit run dashboard/app/jeaguseong_realtime_dev.py

필요 선행 작업:
    python src/build_realtime_spc_raw_replay.py
"""

import os
import re
import time
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# 0. 경로 / 상수
# ---------------------------------------------------------------------------
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))           # dashboard/app/
PROJECT_ROOT = os.path.dirname(os.path.dirname(BASE_DIR))           # dev_실전프로젝트/

# 실시간 재계산 결과 파일 (outputs/csv/)
REALTIME_DIR = os.path.join(PROJECT_ROOT, "outputs", "csv")
RT_Q = {
    5: os.path.join(REALTIME_DIR, "realtime_q_trajectory_raw_5pct.csv"),
    3: os.path.join(REALTIME_DIR, "realtime_q_trajectory_raw_3pct.csv"),
    1: os.path.join(REALTIME_DIR, "realtime_q_trajectory_raw_1pct.csv"),
}
RT_SPC = {
    5: os.path.join(REALTIME_DIR, "realtime_spc_status_raw_5pct.csv"),
    3: os.path.join(REALTIME_DIR, "realtime_spc_status_raw_3pct.csv"),
    1: os.path.join(REALTIME_DIR, "realtime_spc_status_raw_1pct.csv"),
}

# 운영자 처리상태 저장 (dev 전용, 원본과 분리)
REVIEW_FILE = os.path.join(BASE_DIR, "operator_review_status_dev.csv")

# 원본 센서 CSV (Page 2 센서 비교용 — 새 이상탐지에 사용하지 않음)
RAW_FILES = {
    "EV":  os.path.join(PROJECT_ROOT, "data", "raw_optional", "ev_data.csv"),
    "OES": os.path.join(PROJECT_ROOT, "data", "raw_optional", "oes_data.csv"),
    "RFM": os.path.join(PROJECT_ROOT, "data", "raw_optional", "rfm_data.csv"),
}

# 색상
C_Q      = "#2563eb"
C_THR    = "#98a2b3"
C_EXCEED = "#d92d20"
C_BAND   = "rgba(245,158,11,0.13)"
C_RISE   = "#f59e0b"
C_FALL   = "#cbd5e1"

# SPC 상태별 색상 / 블링크
SPC_LAMP = {
    "정상":     {"color": "#2563eb", "blink": False},
    "관찰":     {"color": "#16a34a", "blink": False},
    "주의":     {"color": "#f97316", "blink": True},
    "경고":     {"color": "#dc2626", "blink": True},
    "긴급 경고": {"color": "#dc2626", "blink": True},
}

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
# 1. 컬럼 자동 매핑
# ---------------------------------------------------------------------------
def find_col(df, candidates, contains=None):
    cols  = list(df.columns)
    lower = {c.lower().strip(): c for c in cols}
    for cand in candidates:
        key = cand.lower().strip()
        if key in lower:
            return lower[key]
    needles = contains if contains else candidates
    for c in cols:
        cl = c.lower()
        for n in needles:
            if n.lower() in cl:
                return c
    return None


def col_map(df, spec):
    out = {}
    for std, val in spec.items():
        cands, contains = (val if isinstance(val, tuple) else (val, None))
        out[std] = find_col(df, cands, contains)
    return out


# ---------------------------------------------------------------------------
# 2. 실시간 재계산 데이터 로드
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_realtime_data(resolution: int = 5):
    """
    실시간 재계산 Q trajectory 로드 + detection/FDC 파생.
    반환: (q, det, fdc) — 원본 load_data()와 동일 구조.
    파일 미존재 시 (None, None, None).
    """
    q_file = RT_Q.get(resolution, RT_Q[5])
    if not os.path.exists(q_file):
        return None, None, None

    q = pd.read_csv(q_file)
    q["wafer_id"] = q["wafer_id"].astype(int)
    q = q.sort_values(["wafer_id", "progress_pct"]).reset_index(drop=True)
    if "q_delta" not in q.columns:
        q["q_delta"] = q.groupby("wafer_id")["Q_score"].diff().fillna(0.0)
    q["exceed"] = q["Q_score"] > q["Q_threshold"]

    # detection results 파생
    def _det(wdf):
        anom = wdf[wdf["pred_anomaly"] == 1]
        fd   = anom["progress_pct"].min() if len(anom) > 0 else None
        return pd.Series({
            "wafer_id":              int(wdf["wafer_id"].iloc[-1]),
            "first_detect_progress": fd,
            "lead_time_pct":         (100 - fd) if fd is not None else None,
            "detected_at_pct":       fd,
            "detected":              len(anom) > 0,
            "fault_name":            wdf["fault_name"].iloc[-1],
            "is_fault":              int(wdf["is_fault"].iloc[-1]),
        })

    det = q.groupby("wafer_id", group_keys=False).apply(_det).reset_index(drop=True)
    det["wafer_id"] = det["wafer_id"].astype(int)
    det["detected"] = det["detected"].astype(bool)

    # FDC 최소 skeleton (contribution 분석 없음 — raw replay 한계)
    detected_ids_list = det.loc[det["detected"], "wafer_id"].tolist()
    fdc = pd.DataFrame({
        "wafer_id":          detected_ids_list,
        "top_block":         "EV",
        "top_sensor":        "",
        "top_sensor_pct":    None,
        "top_time":          None,
        "suspected_family":  "",
        "fdc_interpretation": "SPC Rule 기준 이상 감지",
    })

    return q, det, fdc


@st.cache_data(show_spinner=False)
def load_spc_data(resolution: int = 5):
    """SPC 상태 파일 로드. 미존재 시 None."""
    spc_file = RT_SPC.get(resolution, RT_SPC[5])
    if not os.path.exists(spc_file):
        return None
    return pd.read_csv(spc_file)


# ---------------------------------------------------------------------------
# 3. 해석형 문구 변환
# ---------------------------------------------------------------------------
def progress_phrase(pct):
    if pct is None or pd.isna(pct):
        return "구간 정보 없음"
    p = int(round(float(pct)))
    if p <= 30: return f"공정 초기({p}% 구간)"
    if p <= 70: return f"공정 중반({p}% 구간)"
    return f"공정 후반({p}% 구간)"

def leadtime_phrase(lt):
    if lt is None or pd.isna(lt): return "조기 인지 정보 없음"
    v = int(round(float(lt)))
    if v <= 0:  return "조기 인지 여유 없음 (종료 시점 단발 감지)"
    if v >= 70: return f"공정 종료 전 {v}% 구간에서 조기 인지"
    if v >= 40: return f"공정 중반 이전 조기 인지({v}%)"
    return f"공정 후반부 탐지({v}%)"

def progress_token(pct):
    if pct is None or pd.isna(pct): return "—"
    p = int(round(float(pct)))
    if p <= 30: return f"초기 {p}%"
    if p <= 70: return f"중반 {p}%"
    return f"후반 {p}%"

def lead_token(lt):
    if lt is None or pd.isna(lt): return "—"
    v = int(round(float(lt)))
    return "여유 없음" if v <= 0 else f"여유 {v}%"

def family_key(fam):
    f = str(fam)
    if "RF/TCP" in f or "매칭" in f: return "matching"
    if "OES" in f or "플라즈마" in f: return "oes"
    if "He" in f or "Chuck" in f or "척" in f: return "he"
    if ("Cl2" in f) or ("BCl3" in f) or ("가스" in f) or ("Gas" in f): return "gas"
    if ("제어" in f) or ("장비" in f) or ("Pressure" in f) or ("압력" in f) or ("Valve" in f): return "pressure"
    if "TCP" in f: return "tcp"
    if "RF" in f:  return "rf"
    return "generic"

def family_instruction(fam):
    return FDC_INSTRUCTION.get(family_key(fam), FDC_INSTRUCTION["generic"])

def family_short(fam):
    return str(fam).replace(" 이상 의심", "").replace("이상 의심", "").strip()

def remain_phrase(lt):
    if lt is None or pd.isna(lt): return "—"
    v = int(round(float(lt)))
    return "남은 구간 없음 (종료 시점 감지)" if v <= 0 else f"공정 종료 전 {v}% 구간"

def remain_token(lt):
    if lt is None or pd.isna(lt): return "—"
    v = int(round(float(lt)))
    return "여유 없음" if v <= 0 else f"종료 전 {v}%"

def priority_label(max_ratio):
    if max_ratio is None or pd.isna(max_ratio): return "관찰"
    if max_ratio >= 2.0: return "긴급"
    if max_ratio >= 1.2: return "위험"
    return "관찰"

def priority_cls(label):
    return {"긴급": "urgent", "위험": "high", "관찰": "watch"}.get(label, "watch")

PRIO_PHRASE   = {"긴급": "긴급 점검", "위험": "주의 점검", "관찰": "관찰"}
STATUS_COLOR  = {"긴급 점검": "#dc2626", "주의 점검": "#f59e0b", "관찰": "#16a34a", "정상": "#2563eb", "완료": "#2563eb"}
STATUS_BG     = {"긴급 점검": "#fef2f2", "주의 점검": "#fff7ed", "관찰": "#f0fdf4",  "정상": "#ffffff",  "완료": "#ffffff"}
STATUS_BORDER = {"긴급 점검": "#fca5a5", "주의 점검": "#fdba74", "관찰": "#86efac",  "정상": "#94a3b8",  "완료": "#94a3b8"}

def normalize_status_label(s):
    return {"바로 확인 필요": "긴급 점검", "우선 확인 필요": "주의 점검",
            "추이 관찰": "관찰", "추이 관찰 필요": "관찰", "정상 범위": "정상",
            "처리 완료": "완료"}.get(str(s).strip(), str(s).strip())

def normalize_column_label(c):
    return {"확인 센서": "점검 센서", "우선 점검 센서": "점검 센서", "확인 방향": "점검 방향",
            "권장 확인": "점검 방향", "먼저 볼 계열": "점검 계열", "먼저 볼 장비/계열": "점검 계열",
            "같이 볼 센서": "같이 점검할 센서"}.get(str(c).strip(), str(c).strip())

def normalize_compare_label(s):
    return {"정상과 유사": "정상 범위 안", "정상보다 높음": "정상 범위 이탈",
            "정상보다 낮음": "정상 범위 이탈"}.get(s, "비교 데이터 부족")

def qrise_interval(wqx):
    g = wqx.sort_values("progress_pct")
    progs = g["progress_pct"].tolist(); qdv = g["q_delta"].tolist()
    best_i, best_v = None, None
    for i, d in enumerate(qdv):
        if d is None or pd.isna(d): continue
        if best_v is None or d > best_v: best_v, best_i = d, i
    if not best_i: return None
    return f"{progs[best_i-1]}% -> {progs[best_i]}%"

def threshold_approach_phrase(wqx):
    g = wqx.sort_values("progress_pct")
    progs = g["progress_pct"].tolist()
    gap   = (g["Q_threshold"] - g["Q_score"]).tolist()
    first_ex = next((p for p, gp in zip(progs, gap) if gp <= 0), None)
    if first_ex is None: return None
    if first_ex == progs[0]: return "공정 초기 구간부터 기준선 초과"
    idx = progs.index(first_ex)
    return f"{progs[idx-1]}~{first_ex}% 구간에서 기준선 접근 후 초과"

def exceed_segments(progress, mask):
    segs, start, prev = [], None, None
    for p, m in zip(progress, mask):
        if m and start is None:  start = p
        elif (not m) and start is not None: segs.append((start, prev)); start = None
        prev = p
    if start is not None: segs.append((start, prev))
    return segs


# ---------------------------------------------------------------------------
# 4. 운영자 처리상태 저장/로드
# ---------------------------------------------------------------------------
def load_review():
    if not os.path.exists(REVIEW_FILE): return {}
    try: r = pd.read_csv(REVIEW_FILE)
    except Exception: return {}
    out = {}
    for row in r.itertuples(index=False):
        d  = row._asdict()
        wid = int(d.get("wafer_id"))
        handled = str(d.get("handled", False)).strip().lower() in {"true","1","yes"}
        memo    = "" if pd.isna(d.get("memo","")) else str(d.get("memo",""))
        raw     = d.get("status", None)
        if raw is None or (isinstance(raw, float) and pd.isna(raw)) or str(raw).strip()=="":
            status = "완료" if handled else "미확인"
        else:
            status = str(raw).strip()
            if status == "처리 완료": status = "완료"
        updated = "" if pd.isna(d.get("updated_at","")) else str(d.get("updated_at",""))
        out[wid] = {"handled": handled, "memo": memo, "status": status, "updated": updated}
    return out

def save_review(records):
    df = pd.DataFrame(records)
    df["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df.to_csv(REVIEW_FILE, index=False)

def save_review_dict(review):
    save_review([{"wafer_id": w,
                  "status": v.get("status","미확인"),
                  "handled": v.get("status","미확인")=="완료",
                  "memo": v.get("memo","")}
                 for w, v in review.items()])


# ---------------------------------------------------------------------------
# 5. 원본 센서 CSV 로드 (Page 2 시각화 전용)
# ---------------------------------------------------------------------------
RAW_EXCLUDE_COLS = {"wafer_names", "fault_name", "Step Number", "wafer_id", "progress"}

@st.cache_data(show_spinner=False)
def load_raw_block(block):
    path = RAW_FILES.get(block)
    if not path or not os.path.exists(path): return pd.DataFrame()
    df = pd.read_csv(path)
    wn_col = find_col(df, ["wafer_names","wafer_name","wafer_id","wafer"], ["wafer"])
    df["wafer_id"] = pd.to_numeric(df[wn_col].astype(str).str.extract(r"(\d+)")[0], errors="coerce")
    df = df.dropna(subset=["wafer_id"]).copy()
    df["wafer_id"] = df["wafer_id"].astype(int)
    tcol = find_col(df, ["Time","TIME","timestamp"], ["time"])
    if tcol: df = df.sort_values(["wafer_id", tcol]).reset_index(drop=True)
    n    = df.groupby("wafer_id")["wafer_id"].transform("size")
    rank = df.groupby("wafer_id").cumcount()
    df["progress"] = (rank / (n-1).clip(lower=1) * 100.0).where(n>1, 0.0)
    return df

def raw_sensor_cols(df):
    tcol = find_col(df, ["Time","TIME","timestamp"], ["time"])
    exc  = set(RAW_EXCLUDE_COLS) | ({tcol} if tcol else set())
    return [c for c in df.columns if c not in exc and pd.api.types.is_numeric_dtype(df[c])]

@st.cache_data(show_spinner=False)
def normal_trend(block, sensor, normal_ids, grid=60):
    df = load_raw_block(block)
    if df.empty or sensor not in df.columns: return None
    xs   = np.linspace(0, 100, grid)
    mats = []
    sub_all = df[df["wafer_id"].isin(set(normal_ids))]
    for _, sub in sub_all.groupby("wafer_id"):
        s = sub[["progress", sensor]].dropna()
        if len(s) < 2: continue
        mats.append(np.interp(xs, s["progress"].to_numpy(), s[sensor].to_numpy()))
    if not mats: return None
    M = np.vstack(mats)
    return xs, M.mean(axis=0), M.std(axis=0), len(mats)

def sensor_direction(block, sensor, wid, normal_ids):
    try: df = load_raw_block(block)
    except Exception: return None
    if df.empty or sensor not in df.columns: return None
    s = df[df["wafer_id"]==wid][sensor].dropna()
    if s.empty: return None
    nt = normal_trend(block, sensor, tuple(sorted(normal_ids)))
    if nt is None: return None
    sel_mean, nmean, nstd = float(s.mean()), float(np.mean(nt[1])), float(np.mean(nt[2]))
    tol = max(nstd, abs(nmean)*0.005)
    if sel_mean > nmean+tol: return "정상보다 높음"
    if sel_mean < nmean-tol: return "정상보다 낮음"
    return "정상과 유사"


# ---------------------------------------------------------------------------
# 캐릭터 이미지 (BASE_DIR/character OR PROJECT_ROOT/character)
# ---------------------------------------------------------------------------
def get_character_images():
    exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    for char_dir in [
        os.path.join(BASE_DIR, "character"),
        os.path.join(PROJECT_ROOT, "character"),
    ]:
        if os.path.isdir(char_dir):
            imgs = sorted(
                os.path.join(char_dir, f) for f in os.listdir(char_dir)
                if os.path.splitext(f)[1].lower() in exts
            )
            if imgs: return imgs
    return []

def first_character_image():
    imgs = get_character_images()
    if not imgs: return None
    return next((p for p in imgs if "transparent" in os.path.basename(p).lower()), imgs[0])

def render_character_image(position="sidebar"):
    img_path = first_character_image()
    if not img_path: return
    width = 100 if position == "sidebar" else 70
    try: st.image(img_path, width=width)
    except Exception: pass


# ---------------------------------------------------------------------------
# SPC 램프 헬퍼
# ---------------------------------------------------------------------------
def spc_lamp_html(spc_state: str, blink: bool = False) -> str:
    """작은 원형 램프 + 상태 텍스트 HTML 반환."""
    info  = SPC_LAMP.get(spc_state, {"color": "#94a3b8", "blink": False})
    color = info["color"]
    use_blink = blink or info["blink"]
    anim  = "animation:blink-lamp 1s ease-in-out infinite;" if use_blink else ""
    return (
        f"<span style='display:inline-block;width:12px;height:12px;border-radius:50%;"
        f"background:{color};margin-right:6px;vertical-align:middle;{anim}'></span>"
        f"<b style='color:{color}'>{spc_state}</b>"
    )


# ---------------------------------------------------------------------------
# 표시용 헬퍼
# ---------------------------------------------------------------------------
def segment_name(pct):
    if pct is None or pd.isna(pct): return "구간 정보 없음"
    p = float(pct)
    if p <= 20: return "식각 시작 구간"
    if p <= 40: return "식각 초반 구간"
    if p <= 60: return "식각 중반 구간"
    if p <= 80: return "식각 후반 구간"
    return "식각 종료 접근 구간"

def segment_with_pct(pct):
    if pct is None or pd.isna(pct): return "이상 없음"
    return f"{segment_name(pct)} / {int(round(float(pct)))}%"

def segment_short(pct):
    if pct is None or pd.isna(pct): return "—"
    return f"{segment_name(pct).replace(' 구간','')} {int(round(float(pct)))}%"

FAMILY_VIEW = {"rf":"RF/TCP 매칭","matching":"RF/TCP 매칭","tcp":"RF/TCP 매칭","gas":"Gas 공급",
               "pressure":"Pressure 제어","oes":"OES/플라즈마","he":"He Chuck","generic":"장비 조건"}

def family_view(fam): return FAMILY_VIEW.get(family_key(fam), "—")

CHECK_DIRECTION = {"rf":"RF/TCP 매칭 계열 확인","matching":"RF/TCP 매칭 계열 확인",
                   "tcp":"RF/TCP 매칭 계열 확인","gas":"Gas 공급 상태 확인",
                   "pressure":"Pressure 제어 상태 확인","oes":"OES/플라즈마 반응 확인",
                   "he":"He Chuck 상태 확인","generic":"장비 조건 변화 확인"}

def check_direction(fam, detected=True):
    if not detected or not str(fam).strip(): return "장비 조건 변화 확인"
    return CHECK_DIRECTION.get(family_key(fam), "장비 조건 변화 확인")

COSEE_SENSORS = {
    "rf":       ["RF 전력","RF Load","Bias Power","Reflected Power","TCP Load"],
    "matching": ["RF 전력","RF Load","Bias Power","Reflected Power","TCP Load"],
    "tcp":      ["TCP Power","TCP Load","RF 전력","플라즈마 세기","Reflected Power"],
    "gas":      ["BCl3 Flow","Cl2 Flow","MFC 응답","RF 전력","OES 신호"],
    "pressure": ["Chamber Pressure","Vat Valve","배기 상태","RF 전력","OES 신호"],
    "he":       ["Backside He","Chuck 상태","냉각 상태","인접 wafer He"],
    "oes":      ["플라즈마 발광","Gas 신호","RF 전력","endpoint 신호"],
    "generic":  ["RF 전력","RF Load","Chamber Pressure","Gas Flow"],
}
def cosee_sensors(fam): return COSEE_SENSORS.get(family_key(fam), COSEE_SENSORS["generic"])


# ---------------------------------------------------------------------------
# ===========================================================================
# PAGE 설정
# ===========================================================================
st.set_page_config(page_title="금속 식각 FDC 모니터링 [DEV]", layout="wide",
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

  div[data-testid="stVerticalBlockBorderWrapper"] {
      background:#ffffff !important; border:1.5px solid #94a3b8 !important;
      border-radius:12px !important; box-shadow:0 3px 10px rgba(15,23,42,0.12) !important; }
  div[data-testid="stVerticalBlockBorderWrapper"] > div {
      padding:16px 18px !important; background:#ffffff !important; border-radius:12px !important; }
  div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalBlock"] { background:#ffffff !important; }

  .st-key-filter_card,.st-key-selected_wafer_card,.st-key-wafer_table_card,
  .st-key-summary_card,.st-key-sensor_chip_card,.st-key-sensor_result_card,
  .st-key-review_table_card,.st-key-review_input_card,.st-key-page1_header,
  .st-key-p2_header,.st-key-check_guide_card,.st-key-page_header {
      background-color:#ffffff !important; border:1.5px solid #94a3b8 !important;
      border-radius:12px !important; box-shadow:0 3px 10px rgba(15,23,42,0.12) !important;
      padding:22px 26px !important; margin-bottom:18px !important; }
  .st-key-page_header { min-height:110px !important; padding:18px 24px !important; margin-bottom:14px !important; }
  .st-key-sensor_chart_card,.st-key-sensor_result_card,.st-key-sensor_chip_card,
  .st-key-check_guide_card { margin-bottom:10px !important; }

  .st-key-chart_card,.st-key-sensor_chart_card {
      background-color:#ffffff !important; border:1.5px solid #94a3b8 !important;
      border-radius:12px !important; box-shadow:0 3px 10px rgba(15,23,42,0.12) !important;
      padding:10px 12px 4px 12px !important; margin-bottom:18px !important; }
  .st-key-chart_card > div,.st-key-sensor_chart_card > div { gap:0 !important; }
  .st-key-sensor_chart_card,.st-key-sensor_result_card { min-height:390px !important; box-sizing:border-box !important; }
  .st-key-sensor_chip_card,.st-key-check_guide_card { min-height:150px !important; box-sizing:border-box !important; }
  .st-key-wafer_table_card { min-height:430px !important; box-sizing:border-box !important; }

  .st-key-filter_card *,.st-key-selected_wafer_card *,.st-key-wafer_table_card *,
  .st-key-chart_card *,.st-key-sensor_chart_card *,.st-key-summary_card *,
  .st-key-sensor_chip_card *,.st-key-sensor_result_card *,.st-key-review_table_card *,
  .st-key-review_input_card *,.st-key-page1_header *,.st-key-p2_header *,
  .st-key-check_guide_card *,.st-key-page_header * { background-color:transparent; }

  .header-icon-wrap img { border-radius:18px; box-shadow:0 4px 14px rgba(15,23,42,0.18); }
  .main-title-wrap { display:flex; flex-direction:column; justify-content:center; min-height:88px; }
  .main-title { font-size:2.1rem; font-weight:900; color:#0f172a; line-height:1.15; margin:0; }
  .main-subtitle { font-size:1.05rem; color:#64748b; margin-top:8px; margin-bottom:0; }
  .unified-header-text { display:flex; flex-direction:column; justify-content:center;
      align-items:flex-start; text-align:left; min-height:100px; padding-top:15px; box-sizing:border-box; }
  .unified-header-title { font-size:2.1rem; font-weight:900; color:#0f172a; line-height:1.15;
      margin:0; text-align:left; }
  .unified-header-subtitle { font-size:1.05rem; color:#64748b; margin-top:8px; margin-bottom:0; text-align:left; }

  .kpi { background:#ffffff; border:1.5px solid #94a3b8; border-radius:14px; padding:16px 18px;
      box-shadow:0 3px 10px rgba(15,23,42,0.12); height:100%; }
  .kpi-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:2px; }
  .kpi2 { background:#ffffff; border:1.5px solid #94a3b8; border-radius:14px; padding:15px 18px;
      box-shadow:0 3px 10px rgba(15,23,42,0.12); }
  .kpi2 .k2-label { font-size:0.74rem; color:#64748b; font-weight:700; }
  .kpi2 .k2-val { font-size:1.7rem; font-weight:800; color:#2563eb; line-height:1.15; margin-top:6px;
      white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .kpi2 .k2-sub { font-size:0.76rem; color:#64748b; margin-top:6px; }
  @media (max-width:1100px) { .kpi-grid { grid-template-columns:repeat(2,1fr); } }

  .sumcard { background:#ffffff; border:1.5px solid #94a3b8; border-radius:14px; padding:16px 18px;
      box-shadow:0 3px 10px rgba(15,23,42,0.12); }
  .sum-row { display:flex; justify-content:space-between; align-items:center; gap:10px;
      padding:6px 0; font-size:0.84rem; border-bottom:1px solid #f1f5f9; }
  .sum-row:last-child { border-bottom:none; }
  .sum-k { color:#64748b; } .sum-v { color:#0f172a; font-weight:600; text-align:right; }
  .sum-sep { height:1px; background:#cbd5e1; margin:7px 0; }

  .wpanel { background:#fff; border:1.5px solid #94a3b8; border-left:5px solid #94a3b8;
      border-radius:12px; padding:18px 20px; box-shadow:0 3px 10px rgba(15,23,42,0.12); }
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
  .bdg-lg.red   { background:#fee4e2; color:#b42318; } .bdg-lg.amber { background:#fef0c7; color:#b54708; }
  .bdg-lg.blue  { background:#e6effc; color:#1d4ed8; } .bdg-lg.gray  { background:#eef2f6; color:#475467; }
  .bdg-lg.green { background:#e7f4ec; color:#1a7f37; }

  .bdg { display:inline-block; padding:1px 9px; border-radius:6px; font-size:0.73rem; font-weight:600; white-space:nowrap; }
  .bdg.red   { background:#fee4e2; color:#b42318; border:1px solid #fecdca; }
  .bdg.amber { background:#fef0c7; color:#b54708; border:1px solid #fedf89; }
  .bdg.blue  { background:#e6effc; color:#1d4ed8; border:1px solid #c5dcf7; }
  .bdg.gray  { background:#eef2f6; color:#475467; border:1px solid #dde3ea; }
  .bdg.green { background:#e7f4ec; color:#1a7f37; border:1px solid #cce8d6; }
  .bdg.wait  { background:#f2f4f7; color:#98a2b3; border:1px solid #e4e7ec; }
  .pill { display:inline-block; padding:2px 10px; border-radius:12px; font-size:0.74rem;
      background:#eef2f6; color:#1f4a73; border:1px solid #d6e1ee; margin:2px 5px 2px 0; white-space:nowrap; }

  .sec-title { font-size:1.15rem; font-weight:800; color:#111827; margin-bottom:10px; }
  .oneline { font-size:0.81rem; color:#64748b; margin:-2px 0 10px 1px; }
  .gcard .g-h { font-size:1.02rem; font-weight:800; color:#111827; margin:12px 0 6px 0; }
  .gcard .g-h:first-child { margin-top:0; }
  .gcard ul,.gcard ol { margin:2px 0 0 0; padding-left:18px; font-size:0.83rem; color:#344054; line-height:1.6; }
  .gcard .tiny { color:#98a2b3; font-size:0.74rem; margin-top:8px; }
  .gcard .muted { color:#98a2b3; font-size:0.82rem; }
  .mini { background:#fff; border:1.5px solid #94a3b8; border-radius:12px; padding:16px 18px;
      box-shadow:0 3px 10px rgba(15,23,42,0.12); }
  .mini .m-l { font-size:0.72rem; color:#667085; } .mini .m-v { font-size:1.2rem; font-weight:700; color:#101828; }

  .tbl-wrap { max-height:380px; overflow-y:auto; background:#ffffff; border:1.5px solid #64748b;
      border-radius:10px; box-shadow:0 3px 10px rgba(15,23,42,0.12); }
  table.mon { width:100%; border-collapse:collapse; font-size:0.82rem; }
  table.mon thead th { background:#93c5fd; color:#0f172a; font-weight:700; text-align:left;
      padding:7px 11px; border-bottom:1px solid #60a5fa; position:sticky; top:0; }
  table.mon tbody td { padding:7px 11px; border-bottom:1px solid #cbd5e1; color:#1f2937; }
  table.mon tbody tr:nth-child(odd) { background:#ffffff; }
  table.mon tbody tr:nth-child(even) { background:#f1f5f9; }
  table.mon tbody tr:hover { background:#eff6ff; }
  table.mon td.wid { font-weight:700; color:#101828; }
  table.mon td.memo { color:#667085; max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }

  .st-key-chart_card,.st-key-selected_wafer_card { min-height:500px !important; box-sizing:border-box !important; }
  .q-chart-title { font-size:1.35rem; font-weight:900; color:#111827; line-height:1.25; margin-bottom:8px; }
  .st-key-sensor_chip_card { min-height:165px !important; box-sizing:border-box !important; }

  div[data-testid="stFormSubmitButton"] button,
  button[data-testid="stBaseButton-primaryFormSubmit"] {
      background:#ef4444 !important; background-color:#ef4444 !important;
      color:#ffffff !important; border:1.5px solid #ef4444 !important;
      border-radius:10px !important; font-weight:800 !important;
      min-height:42px !important; padding:0 18px !important; }
  div[data-testid="stFormSubmitButton"] button:hover,
  button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
      background:#dc2626 !important; background-color:#dc2626 !important;
      color:#ffffff !important; border-color:#dc2626 !important; }

  /* DEV 배지 */
  .dev-badge { display:inline-block; background:#7c3aed; color:#fff;
      font-size:0.68rem; font-weight:800; padding:2px 8px; border-radius:6px;
      margin-left:8px; vertical-align:middle; letter-spacing:0.05em; }

  /* SPC 램프 블링크 애니메이션 */
  @keyframes blink-lamp {
      0%, 100% { opacity:1; }
      50% { opacity:0.2; }
  }

  /* 재생 진행 바 */
  .replay-bar { width:100%; height:6px; background:#e2e8f0; border-radius:3px; margin:6px 0; }
  .replay-bar-inner { height:6px; background:#2563eb; border-radius:3px; transition:width 0.3s; }

  .stSelectbox label,.stTextInput label,.stToggle label { color:#1f2937 !important; font-weight:700 !important; }
  div[data-testid="stMain"] .stTextInput div[data-baseweb="input"],
  div[data-testid="stMain"] div[data-baseweb="select"] > div {
      background:#f8fafc !important; border-color:#cbd5e1 !important; }
  div[data-testid="stMain"] .stTextInput input { color:#111827 !important; }
  div[data-testid="stForm"] { border:none; padding:0; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 데이터 로드
# ---------------------------------------------------------------------------
_resolution = st.session_state.get("progress_resolution", 5)
q, det, fdc = load_realtime_data(_resolution)

_files_missing = (q is None)
if _files_missing:
    st.error(
        "실시간 재계산 파일이 없습니다. 먼저 아래 명령어를 실행하세요:\n\n"
        "```\npython src/build_realtime_spc_raw_replay.py\n```"
    )
    st.stop()

spc_df = load_spc_data(_resolution)

all_ids     = sorted(q["wafer_id"].unique().tolist())
n_total     = len(all_ids)
fdc_map     = fdc.set_index("wafer_id").to_dict("index")
det_map     = det.set_index("wafer_id").to_dict("index")
detected_ids = sorted(det.loc[det["detected"], "wafer_id"].tolist()) if "detected" in det.columns else []
genuine_ids  = [w for w in detected_ids if w in fdc_map]
nonspecific_ids = [w for w in detected_ids if w not in fdc_map]
n_detect, n_genuine, n_nonspecific = len(detected_ids), len(genuine_ids), len(nonspecific_ids)
normal_ids  = [w for w in all_ids if w not in detected_ids]
ratio_max   = (q.assign(_r=q["Q_score"]/q["Q_threshold"]).groupby("wafer_id")["_r"].max().to_dict())
review      = load_review()

STAGE_RANK = {"긴급 점검":0,"주의 점검":1,"관찰":2,"정상":3,"완료":4}


def wafer_stage(wid):
    if review.get(wid,{}).get("status")=="완료": return ("완료",4,"blue")
    if wid not in detected_ids:                   return ("정상",3,"blue")
    p = priority_label(ratio_max.get(wid))
    if p=="긴급": return ("긴급 점검",0,"red")
    if p=="위험": return ("주의 점검",1,"amber")
    return ("관찰",2,"green")

def wfields(wid):
    fi = fdc_map.get(wid)
    if fi: return (str(fi.get("top_sensor","")).strip() or "센서 미특정",
                   str(fi.get("suspected_family","")).strip())
    return ("센서 미특정","")

def rev_cls(status):
    return {"미확인":"wait","확인 중":"amber","완료":"green"}.get(status,"wait")

RELATED_REAL = {
    "rf":       [("EV","RF Load"),("EV","RF Pwr"),("EV","RF Btm Pwr"),("EV","RF Btm Rfl Pwr"),("EV","TCP Load")],
    "matching": [("EV","RF Load"),("EV","RF Pwr"),("EV","RF Btm Pwr"),("EV","RF Btm Rfl Pwr"),("EV","TCP Load")],
    "tcp":      [("EV","TCP Top Pwr"),("EV","TCP Rfl Pwr"),("EV","TCP Load"),("EV","RF Load"),("EV","RF Pwr")],
    "gas":      [("EV","BCl3 Flow"),("EV","Cl2 Flow"),("EV","RF Load")],
    "pressure": [("EV","Pressure"),("EV","Vat Valve"),("EV","RF Load")],
    "he":       [("EV","He Press"),("EV","Pressure")],
    "oes":      [],
    "generic":  [("EV","RF Load"),("EV","Pressure"),("EV","BCl3 Flow")],
}

def related_real_sensors(wid):
    out, fk = [], "generic"
    fi = fdc_map.get(wid)
    if fi:
        tb, ts = str(fi.get("top_block","")).strip(), str(fi.get("top_sensor","")).strip()
        if tb in RAW_FILES and ts: out.append((tb,ts))
        fk = family_key(fi.get("suspected_family",""))
    for blk, col in RELATED_REAL.get(fk, RELATED_REAL["generic"]):
        if (blk,col) not in out: out.append((blk,col))
    valid=[]
    for blk,col in out:
        try:
            if col in load_raw_block(blk).columns: valid.append((blk,col))
        except Exception: pass
    return valid[:6]

_MANUAL_TEXT = {
    "rf": ("RF 계열",[
        "RF Power 공급값과 실제 출력값이 일치하는지 확인",
        "RF Load / RF Bias Power 변동 여부 확인",
        "RF Reflected Power가 증가했는지 확인",
        "RF Generator 상태 로그와 알람 이력 확인",
        "반복 발생 시 RF Matching 계열과 함께 점검"]),
    "tcp": ("TCP 계열",[
        "TCP Source Power 출력 안정성 확인",
        "TCP Load / TCP Tuner 위치 변화 확인",
        "TCP Reflected Power 상승 여부 확인",
        "TCP Phase Error 또는 Impedance 변동 확인",
        "반복 발생 시 RF/TCP Matching 상태를 함께 점검"]),
    "matching": ("RF/TCP Matching 계열",[
        "Impedance 변동 여부 확인","Phase Error가 튀는 구간 확인",
        "Reflected Power 상승 여부 확인",
        "RF Load, TCP Load가 같은 구간에서 흔들리는지 확인",
        "Matching network 또는 tuner 상태 로그 확인"]),
    "gas": ("Gas 공급 계열",[
        "BCl3 / Cl2 유량 setpoint와 실제 flow 비교",
        "MFC 응답 지연 또는 순간 흔들림 확인",
        "Gas 공급 압력과 valve 상태 확인",
        "같은 Lot 내 인접 wafer에서도 같은 flow 패턴이 반복되는지 확인",
        "반복 발생 시 gas line, MFC, recipe 조건 변경 이력 확인"]),
    "pressure": ("Pressure / 제어 계열",[
        "Chamber Pressure 안정성 확인","Vat Valve Position 변동 여부 확인",
        "Pressure 제어 응답 지연 여부 확인",
        "Gas flow 변화와 pressure 변화가 같은 구간에서 발생했는지 확인",
        "반복 발생 시 throttle valve / pressure control loop 상태 확인"]),
    "he": ("He Chuck 계열",[
        "Backside He Pressure 변동 여부 확인","Wafer chucking 상태 확인",
        "He leak 또는 pressure drop 여부 확인","ESC / chuck 관련 장비 로그 확인",
        "반복 발생 시 wafer contact 상태와 thermal 안정성 확인"]),
    "oes": ("OES / 플라즈마 반응 계열",[
        "해당 파장 intensity가 정상 wafer 대비 상승/저하했는지 확인",
        "Endpoint 신호 변화 구간 확인",
        "Gas flow, RF/TCP power 변화와 같은 구간에서 발생했는지 확인",
        "Plasma 안정성 관련 알람 또는 recipe step 변경 여부 확인",
        "반복 발생 시 chamber condition 또는 plasma 상태 점검"]),
    "generic": ("장비 조건 일반",[
        "선택 wafer의 이상 신호 발생 구간과 센서 변화 구간 비교",
        "동일 Lot / 인접 wafer에서도 같은 패턴이 있는지 확인",
        "장비 로그와 recipe 변경 이력 확인",
        "RF/TCP, gas, pressure, He Chuck 순서로 확대 점검",
        "반복 발생 시 해당 공정 step의 장비 상태 점검"]),
}

_SENSOR_TO_FAMILY = {
    "RF Load":"rf","RF Pwr":"rf","RF Btm Pwr":"rf","RF Btm Rfl Pwr":"rf","RF Bias":"rf",
    "TCP Load":"tcp","TCP Top Pwr":"tcp","TCP Tuner":"tcp","TCP Rfl Pwr":"tcp",
    "Impedance":"matching","Phase Error":"matching","Reflected Power":"matching","Rfl Pwr":"matching",
    "BCl3 Flow":"gas","Cl2 Flow":"gas","Pressure":"pressure","Vat Valve":"pressure",
    "He Press":"he","Backside He":"he","ESC":"he","OES":"oes","Endpt A":"oes","Endpoint":"oes",
}

def _fk_to_label(fk): return _MANUAL_TEXT.get(fk, _MANUAL_TEXT["generic"])[0]

def classify_sensor_family_for_manual(sensor_name, top_block=""):
    sn = str(sensor_name).strip()
    if top_block=="OES" or any(k in sn for k in ("OES","Endpt A","Endpoint","intensity")): return "oes"
    for kw, mapped in _SENSOR_TO_FAMILY.items():
        if kw.lower() in sn.lower(): return mapped
    if re.search(r"\d{3}\.\d", sn): return "oes"
    return "generic"

def field_action_manual_items(wid, selected_sensor="", selected_block=""):
    fi = fdc_map.get(wid, {})
    top_sensor = str(fi.get("top_sensor","")).strip()
    top_block  = str(fi.get("top_block","")).strip()
    suspected  = str(fi.get("suspected_family","")).strip()
    fk_fdc = family_key(suspected) if suspected else "generic"
    if top_block=="OES": fk_fdc="oes"
    if fk_fdc=="generic" and top_sensor:
        for kw, mapped in _SENSOR_TO_FAMILY.items():
            if kw.lower() in top_sensor.lower(): fk_fdc=mapped; break
    fdc_label = _fk_to_label(fk_fdc)
    fk_sensor  = classify_sensor_family_for_manual(selected_sensor, selected_block)
    sensor_label = _fk_to_label(fk_sensor)
    fk_manual = fk_sensor if fk_sensor!="generic" else fk_fdc
    manual_label, items = _MANUAL_TEXT.get(fk_manual, _MANUAL_TEXT["generic"])
    return fdc_label, sensor_label, manual_label, items


PAGES = ["1. 공정 이상 감지 현황", "2. 센서 점검 화면", "3. 조치 기록 공유"]

# ---------------------------------------------------------------------------
# 세션 상태 초기화
# ---------------------------------------------------------------------------
if "selected_wafer" not in st.session_state:
    _cands = sorted(detected_ids, key=lambda w:(wafer_stage(w)[1],-(ratio_max.get(w) or 0),w))
    st.session_state["selected_wafer"] = (_cands[0] if _cands else (all_ids[0] if all_ids else None))
if "active_page"        not in st.session_state: st.session_state["active_page"]        = PAGES[0]
if "replay_on"          not in st.session_state: st.session_state["replay_on"]          = False
if "current_progress"   not in st.session_state: st.session_state["current_progress"]   = None
if "replay_interval_sec" not in st.session_state: st.session_state["replay_interval_sec"] = 1.2
if "progress_resolution" not in st.session_state: st.session_state["progress_resolution"] = 5
if "wf_filter"          not in st.session_state: st.session_state["wf_filter"]          = "전체"
if "batch_filter"       not in st.session_state: st.session_state["batch_filter"]       = "전체 Batch"

# pending 네비게이션
if "pending_page" in st.session_state:
    _pp = st.session_state.pop("pending_page")
    if _pp in PAGES:
        st.session_state["active_page"] = _pp
        st.session_state["page_radio_widget"] = _pp
if "pending_wafer" in st.session_state:
    _pw = st.session_state.pop("pending_wafer")
    if _pw in set(all_ids): st.session_state["selected_wafer"] = _pw
if "pending_block"  in st.session_state: st.session_state["sv_block"]  = st.session_state.pop("pending_block")
if "pending_sensor" in st.session_state: st.session_state["sv_sensor"] = st.session_state.pop("pending_sensor")
if "page_radio_widget" not in st.session_state:
    st.session_state["page_radio_widget"] = st.session_state["active_page"]


# ---------------------------------------------------------------------------
# 사이드바
# ---------------------------------------------------------------------------
with st.sidebar:
    _char_img = first_character_image()
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    if _char_img:
        try:
            _l,_m,_r = st.columns([1,2,1])
            with _m: st.image(_char_img, width=80)
        except Exception:
            st.markdown("<div style='font-size:2rem;text-align:center'>🔧</div>", unsafe_allow_html=True)
    else:
        st.markdown("<div style='font-size:2rem;text-align:center'>🔧</div>", unsafe_allow_html=True)

    st.markdown("""
    <div style="width:100%;text-align:center;margin-top:8px;margin-bottom:16px;">
        <div style="font-size:1.05rem;font-weight:800;color:#0f172a;line-height:1.2;text-align:center;">
            FDC 모니터링
            <span class='dev-badge'>DEV</span>
        </div>
        <div style="font-size:0.78rem;color:#64748b;margin-top:6px;text-align:center;">
            금속 식각 공정 · 실시간 재생 개발 버전
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    page = st.radio("화면", PAGES, key="page_radio_widget", label_visibility="collapsed")
    st.session_state["active_page"] = page

    # ── 실시간 재생 설정 expander ──────────────────────────────────────
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    with st.expander("실시간 재생 설정", expanded=False):
        _res_val = st.selectbox(
            "진행 단위 (해상도)",
            [5, 3, 1],
            index=[5,3,1].index(st.session_state.get("progress_resolution",5)),
            key="progress_resolution",
            format_func=lambda x: f"{x}% 단위",
        )
        _ivl_val = st.selectbox(
            "재생 속도",
            [1.0, 1.2, 1.5],
            index=[1.0,1.2,1.5].index(st.session_state.get("replay_interval_sec",1.2)),
            key="replay_interval_sec",
            format_func=lambda x: f"{x:.1f}초 / 점",
        )

        _c1, _c2 = st.columns(2)
        _is_playing = st.session_state.get("replay_on", False)
        if _is_playing:
            if _c1.button("⏸ 정지", use_container_width=True, key="btn_replay_stop"):
                # 시뮬레이션만 일시정지 — 진행률·필터 그대로 유지
                st.session_state["replay_on"] = False
        else:
            if _c1.button("▶ 재생", use_container_width=True, key="btn_replay_play"):
                st.session_state["replay_on"] = True
                if st.session_state.get("current_progress") is None:
                    st.session_state["current_progress"] = st.session_state["progress_resolution"]
        if _c2.button("초기화", use_container_width=True, key="btn_replay_reset"):
            # 시뮬레이션 진행률만 초기화 — 필터는 건드리지 않음
            st.session_state["replay_on"] = False
            st.session_state["current_progress"] = None

        # 현재 재생 진행 표시
        _cur_p = st.session_state.get("current_progress")
        if _cur_p is not None:
            _pct_int = int(_cur_p)
            st.markdown(
                f"<div style='font-size:0.75rem;color:#64748b;margin-top:4px'>"
                f"현재 진행률: <b style='color:#2563eb'>{_pct_int}%</b></div>"
                f"<div class='replay-bar'><div class='replay-bar-inner' style='width:{_pct_int}%'></div></div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown("<div style='font-size:0.75rem;color:#94a3b8;margin-top:4px'>재생 전</div>",
                        unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------
def batch_of(wid): return int(wid) // 100

def batch_stats(b):
    tot = sum(1 for w in all_ids if batch_of(w)==b)
    det_n = sum(1 for w in detected_ids if batch_of(w)==b)
    return tot, det_n

def fmt_wafer(wid):
    cls = wafer_stage(wid)[2]
    sym = {"red":"🔴","amber":"🟠","green":"🟢","blue":"🔵"}.get(cls,"·")
    return f"{sym} {wid}"

def filtered_ids():
    flt  = st.session_state.get("wf_filter","전체")
    bflt = st.session_state.get("batch_filter","전체 Batch")
    ids  = list(all_ids)
    if flt in STAGE_RANK: ids=[w for w in ids if wafer_stage(w)[0]==flt]
    if bflt!="전체 Batch":
        try:
            b_num=int(bflt.replace("Batch_",""))
            ids=[w for w in ids if batch_of(w)==b_num]
        except ValueError: pass
    return sorted(ids, key=lambda w:(wafer_stage(w)[1],-(ratio_max.get(w) or 0),w))

def mark_page1_filter_changed():
    st.session_state["page1_filter_changed"] = True

def get_spc_state_for_wafer(wid, progress_pct=None):
    """현재 진행률(또는 전체 최대)의 SPC 상태 반환. (spc_state, lamp_color, blink)"""
    if spc_df is None: return ("—","gray",False)
    wdf = spc_df[spc_df["wafer_id"]==wid]
    if wdf.empty: return ("—","gray",False)
    if progress_pct is not None:
        wdf = wdf[wdf["progress_pct"]<=progress_pct]
    if wdf.empty: return ("정상","blue",False)
    last = wdf.sort_values("progress_pct").iloc[-1]
    return (last["spc_state"], last["lamp_color"], bool(last["blink"]))


def render_page_header(title, subtitle, show_filters=False,
                       show_sensor_filters=False, sensor_block_opts=None,
                       current_progress=None):
    _char_img = first_character_image()

    def render_header_identity():
        _ic, _ti = st.columns([0.48, 2.52])
        with _ic:
            if _char_img:
                try:
                    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
                    st.image(_char_img, width=100)
                except Exception:
                    st.html("<div style='width:64px;height:64px;border-radius:18px;background:linear-gradient(135deg,#1d4ed8,#1e3a8a);font-size:2rem;display:flex;align-items:center;justify-content:center;color:#fff'>📈</div>")
            else:
                st.html("<div style='width:64px;height:64px;border-radius:18px;background:linear-gradient(135deg,#1d4ed8,#1e3a8a);font-size:2rem;display:flex;align-items:center;justify-content:center;color:#fff'>📈</div>")
        with _ti:
            replay_info = ""
            if st.session_state.get("replay_on") and current_progress is not None:
                replay_info = (f"<span style='font-size:0.82rem;color:#2563eb;font-weight:700;"
                               f"margin-left:10px'>실시간 재생중 · {int(current_progress)}%</span>")
            st.markdown(
                f"<div class='unified-header-text'>"
                f"<div class='unified-header-title'>{title}"
                f"<span class='dev-badge'>DEV</span>{replay_info}</div>"
                f"<div class='unified-header-subtitle'>{subtitle}</div></div>",
                unsafe_allow_html=True,
            )

    with st.container(border=True, key="page_header"):
        if show_filters:
            _batch_opts = ["전체 Batch"] + [f"Batch_{b}" for b in sorted(set(batch_of(w) for w in all_ids))]
            _cl, _cf1, _cf2 = st.columns([4.0,1.2,1.2])
            with _cl: render_header_identity()
            _wf_dot = {"전체":"#94a3b8","긴급 점검":"#dc2626","주의 점검":"#f59e0b",
                       "관찰":"#16a34a","정상":"#2563eb","완료":"#2563eb"}.get(
                st.session_state.get("wf_filter","전체"),"#94a3b8")
            with _cf1:
                st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-size:0.72rem;color:#64748b;font-weight:700;margin-bottom:4px'>"
                            f"<span style='display:inline-block;width:9px;height:9px;border-radius:50%;"
                            f"background:{_wf_dot};vertical-align:middle;margin-right:5px'></span>점검 상태</div>",
                            unsafe_allow_html=True)
                st.selectbox("점검 상태",["전체","긴급 점검","주의 점검","관찰","정상","완료"],
                             key="wf_filter",label_visibility="collapsed",on_change=mark_page1_filter_changed)
            with _cf2:
                st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
                st.markdown("<div style='font-size:0.72rem;color:#64748b;font-weight:700;margin-bottom:4px'>Batch 필터</div>",
                            unsafe_allow_html=True)
                st.selectbox("Batch 필터",_batch_opts,key="batch_filter",label_visibility="collapsed",
                             on_change=mark_page1_filter_changed)
        elif show_sensor_filters:
            _blk_opts = sensor_block_opts or list(RAW_FILES.keys())
            _cl,_cf1,_cf2 = st.columns([4.0,1.2,2.0])
            with _cl: render_header_identity()
            with _cf1:
                st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                _block = st.selectbox("데이터 구분",_blk_opts,key="sv_block",label_visibility="visible")
            try:
                _raw_opts = load_raw_block(_block)
                _sensors  = raw_sensor_cols(_raw_opts)
            except Exception: _sensors=[]
            if st.session_state.get("sv_sensor") not in _sensors:
                st.session_state["sv_sensor"] = _sensors[0] if _sensors else None
            with _cf2:
                st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                _sensor = st.selectbox("점검 센서",_sensors,key="sv_sensor",label_visibility="visible")
            return _block, _sensor
        else:
            _cl,_ = st.columns([4.0,2.4])
            with _cl: render_header_identity()
    return None


def kpi_row(sel, current_progress=None):
    label,_,cls = wafer_stage(sel)
    detected     = sel in detected_ids
    sensor, fam  = wfields(sel)
    spc_state, spc_color, spc_blink = get_spc_state_for_wafer(sel, current_progress)
    if detected and fam: cause_v, cause_s = (sensor or "센서 미특정"), family_view(fam)
    elif detected:       cause_v, cause_s = (sensor or "센서 미특정"), "장비 조건"
    else:                cause_v, cause_s = "정상", "이상 없음"
    b = batch_of(sel)
    btot, bdet = batch_stats(b)
    _slabel = normalize_status_label(label)
    _sc  = STATUS_COLOR.get(_slabel,"#2563eb")
    _sb  = STATUS_BORDER.get(_slabel,"#94a3b8")
    _spc_lamp = spc_lamp_html(spc_state, spc_blink)
    html = (
        f"<div class='kpi2'><div class='k2-label'>불량률</div>"
        f"<div class='k2-val'>{n_detect} / {n_total}장</div>"
        f"<div class='k2-sub'>이상 감지 {n_detect}장 · 전체 {n_total}장</div></div>"
        f"<div class='kpi2' style='border-color:{_sb}'><div class='k2-label'>이상 예측 원인</div>"
        f"<div class='k2-val' style='color:{_sc};font-size:1.3rem'>{cause_v}</div>"
        f"<div class='k2-sub'>{cause_s}</div></div>"
        f"<div class='kpi2' style='border-color:{_sb}'><div class='k2-label'>선택 WAFER</div>"
        f"<div class='k2-val' style='color:{_sc}'>{sel}</div>"
        f"<div class='k2-sub'>점검 단계: {_slabel}</div></div>"
        f"<div class='kpi2'><div class='k2-label'>현재 SPC 상태</div>"
        f"<div class='k2-val' style='font-size:1.1rem'>{_spc_lamp}</div>"
        f"<div class='k2-sub'>SPC Rule 기준 · 현재 진행률 기준</div></div>"
    )
    st.html(f"<div class='kpi-grid'>{html}</div>")


def process_summary_panel(sel, current_progress=None):
    label,_,cls = wafer_stage(sel)
    detected     = sel in detected_ids
    sensor, fam  = wfields(sel)
    di  = det_map.get(sel,{})
    seg = segment_with_pct(di.get("first_detect_progress")) if detected else "이상 없음"
    famv= family_view(fam) if (detected and fam) else ("장비 조건" if detected else "—")
    pdir= check_direction(fam,detected) if detected else "정상 — 별도 확인 불필요"
    ratio  = ratio_max.get(sel)
    ratio_s= f"{ratio:.2f}" if (ratio is not None and not pd.isna(ratio)) else "—"
    n_done = sum(1 for w in all_ids if review.get(w,{}).get("status")=="완료")
    spc_state, spc_lc, spc_blink = get_spc_state_for_wafer(sel, current_progress)
    _spc_lamp = spc_lamp_html(spc_state, spc_blink)
    rows=[
        ("선택 wafer",f"<b>{sel}</b> &nbsp;<span class='bdg {cls}'>{normalize_status_label(label)}</span>"),
        ("이탈 시작",seg),("점검 센서",sensor if detected else "—"),("점검 계열",famv),("점검 방향",pdir),
        ("현재 SPC 상태",_spc_lamp),
        ("__sep__",""),
        ("전체 wafer",f"{n_total}장"),("이상 감지",f"<b style='color:#b42318'>{n_detect}장</b>"),
        ("우선 점검(FDC)",f"{n_genuine}장"),("처리 완료",f"{n_done}장"),
        ("선택 wafer Q 최대비",ratio_s),
    ]
    body=""
    for k,v in rows:
        if k=="__sep__": body+="<div class='sum-sep'></div>"
        else: body+=f"<div class='sum-row'><span class='sum-k'>{k}</span><span class='sum-v'>{v}</span></div>"
    st.html(f"<div class='sumcard'><div class='sec-title'>공정 요약 정보</div>{body}</div>")


def summary_panel(sel):
    label,_,cls = wafer_stage(sel)
    detected     = sel in detected_ids
    sensor, fam  = wfields(sel)
    di = det_map.get(sel,{})
    fd = di.get("first_detect_progress")
    if detected and fam:
        ilsa,psens,pfam = segment_with_pct(fd), sensor, family_view(fam)
        pdir = f"{sensor}와 같은 {family_view(fam)} 계열 센서를 우선 확인"
    elif detected:
        ilsa,psens,pfam,pdir = segment_with_pct(fd),"센서 미특정","장비 조건","장비 조건 변화 확인"
    else:
        ilsa,psens,pfam,pdir = "이상 없음","—","—","정상 — 별도 확인 불필요"
    st.html(
        f"<div class='wpanel {cls}'>"
        f"<div class='w-head'><span class='w-id'>선택 wafer {sel}</span>"
        f"<span class='bdg-lg {cls}'>{normalize_status_label(label)}</span></div>"
        f"<div class='w-grid'><span>이탈 시작: <b>{ilsa}</b></span>"
        f"<span>점검 센서: <b>{psens}</b></span>"
        f"<span>점검 계열: <b>{pfam}</b></span></div>"
        f"<div class='w-rec'>점검 방향: {pdir}</div></div>"
    )


# Q chart — 재생 모드 진행률 필터 지원
def ialike_chart(sel, current_progress=None):
    wq = q[q["wafer_id"]==sel].sort_values("progress_pct").reset_index(drop=True)
    if current_progress is not None:
        wq = wq[wq["progress_pct"]<=current_progress]
    if wq.empty:
        st.info("이 진행률 구간에 데이터가 없습니다.")
        return
    prog = wq["progress_pct"].tolist()
    qs   = wq["Q_score"].tolist()
    th   = wq["Q_threshold"].tolist()
    exmask = (wq["Q_score"]>wq["Q_threshold"]).tolist()
    fd   = det_map.get(sel,{}).get("first_detect_progress")
    fig  = go.Figure()
    for s,e in exceed_segments(prog,exmask):
        fig.add_vrect(x0=s-5,x1=e+5,fillcolor=C_BAND,line_width=0)
    fig.add_trace(go.Scatter(x=prog,y=qs,name="선택 wafer 이탈 정도",mode="lines+markers",
                             line=dict(color=C_Q,width=3.5),marker=dict(size=7)))
    fig.add_trace(go.Scatter(x=prog,y=th,name="정상 기준선",mode="lines",
                             line=dict(color=C_THR,width=2.4,dash="dash")))
    ex_x=[p for p,m in zip(prog,exmask) if m]
    ex_y=[v for v,m in zip(qs,exmask)   if m]
    if ex_x:
        fig.add_trace(go.Scatter(x=ex_x,y=ex_y,name="기준선 초과 지점",mode="markers",
                                 marker=dict(color=C_EXCEED,size=12,line=dict(color="white",width=1.5))))
    if sel in detected_ids and fd is not None and not pd.isna(fd):
        fdv=float(fd)
        if current_progress is None or fdv<=current_progress:
            fig.add_vline(x=fdv,line=dict(color=C_EXCEED,width=2.0,dash="dot"))
            _xa="left" if fdv<=20 else ("right" if fdv>=90 else "center")
            fig.add_annotation(x=fdv,xref="x",yref="paper",y=0.98,yanchor="top",xanchor=_xa,
                               text=f"이탈 시작 · {segment_name(fdv)}",showarrow=False,
                               font=dict(color=C_EXCEED,size=12),bgcolor="rgba(255,255,255,0.78)")
    fig.update_layout(height=420,margin=dict(l=10,r=12,t=30,b=18),
                      plot_bgcolor="white",paper_bgcolor="white",hovermode="x unified",
                      legend=dict(orientation="h",yanchor="bottom",y=1.0,x=0,
                                  font=dict(size=12),bgcolor="rgba(0,0,0,0)"),font=dict(size=13))
    fig.update_xaxes(title_text="식각 진행률 (%)",tickvals=prog,ticksuffix="%",
                     gridcolor="#eef1f5",showline=True,linecolor="#e4e7ec",
                     title_font=dict(size=15),tickfont=dict(size=13))
    fig.update_yaxes(title_text="이탈 정도",gridcolor="#eef1f5",zeroline=False,
                     title_font=dict(size=15),tickfont=dict(size=13))
    st.plotly_chart(fig,width="stretch",config={"displayModeBar":False})


def interp_card(sel):
    detected = sel in detected_ids
    sensor, fam = wfields(sel)
    di  = det_map.get(sel,{})
    seg = segment_short(di.get("first_detect_progress"))
    cosee=[c for _,c in related_real_sensors(sel)]
    _ic_title, _ic_img = st.columns([5,1])
    _ic_title.markdown("<div class='sec-title'>🧭 점검 해석</div>",unsafe_allow_html=True)
    with _ic_img: render_character_image("summary")
    if not detected:
        st.html("<div class='gcard'><div class='muted'>정상 범위입니다. 별도 확인 항목이 없습니다.</div></div>")
        return
    if fam:
        summ=(f"<ul><li>선택 wafer는 <b>{seg} 구간</b>부터 정상 기준선을 벗어났습니다.</li>"
              f"<li>{sensor}가 이상 신호와 함께 크게 반응했습니다.</li></ul>")
        steps=(f"<ol><li>{sensor} 변화에서 이탈 시작 구간과 같은 시간대에 흔들림이 있는지 확인</li>"
               f"<li>{sensor}와 같은 {family_view(fam)} 계열 센서도 함께 확인</li>"
               f"<li>{', '.join(cosee[:5]) if cosee else sensor} 순서로 추가 확인</li></ol>")
    else:
        summ=(f"<ul><li>선택 wafer는 <b>{seg} 구간</b>부터 정상 기준선을 벗어났습니다.</li>"
              "<li>특정 센서가 두드러지게 반응하지는 않았습니다.</li></ul>")
        steps=(f"<ol><li>이탈 시작 구간의 센서 흔들림이 있는지 확인</li>"
               "<li>장비 조건 변화가 있었는지 확인</li>"
               f"<li>{', '.join(cosee[:5]) if cosee else '관련 계열 센서'} 순서로 추가 확인</li></ol>")
    st.html("<div class='gcard'><div class='g-h'>🔎 이상 감지 요약</div>"+summ+
            "<div class='g-h'>🛠️ 점검 우선순서</div>"+steps+
            "<div class='g-h'>🔬 같이 점검할 센서</div></div>")
    chips_data = related_real_sensors(sel)
    if chips_data:
        n_per_row=3
        for _rs in range(0,len(chips_data),n_per_row):
            _row=chips_data[_rs:_rs+n_per_row]
            _bcols=st.columns(len(_row))
            for _bi,(_blk,_col) in enumerate(_row):
                _lbl=f"⭐ {_col}" if (_rs==0 and _bi==0) else _col
                if _bcols[_bi].button(_lbl,key=f"snav_{sel}_{_rs+_bi}_{_col}",use_container_width=True):
                    st.session_state["pending_page"]=PAGES[1]
                    st.session_state["pending_wafer"]=sel
                    st.session_state["pending_block"]=_blk
                    st.session_state["pending_sensor"]=_col
                    st.rerun()
    else:
        st.html(f"<div><span class='pill'>{sensor}</span></div>")


# ===========================================================================
# Page 1 : 공정 이상 감지 현황
# ===========================================================================
if page == PAGES[0]:
    _cur_prog = st.session_state.get("current_progress")  # None = 재생 전 (전체 표시)

    render_page_header("공정 이상 감지 현황",
                       "MPCA 기반 이상 감지 · 금속 식각 공정 · 실시간 재생 DEV",
                       show_filters=True,
                       current_progress=_cur_prog)

    _cur_filter_sig = (st.session_state.get("wf_filter","전체"),
                       st.session_state.get("batch_filter","전체 Batch"))
    if "prev_page1_filter_sig" not in st.session_state:
        st.session_state["prev_page1_filter_sig"] = _cur_filter_sig
    _cand_after_filter    = filtered_ids()
    _filter_changed_by_user = st.session_state.pop("page1_filter_changed", False)
    if _filter_changed_by_user:
        st.session_state["prev_page1_filter_sig"] = _cur_filter_sig
        if _cand_after_filter:
            st.session_state["selected_wafer"] = _cand_after_filter[0]
            st.rerun()

    sel = st.session_state["selected_wafer"]

    # KPI 4종 (SPC 상태 포함)
    kpi_row(sel, current_progress=_cur_prog)

    # Q chart (좌) + 점검 해석 (우)
    gcol, icol = st.columns([65,35], gap="small")
    with gcol:
        with st.container(border=True, key="chart_card"):
            sel = st.session_state["selected_wafer"]
            _chart_title = "선택 wafer 공정 이탈 흐름"
            if _cur_prog is not None:
                _chart_title += f" (현재 {int(_cur_prog)}% 까지)"
            st.markdown(f"<div class='sec-title'>{_chart_title}</div>", unsafe_allow_html=True)
            ialike_chart(sel, current_progress=_cur_prog)
    with icol:
        with st.container(border=True, key="selected_wafer_card"):
            # SPC 상태 표시
            _spc_s, _spc_lc, _spc_blink = get_spc_state_for_wafer(sel, _cur_prog)
            if _spc_s not in ("—", "정상"):
                _lamp_html = spc_lamp_html(_spc_s, _spc_blink)
                _msg_map = {
                    "관찰": "현재 진행률 기준 관찰",
                    "주의": "현재 진행률 기준 주의 - 추가 확인 필요",
                    "경고": "SPC Rule 기준 경고 - 추가 확인 필요",
                    "긴급 경고": "SPC Rule 기준 긴급 경고 - 점검 필요",
                }
                _msg = _msg_map.get(_spc_s, "")
                _lamp_color_val = SPC_LAMP.get(_spc_s, {}).get("color", "#94a3b8")
                st.markdown(
                    f"<div style='background:#f8fafc;border-left:4px solid "
                    f"{_lamp_color_val};border-radius:8px;"
                    f"padding:8px 12px;margin-bottom:10px;font-size:0.88rem;'>"
                    f"현재 SPC 상태: {_lamp_html}<br>"
                    f"<span style='color:#64748b;font-size:0.80rem'>{_msg}</span></div>",
                    unsafe_allow_html=True,
                )
            interp_card(sel)

    # 점검 대상 wafer 목록 (좌) + 공정 요약 (우)
    tcol, scol = st.columns([2.4,1], gap="small")
    with tcol:
        with st.container(border=True, key="wafer_table_card"):
            st.markdown("<div class='sec-title'>점검 대상 wafer 목록</div>", unsafe_allow_html=True)
            n_done_tbl = sum(1 for w in all_ids if review.get(w,{}).get("status")=="완료")
            st.markdown(
                f"<div class='oneline'>전체 {n_total}장 · 확인 필요 {n_detect}장 · "
                f"우선 점검(FDC) {n_genuine}장 · 일시 관찰 {n_nonspecific}장 · 완료 {n_done_tbl}장</div>",
                unsafe_allow_html=True)
            _tbl_records=[]
            for wid in filtered_ids():
                label,_,_ = wafer_stage(wid)
                sensor, fam = wfields(wid)
                di = det_map.get(wid,{})
                rstat = review.get(wid,{}).get("status","미확인")
                detected = wid in detected_ids
                _spc_s2, _spc_lc2, _ = get_spc_state_for_wafer(wid, _cur_prog)
                _tbl_records.append({
                    "선택":     "✓" if wid==sel else "",
                    "확인 상태": normalize_status_label(rstat),
                    "Wafer ID": wid,
                    "점검 단계": normalize_status_label(label),
                    "SPC 상태":  _spc_s2,
                    "이탈 시작": segment_short(di.get("first_detect_progress")) if detected else "—",
                    "점검 센서": sensor if detected else "—",
                    "점검 계열": family_view(fam) if (detected and fam) else ("장비 조건" if detected else "—"),
                })
            if _tbl_records:
                _tbl_df = pd.DataFrame(_tbl_records)
                _tbl_event = st.dataframe(
                    _tbl_df, use_container_width=True, hide_index=True, height=330,
                    selection_mode="single-row", on_select="rerun", key="wafer_table_selection",
                    column_config={
                        "선택":     st.column_config.TextColumn("",     width="small"),
                        "확인 상태": st.column_config.TextColumn("확인 상태", width="small"),
                        "Wafer ID": st.column_config.NumberColumn("Wafer ID", width="small"),
                        "점검 단계": st.column_config.TextColumn("점검 단계", width="small"),
                        "SPC 상태":  st.column_config.TextColumn("SPC 상태",  width="small"),
                        "이탈 시작": st.column_config.TextColumn("이탈 시작",  width="medium"),
                        "점검 센서": st.column_config.TextColumn("점검 센서",  width="small"),
                        "점검 계열": st.column_config.TextColumn("점검 계열",  width="medium"),
                    },
                )
                if _tbl_event.selection.rows:
                    _clicked = int(_tbl_df.iloc[_tbl_event.selection.rows[0]]["Wafer ID"])
                    if _clicked != st.session_state["selected_wafer"]:
                        st.session_state["selected_wafer"] = _clicked
                        st.rerun()
            else:
                st.caption("필터 조건에 해당하는 wafer가 없습니다.")
    with scol:
        process_summary_panel(sel, current_progress=_cur_prog)

    # 확인 상태 / 메모 입력
    with st.container(border=True, key="review_input_card"):
        st.markdown(f"<div class='sec-title'>확인 상태 · 메모 입력 — wafer {sel}</div>", unsafe_allow_html=True)
        cur = review.get(sel, {"status":"미확인","memo":""})
        opts=["미확인","확인 중","완료"]
        with st.form(f"rev_{sel}", border=False):
            fc1,fc2,fc3=st.columns([1.3,3,0.8])
            new_status = fc1.selectbox("확인 상태",opts,
                                        index=opts.index(cur.get("status","미확인")),
                                        label_visibility="collapsed")
            new_memo = fc2.text_input("메모",value=cur.get("memo",""),
                                       placeholder="확인 내용·조치 결과 입력",label_visibility="collapsed")
            ok = fc3.form_submit_button("저장",type="primary")
        if ok:
            review[sel]={"status":new_status,"memo":new_memo or "","handled":new_status=="완료"}
            save_review_dict(review); st.rerun()

    # ── 재생 자동 진행 (페이지 1 렌더 후 실행) ──────────────────────────
    if st.session_state.get("replay_on"):
        _resolution_val = st.session_state.get("progress_resolution", 5)
        _interval_val   = st.session_state.get("replay_interval_sec", 1.2)
        _cur_p2         = st.session_state.get("current_progress") or _resolution_val
        if _cur_p2 < 100:
            time.sleep(float(_interval_val))
            st.session_state["current_progress"] = min(100, _cur_p2 + _resolution_val)
            st.rerun()
        else:
            st.session_state["replay_on"] = False


# ===========================================================================
# Page 2 : 센서 점검 화면
# ===========================================================================
elif page == PAGES[1]:
    sel = st.session_state["selected_wafer"]
    sensor0, fam0 = wfields(sel)
    fi = fdc_map.get(sel)
    default_block  = (str(fi.get("top_block","")).strip() if fi else "")
    if default_block not in RAW_FILES: default_block="EV"
    try:    default_sensors = raw_sensor_cols(load_raw_block(default_block))
    except: default_sensors = []
    default_sensor = sensor0 if sensor0 in default_sensors else (default_sensors[0] if default_sensors else None)

    if st.session_state.get("sv_wafer") != sel:
        st.session_state["sv_wafer"] = sel
        if st.session_state.get("sv_block") not in RAW_FILES:
            st.session_state["sv_block"] = default_block
        try:    _cur_blk_sensors=raw_sensor_cols(load_raw_block(st.session_state["sv_block"]))
        except: _cur_blk_sensors=[]
        if st.session_state.get("sv_sensor") not in _cur_blk_sensors:
            st.session_state["sv_sensor"] = default_sensor

    block_opts = list(RAW_FILES.keys())
    if st.session_state.get("sv_block") not in block_opts:
        st.session_state["sv_block"] = default_block
    block, sensor = render_page_header("센서 점검 화면","정상 wafer 기준과 선택 wafer 센서 흐름 비교",
                                       show_sensor_filters=True, sensor_block_opts=block_opts)
    raw_df = load_raw_block(block)

    di  = det_map.get(sel,{})
    fd  = di.get("first_detect_progress")
    sub = raw_df[raw_df["wafer_id"]==sel].sort_values("progress") if not raw_df.empty else pd.DataFrame()
    has_data = not (sub.empty or sensor is None or (sensor not in sub.columns) or sub[sensor].dropna().empty)
    nt        = normal_trend(block, sensor, tuple(sorted(normal_ids))) if has_data else None
    direction = sensor_direction(block, sensor, sel, normal_ids) if has_data else None
    cmp_txt   = normalize_compare_label(direction)

    _stage_lbl2,_,_ = wafer_stage(sel)
    _slabel2 = normalize_status_label(_stage_lbl2)
    _sc2  = STATUS_COLOR.get(_slabel2,"#2563eb")
    _sb2  = STATUS_BORDER.get(_slabel2,"#94a3b8")
    _cmp_color = ("#b42318" if direction in ("정상보다 높음","정상보다 낮음")
                  else ("#1a7f37" if direction=="정상과 유사" else "#64748b"))
    _kpi2_html=(
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

    gcol,icol = st.columns([65,35], gap="small")
    with gcol:
        with st.container(border=True, key="sensor_chart_card"):
            st.markdown(f"<div class='sec-title'>선택 센서 원본 시계열 — wafer {sel} · {sensor}</div>",unsafe_allow_html=True)
            if not has_data:
                st.info(f"이 구분({block})에 wafer {sel}의 센서 데이터가 없습니다.")
            else:
                fig=go.Figure()
                if nt is not None:
                    xs,mean,std,kk=nt
                    fig.add_trace(go.Scatter(x=np.concatenate([xs,xs[::-1]]),
                                             y=np.concatenate([mean+std,(mean-std)[::-1]]),
                                             fill="toself",fillcolor="rgba(148,163,184,0.15)",
                                             line=dict(width=0),hoverinfo="skip",name="정상 범위"))
                    fig.add_trace(go.Scatter(x=xs,y=mean,mode="lines",name="정상 평균",
                                             line=dict(color="#94a3b8",width=1.8,dash="dot")))
                fig.add_trace(go.Scatter(x=sub["progress"],y=sub[sensor],mode="lines+markers",
                                         name="선택 wafer",line=dict(color=C_Q,width=2.2),
                                         marker=dict(size=4)))
                if sel in detected_ids and fd is not None and not pd.isna(fd):
                    fig.add_vline(x=float(fd),line=dict(color=C_EXCEED,width=1.3,dash="dot"))
                    fig.add_annotation(x=float(fd),xref="x",yref="paper",y=0.98,
                                       yanchor="top",xanchor="center",text="이탈 시작",showarrow=False,
                                       font=dict(color=C_EXCEED,size=10),bgcolor="rgba(255,255,255,0.78)")
                fig.update_layout(height=330,margin=dict(l=6,r=10,t=20,b=4),
                                  plot_bgcolor="white",paper_bgcolor="white",hovermode="x unified",
                                  legend=dict(orientation="h",yanchor="bottom",y=1.0,x=0,
                                              font=dict(size=10),bgcolor="rgba(0,0,0,0)"),font=dict(size=11))
                fig.update_xaxes(title_text="식각 진행률 (%)",range=[0,100],ticksuffix="%",
                                 gridcolor="#eef1f5",showline=True,linecolor="#e4e7ec")
                fig.update_yaxes(title_text=sensor,gridcolor="#eef1f5",zeroline=False)
                st.plotly_chart(fig,width="stretch",config={"displayModeBar":False})
    with icol:
        with st.container(border=True, key="sensor_result_card"):
            st.markdown("<div class='sec-title'>센서 점검 해석</div>",unsafe_allow_html=True)
            _fam2=wfields(sel)[1]
            _pdir2=(f"{family_view(_fam2)} 계열 센서와 함께 확인" if _fam2 else "장비 조건 변화 확인")
            _rel2="평균 기준 차이 있음" if direction in ("정상보다 높음","정상보다 낮음") else "구간별 추가 확인 필요"
            st.html(f"<div style='font-size:0.92rem;line-height:2.0'>"
                    f"<div><span class='pill'>선택 센서</span> <b>{sensor}</b></div>"
                    f"<div><span class='pill'>센서 상태</span> {cmp_txt}</div>"
                    f"<div><span class='pill'>이탈 구간</span> {_rel2}</div>"
                    f"<div><span class='pill'>점검 방향</span> {_pdir2}</div></div>")

    bot_l,bot_r=st.columns([55,45],gap="small")
    with bot_l:
        with st.container(border=True, key="sensor_chip_card"):
            st.markdown("<div class='sec-title'>🔬 같이 점검할 센서</div>",unsafe_allow_html=True)
            st.markdown("<div class='oneline'>클릭하면 이 화면의 차트가 바뀝니다.</div>",unsafe_allow_html=True)
            _chips2=related_real_sensors(sel)
            if _chips2:
                _n=min(len(_chips2),6)
                _chip_cols=st.columns(_n)
                for _ci,(_cblk,_ccol) in enumerate(_chips2[:_n]):
                    _ctag="⭐ " if _ci==0 else ""
                    if _chip_cols[_ci].button(f"{_ctag}{_ccol}",key=f"chip2_{sel}_{_cblk}_{_ccol}",use_container_width=True):
                        st.session_state["pending_block"]=_cblk
                        st.session_state["pending_sensor"]=_ccol
                        st.session_state["pending_wafer"]=sel; st.rerun()
            else:
                st.caption("이 wafer에 연계된 센서 정보가 없습니다.")
    with bot_r:
        with st.container(border=True, key="check_guide_card"):
            _cur_sensor=sensor or st.session_state.get("sv_sensor","")
            _cur_block =block  or st.session_state.get("sv_block","")
            _fdc_lbl,_sensor_lbl,_manual_lbl,_manual_items = field_action_manual_items(
                sel, selected_sensor=_cur_sensor, selected_block=_cur_block)
            st.markdown("<div class='sec-title'>📋 현장 조치 매뉴얼</div>",unsafe_allow_html=True)
            st.html(
                "<div style='font-size:0.90rem;line-height:1.8;color:#334155'>"
                f"<div><span style='color:#64748b'>FDC 기준 점검 계열:</span> <b>{_fdc_lbl}</b></div>"
                f"<div><span style='color:#64748b'>현재 확인 센서:</span> <b>{_cur_sensor or '—'}</b></div>"
                f"<div><span style='color:#64748b'>센서 기준 계열:</span> <b>{_sensor_lbl}</b></div>"
                "<div style='font-size:0.78rem;line-height:1.5;color:#64748b;margin-top:4px;margin-bottom:8px'>"
                "현재 확인 센서는 관련 센서 원본 흐름 확인용이며, 기본 조치 방향은 FDC 기준 점검 계열을 우선합니다."
                "</div>"
                f"<div style='font-weight:800;color:#0f172a;margin-bottom:2px'>표시 매뉴얼: {_manual_lbl}</div>"
                + "".join(f"<div>{i+1}) {item}</div>" for i,item in enumerate(_manual_items))
                + "</div>"
            )


# ===========================================================================
# Page 3 : 조치 기록 공유
# ===========================================================================
elif page == PAGES[2]:
    render_page_header("조치 기록 공유","확인 상태와 조치 내용 공유")

    n_done = sum(1 for w in detected_ids if review.get(w,{}).get("status")=="완료")
    n_prog = sum(1 for w in detected_ids if review.get(w,{}).get("status")=="확인 중")
    n_unseen = max(0, n_detect - n_done - n_prog)
    upds = [review[w]["updated"] for w in review if review.get(w,{}).get("updated")]
    last_upd = max(upds) if upds else "—"
    m1,m2,m3,m4=st.columns(4)
    m1.html(f"<div class='mini'><div class='m-l'>미확인</div><div class='m-v'>{n_unseen}</div></div>")
    m2.html(f"<div class='mini'><div class='m-l'>확인 중</div><div class='m-v'>{n_prog}</div></div>")
    m3.html(f"<div class='mini'><div class='m-l'>완료</div><div class='m-v'>{n_done}</div></div>")
    m4.html(f"<div class='mini'><div class='m-l'>최근 업데이트</div><div class='m-v' style='font-size:0.84rem'>{last_upd}</div></div>")

    with st.expander("조치기록 초기화", expanded=False):
        st.caption("operator_review_status_dev.csv의 처리 상태, 메모, 업데이트 시간을 초기화합니다.")
        _do_reset = st.checkbox("초기화를 진행합니다", key="reset_review_confirm")
        if st.button("초기화 실행", key="reset_review_btn", disabled=not _do_reset):
            _reset_records = [{"wafer_id":w,"status":"미확인","handled":False,"memo":"","updated_at":""} for w in all_ids]
            pd.DataFrame(_reset_records).to_csv(REVIEW_FILE, index=False)
            st.success("조치 기록이 초기화되었습니다."); st.rerun()

    with st.container(border=True, key="review_table_card"):
        st.markdown("<div class='sec-title'>조치 기록</div>",unsafe_allow_html=True)
        rows=""
        for wid in sorted(detected_ids, key=lambda w:(wafer_stage(w)[1],-(ratio_max.get(w) or 0),w)):
            label,_,cls = wafer_stage(wid)
            sensor,fam  = wfields(wid)
            rv    = review.get(wid,{})
            rstat = rv.get("status","미확인")
            memo  = str(rv.get("memo","") or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            upd   = rv.get("updated","") or "—"
            rows+=(f"<tr><td class='wid'>{wid}</td>"
                   f"<td><span class='bdg {cls}'>{normalize_status_label(label)}</span></td>"
                   f"<td>{sensor}</td><td>{family_view(fam) if fam else '장비 조건'}</td>"
                   f"<td><span class='bdg {rev_cls(rstat)}'>{normalize_status_label(rstat)}</span></td>"
                   f"<td class='memo'>{memo or '—'}</td><td>{upd}</td></tr>")
        st.html("<div class='tbl-wrap'><table class='mon'><thead><tr>"
                "<th>Wafer ID</th><th>점검 단계</th><th>점검 센서</th><th>점검 계열</th>"
                f"<th>확인 상태</th><th>메모</th><th>업데이트 시간</th></tr></thead><tbody>{rows}</tbody></table></div>")

    with st.container(border=False, key="review_input_section"):
        with st.expander("선택 wafer 조치 내용 입력", expanded=False):
            cur_ids = sorted(detected_ids, key=lambda w:(wafer_stage(w)[1],-(ratio_max.get(w) or 0),w)) or sorted(all_ids)
            _cur_sel3 = st.session_state.get("selected_wafer")
            _p3_last  = st.session_state.get("_p3_last_seen_wafer")
            if _cur_sel3 != _p3_last:
                if _cur_sel3 in cur_ids: st.session_state["wafer_p3_widget"] = _cur_sel3
                elif st.session_state.get("wafer_p3_widget") not in cur_ids:
                    st.session_state["wafer_p3_widget"] = cur_ids[0] if cur_ids else None
            st.session_state["_p3_last_seen_wafer"] = _cur_sel3
            sel = st.selectbox("wafer 선택", cur_ids, format_func=fmt_wafer, key="wafer_p3_widget")
            if sel != _cur_sel3 and _cur_sel3 in cur_ids:
                st.session_state["selected_wafer"] = sel; st.rerun()
            cur = review.get(sel, {"status":"미확인","memo":""})
            opts=["미확인","확인 중","완료"]
            with st.form(f"rev3_{sel}", border=False):
                fc1,fc2,fc3=st.columns([1.3,3,0.8])
                new_status = fc1.selectbox("확인 상태",opts,index=opts.index(cur.get("status","미확인")),label_visibility="collapsed")
                new_memo   = fc2.text_input("메모",value=cur.get("memo",""),placeholder="확인 내용·조치 결과 입력",label_visibility="collapsed")
                ok = fc3.form_submit_button("저장",type="primary")
            if ok:
                review[sel]={"status":new_status,"memo":new_memo or "","handled":new_status=="완료"}
                save_review_dict(review); st.rerun()
