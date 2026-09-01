## V6.0.21

- **미국 개별 종목 히트맵을 테마 그룹 중첩 구조로 개편**: 빅테크·플랫폼, AI·반도체, AI·클라우드·소프트웨어, 소비·유통, 바이오·헬스케어, 에너지·전력, 결제·금융 7개 테마로 묶어, 카테고리 타일 안에 개별 종목 타일이 들어가는 구조(Finviz 스타일)로 바꿨습니다. 카테고리 타일 색은 그룹 평균 등락률, 크기는 그룹 내 종목들의 변동폭 합입니다.
- 로고 이미지는 지원되지 않아 티커 텍스트로 표시된다는 점을 캡션에 명시했습니다.
- 한국 개별 종목 히트맵은 업종당 대표 종목이 1개뿐이라 테마 그룹화 대상에서 제외하고 기존 평면(flat) 구조를 유지합니다.

## V6.0.20

- **통합판단(Decision Dashboard)도 눌림목·모멘텀 가격 계획을 항상 함께 표시**하도록 변경했습니다 (기존엔 우선 방식 하나만 표시). 핵심분석(Entry Engine)과 표시 방식이 일관됩니다.
- **우선 진입 방식 하이라이트 추가**: 두 화면 모두에서, 현재 더 적합한 방식(Preferred Approach)의 가격 계획 카드에 파란 테두리와 "⭐ 우선 방식" 배지가 표시됩니다. 두 방식이 모두 유효한 경우(Both Valid)는 둘 다 하이라이트됩니다.

## V6.0.19

- **포지션 사이징 계산기에 서술형 요약 추가**: "진입가 X에 N주 매수 → 투입금액/잔여현금 → 손절가 Y까지 하락 시 주당 손실 · 총 손실 · 계좈 대비 %"를 문장으로 풀어서 보여줍니다. 리스크 역산 공식만 보여주던 이전 방식 대신, 실제 매수·손절 시나리오를 이야기하듯 따라갈 수 있게 했습니다.
- 투입 금액 카드에 잔여 현금을 함께 표시합니다.

## V6.0.18

- **포지션 사이징 계산기 이해도 개선**:
  - 계산 과정을 "허용 손실 ÷ 주당 리스크 = 참고 수량" 수식 형태로 그대로 보여줘서, 숫자가 왜 그렇게 나왔는지 바로 보이게 했습니다.
  - 투입 금액이 계좌의 70% 이상이면 **경고 박스**로 "손실 허용 비율"과 "투입 비중"이 다른 개념임을 설명합니다 (손절 거리가 좁을수록 적은 리스크 비율로도 큰 금액이 필요해질 수 있음).
  - **계좌 현금 한도 반영**: 리스크 기준 필요 수량이 실제 살 수 있는 수량(계좌 규모 ÷ 진입가)보다 많으면 자동으로 제한하고, 이 경우 실제 손실이 목표보다 작아진다는 점을 안내합니다.
  - Risk 배율이 1.00×(축소 없음)일 때는 "허용 손실 한도를 낮췄다"는 문구를 더 이상 표시하지 않습니다 — 배율이 실제로 적용될 때만 표시해 같은 숫자를 두 번 말하는 혼란을 없앴습니다.

## V6.0.17

- **개별 종목 히트맵 추가**: 업종 히트맵 아래에 시가총액 상위 대형주(미국: 나스닥 대표 대형 기술주 · 한국: 코스피 대표 종목) 개별 등락률 히트맵을 추가했습니다.
- 히트맵에 **범례**(상승/하락 색상, 타일 크기 = 등락폭)와 **"히트맵 읽는 법" 설명 expander**를 추가했습니다.
- **화폐 단위 명시**: 지수 카드, 가격 계획(진입가/손절가/목표가) 카드에 원화(원)·달러($) 단위를 명확히 표시했습니다. 지역(미국/한국)에 따라 자동으로 구분됩니다.
- **포지션 사이징 계산기 입력 개선**: 계좌 규모 입력을 콤마 포함 텍스트로 받을 수 있도록 변경하고, 입력 즉시 파싱된 값을 원/달러 단위로 확인해주는 문구를 추가했습니다 (예: "20"과 "20,000,000"을 헷갈리는 실수 방지).

## V6.0.16

- **포지션 사이징 계산기 추가**: 눌림목/모멘텀 가격 계획 카드 아래에 계좌 규모 · 1회 손실 허용 비율을 입력하면 참고 매수 수량을 계산해주는 계산기를 추가했습니다. 손절가 기준 리스크(진입가-손절가)와 Risk Engine의 포지션 배율을 함께 반영합니다. 매수 여부·수량을 결정해주는 기능이 아니라 리스크 관리 참고용입니다.
- **스캐너 결과에 목표가 추가**: 모멘텀/눌림목 진입 후보 탭에 진입가·손절가·목표가1 컬럼을 추가해, 여러 종목을 한 번에 훑을 때도 가격 계획을 바로 확인할 수 있습니다.

