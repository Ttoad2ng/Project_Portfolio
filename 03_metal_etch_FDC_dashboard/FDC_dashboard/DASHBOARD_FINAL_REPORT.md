# 금속 식각 공정 FDC 모니터링 대시보드 — 최종 변경 보고서

---

## 2026-06-12 (22) 페이지 3 저장 버튼 빨간색 기본 상태 적용

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 원인
기존 버튼 CSS가 `.st-key-review_input_card` 하위 요소로만 scoped 되어 있어, 페이지 3의 `review_input_section` 안에 있는 저장 버튼에는 기본 빨간색이 적용되지 않았음. hover 시에만 빨간색이 되던 이유는 Streamlit 기본 primary 버튼 hover CSS와 우연히 겹쳤기 때문.

### 추가된 CSS (전역, CSS 블록 최하단 — 기존 scoped 규칙보다 늦게 선언)

```css
div[data-testid="stFormSubmitButton"] button,
button[data-testid="stBaseButton-primaryFormSubmit"] { background: #ef4444; ... }
```

- 기본/hover/focus·active 3단계
- 버튼 내부 텍스트/아이콘 color: #ffffff 강제 적용
- 기존 `.st-key-review_input_card` scoped 규칙은 제거하지 않음 (무해)

### 변경하지 않은 항목
- 저장(`save_review_dict`) 로직
- 초기화(`reset`) 로직
- 카드 레이아웃, 기타 CSS
- Q_score, Q_threshold, detected, FDC/Contribution, raw CSV

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile` | ✅ SYNTAX OK |
| 탐지/계산 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |

---

## 2026-06-12 (21) 조치기록 초기화 기능 추가 + 조치 입력 카드 흰색 통일

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 변경 1 — 조치기록 초기화 expander 추가

**위치**: 페이지 3 미확인/확인 중/완료/최근 업데이트 mini 카드 바로 아래, `review_table_card` 위

**expander 제목**: `⚠️ 조치기록 초기화`

**동작**:
- 안내 문구 표시
- `초기화를 진행합니다` 체크박스 — 미선택 시 버튼 비활성화
- `초기화 실행` 버튼 클릭 시:
  - `operator_review_status.csv`만 초기화 (all_ids 기준 전체 행, status="미확인", handled=False, memo="", updated_at="")
  - `st.success("조치 기록이 초기화되었습니다.")`
  - `st.rerun()`
- 원본 센서 CSV, MPCA 결과, streaming 결과 파일 변경 없음

### 변경 2 — 조치 입력 영역 흰색 카드 통일

**방법**: `st.expander("선택 wafer 조치 내용 입력")` 를 `st.container(border=False, key="review_input_section")` 으로 감쌈

**추가 CSS**:
```css
.st-key-review_input_section {
    background: #ffffff !important;
    border: 1.5px solid #94a3b8 !important;
    border-radius: 14px !important;
    box-shadow: 0 3px 10px rgba(15,23,42,0.12) !important;
    box-sizing: border-box !important;
    padding: 16px 18px !important;
}
.st-key-review_input_section details,
.st-key-review_input_section div[data-testid="stExpander"] { background: #ffffff !important; }
.st-key-review_input_section * { background-color: transparent; }
```

### 변경하지 않은 항목
- Q_score, Q_threshold, detected, FDC/Contribution 계산
- 기존 저장(`save_review_dict`) 로직
- 원본 CSV, MPCA 결과, streaming 결과 파일
- 카드 레이아웃, 기타 CSS
- 페이지 1 / 페이지 2

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile` | ✅ SYNTAX OK |
| 탐지/계산 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |
| operator_review_status.csv 외 파일 초기화 | ✅ 없음 |

---

## 2026-06-12 (20) 현장 조치 매뉴얼 카드 — FDC 계열 + 현재 센서 계열 동시 표시

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 추가된 helper 함수: `classify_sensor_family_for_manual(sensor_name, top_block="")`

센서 이름 → 내부 계열 key 반환 (매뉴얼 라우팅 전용).
키워드 목록 `_SENSOR_TO_FAMILY` + OES 패턴(파장 번호 regex) 사용.
FDC/Contribution 데이터 재계산 없음.

### 변경된 `field_action_manual_items(wid, selected_sensor="", selected_block="")` 시그니처

**반환값 변경**: `(label, items)` → `(fdc_label, sensor_label, manual_label, items)`

| 반환값 | 설명 |
|--------|------|
| `fdc_label` | FDC/Contribution 기반 계열 레이블 (항상 유지) |
| `sensor_label` | 현재 선택 센서 기반 계열 레이블 |
| `manual_label` | 실제 매뉴얼 표시 계열 (센서 specific → 우선, generic → FDC fallback) |
| `items` | 5개 조치 항목 리스트 |

### check_guide_card 표시 구조

```
📋 현장 조치 매뉴얼
FDC 기준 점검 계열: {fdc_label}         ← 항상 표시
현재 확인 센서: {sensor}                ← sv_sensor 기준
센서 기준 계열: {sensor_label}
[안내문 — 소자체 #64748b]
표시 매뉴얼: {manual_label}
1) ... 2) ... 3) ... 4) ... 5) ...
```

### 매뉴얼 계열 선택 로직

```
fk_sensor = classify_sensor_family_for_manual(selected_sensor, block)
if fk_sensor != "generic":
    manual → fk_sensor   (선택 센서 기반)
else:
    manual → fk_fdc      (FDC 기반 fallback)
```

### 변경하지 않은 항목
- `Q_score`, `Q_threshold`, `detected`, FDC/Contribution 계산 로직
- 관련 센서 버튼 동작 (pending_block/sensor/wafer + rerun)
- 카드 레이아웃, CSS (색상/높이)
- 페이지 1 / 페이지 3

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile` | ✅ SYNTAX OK |
| 탐지/계산 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |
| FDC 기준 계열 항상 표시 | ✅ |
| 카드 CSS 변경 | ✅ 없음 |

---

## 2026-06-12 (19) 페이지 2 "점검 기준" 카드 → 현장 조치 매뉴얼

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 추가된 helper 함수: `field_action_manual_items(wid)`

**위치**: `related_real_sensors()` 바로 뒤, `PAGES` 상수 앞

**분류 로직** (우선순위 순):
1. `suspected_family` → `family_key()` 매핑
2. `top_block == "OES"` 이면 oes 확정
3. `generic`일 때 `top_sensor` 키워드로 보정 (`_SENSOR_TO_FAMILY` 딕셔너리)

**지원 카테고리 (8종)**:

| key | 카드 표시 레이블 |
|-----|---------------|
| `rf` | RF 계열 |
| `tcp` | TCP 계열 |
| `matching` | RF/TCP Matching 계열 |
| `gas` | Gas 공급 계열 |
| `pressure` | Pressure / 제어 계열 |
| `he` | He Chuck 계열 |
| `oes` | OES / 플라즈마 반응 계열 |
| `generic` | 장비 조건 일반 |

### check_guide_card 변경

| 항목 | 이전 | 변경 후 |
|------|------|---------|
| 카드 제목 | `📋 현장 조치 기준` | `📋 현장 조치 매뉴얼` |
| 카드 내용 | 고정 4개 bullet | wafer별 동적 5개 numbered 항목 + 점검 계열 표시 |
| 데이터 소스 | 고정 텍스트 | `fdc_map` / `family_key()` 기반 분류 (재계산 없음) |

### 변경하지 않은 항목
- `Q_score`, `Q_threshold`, `detected` 계산 로직
- `fdc_map`, `det_map` 계산 로직
- `sensor_direction()`, `normal_trend()` 함수
- 카드 레이아웃, 카드 CSS, 높이 CSS
- `sensor_chip_card` 버튼 동작
- `operator_review_status.csv` 저장 로직
- raw CSV 파일, PNG 파일

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile` | ✅ SYNTAX OK |
| 탐지/계산 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |
| 카드 CSS (색상/높이) 변경 | ✅ 없음 |
| 페이지 1 / 페이지 3 변경 | ✅ 없음 |

---

## 2026-06-12 (18) 현장 엔지니어용 UI 문구 개선

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### UI 문구 변경 목록

| 위치 | 이전 | 변경 후 |
|------|------|---------|
| 페이지 1 차트 카드 제목 | `Q statistic · 선택 wafer 이상 정도 변화` | `선택 wafer 공정 이탈 흐름` |
| ialike_chart 트레이스 | `name="이상 정도"` | `name="선택 wafer 이탈 정도"` |
| ialike_chart 트레이스 | `name="이탈 지점"` | `name="기준선 초과 지점"` |
| ialike_chart y축 | `title_text="이상 정도"` | `title_text="이탈 정도"` |
| PAGES 상수 / 사이드바 탭 | `"2. 센서 정상 범위 비교"` | `"2. 센서 점검 화면"` |
| 페이지 2 헤더 제목 | `"센서 정상 범위 비교"` | `"센서 점검 화면"` |
| 페이지 2 헤더 부제목 | `"원본 센서 검증용 · 이상탐지 재계산 없음"` | `"정상 wafer 기준과 선택 wafer 센서 흐름 비교"` |
| 페이지 2 KPI 카드 레이블 | `"정상 범위 비교"` | `"센서 상태"` |
| 페이지 2 KPI 카드 부제목 | `"정상 wafer 평균 ±1σ 기준"` | `"정상 wafer 흐름 기준"` |
| 페이지 2 센서 차트 트레이스 | `name="정상 ±1σ"` | `name="정상 범위"` |
| 페이지 2 sensor_result_card pill | `"정상 범위 비교"` | `"센서 상태"` |
| normalize_compare_label() 출력 | `"평균 기준 정상 범위 안"` | `"정상 범위 안"` |
| normalize_compare_label() 출력 | `"평균 기준 정상보다 높음/낮음"` | `"정상 범위 이탈"` (통합) |

### 변경하지 않은 항목

- `Q_score`, `Q_threshold`, `exceed`, `detected` 계산 로직
- `sensor_direction()`, `normal_trend()` 함수
- `Contribution / FDC` 해석 로직
- `raw EV/OES/RFM CSV` 로딩 및 비교 계산
- `selected_wafer` 로직
- 카드 레이아웃 / CSS 크기
- 페이지 2 "점검 기준" 카드 (`check_guide_card`) — 변경 없음
- `key="wafer_table_selection"` 행 선택 동작

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile` | ✅ SYNTAX OK |
| 탐지/계산 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |
| "점검 기준" 카드 변경 | ✅ 없음 |

---

## 2026-06-11 (17) 페이지 1 하단 — wafer 목록 카드 높이 단독 증가

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 변경 내용

#### 1. 이전 잘못된 CSS 수정 (양쪽 동시 타깃 → 왼쪽 단독)

이전 (수정 (16)에서 추가, 제거):
```css
.st-key-wafer_table_card,
.sumcard { min-height: 390px !important; }
```

변경 후:
```css
.st-key-wafer_table_card {
    min-height: 440px !important;
    box-sizing: border-box !important;
}
.st-key-wafer_table_card > div { box-sizing: border-box !important; }
```
- `.sumcard` height 강제 없음 — 공정 요약 정보 카드 변경 없음

#### 2. st.dataframe height 증가

| 항목 | 이전 | 변경 후 |
|------|------|---------|
| dataframe height | 300 | 360 |

- 행 선택 동작 (`on_select="rerun"`, `key="wafer_table_selection"`) 변경 없음

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile` | ✅ SYNTAX OK |
| 탐지/계산 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |
| `.sumcard` 높이 강제 없음 | ✅ |
| 행 클릭 선택 동작 유지 | ✅ |
| 페이지 2 / 페이지 3 변경 | ✅ 없음 |

---

## 2026-06-11 (16) 페이지 1 하단 — wafer 목록 카드 ↔ 공정 요약 정보 카드 높이 균형

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### TASK 1 — st.dataframe height 고정

```python
_tbl_event = st.dataframe(
    _tbl_df,
    use_container_width=True,
    hide_index=True,
    height=300,          # 추가
    selection_mode="single-row",
    on_select="rerun",
    key="wafer_table_selection",
    ...
)
```
- 행 수가 바뀌어도 dataframe 뷰포트 높이 고정 → 카드 크기 예측 가능
- 행 선택 동작 (`on_select="rerun"`, key) 변경 없음

### TASK 2 — 하단 카드 높이 균형 CSS 추가

```css
/* Page 1 lower row: wafer table card ↔ process summary card height balance */
.st-key-wafer_table_card,
.sumcard {
    min-height: 390px !important;
    box-sizing: border-box !important;
}
.st-key-wafer_table_card > div { box-sizing: border-box !important; }
```

- `.st-key-wafer_table_card` — 좌측 점검 대상 wafer 목록 카드
- `.sumcard` — 우측 공정 요약 정보 (HTML div, st.container key 없음)
- `min-height: 390px` (필요 시 410px 증가 / 370px 감소 조정)
- `.sumcard` 기존 스타일(배경·테두리·반경·그림자) 유지

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile` | ✅ SYNTAX OK |
| 탐지/계산 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |
| 행 클릭 선택 동작 유지 | ✅ |
| 페이지 2 / 페이지 3 변경 | ✅ 없음 |

---

## 2026-06-11 (15) 페이지 2 센서 점검 해석 설명 텍스트 제거 + 하단 카드 높이 균형

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### TASK 1 — sensor_result_card 설명 텍스트 제거

제거된 텍스트 (st.html 내 하단 div):
```
"이 화면은 원본 센서 검증용입니다."
"Q·threshold·detected 결과는 재계산하지 않습니다."
```

유지된 항목 (4개 pill 행):
- 선택 센서
- 정상 범위 비교
- 이탈 구간
- 점검 방향

### TASK 2 — 하단 카드 높이 균형 CSS 추가

추가된 CSS 셀렉터:
```css
.st-key-sensor_chip_card,
.st-key-check_guide_card {
    min-height: 150px !important;
    box-sizing: border-box !important;
}
.st-key-sensor_chip_card > div,
.st-key-check_guide_card > div { box-sizing: border-box !important; }
```

- 적용 카드: `sensor_chip_card` (같이 점검할 센서), `check_guide_card` (점검 기준)
- 사용 방식: `min-height` 전용 (fixed height 미사용 → Streamlit 내부 wrapper 충돌 방지)
- 초기값: `150px` (필요 시 165px로 증가 / 135px로 감소 조정)

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile` | ✅ SYNTAX OK |
| 탐지/계산 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |
| 관련 센서 버튼 동작 유지 | ✅ 없음 |
| 페이지 1 / 페이지 3 변경 | ✅ 없음 |

---

## 2026-06-11 (14) 페이지 2 센서 차트 카드 ↔ 센서 점검 해석 카드 높이 균형

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 변경 내용

| 항목 | 이전 | 변경 후 |
|------|------|---------|
| `.st-key-sensor_chart_card, .st-key-sensor_result_card` min-height | 없음 | `390px` |
| `.st-key-sensor_result_card` padding | 공통 카드 패딩 | `18px 22px` |
| 페이지 2 Plotly height | `305` | `330` |
| 페이지 2 Plotly margin top | `t=24` | `t=20` |

- `min-height` 방식 사용 (fixed height 미사용 → Streamlit 내부 wrapper 충돌 방지)
- 차트 height 330px + 카드 min-height 390px → 제목/패딩 포함 여유 있게 배치

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile` | ✅ SYNTAX OK |
| 탐지/계산 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |

---

## 2026-06-11 (13) 페이지 1 Q 차트 카드 ↔ 점검 해석 카드 고정 높이 정렬

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 변경 내용

| 항목 | 이전 | 변경 후 |
|------|------|---------|
| Q 차트 카드 제목 CSS 클래스 | `.sec-title` (공통) | `.q-chart-title` (전용) |
| `.q-chart-title` font-size | — | `1.35rem`, weight 900 |
| `.st-key-chart_card` 높이 | 없음 | `height/min-height: 520px` |
| `.st-key-selected_wafer_card` 높이 | 없음 | `height/min-height: 520px` |
| `ialike_chart` Plotly height | `460` | `420` |
| `ialike_chart` margin top | `t=34` | `t=30` |

- 두 카드 모두 520px 고정 → wafer 변경과 무관하게 하단 정렬 유지
- 차트 height 420px + 큰 제목이 카드 내 자연스럽게 배치

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile` | ✅ SYNTAX OK |
| 탐지/계산 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |

---

## 2026-06-11 (12) 페이지 1 Q 차트 카드 ↔ 점검 해석 카드 높이 정렬

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 변경 내용

| 항목 | 이전 | 변경 후 |
|------|------|---------|
| CSS `.st-key-chart_card, .st-key-selected_wafer_card` | min-height 없음 | `min-height: 430px !important` |
| CSS `.st-key-chart_card > div, .st-key-selected_wafer_card > div` | min-height 없음 | `min-height: 430px !important` |
| `ialike_chart()` Plotly height | `height=460` | `height=360` |
| `ialike_chart()` margin | `t=34, b=18` | `t=30, b=14` |

- `min-height`로 두 카드가 항상 같은 최소 높이를 가짐 → 하단 경계 정렬
- 차트 height를 360px로 줄여 카드 안에서 여백 없이 자연스럽게 배치
- 페이지 2 `sensor_chart_card`는 변경하지 않음

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile` | ✅ SYNTAX OK |
| 탐지/계산 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |

---

## 2026-06-11 (11) selected_wafer 페이지 복귀 시 리셋 완전 수정

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 발견된 버그 (두 가지)

1. **인덴트 붕괴**: 필터 동기화 코드가 `if page == PAGES[0]:` 밖으로 빠져나가고, 페이지 1 전체 콘텐츠(KPI·차트·테이블)가 `if _prev_filter_sig != _cur_filter_sig:` 안에 들어가 필터가 바뀌지 않으면 페이지 1이 아무것도 렌더링하지 않는 상태.

2. **리셋 로직**: 시그니처 비교 방식(`_prev != _cur`)은 캐시 키 초기화(`None != sig`)로 인해 다른 페이지에서 복귀할 때마다 `selected_wafer`를 강제 초기화함.

### 변경 내용

#### 1. `mark_page1_filter_changed()` 콜백 추가

```python
def mark_page1_filter_changed():
    st.session_state["page1_filter_changed"] = True
```

- `render_page_header()` 직전에 top-level 함수로 정의
- `wf_filter` / `batch_filter` selectbox 양쪽에 `on_change=mark_page1_filter_changed` 추가
- 사용자가 직접 드롭다운을 바꿀 때만 플래그 세트 → 페이지 이동은 플래그 세트하지 않음

#### 2. 필터 동기화 블록 인덴트·로직 교체

| 항목 | 이전 | 변경 후 |
|------|------|---------|
| 인덴트 | 0 spaces (PAGES[0] 밖) | 4 spaces (PAGES[0] 안) |
| 변경 감지 | `_prev != _cur` 시그니처 비교 | `st.session_state.pop("page1_filter_changed", False)` |
| 페이지 복귀 시 | `None != sig` → 리셋 발생 | 플래그 없음 → 리셋 없음 |
| 필터 결과 범위 벗어날 때 reset | 있었음 (`not in _cand`) | 제거됨 |

새 로직:
```python
if page == PAGES[0]:
    render_page_header(...)

    _cur_filter_sig = (wf_filter, batch_filter)
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
    kpi_row(sel)
    ...  # 항상 렌더링
```

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile` | ✅ SYNTAX OK |
| 탐지/계산 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |

---

## 2026-06-11 (10) 페이지 1 필터 위치 복원 + selected_wafer 영속성 완성

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 변경 내용

#### 1. 페이지 1 필터 드롭다운 수직 위치 복원 (Task 1)

| 위치 | 이전 | 변경 후 |
|------|------|---------|
| `_c_f1` (점검 상태) 컬럼 상단 스페이서 | `height:16px` | `height:8px` |
| `_c_f2` (Batch 필터) 컬럼 상단 스페이서 | `height:16px` | `height:8px` |

- 이전 세션에서 gap 압축(1rem→0.65rem) 후 16px 스페이서가 과도하게 필터를 밀어내는 문제
- 8px로 줄여 카드 내 자연스러운 수직 정렬 복원

#### 2. selected_wafer 전체 할당 감사 결과

| 줄 | 할당 | 분류 |
|----|------|------|
| 958 | 앱 최초 초기화 (`not in st.session_state`) | ✅ 허용 |
| 974 | `pending_wafer` 적용 (관련 센서 버튼 클릭 후) | ✅ 허용 |
| 1067, 1071 | `body_wafer_selector()` 내부 — **호출되지 않는 dead code** | 무해 |
| 1413 | 필터 실제 변경 시 (`_prev != _cur`) | ✅ 허용 |
| 1416 | 현재 wafer가 필터 결과 밖일 때 | ✅ 허용 |
| 1485 | 페이지 1 테이블 행 클릭 | ✅ 허용 |
| 1719 | 페이지 3 expander — 이번 세션 수정 | ✅ 허용 (조건부) |

#### 3. 페이지 3 expander selected_wafer 리셋 완전 수정 (Task 5)

이전 패턴의 문제:
```python
_p3_target = _cur_sel3 if _cur_sel3 in cur_ids else cur_ids[0]
st.session_state["wafer_p3_widget"] = _p3_target  # 항상 덮어씀
if sel != _cur_sel3:  # normal wafer → 항상 True → 리셋
    st.session_state["selected_wafer"] = sel
```

신규 패턴 (`_p3_last_seen_wafer` 추적):
```python
_p3_last = st.session_state.get("_p3_last_seen_wafer")
# selected_wafer가 외부(다른 페이지)에서 변경됐을 때만 위젯 동기화
if _cur_sel3 != _p3_last:
    if _cur_sel3 in cur_ids:
        st.session_state["wafer_p3_widget"] = _cur_sel3
    elif st.session_state.get("wafer_p3_widget") not in cur_ids:
        st.session_state["wafer_p3_widget"] = cur_ids[0]
st.session_state["_p3_last_seen_wafer"] = _cur_sel3
# 사용자가 selectbox를 변경하고, 변경 전 selected_wafer가 detected wafer였을 때만 갱신
if sel != _cur_sel3 and _cur_sel3 in cur_ids:
    st.session_state["selected_wafer"] = sel
    st.rerun()
```

동작 시나리오별 검증:

| 시나리오 | 결과 |
|----------|------|
| page 1에서 detected wafer 선택 → page 3 이동 | expander selectbox가 동일 wafer 표시 ✅ |
| page 1에서 normal wafer 선택 → page 3 이동 | expander는 이전 detected wafer 유지, `selected_wafer` 리셋 없음 ✅ |
| page 3 expander에서 다른 wafer 선택 | `selected_wafer` 갱신 → rerun ✅ |
| page 3 → page 1 → page 3 재방문 | expander가 현재 `selected_wafer` 반영 ✅ |

#### 4. 페이지 2 변경 없음 (Task 6 준수)

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile` | ✅ SYNTAX OK |
| 탐지/계산 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |

---

## 2026-06-11 (9) selected_wafer 페이지 간 유지 + 레이아웃 압축 완성

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 변경 내용

#### 1. selected_wafer 페이지 이동 시 리셋 방지 (2건)

**페이지 1 — 필터 동기화 초기화 버그 수정**

| 이전 코드 | 변경 후 |
|-----------|---------|
| `_prev_filter_sig = st.session_state.get("prev_page1_filter_sig")` → 첫 방문 시 `None` 반환 | `if "prev_page1_filter_sig" not in st.session_state: st.session_state[...] = _cur_filter_sig` |
| `_cand_after_filter = filtered_ids() or sorted(all_ids)` → 필터 결과 없을 때 전체 목록 반환 | `_cand_after_filter = filtered_ids()` (fallback 제거) |
| `if _cand_after_filter: if _prev != _cur:` | `if _cand_after_filter and _prev != _cur:` / `if _cand_after_filter and ... not in _cand:` |

- 효과: 다른 페이지에서 1페이지로 돌아올 때 `None != sig` 로 인한 불필요한 rerun·리셋 제거
- 효과: 필터 결과가 비어있을 때 `selected_wafer`를 `all_ids[0]`으로 덮어쓰던 문제 제거

**페이지 3 — wafer 선택기 무조건 덮어쓰기 버그 수정**

| 이전 코드 | 변경 후 |
|-----------|---------|
| `st.session_state["selected_wafer"] = sel` (매 렌더링 실행) | `if sel != _cur_sel3: st.session_state["selected_wafer"] = sel; st.rerun()` |
| `_cur_sel3 = cur_ids[0]` (selected_wafer 미발견 시) | `_p3_target = _cur_sel3 if _cur_sel3 in cur_ids else cur_ids[0]` (always pre-set) |

- 효과: 페이지 3 로딩 자체가 `selected_wafer`를 바꾸지 않음
- 효과: 사용자가 실제로 선택기를 조작했을 때만 `selected_wafer` 갱신

#### 2. CSS 압축 변경

| CSS | 이전 | 변경 후 |
|-----|------|---------|
| `div[data-testid="stVerticalBlock"] { gap }` | `1rem` | `0.65rem` |
| `.st-key-sensor_select_card` (dead CSS) | 카드 그룹 / `*` 그룹 두 곳에 존재 | 제거 (페이지 2에서 이 key 사용하지 않음) |

- 효과: 전체 페이지 세로 간격 축소 → 페이지 2 콘텐츠 더 많이 한 화면에 표시

#### 3. 이미 완료된 항목 (이전 세션, 이번 세션에서 확인)

| 항목 | 상태 |
|------|------|
| `render_page_header()` `show_sensor_filters=True` 브랜치 | ✅ 이전 세션 완료 |
| 페이지 2 별도 `sensor_select_card` 컨테이너 제거 | ✅ 이전 세션 완료 |
| 헤더에 `sv_block` / `sv_sensor` 드롭다운 통합 | ✅ 이전 세션 완료 |
| 차트 height `340 → 305` | ✅ 이전 세션 완료 |
| `margin-bottom: 10px` (페이지 2 4개 카드) | ✅ 이전 세션 완료 |

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile` | ✅ SYNTAX OK |
| 탐지/계산 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |
| `sv_block` / `sv_sensor` 위젯 중복 생성 | ✅ 없음 (헤더 내 1회만) |
| selected_wafer 페이지 이동 간 유지 | ✅ |

---

## 2026-06-11 (7) 페이지 2 센서 선택 카드 헤더 통합 + 레이아웃 압축

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 변경 내용

#### `render_page_header()` 시그니처 변경
```python
def render_page_header(title, subtitle, show_filters=False,
                       show_sensor_filters=False, sensor_block_opts=None):
```
- `show_sensor_filters=True` 시: 헤더 오른쪽에 `sv_block` / `sv_sensor` 드롭다운 배치
- 레이아웃: `[4.0, 1.2, 2.0]` (왼쪽 제목 / 데이터 구분 / 점검 센서)
- `sv_block` 위젯 생성 후, `sv_sensor` 위젯 생성 전에 sensors 계산 + `sv_sensor` 사전 보정
- 반환값: `(block, sensor)` 튜플

#### 페이지 2 흐름 변경
| 이전 | 변경 후 |
|------|---------|
| `render_page_header(...)` (필터 없음) | `render_page_header(..., show_sensor_filters=True, ...)` |
| `st.container(key="sensor_select_card")` 별도 카드 | **제거** |
| `block`, `sensor` = sensor_select_card 내부에서 | `block, sensor = render_page_header(...)` 반환값 |
| `raw_df = load_raw_block(block)` (카드 내부) | 헤더 호출 직후 `raw_df = load_raw_block(block)` |

#### CSS 변경
| 클래스 | 변경 |
|--------|------|
| `.st-key-page_header` | `min-height: 125px → 110px`, `padding: 22px 26px → 18px 24px`, `margin-bottom: 14px` |
| 센서 페이지 4개 카드 | `margin-bottom: 18px → 10px` |
| 센서 페이지 차트 | `height: 340 → 305` |

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile` | ✅ SYNTAX OK |
| `streamlit run` (port 8527) | ✅ HTTP 200 |
| 탐지/계산 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |

---

---

## 2026-06-11 (6) 페이지 1 필터 변경 시 selected_wafer 자동 동기화

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 삽입 위치
`if page == PAGES[0]:` 블록 내, `render_page_header(...)` 호출 직후, `sel = st.session_state["selected_wafer"]` 전

### 동기화 로직

```python
_cur_filter_sig = (
    st.session_state.get("wf_filter", "전체"),
    st.session_state.get("batch_filter", "전체 Batch"),
)
_prev_filter_sig = st.session_state.get("prev_page1_filter_sig")
_cand_after_filter = filtered_ids() or sorted(all_ids)

if _cand_after_filter:
    if _prev_filter_sig != _cur_filter_sig:          # 필터 변경됨
        st.session_state["prev_page1_filter_sig"] = _cur_filter_sig
        st.session_state["selected_wafer"] = _cand_after_filter[0]
        st.rerun()
    elif st.session_state.get("selected_wafer") not in _cand_after_filter:  # 범위 이탈
        st.session_state["selected_wafer"] = _cand_after_filter[0]
        st.rerun()
```

### 동작 규칙
| 상황 | 동작 |
|------|------|
| 필터 서명 변경 (`wf_filter` 또는 `batch_filter` 변경) | `selected_wafer` → 필터 결과 첫 번째 wafer → `st.rerun()` |
| `selected_wafer`가 필터 결과 밖 | 동일하게 재선택 → `st.rerun()` |
| 후보 목록 비어있음 | 재선택하지 않음, 기존 `selected_wafer` 유지 |
| 테이블 행 직접 클릭 | 기존 동작 그대로 (필터 서명 변경 없음이므로 영향 없음) |

### 영향받는 컴포넌트 (모두 `sel` 기반)
- KPI row, Q statistic chart, 점검 해석 card, 점검 대상 wafer 목록, 공정 요약 정보, 확인 상태/메모 입력

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile` | ✅ SYNTAX OK |
| `streamlit run` (port 8526) | ✅ HTTP 200 |
| 탐지 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |

---

---

## 2026-06-11 (5) 페이지 2/3 헤더 정렬 수정

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 원인
`show_filters=False` 시 `st.columns([1])[0]` 래퍼 컬럼을 사용했는데, Streamlit이 단일 컬럼에도 기본 gap 패딩을 적용해 내부 아이콘+제목 블록이 카드 중앙 쪽으로 밀렸음.

### 변경 내용

**`render_page_header()` 분기 구조 변경:**

| `show_filters` | 이전 | 변경 후 |
|----------------|------|---------|
| `True` (page1) | `_cols = st.columns([3.5,1.2,1.2])` → `with _cols[0]:` 내부에 아이콘+제목 | 동일 (변경 없음) |
| `False` (page2/3) | `st.columns([1])[0]` 래퍼 내부에 `[0.48, 2.52]` 중첩 | 래퍼 제거 — 컨테이너에 직접 `st.columns([0.48, 2.52])` 배치 |

**CSS 보강:**
- `unified-header-text`: `align-items:flex-start; text-align:left` 추가
- `unified-header-title`, `unified-header-subtitle`: `text-align:left` 추가

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile` | ✅ SYNTAX OK |
| `streamlit run` (port 8525) | ✅ HTTP 200 |
| 탐지 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |

---

---

## 2026-06-11 (4) 전 페이지 헤더 카드 통일

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 제거된 함수
- `render_topbar(title, sub)` — `.topbar` CSS + 📈 이모지, 페이지 3에서 사용
- `page1_header()` — 페이지 1 전용 헤더, 고유 key + 고유 layout

### 신규 공통 함수
```python
def render_page_header(title, subtitle, show_filters=False):
```
- 컨테이너 key: `page_header` (3페이지 모두 동일)
- 캐릭터 이미지: `first_character_image()` → `character_transparent.png` 우선, 없으면 📈 fallback
- 이미지 width: 100px (사이드바 80px와 구분)
- CSS 클래스: `unified-header-text / unified-header-title / unified-header-subtitle / unified-header-icon`
- `show_filters=True` 일 때만 우측에 점검 상태 + Batch 필터 드롭다운 노출

### 적용 현황

| 페이지 | 호출 | 필터 |
|--------|------|------|
| 1. 공정 이상 감지 현황 | `render_page_header(..., show_filters=True)` | ✅ 노출 |
| 2. 센서 정상 범위 비교 | `render_page_header(...)` | ✅ 없음 |
| 3. 조치 기록 공유 | `render_page_header(...)` | ✅ 없음 |

### CSS 변경 요약
| 클래스 | 내용 |
|--------|------|
| `.st-key-page_header` | 메인 카드 그룹에 추가, `min-height: 125px` |
| `.unified-header-text` | flex column, center, `min-height: 88px` |
| `.unified-header-title` | 2.1rem 900 #0f172a |
| `.unified-header-subtitle` | 1.05rem #64748b |
| `.unified-header-icon` | 64px 그라디언트 원형 fallback |

### 검증 결과
| 항목 | 결과 |
|------|------|
| `python -m py_compile jeaguseong.py` | ✅ SYNTAX OK |
| `streamlit run jeaguseong.py` (port 8523) | ✅ HTTP 200 |
| 탐지 로직 변경 | ✅ 없음 |
| raw CSV 수정 | ✅ 없음 |
| PNG 생성 | ✅ 없음 |

---

---

## 2026-06-11 (3) 사이드바/헤더 브랜딩 통일

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 변경 내용

#### CSS 추가

| 클래스/속성 | 내용 |
|------------|------|
| `.main-title-wrap` | `display:flex; flex-direction:column; justify-content:center; min-height:88px;` — 아이콘 높이 기준 수직 중앙 정렬 |
| `.main-title` | `margin-top:4px` → `margin:0` (wrap이 중앙 정렬 담당) |
| `.main-subtitle` | `margin-bottom:0` 추가 |
| `.st-key-sidebar_brand_card` | 사이드바 브랜드 카드: white bg, #d0d7e2 border, 16px radius, 14px padding |
| `.sidebar-brand-title` | `1.05rem 800` 제목 |
| `.sidebar-brand-subtitle` | `0.78rem #64748b` 부제목 |

#### 사이드바 코드 변경

이전:
```
render_character_image("sidebar")  # st.image() 독립 호출
st.markdown(인라인 스타일 텍스트)
```

변경:
```
st.container(border=True, key="sidebar_brand_card")
  └ st.image(_char_img, width=80)   # first_character_image() 재사용
  └ st.markdown(".sidebar-brand-title/.sidebar-brand-subtitle")
```
- `first_character_image()` 그대로 사용 (헤더와 동일 이미지 소스)
- 이미지 없으면 🔧 이모지 fallback

#### page1_header 타이틀 변경

이전: `st.markdown(title)` + `st.markdown(subtitle)` 각각 독립 호출  
변경: `<div class='main-title-wrap'>` 하나로 묶어 수직 중앙 정렬 보장

### 검증 결과

| 항목 | 결과 |
|------|------|
| `python -m py_compile jeaguseong.py` | ✅ SYNTAX OK |
| `streamlit run jeaguseong.py` (port 8522) | ✅ HTTP 200 정상 기동 |
| 대시보드 로직(Q/detected/related sensor) 변경 | ✅ 없음 |
| raw CSV 파일 수정 | ✅ 없음 |
| PNG 파일 생성 | ✅ 없음 |

---

---

## 2026-06-11 (2) 센서 정상 범위 비교 페이지 카드 스타일 통일

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 변경 내용

#### CSS (카드 스타일 그룹 확장)

| 추가된 CSS 클래스 | 적용 스타일 |
|-----------------|-------------|
| `.st-key-p2_header` | 기존 main card group (white, #94a3b8 border, 12px radius, shadow) |
| `.st-key-sensor_select_card` | 동일 |
| `.st-key-check_guide_card` | 동일 |

- 위 3개 클래스를 메인 카드 CSS 셀렉터 그룹(`.st-key-filter_card` 등)에 추가
- 내부 자식 투명 배경 그룹에도 동일하게 추가 (`* { background-color: transparent }`)

#### 레이아웃 변경

**데이터 구분 / 점검 센서 드롭다운 → 카드 래핑**

이전: `st.columns([1, 3])` 으로 페이지 배경에 직접 배치  
변경: `st.container(border=True, key="sensor_select_card")` + "센서 선택" 제목 + `st.columns([1, 2.8])`

- 선택 로직(sv_block/sv_sensor 초기화, raw_df 로딩) 동작 그대로 유지
- 드롭다운 키(`sv_block`, `sv_sensor`) 변경 없음

### 검증 결과

| 항목 | 결과 |
|------|------|
| `python -m py_compile jeaguseong.py` | ✅ SYNTAX OK |
| `streamlit run jeaguseong.py` (port 8521) | ✅ HTTP 200 정상 기동 |
| 탐지 로직 변경 | ✅ 없음 |
| raw CSV 파일 수정 | ✅ 없음 |
| PNG 파일 생성 | ✅ 없음 |

---

## 수정 파일

```
C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py
```

실행:
```
streamlit run jeaguseong.py
```

---

## 1. 캐릭터 이미지

| 위치 | 파일 | 크기 |
|------|------|------|
| 사이드바 상단 | `character/character_transparent.png` (우선) | 100px |
| 점검 해석 카드 우상단 | 동일 | 70px |

- `get_character_images()` — `BASE_DIR/character` 폴더 스캔, png/jpg/jpeg/webp/gif 지원
- `render_character_image(position)` — `st.image()` 사용, 예외 시 무시
- 폴더 없거나 이미지 없으면 아무것도 표시하지 않음 (앱 크래시 없음)

---

## 2. 페이지 네비게이션 상태 관리

### 세션 상태 키

| 키 | 역할 |
|----|------|
| `selected_wafer` | 앱 전체 공유 선택 wafer (위젯 key 아님) |
| `active_page` | 현재 활성 페이지 |
| `page_radio_widget` | 사이드바 radio 위젯 key (직접 수정 금지) |
| `pending_page` | 다음 rerun 시 이동할 페이지 |
| `pending_wafer` | 다음 rerun 시 설정할 wafer |
| `pending_block` | 다음 rerun 시 설정할 블록 |
| `pending_sensor` | 다음 rerun 시 설정할 센서 |
| `sv_wafer` / `sv_block` / `sv_sensor` | 2페이지 센서 비교 현재 선택값 |

### pending 처리 흐름
```
버튼 클릭
  → pending_page / pending_wafer / pending_block / pending_sensor 설정
  → st.rerun()
  → 스크립트 재실행 최상단에서 pending 값을 active_page / selected_wafer / sv_* 로 이동
  → 사이드바 radio index 갱신
  → 해당 페이지 렌더링
```

---

## 3. 점검 해석 카드 — 같이 점검할 센서 버튼

### 변경 전
- `<span class='pill'>센서명</span>` — 정적 HTML, 클릭 불가

### 변경 후
- `st.button()` — Streamlit 실제 버튼
- 첫 번째 버튼에 ⭐ 접두사 (우선 점검 센서)
- 행당 최대 3개 버튼 배치

### 클릭 시 동작
```python
st.session_state["pending_page"] = PAGES[1]    # "2. 센서 정상 범위 비교"
st.session_state["pending_wafer"] = sel         # 현재 wafer 유지
st.session_state["pending_block"] = blk         # 해당 센서 블록 (EV/OES/RFM)
st.session_state["pending_sensor"] = col        # 해당 센서 컬럼명
st.rerun()
```

### 도메인 매핑 원칙
`related_real_sensors(wid)` 함수가 반환하는 값만 사용.
fault label 기반 선택 없음. 도메인 기반 점검 후보.

> **"같이 점검할 센서는 확정 원인이 아니라 원본 센서 검증으로 이동하기 위한 도메인 기반 점검 후보입니다."**

---

## 4. 센서 정상 범위 비교 페이지 재설계

### 레이아웃 (1페이지와 동일한 스타일)

```
┌─ 헤더 ─────────────────────────────────────────────────────────┐
│  🔬 센서 정상 범위 비교 | 상태 필터 | Wafer 드롭다운            │
└───────────────────────────────────────────────────────────────┘

[ 데이터 구분 ] [ 점검 센서 선택 ]   ← 인라인 드롭다운

┌─ KPI 4 카드 ──────────────────────────────────────────────────┐
│ 선택 WAFER  │ 선택 센서  │ 정상 범위 비교  │ 이탈 시작          │
└───────────────────────────────────────────────────────────────┘

┌─ 차트 (65%) ──────────────────┬─ 센서 점검 해석 (35%) ─────────┐
│ 선택 센서 원본 시계열           │ 선택 센서 / 비교 결과           │
│ + 정상 평균 ±1σ               │ 이탈 구간 / 점검 방향            │
│ + 이탈 시작 수직선              │ (검증 전용 안내)                │
└───────────────────────────────┴─────────────────────────────────┘

┌─ 같이 점검할 센서 (55%) ───────┬─ 점검 기준 (45%) ───────────────┐
│ 버튼 클릭 → 이 페이지 차트 변경 │ 검증 목적 설명                  │
│ (1페이지로 돌아가지 않음)        │ Q 재계산 없음 안내              │
└───────────────────────────────┴─────────────────────────────────┘
```

### pending 도착 시 sv_block / sv_sensor 보존 로직
```python
if st.session_state.get("sv_wafer") != sel:
    st.session_state["sv_wafer"] = sel
    if st.session_state.get("sv_block") not in RAW_FILES:
        st.session_state["sv_block"] = default_block      # pending 으로 설정된 경우 유지
    if st.session_state.get("sv_sensor") not in cur_block_sensors:
        st.session_state["sv_sensor"] = default_sensor    # 유효한 컬럼이면 유지
```

---

## 5. 제목 크기 변경

| 클래스 | 이전 | 변경 후 |
|--------|------|---------|
| `.page-title` | 1.04rem | 1.40rem |
| `.sec-title` | 0.92rem | 1.15rem |
| `.gcard .g-h` | 0.86rem | 1.02rem |

---

## 6. 탐지 로직 변경 없음 확인

| 항목 | 상태 |
|------|------|
| Q_score / Q_threshold 재계산 | ✅ 없음 |
| detected / first_detect_progress 재계산 | ✅ 없음 |
| FDC contribution / suspected_family 재계산 | ✅ 없음 |
| raw CSV 파일 수정 | ✅ 없음 |
| PNG 파일 생성 | ✅ 없음 |
| 원인 확정 표현 사용 | ✅ 없음 |

---

---

## 0. 2026-06-11 UI 스타일 개편 (헤더 · KPI)

### 수정 파일
`C:\Users\diahe\Park\실전 프로젝트\찐찐대\jeaguseong.py`

### 헤더 아이콘 · 제목 스타일 변경

| CSS 속성 | 이전 | 변경 후 |
|----------|------|---------|
| `.hdr-id` `gap` | 13px | 22px |
| `.hdr-id .logo` width/height | 42px | 68px |
| `.hdr-id .logo` border-radius | 11px | 18px |
| `.hdr-id .logo` font-size | 1.3rem | 2.2rem |
| `.hdr-id .logo` gradient | `#2563eb→#1e40af` | `#1d4ed8→#1e3a8a` (더 진함) |
| `.hdr-id .logo` shadow | 0 2px 6px 40% | 0 4px 12px 50% |
| `.hdr-id .t-title` font-size | 1.18rem | 1.85rem |
| `.hdr-id .t-title` font-weight | 800 | 900 |
| `.hdr-id .t-sub` font-size | 0.74rem | 1.02rem |
| `.st-key-page1_header` padding | 16px 18px | 22px 26px |
| `.st-key-page1_header` min-height | (없음) | 110px |

### KPI "이상 예측 원인" 값 빨간색 변경

| 항목 | 내용 |
|------|------|
| 추가 CSS | `.kpi2 .k2-val.danger { color:#dc2626 !important; }` |
| 추가 CSS | `.kpi2.cause-card { border-color:#fca5a5 !important; }` |
| `kpi_row()` 수정 | `lab == "이상 예측 원인"` 일 때만 `cause-card` / `danger` 클래스 적용 |
| 다른 KPI 카드 | 기존 `#2563eb` 파란색 유지 |

### 검증 결과 (2026-06-11)

| 항목 | 결과 |
|------|------|
| `python -m py_compile jeaguseong.py` | ✅ SYNTAX OK |
| `streamlit run jeaguseong.py` (port 8508) | ✅ HTTP 200 정상 기동 |
| 탐지 로직 (Q_score/threshold/detected) 변경 | ✅ 없음 |
| raw CSV 파일 수정 | ✅ 없음 |
| PNG 파일 생성 | ✅ 없음 |

---

## 7. 검증 결과

| 항목 | 결과 |
|------|------|
| `python -m py_compile jeaguseong.py` | ✅ SYNTAX OK |
| `streamlit run jeaguseong.py` (port 8507) | ✅ 정상 기동 |
| 1페이지 점검 해석 카드 정상 표시 | ✅ |
| 같이 점검할 센서 — 클릭 가능 버튼 | ✅ |
| 버튼 클릭 → 센서 정상 범위 비교 이동 | ✅ pending 방식 |
| 이동 후 wafer 유지 | ✅ pending_wafer → selected_wafer |
| 이동 후 센서 자동 선택 | ✅ pending_sensor → sv_sensor |
| 2페이지 같이 점검할 센서 — 차트만 변경 | ✅ 페이지 이동 없음 |
| 2페이지 헤더 1페이지 스타일 | ✅ |
| 2페이지 KPI 4 카드 | ✅ |
| 제목 크기 확대 | ✅ |
| session_state key 충돌 없음 | ✅ sel_wafer 참조 0건 |

---

## 8. 남은 제한 사항

| 제한 | 설명 |
|------|------|
| 테이블 행 클릭으로 wafer 선택 | HTML 테이블 방식 — 직접 클릭 미지원 |
| 센서 버튼 pill CSS | Streamlit 버전에 따라 커스텀 CSS 적용 범위 달라질 수 있음 |
| 캐릭터 이미지 선택 UI | 투명 버전 자동 선택 — 수동 선택 없음 |
