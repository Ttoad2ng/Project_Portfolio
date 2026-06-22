# REALTIME SPC RAW RECALC DEV REPORT

**생성일:** 2026-06-22  
**작업 폴더:** `C:\Users\diahe\Park\dev_실전프로젝트`  
**대시보드:** `dashboard/app/jeaguseong_realtime_dev.py`  
**전처리 스크립트:** `src/build_realtime_spc_raw_replay.py`

---

## 1. 개요

발표용 원본 대시보드(`dashboard/reference/jeaguseong.py`)를 수정하지 않고, 별도 DEV 버전으로 분리하여 다음 기능을 추가한 보고서입니다.

| 항목 | 내용 |
|------|------|
| 진행률 해상도 | 5% / 3% / 1% 단위 선택 가능 |
| Q 재계산 방식 | 원시 데이터(EV/OES/RFM) 기반 직접 계산 — 보간 없음 |
| SPC 규칙 | Q_ratio 기반 5단계 분류 (정상 / 관찰 / 주의 / 경고 / 긴급 경고) |
| 경고 램프 | CSS @keyframes 블링크 애니메이션 |
| 재생 속도 | 1.0 / 1.2 / 1.5 초/점 선택 가능 |

---

## 2. 파일 구조

```
dev_실전프로젝트/
├── dashboard/
│   ├── app/
│   │   └── jeaguseong_realtime_dev.py       ← DEV 대시보드 (신규)
│   └── reference/
│       └── jeaguseong.py                     ← 원본 (수정 없음, READ ONLY)
├── src/
│   └── build_realtime_spc_raw_replay.py     ← 전처리 스크립트 (신규)
├── data/
│   └── raw_optional/
│       ├── ev_data.csv                       ← EV 센서 원시 데이터
│       ├── oes_data.csv                      ← OES 센서 원시 데이터
│       └── rfm_data.csv                      ← RFM 센서 원시 데이터
└── outputs/
    ├── csv/
    │   ├── realtime_q_trajectory_raw_5pct.csv
    │   ├── realtime_q_trajectory_raw_3pct.csv
    │   ├── realtime_q_trajectory_raw_1pct.csv
    │   ├── realtime_spc_status_raw_5pct.csv
    │   ├── realtime_spc_status_raw_3pct.csv
    │   └── realtime_spc_status_raw_1pct.csv
    └── reports/
        └── REALTIME_SPC_RAW_RECALC_DEV_REPORT.md  ← 이 파일
```

---

## 3. MPCA 재계산 방법론

### 3.1 원시 데이터 로드

- **EV** (`ev_data.csv`): 12829행 × 23컬럼, 19개 수치형 센서, 129 웨이퍼
- **OES** (`oes_data.csv`): 4786행 × 131컬럼, 126 웨이퍼
- **RFM** (`rfm_data.csv`): 3519행 × 73컬럼, 70개 센서, 126 웨이퍼
- **3-sensor inner join**: 124 웨이퍼 (EV 3개 추가 웨이퍼 제외)

### 3.2 정상 라벨 기준

```python
NORMAL_LABEL = "calibration"
```

- `fault_name == 'calibration'` 인 웨이퍼만 정규 데이터로 학습
- Holdout 웨이퍼(Group 33 fault) 및 이상 웨이퍼는 학습에서 완전 제외

### 3.3 피처 구성

| 구분 | 피처 수 | 선택 기준 |
|------|---------|---------|
| EV | 19 | 전체 수치 센서 |
| OES | 20 | 정상 웨이퍼 행 기준 분산 상위 20개 파장 |
| RFM | 70 | 전체 수치 센서 |
| **합계** | **109** | 근상수(std < 1e-10) 제거 후 실제 적용 수 변동 |

### 3.4 누적 평균 피처 계산

각 진행률 p%에서의 피처:
```
feature(wafer_k, p%) = mean(sensor rows where progress <= p%)
```

- 진행률 할당: `rank / (n-1) * 100` (rank = 시간 순 0-based index)
- 보간 없음 — floor(n_rows × p/100) 행까지의 실제 평균만 사용
- 누적 평균(expanding mean)을 진행률 단계별로 인덱싱

### 3.5 PCA / Q 계산

각 진행률 단계 p%마다 독립적으로:
1. **정상 웨이퍼만으로** `StandardScaler.fit()` + `PCA.fit()` (target variance 95%)
2. **전체 124 웨이퍼**에 `transform()`
3. `Q = ||X_scaled - PCA.inverse_transform(PCA.transform(X_scaled))||²`
4. `Q_threshold = 99th percentile of Q_scores(normal training wafers)`

---

## 4. SPC 규칙

| 단계 | 조건 | 램프 색 | 블링크 |
|------|------|---------|--------|
| R5 긴급 경고 | Q_ratio ≥ 1.20 또는 연속 2회 Q_ratio ≥ 1.00 | 빨간색 | O |
| R4 경고 | Q_ratio ≥ 1.00 | 빨간색 | O |
| R3 주의 | Q_ratio ≥ 0.95 또는 연속 2회 Q_ratio ≥ 0.90 | 주황색 | O |
| R2 관찰 | Q_ratio ≥ 0.80 또는 연속 3회 상승 | 초록색 | X |
| R1 정상 | 그 외 | 파란색 | X |