## V6.0.15

- **Entry Engine 가격 계획 추가**: 눌림목/모멘텀 각 Setup에 진입 기준가·손절가·목표가 1·2·R:R 비율을 명시적으로 계산해 표시합니다 (`SetupScore.entry_price/stop_loss/target1/target2/risk_reward1/risk_reward2/risk_pct`). READY/CONFIRMED 상태가 아니어도 항상 계산되어, 지금 조건이 갖춰지면 어떤 가격대를 볼지 미리 계획할 수 있습니다.
- V6 통합 판단(Decision Dashboard) 상단에 '추천 매수가·목표가·손절가' 섹션을 추가해 상세 분석까지 가지 않아도 가격 계획을 바로 확인할 수 있습니다.
- 목표가는 실제 지지/저항 Zone을 우선 사용하고, 구조가 없으면 ATR 배수로 대체해 항상 값을 표시합니다.
- **시장환경 대시보드 확장**: 지수 카드 요약(MA5/20/60/120/200 위치), 업종 히트맵(미국 11개 섹터 ETF · 한국 대표종목 참고용), 공포·탐욕 게이지(Market Regime 점수 기반 자체 산출), 매크로 리스크 종합차트(지수·VIX·유가·금·달러 정규화 비교)를 추가했습니다.
- 공포·탐욕 게이지는 CNN Fear & Greed Index와 동일하지 않은 자체 산출값임을 명시했습니다.

## V6.0.14
- Added a Calibration scope summary showing the exact threshold meaning, full price-data range, Entry-calculation range, and horizon-specific validation windows/trading-day counts.
- Added explicit definitions for validation date, reference close, Setup episode, and 5D/10D/20D/60D outcome windows.
- Added an actual case-generation flow: qualifying trading days → Setup episodes → horizon-specific validation samples.
- Clarified that 'qualifying trading days' means all days with Entry Score greater than or equal to the selected threshold.

# V6.0.14

- Reworked Entry Calibration sampling so low thresholds (30-50) do not collapse into only a few episode-start cases.
- Clarified that a threshold means Entry Score >= selected value (e.g. 40 means 40-100).
- Separated qualifying days, Setup episodes, and horizon-specific validation dates.
- Added independent 5D/10D/20D/60D sampling gaps and sample counts.
- Added sample concentration checks across Setup episodes and a "국면 집중" warning.
- Added actual 20D validation dates, Entry Scores, reference closes, forward returns, and MDD for auditability.
- Kept the 30-90 slider with 5-point steps and 75 default.

## V6.0.12
- Expanded Entry Calibration threshold range to **30~90** with **5-point steps** while keeping 75 as the default.
- Added plain-language guidance that low thresholds are for score-discrimination testing, not relaxed buy recommendations.
- Added threshold-zone interpretation for comparison / neutral / broad / balanced / strict validation ranges.
- Preserved the V6.0.11 Decision Dashboard, Quant interpretation, and historical validation case logic.

## V6.0.11
- Added **V6 통합 판단 (Decision Dashboard)** between Scanner and detailed analysis.
- Reorganized the workflow into Scanner → Integrated Decision → Core / Quant / Options / Market / Calibration / History.
- Added Quant Profile classification, Overall × Quant consistency, and Entry Implication.
- Added automatic Quant Chart Interpretation for trend structure, price position, momentum, and demand.
- Renamed Trend / Leadership to **Trend Strength** in the primary UI to reduce overlap with Relative Strength.
- Added 5D / 10D / 20D / 60D average-return strips to Calibration strategy cards; 60D is explicitly treated as trend-persistence context.
- Reuses existing scoring engines; this release focuses on hierarchy, interpretation, and decision flow.

## V6.0.9
- Reworked Calibration case counting into Setup Episodes and 20D validation cases.
- A new Setup Episode requires at least 3 below-threshold trading rows before re-entry.
- Primary 20D validation cases are spaced by at least 20 trading rows to reduce overlapping forward-return windows.
- Fixed stale-cache risk that could show inconsistent positive-case counts and hit rates such as `0 / N (84%)`.
- Added explicit validation-window, lookback, forward-buffer, case-counting, and sample-confidence explanations in the UI.
- Replaced the ambiguous `Independent` label with `Setup 구간` and `20D 검증 사례`.

## V6.0.8
- Adjusted Calibration strategy card layout to prevent text clipping by removing fixed card height and increasing stat box space.

# Changelog

## V6.0.8
- Renamed Calibration to **과거 진입 검증 (Entry Calibration)** and reorganized it around current-entry validation.
- Pulls the current Pullback / Momentum scores and readiness directly from the main analysis.
- Clarifies that the shared threshold selects historical validation cases and does not modify the current Entry score.
- Adds historical Entry style classification: Pullback-oriented, Momentum-oriented, mixed, or insufficient data.
- Adds plain-language strategy cards with independent cases, 20D positive cases, median/average return, and MDD.
- Adds Current × Historical Validation alignment interpretation.
- Uses spaced independent signal observations for headline performance statistics to reduce multi-day signal duplication.
- Moves detailed 5D/10D/20D/60D statistics and raw rows into expandable sections.

