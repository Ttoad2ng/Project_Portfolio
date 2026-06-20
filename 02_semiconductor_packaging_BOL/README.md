
<h2># Project 02 — 반도체 패키징 공정 불량 분석 및 예측</h2>

> **Semiconductor Back-end-of-Line (BOL) Process Defect Analysis & ML Prediction**

---

### Background

반도체 패키징(BOL) 공정은 5개의 Stage로 구성되며, 각 Stage의 공정 변수가 최종 불량 여부에 복합적으로 영향을 미친다.  
본 프로젝트는 통계 분석을 통해 정상/불량 그룹 간 의미 있는 차이를 보이는 변수를 선별하고,  
머신러닝 모델을 통해 불량을 사전에 예측하는 파이프라인을 구축한다.

<p align="center">
  <img src="./images/모델 성능.png">
</p>
---

### Summary

- **(1) Data Information**
  - `features_train.csv`: **16,998개 샘플**, **40개 피처** (5-Stage 공정 변수 — 온도, 유량, 압력 등)
  - `labels_train.csv`: 정상(0) / 불량(1) 레이블
  - 5개 공정 Stage별 주요 변수로 구성 (각 Stage당 복수의 공정 파라미터)

- **(2) Data Preprocessing**
  - EDA: 30% 이상 결측 피처 제거, 나머지는 Median 대체
  - 공정 Stage별로 중요 피처 선정
  - Q-Q Plot + Shapiro-Wilk 검정으로 정규성 확인
  - 결측 처리 후 VIF 확인 및 다중공선성 제거

- **(3) Statistical Analysis**
  - **Welch t-test**: 정규 분포 변수에서 정상/불량 그룹 간 평균 차이 검증
  - **Mann-Whitney U test**: 비정규 분포 변수에서 그룹 간 중위수 차이 검증
  - 통계적으로 유의한 변수만 모델 학습에 투입
  - 통합 공정 기반으로 불량을 예측하고 업스트림 공정 기여 원인 탐색

- **(4) Machine Learning**
  - Train/Test Split → KNNImputer → StandardScaler → PCA (선택적)
  - SMOTE (학습 데이터에만 적용): 클래스 불균형 처리
  - 모델 비교: `LightGBM` / `XGBoost` / `Random Forest`
  - Threshold 최적화 (Recall 기준)
  - Stratified K-Fold 교차 검증
  - Feature Importance + SHAP 분석

- **(5) Key Findings**
  - 공정 Stage별 주요 변수(온도, 유량, 압력 계열)에서 정상/불량 그룹 간 통계적으로 유의한 차이 확인
  - 통계적으로 유의한 변수만 사용했을 때 ML 모델의 Recall 성능 향상
  - SHAP 분석을 통해 특정 공정 Stage의 온도/압력 변수가 불량 예측에 가장 크게 기여함을 확인

- **(6) Retrospective**
  - 통계 분석과 ML 모델링을 순차적으로 연결한 체계적인 파이프라인 구성
  - 결측 처리 전략(30% 기준 제거 + Median 대체)의 타당성을 추가로 검증할 여지가 있음
  - SHAP 인사이트를 공정 개선 방향으로 연결하는 후속 작업 필요

---

### Stack

`Python` · `Pandas` · `Scikit-learn` · `LightGBM` · `XGBoost` · `SHAP` · `SMOTE (imbalanced-learn)` · `SciPy`

---

### Files

| 파일 | 설명 |
|------|------|
| `통계&머신러닝코드합본_최종.ipynb` | 통계 분석 + ML 모델링 전체 코드 |
| `반도체_패키징_공정_불량_분석_및_예측_.pdf` | 최종 결과 보고서 |

---

### GitHub

> 🔗 [GitHub Repository]( )  <!-- 링크 추가 예정 -->