- `Q_ratio = Q_score / Q_threshold`
- 사용 표현: "SPC Rule 기준", "현재 진행률 기준", "추가 확인 필요", "점검 필요"
- 사용 금지: "불량 확정", "원인 확정", "실제 장비 실시간 입력"

---

## 5. 실시간 재생 모드

### 5.1 session_state 관리

```python
st.session_state["replay_on"]           # bool — 재생 중 여부
st.session_state["current_progress"]    # float or None — 현재 진행률 (None = 전체 표시)
st.session_state["replay_interval_sec"] # float — 재생 속도 (1.0 / 1.2 / 1.5)
st.session_state["progress_resolution"] # int — 진행 단위 (5 / 3 / 1%)
```

### 5.2 자동 진행 메커니즘

```python
if st.session_state.get("replay_on"):
    time.sleep(interval)
    st.session_state["current_progress"] = min(100, current + resolution)
    st.rerun()
```

- Page 1 렌더 완료 후 실행
- `current_progress == 100` 도달 시 자동 정지
- `st.rerun()` 호출로 전체 화면 갱신

### 5.3 진행률 필터

재생 중에는 `current_progress` 이하의 데이터만 시각화:
- Q trajectory 차트: `wq = wq[wq["progress_pct"] <= current_progress]`
- KPI SPC 상태: `spc_df[spc_df["progress_pct"] <= current_progress]`
- 이탈 감지 표시선(vline): `fd <= current_progress` 조건 확인

---

## 6. CSS 블링크 애니메이션

```css
@keyframes blink-lamp {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.2; }
}
```

- 주기: 1.0초 (`ease-in-out infinite`)
- 적용: `spc_lamp_html()` 함수에서 `blink=True` 조건에 inline style로 적용

---

## 7. 생성된 CSV 파일 요약

### Q trajectory 파일

| 파일 | 행 수 | 컬럼 수 | 설명 |
|------|-------|---------|------|
| realtime_q_trajectory_raw_5pct.csv | 2480 | 11 | 124 웨이퍼 × 20 단계 |
| realtime_q_trajectory_raw_3pct.csv | 4216 | 11 | 124 웨이퍼 × 34 단계 |
| realtime_q_trajectory_raw_1pct.csv | 12400 | 11 | 124 웨이퍼 × 100 단계 |

**컬럼:** `wafer_id, progress_pct, Q_score, Q_threshold, Q_ratio, pred_anomaly, fault_name, is_fault, raw_recalc_source, progress_resolution, q_delta`

### SPC 상태 파일

| 파일 | 행 수 | 컬럼 수 | 설명 |
|------|-------|---------|------|
| realtime_spc_status_raw_5pct.csv | 2480 | 14 | Q trajectory + SPC 분류 |
| realtime_spc_status_raw_3pct.csv | 4216 | 14 | |
| realtime_spc_status_raw_1pct.csv | 12400 | 14 | |

**추가 컬럼:** `spc_state, spc_level, rule_hit, rule_message, lamp_color, blink`

---

## 8. 주요 설계 원칙 준수 현황

| 원칙 | 준수 여부 |
|------|---------|
| 원본 `jeaguseong.py` 미수정 | ✅ READ ONLY 유지 |
| 보간 없는 Q 재계산 | ✅ cumulative mean 기반 직접 계산 |
| 정상 데이터만으로 scaler/PCA 학습 | ✅ `fault_name == 'calibration'` 기준 |
| holdout 웨이퍼 학습 제외 | ✅ Group 33 fault 완전 분리 |
| 원본 CSV 수정 없음 | ✅ 새 파일만 outputs/csv/ 에 저장 |
| 카드 크기/레이아웃 미변경 | ✅ 기존 CSS 클래스 유지 |
| 캐릭터 이미지 인터넷 다운로드 없음 | ✅ 로컬 경로 탐색만 |
| 금지 표현 사용 없음 | ✅ "불량 확정" / "원인 확정" 없음 |

---

## 9. 실행 방법

### 선행 작업 (전처리 스크립트)
```bash
cd C:\Users\diahe\Park\dev_실전프로젝트
python src/build_realtime_spc_raw_replay.py
```

### 대시보드 실행
```bash
streamlit run dashboard/app/jeaguseong_realtime_dev.py
```

### 문법 검증
```bash
python -m py_compile dashboard/app/jeaguseong_realtime_dev.py
python -m py_compile src/build_realtime_spc_raw_replay.py
```

---

## 10. 한계 및 주의사항

1. **FDC contribution 분석 없음**: raw replay 버전에서는 센서별 기여도 계산 없이 "SPC Rule 기준 이상 감지" 문구만 표시
2. **OES 차원 축소**: 상위 20개 파장만 사용 (전체 129개 파장 중) — 분산 기준 선택이므로 일부 파장 정보 손실 가능
3. **조기 단계 품질**: 1% 해상도에서 OES(38행/웨이퍼)는 첫 1~2행만 사용 → 초기 Q 값 안정성 낮음
4. **재생 속도**: `time.sleep()` + `st.rerun()` 방식이므로 실제 렌더링 시간 포함 시 설정 속도보다 느릴 수 있음
5. **다중 탭**: session_state는 탭별로 독립 — 동시에 여러 탭에서 재생 시 서로 간섭 없음
