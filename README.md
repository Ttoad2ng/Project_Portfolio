
# Data Analytics Portfolio

반도체 공정 데이터를 다루는 데이터 분석 프로젝트 포트폴리오입니다.  
EDA와 통계 분석부터 머신러닝 모델링, 실시간 이상 탐지 대시보드까지 end-to-end 분석 경험을 담았습니다.

---

## Projects

---

### Project 01 — 불량은 우연이 아니다: 데이터 시각화로 찾는 숨은 이상탐지

> Wafer Defect Hidden Pattern Detection via Data Visualization

웨이퍼 스캐닝 결함 데이터(63,909개)를 분석하여, 결함의 공간적 분포·광학 특성·형태 특성을 다각도로 시각화한다.  
가우시안 블러 히트맵과 극좌표계 분석을 통해 공정별 결함 패턴의 구조적 차이를 발굴한다.

**Key Stack** `Python` · `Pandas` · `Matplotlib` · `Seaborn` · `SciPy`

> 🔗 [웨이퍼 결함 분석 프로젝트 바로가기](01_wafer_defect_detection)

---

### Project 02 — 반도체 패키징 공정 불량 분석 및 예측

> Semiconductor BOL Process Defect Analysis & ML Prediction

5-Stage 반도체 패키징 공정 데이터(16,998개, 40피처)를 대상으로  
Welch t-test / Mann-Whitney U 검정으로 불량 유의 변수를 선별하고,  
LightGBM·XGBoost·Random Forest 비교 및 SHAP 분석으로 불량 예측 모델을 구축한다.

**Key Stack** `Python` · `Scikit-learn` · `LightGBM` · `XGBoost` · `SHAP` · `SMOTE`

> 🔗 [반도체 패키징 공정 분석 프로젝트 바로가기](02_semiconductor_packaging_BOL)

---

### Project 03 — 금속 에칭 공정 FDC 모니터링 대시보드

> Metal Etching Process FDC Monitoring Dashboard (Streamlit)

EV·OES·RFM 3종 다변량 센서 데이터에 MPCA 기반 스트리밍 이상 탐지를 적용하고,  
FDC Contribution 분석으로 이상 원인 센서 계열을 식별한다.  
현장 엔지니어를 위한 3페이지 Streamlit 대시보드(이상 감지 현황 / 센서 점검 / 조치 기록)를 구현한다.

**Key Stack** `Python` · `Streamlit` · `Plotly` · `Scikit-learn (PCA)` · `Pandas`

> 🔗 [금속 에칭 공정 FDC 시스템 바로가기](03_metal_etch_FDC_dashboard)
> 🔗 [금속 에칭 공정 FDC 시스템 대시보드 바로가기](https://fdc-monitoring-dashboard-pprv4chs5yrhooo2dpm3oy.streamlit.app/)


---

## Skills Overview

| 영역 | 주요 기술 |
|------|----------|
| 데이터 처리 | Pandas, NumPy, KNNImputer, SMOTE |
| 통계 분석 | t-test, Mann-Whitney U, Shapiro-Wilk, Q-Q Plot, VIF |
| 시각화 | Matplotlib, Seaborn, Plotly, 가우시안 블러 히트맵, 극좌표계 시각화 |
| 머신러닝 | LightGBM, XGBoost, Random Forest, Scikit-learn, SHAP |
| 이상 탐지 | MPCA (Q statistic), 스트리밍 감지, FDC Contribution 분석 |
| 대시보드 | Streamlit, 다중 페이지 설계, 세션 상태 관리, 커스텀 CSS |

---

## Contact

> E-mail: [diaheejung@naver.com]
