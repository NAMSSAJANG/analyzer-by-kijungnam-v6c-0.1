"""Streamlit UI for the independent Trade Lab accounting engine."""
import pandas as pd
import streamlit as st

from trade_engine import Costs, Position, SCENARIOS, affordable_shares, simulate, target_average


def render_trade_lab():
    st.header("Trade Lab · 분할매매 실험실")
    st.caption("수량·평단·현금·총자산을 함께 비교합니다. 종목 검색 없이 사용할 수 있으며 모든 금액은 선택한 한 통화 기준입니다.")
    currency = st.selectbox("계산 통화", ["USD", "KRW"], key="tl_currency")
    cols = st.columns(4)
    shares = cols[0].number_input("보유수량 (주)", min_value=0, value=20, step=1, key="tl_shares")
    average = cols[1].number_input("기존 평균단가", min_value=0.0, value=100.0, key="tl_average")
    price = cols[2].number_input("현재가 / 시작가", min_value=0.01, value=70.0, key="tl_price")
    cash = cols[3].number_input("시작 현금 (추가매수 자금 포함)", min_value=0.0, value=1400.0, key="tl_cash")
    st.caption(f"단위: {currency}. 기존 평균단가는 매수비용을 포함한 값으로 입력하세요. 시작 현금은 모든 비교 전략에 똑같이 적용합니다.")
    with st.expander("수수료·거래세·체결 오차"):
        c = st.columns(4)
        bf = c[0].number_input("매수 수수료 (%)", 0.0, 10.0, 0.0, .01, key="tl_bf")
        sf = c[1].number_input("매도 수수료 (%)", 0.0, 10.0, 0.0, .01, key="tl_sf")
        tax = c[2].number_input("매도금액 기준 거래세 (%)", 0.0, 10.0, 0.0, .01, key="tl_tax")
        slip = c[3].number_input("불리한 체결 오차 (%)", 0.0, 10.0, 0.0, .01, key="tl_slip")
        st.caption("기본 비용은 0이므로 적용할 값을 직접 입력하세요. 거래세는 매도대금 기준이며 양도소득세 계산은 포함하지 않습니다. 환율·배당·주식분할·이자는 반영하지 않습니다.")
    costs = Costs(bf / 100, sf / 100, tax / 100, slip / 100)
    try:
        initial = Position(shares, average, cash, price, costs)
    except ValueError as exc:
        st.info(str(exc))
        return
    calculator, scenario, target = st.tabs(["매매 계산 · 물타기/불타기", "시나리오 · 단순보유 비교", "목표 평단 · 수량 늘리기"])
    with calculator:
        st.subheader("계획한 순서대로 매수·매도")
        st.caption("표 위에서 아래로 실행합니다. 가격과 수량을 수정하거나 행을 추가하세요. 현금·수량이 부족한 주문은 전량 미체결 처리합니다.")
        orders = st.data_editor(pd.DataFrame([{"매매": "매수", "가격": float(price), "수량": 1}]),
            num_rows="dynamic", hide_index=True, key="tl_orders",
            column_config={"매매": st.column_config.SelectboxColumn(options=["매수", "매도"], required=True),
                           "가격": st.column_config.NumberColumn(min_value=.01, required=True),
                           "수량": st.column_config.NumberColumn(min_value=1, step=1, required=True)})
        mark = st.number_input("매매 후 평가할 가격", min_value=.01, value=float(price), key="tl_mark")
        if st.button("매매 계획 계산", type="primary", key="tl_calc"):
            p = Position(shares, average, cash, price, costs)
            rows = [{"순서": 0, "결과": "시작", **p.snapshot(price)}]
            for idx, row in enumerate(orders.to_dict("records"), 1):
                try:
                    p.trade(row["매매"], row["수량"], row["가격"])
                    status = f'{row["매매"]} 체결'
                except (ValueError, TypeError, ArithmeticError) as exc:
                    status = f"미체결: {exc}"
                rows.append({"순서": idx, "결과": status, **p.snapshot(mark)})
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            last = p.snapshot(mark)
            hold = initial.snapshot(mark)
            st.metric("단순보유 대비 총자산 차이", f'{last["총자산"] - hold["총자산"]:,.2f} {currency}')
            st.caption("평가손익은 잔여주식의 비용 포함 원가 기준입니다. 매도해도 잔여주식 평단은 유지됩니다. 전체투자 본전가는 누적 실현손익과 남은 현금을 포함하고, 잔여주식 본전가는 보유주식만의 청산비용을 포함합니다.")
    with scenario:
        st.subheader("같은 시작 자산으로 전략 비교")
        core = st.number_input("매도하지 않고 유지할 수량", min_value=0, max_value=shares, value=0, key=f"tl_core_{shares}")
        st.caption("각 규칙은 시작 이후 조건이 처음 충족된 관측점에서 한 번만 처리됩니다. 같은 단계에서는 표 순서로 처리하고, 미체결 주문도 자동 재시도하지 않습니다.")
        rules = st.data_editor(pd.DataFrame([
            {"매매": "매도", "조건": "이상", "기준가격": round(price * 1.10, 2), "수량": max(1, shares // 5)},
            {"매매": "매수", "조건": "이하", "기준가격": round(price * .95, 2), "수량": max(1, shares // 4)},
            {"매매": "매수", "조건": "이하", "기준가격": round(price * .85, 2), "수량": max(1, shares // 4)},
        ]), num_rows="dynamic", hide_index=True, key="tl_rules",
            column_config={"매매": st.column_config.SelectboxColumn(options=["매수", "매도"], required=True),
                           "조건": st.column_config.SelectboxColumn(options=["이하", "이상"], required=True),
                           "기준가격": st.column_config.NumberColumn(min_value=.01, required=True),
                           "수량": st.column_config.NumberColumn(min_value=1, step=1, required=True)})
        custom = st.text_input("직접 가격 경로 (선택 · 쉼표로 구분, 첫 가격은 시작가)", placeholder="70, 80, 65, 85, 60, 90", key="tl_path")
        st.caption("조건가격을 건너뛰면 실제 관측가격에 체결 오차를 더해 계산합니다. 관측점 사이의 움직임과 일중 고저가는 추정하지 않습니다. 이는 가정 시나리오이며 과거 주가 백테스트나 확률 예측이 아닙니다.")
        if st.button("5가지 시나리오 비교", type="primary", key="tl_sim"):
            paths = {name: [price * x for x in multipliers] for name, multipliers in SCENARIOS.items()}
            try:
                if custom.strip():
                    values = [float(x.strip()) for x in custom.split(",")]
                    if not values or abs(values[0] - price) > .000001:
                        raise ValueError("직접 경로의 첫 가격은 현재가 / 시작가와 같아야 합니다.")
                    paths["직접 경로"] = values
                summary = []
                details = []
                for name, path in paths.items():
                    for strategy, recycle, active in [("단순보유", False, []), ("분할매매 · 매도금 보관", False, rules.to_dict("records")), ("분할매매 · 매도금 재사용", True, rules.to_dict("records"))]:
                        records, journal = simulate(shares, average, cash, path, active, costs, core, recycle)
                        end = records[-1]
                        summary.append({"시나리오": name, "전략": strategy, **{k: end[k] for k in ["보유수량", "평균단가", "현금", "총자산", "실현손익", "기간수익률(%)", "최대낙폭(%)"]}, "단순보유 대비": end["총자산"] - end["단순보유 총자산"]})
                        details.append((name, strategy, records, journal))
                frame = pd.DataFrame(summary)
                st.dataframe(frame, hide_index=True, use_container_width=True)
                st.download_button("비교 결과 CSV 저장", frame.to_csv(index=False).encode("utf-8-sig"), "trade_lab_scenarios.csv", "text/csv")
                for name, strategy, records, journal in details:
                    if strategy == "단순보유":
                        continue
                    with st.expander(f"{name} · {strategy} · 경로와 매매 내역"):
                        history = pd.DataFrame(records).set_index("단계")
                        st.line_chart(history[["총자산", "단순보유 총자산"]])
                        st.dataframe(history, use_container_width=True)
                        st.dataframe(pd.DataFrame(journal), hide_index=True, use_container_width=True) if journal else st.caption("조건을 충족한 주문이 없습니다.")
                st.caption("기간수익률 = 최종 총자산 ÷ 시작 시가평가 총자산 − 1. 최대낙폭은 관측된 총자산의 이전 최고점 대비 하락률입니다. 총자산에는 미매도 주식의 향후 매도비용이 차감되지 않습니다. 수량 증가만으로 전략이 우수하다고 판단하지 않습니다.")
            except (ValueError, TypeError, ArithmeticError) as exc:
                st.error(f"입력값을 확인해 주세요: {exc}")
    with target:
        st.subheader("목표 평단과 필요한 자금")
        c = st.columns(2)
        buy_price = c[0].number_input("추가매수 예정가격", min_value=.01, value=float(price), key="tl_target_buy")
        target_avg = c[1].number_input("목표 평균단가", min_value=.01, value=max(.01, (average + price) / 2), key="tl_target_avg")
        try:
            quantity, required = target_average(shares, average, buy_price, target_avg, costs)
            st.write(f"목표 평단에 도달하거나 넘어서는 최소 수량: **{quantity:,}주** · 필요 자금 **{required:,.2f} {currency}** · 현금 외 추가 필요 **{max(0, required - cash):,.2f} {currency}**")
        except ValueError as exc:
            st.info(str(exc))
        goal = st.number_input("목표 보유수량", min_value=1, value=max(1, shares + 10), key="tl_goal")
        need = max(0, goal - shares)
        required = float(costs.buy_unit(buy_price)) * need
        st.write(f"추가 {need:,}주 · 필요 자금 {required:,.2f} {currency} · 현재 목표 달성률 {shares / goal * 100:.1f}%")
        st.subheader("일부 매도 후 재매수로 수량 늘리기")
        c = st.columns(3)
        sell_q = c[0].number_input("먼저 매도할 수량", min_value=0, max_value=shares, value=min(shares, 4), key=f"tl_sell_q_{shares}")
        sell_price = c[1].number_input("예정 매도가", min_value=.01, value=price * 1.1, key="tl_sell_price")
        rebuy = c[2].number_input("예정 재매수가", min_value=.01, value=float(price), key="tl_rebuy")
        proceeds = float(costs.sell_unit(sell_price)) * sell_q
        bought = affordable_shares(proceeds, rebuy, costs)
        st.write(f"매도대금만 재사용 시 {bought:,}주 재매수 → 최종 {shares - sell_q + bought:,}주 ({bought - sell_q:+,}주), 잔액 {proceeds - float(costs.buy_unit(rebuy)) * bought:,.2f} {currency}")
        st.caption("매도 후 예정 재매수가가 오지 않으면 재매수되지 않습니다. 위 결과는 두 가격에서 모두 체결된다는 가정입니다.")
        st.subheader("물타기·불타기 자금별 회복 비교")
        recovery = []
        for fraction in (0, .25, .5, .75, 1):
            budget = cash * fraction
            q = affordable_shares(budget, buy_price, costs)
            p = Position(shares, average, cash, price, costs)
            if q:
                p.trade("매수", q, buy_price)
            snap = p.snapshot(price)
            be = snap["잔여주식 본전가"]
            recovery.append({"현금 사용 비율(%)": fraction * 100, "추가수량": q,
                "실제 투입액": float(costs.buy_unit(buy_price)) * q,
                "새 평단": snap["평균단가"], "평가손익": snap["평가손익"],
                "종목 평가금액": snap["보유수량"] * price,
                "본전가": be, "본전 필요 변동률(%)": (be / price - 1) * 100 if be is not None else None})
        st.dataframe(pd.DataFrame(recovery), hide_index=True, use_container_width=True)
        st.caption("평단이 낮아져도 투자금과 하락 노출은 커질 수 있습니다. 본전 도달 날짜는 예측하지 않으며 필요한 가격 변동만 계산합니다.")
