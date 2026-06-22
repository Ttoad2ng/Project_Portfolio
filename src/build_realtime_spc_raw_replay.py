#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/build_realtime_spc_raw_replay.py
=====================================
Fine-grained MPCA Q trajectory generator from raw EV/OES/RFM data.

Generates 5%, 3%, 1% resolution Q trajectory and SPC status CSV files.
No interpolation - all Q scores computed directly from raw data at each progress cutoff.

Usage:
    python src/build_realtime_spc_raw_replay.py

Outputs (in outputs/csv/):
    realtime_q_trajectory_raw_5pct.csv
    realtime_q_trajectory_raw_3pct.csv
    realtime_q_trajectory_raw_1pct.csv
    realtime_spc_status_raw_5pct.csv
    realtime_spc_status_raw_3pct.csv
    realtime_spc_status_raw_1pct.csv

Notes:
    - Normal label: fault_name == 'calibration'
    - Scaler/PCA fit only on normal training wafers
    - Group 33 fault wafers (holdout) are not used for fitting
    - Q threshold = 99th percentile of normal training Q scores
    - OES dimensionality reduced to top-20 by variance before combining
"""

import os
import re
import warnings
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data", "raw_optional")
OUT_DIR  = os.path.join(BASE_DIR, "outputs", "csv")
os.makedirs(OUT_DIR, exist_ok=True)

EV_FILE  = os.path.join(DATA_DIR, "ev_data.csv")
OES_FILE = os.path.join(DATA_DIR, "oes_data.csv")
RFM_FILE = os.path.join(DATA_DIR, "rfm_data.csv")

RESOLUTIONS        = [5, 3, 1]
RAW_RECALC_SOURCE  = "raw_ev_oes_rfm_recalculated"
NORMAL_LABEL       = "calibration"
Q_THRESHOLD_PCT    = 99   # percentile for threshold from normal training data
OES_TOP_K          = 20   # top OES wavelength columns by variance


# ---------------------------------------------------------------------------
# Block loading
# ---------------------------------------------------------------------------
def _extract_wafer_key(name):
    m = re.search(r"\d+", str(name))
    return int(m.group()) if m else None


def load_block(filepath, sort_time=True):
    """Load raw sensor CSV, add wafer_key, fault_name, is_fault, exp_group, progress."""
    df = pd.read_csv(filepath)

    # Identify wafer name column
    wn_col = next(
        (c for c in df.columns if "wafer" in c.lower() and "name" in c.lower()),
        next((c for c in df.columns if "wafer" in c.lower()), None),
    )
    if wn_col is None:
        raise ValueError(f"No wafer name column in {filepath}")

    df["wafer_key"] = df[wn_col].apply(_extract_wafer_key)
    df = df.dropna(subset=["wafer_key"]).copy()
    df["wafer_key"] = df["wafer_key"].astype(int)

    # fault_name
    fn_col = next((c for c in df.columns if "fault" in c.lower()), None)
    df["fault_name"] = (
        df[fn_col].fillna(NORMAL_LABEL).astype(str).str.strip()
        if fn_col else NORMAL_LABEL
    )
    df["is_fault"] = df["fault_name"].str.lower() != NORMAL_LABEL.lower()

    # exp_group: 29=Feb, 31=Mar, 33=Apr
    df["exp_group"] = df["wafer_key"].apply(
        lambda k: 29 if k < 3000 else (31 if k < 3200 else 33)
    )

    # Sort by time within wafer (file order if no time column)
    if sort_time:
        tcol = next(
            (c for c in df.columns if c.upper() in ("TIME",)), None
        )
        if tcol:
            df = df.sort_values(["wafer_key", tcol]).reset_index(drop=True)
        else:
            df = df.sort_values("wafer_key").reset_index(drop=True)

    # Progress 0-100% based on row rank within each wafer
    n    = df.groupby("wafer_key")["wafer_key"].transform("size")
    rank = df.groupby("wafer_key").cumcount()
    df["progress"] = (rank / (n - 1).clip(lower=1) * 100.0).where(n > 1, 0.0)

    return df


def _get_sensor_cols(df, additional_exclude=None):
    """Return numeric sensor columns, excluding metadata columns."""
    exc = {"wafer_key", "fault_name", "is_fault", "exp_group", "progress",
           "wafer_names", "wafer_name", "Step Number", "Time", "TIME"}
    if additional_exclude:
        exc.update(additional_exclude)
    return [
        c for c in df.columns
        if c not in exc
        and not c.lower().startswith("unnamed")
        and pd.api.types.is_numeric_dtype(df[c])
    ]


# ---------------------------------------------------------------------------
# Cumulative mean precomputation
# ---------------------------------------------------------------------------
def precompute_cum_means(df, sensor_cols, wafer_keys):
    """
    Pre-compute cumulative mean vectors for each wafer (expanding window).
    Returns dict: {wafer_key: DataFrame(index=row_num, columns=sensor_cols)}
    """
    result = {}
    for wk in wafer_keys:
        sub = df[df["wafer_key"] == wk][sensor_cols].reset_index(drop=True)
        filled = sub.fillna(sub.mean()).fillna(0.0)
        result[wk] = filled.expanding().mean()
    return result


def features_at_progress(cum_dict, wafer_keys, n_rows_dict, p_pct):
    """
    Get cumulative mean feature vector at progress p_pct% for every wafer.
    Uses at least 1 row per wafer (no zero-row case).
    Returns np.ndarray of shape (len(wafer_keys), n_sensor_cols).
    """
    sample_cm = next(v for v in cum_dict.values() if v is not None and len(v) > 0)
    n_cols = sample_cm.shape[1]
    arr = np.zeros((len(wafer_keys), n_cols), dtype=float)
    for i, wk in enumerate(wafer_keys):
        cm = cum_dict.get(wk)
        n  = n_rows_dict.get(wk, 0)
        if cm is None or n == 0:
            continue
        use_n   = max(1, int(np.floor(n * p_pct / 100.0)))
        row_idx = min(n - 1, use_n - 1)
        arr[i]  = cm.iloc[row_idx].values
    return arr


# ---------------------------------------------------------------------------
# Q statistic (PCA residual)
# ---------------------------------------------------------------------------
def compute_q(X_scaled, pca):
    """Hotelling Q = sum of squared residuals from PCA reconstruction."""
    X_hat = pca.inverse_transform(pca.transform(X_scaled))
    return np.sum((X_scaled - X_hat) ** 2, axis=1)


def fit_mpca(X_normal_scaled, var_target=0.95, max_comp=50):
    """Fit PCA on normal training data. Returns fitted PCA object."""
    n_samp, n_feat = X_normal_scaled.shape
    cap = min(n_samp - 1, n_feat, max_comp)
    cap = max(cap, 1)
    probe = PCA(n_components=cap).fit(X_normal_scaled)
    cum_v = np.cumsum(probe.explained_variance_ratio_)
    n_comp = max(1, int(np.searchsorted(cum_v, var_target) + 1))
    n_comp = min(n_comp, cap)
    return PCA(n_components=n_comp).fit(X_normal_scaled)


# ---------------------------------------------------------------------------
# SPC rule classification
# ---------------------------------------------------------------------------
def classify_spc_for_wafer(q_ratios, q_scores):
    """
    Apply SPC monitoring rules to a single wafer's Q history.

    Rules (priority high -> low):
        R5 (긴급 경고): Q_ratio >= 1.20  OR  2 consecutive Q_ratio >= 1.00
        R4 (경고):      Q_ratio >= 1.00
        R3 (주의):      Q_ratio >= 0.95  OR  2 consecutive Q_ratio >= 0.90
        R2 (관찰):      Q_ratio >= 0.80  OR  3 consecutive Q_score rising
        R1 (정상):      otherwise

    Returns list of dicts (one per progress step).
    """
    results = []
    n = len(q_ratios)
    for i in range(n):
        qr = float(q_ratios[i])
        qs = float(q_scores[i])

        consec_exceed_2 = (i >= 1 and q_ratios[i] >= 1.0 and q_ratios[i-1] >= 1.0)
        consec_90_2     = (i >= 1 and q_ratios[i] >= 0.9 and q_ratios[i-1] >= 0.9)
        consec_rise_3   = (i >= 2
                           and q_scores[i]   > q_scores[i-1]
                           and q_scores[i-1] > q_scores[i-2])

        if qr >= 1.20 or consec_exceed_2:
            state = "긴급 경고"; lvl = 5
            rule  = "R5: Q_ratio>=1.20" if qr >= 1.20 else "R5: 2연속 임계 초과"
            msg   = "SPC Rule 기준 긴급 경고 - 점검 필요"
            lamp, blink = "red", True

        elif qr >= 1.00:
            state = "경고"; lvl = 4
            rule  = "R4: Q_ratio>=1.00"
            msg   = "SPC Rule 기준 경고 - 추가 확인 필요"
            lamp, blink = "red", True

        elif qr >= 0.95 or consec_90_2:
            state = "주의"; lvl = 3
            rule  = "R3: Q_ratio>=0.95" if qr >= 0.95 else "R3: 2연속 Q_ratio>=0.90"
            msg   = "현재 진행률 기준 주의 - 추가 확인 필요"
            lamp, blink = "orange", True

        elif qr >= 0.80 or consec_rise_3:
            state = "관찰"; lvl = 2
            rule  = "R2: Q_ratio>=0.80" if qr >= 0.80 else "R2: 3연속 Q_score 상승"
            msg   = "현재 진행률 기준 관찰"
            lamp, blink = "green", False

        else:
            state = "정상"; lvl = 1
            rule  = "없음"
            msg   = "정상 범위"
            lamp, blink = "blue", False

        results.append(dict(
            spc_state=state, spc_level=lvl,
            rule_hit=rule, rule_message=msg,
            lamp_color=lamp, blink=blink,
        ))
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    sep = "=" * 62
    print(sep)
    print("  Realtime SPC Raw Replay - Fine-grained MPCA Build Script")
    print(sep)
    print(f"  Raw data dir : {DATA_DIR}")
    print(f"  Output dir   : {OUT_DIR}")
    print(sep)

    # 1. Load blocks
    print("\n[1] Loading raw data blocks ...")
    ev  = load_block(EV_FILE,  sort_time=True)
    oes = load_block(OES_FILE, sort_time=False)
    rfm = load_block(RFM_FILE, sort_time=True)
    print(f"    EV  : {ev['wafer_key'].nunique():3d} wafers | {len(ev):6d} rows")
    print(f"    OES : {oes['wafer_key'].nunique():3d} wafers | {len(oes):6d} rows")
    print(f"    RFM : {rfm['wafer_key'].nunique():3d} wafers | {len(rfm):6d} rows")

    # 2. Inner-join wafer keys
    common_keys = sorted(
        set(ev["wafer_key"]) & set(oes["wafer_key"]) & set(rfm["wafer_key"])
    )
    print(f"\n[2] Inner-join wafer count: {len(common_keys)}")

    # 3. Wafer metadata (from EV master)
    wafer_meta = (ev[ev["wafer_key"].isin(common_keys)]
                    .groupby("wafer_key")[["fault_name", "is_fault", "exp_group"]]
                    .first())
    normal_keys = sorted(wafer_meta.index[~wafer_meta["is_fault"]].tolist())
    fault_keys  = sorted(wafer_meta.index[wafer_meta["is_fault"]].tolist())
    print(f"    Normal wafers : {len(normal_keys)}")
    print(f"    Fault wafers  : {len(fault_keys)}")
    normal_set = set(normal_keys)

    # 4. Sensor column selection
    ev_cols  = _get_sensor_cols(ev)
    rfm_cols = _get_sensor_cols(rfm)

    # OES: select top-K by variance on normal training rows
    oes_num_cols = _get_sensor_cols(oes)
    oes_norm_rows = oes[oes["wafer_key"].isin(normal_keys)][oes_num_cols]
    oes_var = oes_norm_rows.var().sort_values(ascending=False)
    oes_cols = oes_var.head(OES_TOP_K).index.tolist()

    total_feats = len(ev_cols) + len(oes_cols) + len(rfm_cols)
    print(f"\n[3] Feature dimensions:")
    print(f"    EV  cols : {len(ev_cols)}")
    print(f"    OES cols : {len(oes_cols)} (top-{OES_TOP_K} by variance)")
    print(f"    RFM cols : {len(rfm_cols)}")
    print(f"    Combined : {total_feats}")

    # 5. Filter to common wafers
    ev_sub  = ev[ev["wafer_key"].isin(common_keys)].copy()
    oes_sub = oes[oes["wafer_key"].isin(common_keys)].copy()
    rfm_sub = rfm[rfm["wafer_key"].isin(common_keys)].copy()

    # 6. Precompute cumulative means (once per block)
    print("\n[4] Precomputing cumulative means ...")
    ev_cum  = precompute_cum_means(ev_sub,  ev_cols,  common_keys)
    oes_cum = precompute_cum_means(oes_sub, oes_cols, common_keys)
    rfm_cum = precompute_cum_means(rfm_sub, rfm_cols, common_keys)
    print("    Done.")

    ev_nrows  = {wk: int((ev_sub["wafer_key"]  == wk).sum()) for wk in common_keys}
    oes_nrows = {wk: int((oes_sub["wafer_key"] == wk).sum()) for wk in common_keys}
    rfm_nrows = {wk: int((rfm_sub["wafer_key"] == wk).sum()) for wk in common_keys}

    # 7. Generate for each resolution
    for resolution in RESOLUTIONS:
        print(f"\n{sep}")
        print(f"  Resolution: {resolution}%")
        print(sep)

        if resolution == 1:
            steps = list(range(1, 101))
        elif resolution == 3:
            steps = list(range(3, 100, 3)) + [100]
        else:
            steps = list(range(5, 101, 5))

        traj_rows = []
        n_wafers  = len(common_keys)

        for si, p in enumerate(steps):
            # Feature vectors at progress p%
            ev_f  = features_at_progress(ev_cum,  common_keys, ev_nrows,  p)
            oes_f = features_at_progress(oes_cum, common_keys, oes_nrows, p)
            rfm_f = features_at_progress(rfm_cum, common_keys, rfm_nrows, p)
            X = np.hstack([ev_f, oes_f, rfm_f])
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

            # Normal training subset
            norm_idx    = [i for i, wk in enumerate(common_keys) if wk in normal_set]
            X_normal    = X[norm_idx]

            # Remove near-constant features
            std_mask = X_normal.std(axis=0) > 1e-10
            if std_mask.sum() < 2:
                std_mask = np.ones(X.shape[1], dtype=bool)
            X_filt  = X[:, std_mask]
            Xn_filt = X_normal[:, std_mask]

            # Fit scaler + PCA on normal training data
            scaler   = StandardScaler()
            Xn_sc    = scaler.fit_transform(Xn_filt)
            pca      = fit_mpca(Xn_sc)

            # Q scores for all wafers
            X_sc    = scaler.transform(X_filt)
            Q_all   = compute_q(X_sc,  pca)
            Q_norm  = compute_q(Xn_sc, pca)
            q_thr   = float(np.percentile(Q_norm, Q_THRESHOLD_PCT))
            if q_thr <= 0:
                q_thr = float(max(np.percentile(Q_norm, 95), 1e-8))

            for i, wk in enumerate(common_keys):
                traj_rows.append({
                    "wafer_id":           wk,
                    "progress_pct":       p,
                    "Q_score":            float(Q_all[i]),
                    "Q_threshold":        q_thr,
                    "Q_ratio":            float(Q_all[i] / q_thr) if q_thr > 0 else 0.0,
                    "pred_anomaly":       int(Q_all[i] > q_thr),
                    "fault_name":         wafer_meta.loc[wk, "fault_name"],
                    "is_fault":           int(wafer_meta.loc[wk, "is_fault"]),
                    "raw_recalc_source":  RAW_RECALC_SOURCE,
                    "progress_resolution": resolution,
                })

            # Progress log
            if si % 10 == 0 or p == steps[-1]:
                n_det = int((Q_all > q_thr).sum())
                n_c   = pca.n_components_
                print(f"  p={p:3d}%: n_comp={n_c:2d}, Q_thr={q_thr:.4f}, "
                      f"detected={n_det}/{n_wafers}")

        # Build trajectory DataFrame
        traj = pd.DataFrame(traj_rows)
        traj = traj.sort_values(["wafer_id", "progress_pct"]).reset_index(drop=True)
        traj["q_delta"] = traj.groupby("wafer_id")["Q_score"].diff().fillna(0.0)

        traj_path = os.path.join(OUT_DIR, f"realtime_q_trajectory_raw_{resolution}pct.csv")
        traj.to_csv(traj_path, index=False)
        print(f"\n  Saved trajectory  -> {traj_path}")

        # SPC status
        spc_rows = []
        for wk, wdf in traj.groupby("wafer_id"):
            wdf = wdf.sort_values("progress_pct").reset_index(drop=True)
            spc = classify_spc_for_wafer(wdf["Q_ratio"].values, wdf["Q_score"].values)
            for j in range(len(wdf)):
                row = wdf.iloc[j]
                spc_rows.append({
                    "wafer_id":           int(row["wafer_id"]),
                    "progress_pct":       row["progress_pct"],
                    "Q_score":            row["Q_score"],
                    "Q_threshold":        row["Q_threshold"],
                    "Q_ratio":            row["Q_ratio"],
                    "q_delta":            row["q_delta"],
                    **spc[j],
                    "progress_resolution": resolution,
                    "raw_recalc_source":  RAW_RECALC_SOURCE,
                })

        spc_df   = pd.DataFrame(spc_rows)
        spc_path = os.path.join(OUT_DIR, f"realtime_spc_status_raw_{resolution}pct.csv")
        spc_df.to_csv(spc_path, index=False)
        print(f"  Saved SPC status  -> {spc_path}")

        # Quick summary
        last_step = traj[traj["progress_pct"] == traj["progress_pct"].max()]
        n_fault_det = last_step[
            (last_step["is_fault"] == 1) & (last_step["pred_anomaly"] == 1)
        ].shape[0]
        n_fault_tot = last_step[last_step["is_fault"] == 1].shape[0]
        print(f"  At 100%: fault detected {n_fault_det}/{n_fault_tot}")

    print(f"\n{sep}")
    print("  All files generated successfully.")
    print(sep)


if __name__ == "__main__":
    main()
