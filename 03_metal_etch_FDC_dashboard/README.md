# Project 03. 배치 drift를 반영한 금속 식각 FDC

[전체 포트폴리오](../README.md) · [Live Dashboard](https://fdc-monitoring-dashboard-pprv4chs5yrhooo2dpm3oy.streamlit.app/)

EV·OES·RFM 센서 데이터를 통합하고 정상 패턴 기반 MPCA로 이상을 탐지했습니다.
배치별 분포 차이를 반영한 관리한계와 센서 기여도 분석을 통해 현장 점검을 지원하는 Streamlit 대시보드를 구현했습니다.

![FDC 대시보드](images/dashboard_main.png)

## 문제 정의

분석 대상은 **126개 웨이퍼(정상 106개, 이상 20개)**입니다.
이상 유형별 표본이 부족해 결함 유형을 직접 분류하기보다 정상 패턴에서의 이탈을 탐지하는 방식으로 접근했습니다.
단일 정상 분포를 가정한 Global MPCA에서는 배치 간 drift로 오경보가 특정 배치에 집중되는 문제가 있었습니다.

## 분석 방법

1. EV·OES·RFM 센서 블록을 통합하고 공통 변동 구조를 확인했습니다.
2. PCA로 고차원 변수를 압축하고 정상 패턴을 학습했습니다.
3. T²와 Q 통계량으로 주성분 공간과 잔차 공간의 이탈을 평가했습니다.
4. 배치별 관리한계를 적용해 drift에 따른 오경보 편차를 완화했습니다.
5. 실제 센서값과 PCA 복원값의 잔차 기여도로 원인 후보 센서를 추적했습니다.

## 포트폴리오에 기록된 평가 결과

| 지표 | 결과 |
|---|---|
| Recall | **100%** |
| F1-score | **93%** |
| 배치 29 FAR | 3.1% |
| 배치 31 FAR | 2.8% |
| 배치 33 FAR | 2.9% |
| 관리한계 | 배치별 99% 기준 |

분석 데이터에서 얻은 결과이며, 결함 유형별 표본이 적어 신규 조건에 대한 일반화에는 추가 검증이 필요합니다.

## 대시보드

| 화면 | 기능 |
|---|---|
| 공정 이상 감지 현황 | 웨이퍼 목록, Q 통계량 차트, 점검 대상 KPI와 해석 |
| 센서 점검 | EV/OES/RFM 시계열과 정상 기준 비교, 이탈 구간과 점검 방향 |
| 조치 기록 공유 | 조치 내용 저장, 확인·완료 상태 관리 |

분석 모델의 T²·Q 평가와 공개 대시보드의 Q 중심 표시를 구분했습니다.
센서 기여도는 점검 후보를 제시하며 물리적 원인을 확정하지 않습니다.

## 본인 기여

데이터 통합·EDA, MPCA 모델링·해석에 참여하고 Streamlit 대시보드를 구현했습니다.

## 한계와 후속 과제

결함 유형별 표본 확보 후 자동 분류 성능을 검증할 필요가 있습니다.
장비 정비 이력과 장기 시계열 연속성이 부족하므로, 고장·정비 시점 예측으로 확장하려면 추가 데이터가 필요합니다.

## 기술

Python · Pandas · NumPy · Scikit-learn · PCA/MPCA · Streamlit · Plotly

## 실행

저장소를 내려받은 뒤 저장소 루트에서 실행합니다. 의존성 파일명은 현재 저장소의 `requirments.txt`를 사용합니다.

```bash
cd 03_metal_etch_FDC_dashboard/FDC_dashboard
python -m pip install -r requirments.txt
python -m streamlit run FDC_dashboard.py
```

## 분석 자료

- [대시보드 코드](FDC_dashboard/FDC_dashboard.py)
- [대시보드 상세 보고서](FDC_dashboard/DASHBOARD_FINAL_REPORT.md)
- [센서 분석·MPCA·drift 노트북](notebooks/)
- [분석 보고서](%EA%B8%88%EC%86%8D_%EC%97%90%EC%B9%AD_%EB%8D%B0%EC%9D%B4%ED%84%B0_%EB%B6%84%EC%84%9D.pdf)