## V6.0.6
- Separated preferred entry approach from actual entry readiness.
- Added a four-part Entry Decision summary: Pullback score, Momentum score, preferred approach, and current readiness.
- Added situation-specific Korean interpretation for mature pullbacks, developing pullbacks, confirmed momentum, extended momentum, and no-clear-setup cases.
- Updated top Decision Summary and Analysis Consensus to avoid interpreting a relative setup preference as an automatic buy signal.

# Changelog

## V6.0.5
- Polished summary card labels with Korean-first / English-on-next-line formatting for aligned value rows.
- Increased Consensus lens card height so long notes (especially Entry Setup) remain fully visible.
- Refined 10-day chart label offsets so numeric tags stay closer to their own series.

# V6.0.4

- Renamed the top stock overview to **종합 판단 요약 (Decision Summary)** and standardized its five summary cards to the same height.
- Reordered the overall-analysis flow to Decision Summary → AI Briefing → Entry → Risk → Analysis Consensus → 10D trajectory → detailed Company/Market analysis.
- Added a dedicated **Analysis Consensus · 분석 관점 일치도** section with Company, Quant/Trend, Entry Setup, Market Regime, and Options lenses.
- Separated **Signal Agreement** from **Data Confidence** and added a plain-language consensus interpretation.
- Rewrote Company Quality factor descriptions so each card explains what Growth, Profitability, Balance Sheet, Cash Flow, and Valuation actually mean.
- Kept Opportunity / Entry / Risk scoring engines unchanged; this release focuses on information hierarchy, explainability, and layout consistency.

# V6.0.3

- Polished 10-trading-day charts with vertical trading-day guides, non-overlapping colored score labels, and per-series 5D change summaries.
- Added Korean + English naming for Opportunity, Pullback Entry, Momentum Entry, Company Quality factors, and key Quant factors.
- Added clearer Entry status color hierarchy and detailed status explanations.
- Added Risk Engine status colors and a clearer overall risk summary.
- Normalized auxiliary Quant and Company card heights.
- Replaced developer-oriented missing-data wording with user-friendly explanations.
- Expanded AI briefings for first-time users without changing V6 scoring logic.
- Kept the V6 engine logic unchanged; this release focuses on visual clarity and explainability.

# V6.0.2

- 스캐너를 종목 검색 위로 이동하고 주요 스캐너 탭을 한글화했습니다.
- 종목 매력도 / 모멘텀 진입 / 눌림목 진입 의미 설명을 추가했습니다.
- 상단 V6 안내 경고 배너를 제거했습니다.
- 카드 높이와 섹션 간격을 정리했습니다.
- Market Regime을 사용자 화면에서 '시장 국면'과 한글 상태명으로 표시합니다.
- 최근 10영업일 차트를 실제 거래일 기준 카테고리 축으로 변경하고 모든 마커와 색상 일치 숫자 라벨을 표시합니다.
- 퀀트 분석에 AI 퀀트 브리핑과 세부 점수를 추가했습니다.
- 시장환경을 V5 스타일의 시장 건강도 + 10D + Market Pulse + 금리/신용 패널 구조로 보강했습니다.
- Market Pulse 12와 금리/신용 지표에 해석 문구를 추가했습니다.

# Changelog

## V6.0.1 — Explainability & UX Restoration

- Preserved V6 Opportunity / Setup / Risk / Market / Consensus architecture.
- Removed Scanner from individual-stock radio navigation; Scanner is now an independent section.
- Added separate Quant Analysis menu.
- Restored AI Overall, Company, Quant, Entry and Market/Risk briefing cards.
- Added Korean-facing Entry state labels while preserving internal English states.
- Added direct explanations of Pullback Entry and Momentum Entry.
- Standardized Entry / Risk / factor card heights and increased section spacing.
- Restored 10-trading-day reconstructed score charts.
- Added Quant Composite explainability layer.
- Restored CAN SLIM analysis and CAN SLIM reading guide.
- Restored auxiliary quant indicators.
- Restored detailed technical and financial indicator rows and peer comparison.
- Restored V5-style Market Pulse with equities, volatility, commodities, FX and crypto.
- Added rate/credit helper panel.
- Expanded Calibration UX: threshold explanation, independent signals, median 20D, validation period, result summary, table guide and small-sample warning.
- Added `.streamlit/config.toml` and `.gitignore`.
- Expanded offline smoke tests to include Quant / CAN SLIM and Calibration outputs.

## V6.0

- Introduced Opportunity Engine, Entry Engine V3, Risk Engine, US/KR Market Regime, S/R Zones, Consensus V2, market scanners, SQLite history and price-only calibration foundation.
