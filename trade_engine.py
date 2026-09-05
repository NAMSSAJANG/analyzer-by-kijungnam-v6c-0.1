"""Deterministic, long-only position accounting. No data feeds or UI dependencies."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR


def dec(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("입력값은 유한한 숫자여야 합니다.")
    return result


@dataclass(frozen=True)
class Costs:
    buy_fee: float = 0.0
    sell_fee: float = 0.0
    sell_tax: float = 0.0
    slippage: float = 0.0

    def __post_init__(self):
        for value in (self.buy_fee, self.sell_fee, self.sell_tax, self.slippage):
            if not 0 <= dec(value) < 1:
                raise ValueError("비용 비율은 0 이상 1 미만이어야 합니다.")
        if dec(self.sell_fee) + dec(self.sell_tax) >= 1:
            raise ValueError("매도 수수료와 거래세 합계는 100% 미만이어야 합니다.")

    def buy_unit(self, price):
        return dec(price) * (1 + dec(self.slippage)) * (1 + dec(self.buy_fee))

    def sell_unit(self, price):
        return dec(price) * (1 - dec(self.slippage)) * (1 - dec(self.sell_fee) - dec(self.sell_tax))


class Position:
    def __init__(self, shares, average, cash, price, costs=None, core=0, recycle=True):
        self.shares, self.cash, self.price = map(dec, (shares, cash, price))
        self.core = dec(core)
        average = dec(average)
        if min(self.shares, average, self.cash, self.core) < 0 or self.price <= 0:
            raise ValueError("수량·평단·현금은 0 이상, 현재가는 0 초과여야 합니다.")
        if self.shares != self.shares.to_integral_value() or self.core != self.core.to_integral_value():
            raise ValueError("이 버전은 정수 주식 수량을 사용합니다.")
        if self.core > self.shares:
            raise ValueError("유지 수량은 초기 보유수량 이하여야 합니다.")
        self.costs = costs or Costs()
        self.basis = self.shares * average
        self.initial_book = self.basis + self.cash
        self.initial_equity = self.shares * self.price + self.cash
        if self.initial_equity <= 0:
            raise ValueError("초기 총자산이 0보다 커야 합니다.")
        self.initial_shares, self.initial_cash = self.shares, self.cash
        self.buy_budget = self.cash
        self.recycle = recycle
        self.realized = Decimal(0)

    def trade(self, side, quantity, price):
        quantity, price = dec(quantity), dec(price)
        if side not in ("매수", "매도") or quantity <= 0 or price <= 0:
            raise ValueError("매수/매도, 양수 수량과 가격을 입력하세요.")
        if quantity != quantity.to_integral_value():
            raise ValueError("매매 수량은 정수여야 합니다.")
        if side == "매수":
            amount = self.costs.buy_unit(price) * quantity
            if amount > self.cash or (not self.recycle and amount > self.buy_budget):
                raise ValueError("매수 가능 현금 부족")
            self.cash -= amount
            self.buy_budget -= amount
            self.basis += amount
            self.shares += quantity
        else:
            if quantity > self.shares - self.core:
                raise ValueError("매도 가능 수량 부족 (유지 수량 포함)")
            proceeds = self.costs.sell_unit(price) * quantity
            removed_basis = self.basis / self.shares * quantity
            self.realized += proceeds - removed_basis
            self.basis -= removed_basis
            self.shares -= quantity
            self.cash += proceeds
            if self.recycle:
                self.buy_budget += proceeds
        self.price = price

    def snapshot(self, price):
        price = dec(price)
        if price <= 0:
            raise ValueError("평가 가격은 0 초과여야 합니다.")
        equity = self.cash + self.shares * price
        factor = self.costs.sell_unit(1)
        average = self.basis / self.shares if self.shares else None
        remaining_be = average / factor if average is not None else None
        total_be = max(Decimal(0), (self.initial_book - self.cash) / (self.shares * factor)) if self.shares else None
        return {"가격": float(price), "보유수량": int(self.shares),
                "평균단가": float(average) if average is not None else None,
                "현금": float(self.cash), "실현손익": float(self.realized),
                "평가손익": float(self.shares * price - self.basis),
                "총자산": float(equity),
                "기간수익률(%)": float((equity / self.initial_equity - 1) * 100),
                "잔여주식 본전가": float(remaining_be) if remaining_be is not None else None,
                "전체투자 본전가": float(total_be) if total_be is not None else None,
                "청산가정 총손익": float(self.cash + self.shares * self.costs.sell_unit(price) - self.initial_book)}


def target_average(shares, average, buy_price, target, costs=None):
    shares, average, buy_price, target = map(dec, (shares, average, buy_price, target))
    if shares <= 0 or average < 0 or buy_price <= 0 or target <= 0:
        raise ValueError("목표 평단 계산에는 양수 보유수량·매수가·목표가가 필요합니다.")
    unit = (costs or Costs()).buy_unit(buy_price)
    if target == average:
        return 0, 0.0
    if not min(average, unit) < target < max(average, unit):
        raise ValueError("목표 평단은 기존 평단과 비용 포함 매수단가 사이여야 합니다. 경계값은 유한 수량으로 달성할 수 없습니다.")
    exact = shares * (average - target) / (target - unit)
    quantity = int(exact.to_integral_value(rounding="ROUND_CEILING"))
    return quantity, float(unit * quantity)


def affordable_shares(cash, price, costs=None):
    cash, price = dec(cash), dec(price)
    if cash < 0 or price <= 0:
        raise ValueError("자금은 0 이상, 가격은 0 초과여야 합니다.")
    return int((cash / (costs or Costs()).buy_unit(price)).to_integral_value(rounding=ROUND_FLOOR))


def simulate(shares, average, cash, path, rules, costs=None, core=0, recycle=True):
    """At each supplied observation, execute newly satisfied rules once, in table order.

    Fill at the observed price with adverse slippage, not at a skipped trigger.
    Starting observation only values the portfolio; it does not trigger orders.
    Rejected rules are recorded once and not retried automatically.
    """
    path = [dec(p) for p in path]
    if len(path) < 2 or any(p <= 0 for p in path):
        raise ValueError("가격 경로에는 양수 가격이 두 개 이상 필요합니다.")
    for rule in rules:
        q = dec(rule["수량"])
        if rule["매매"] not in ("매수", "매도") or rule["조건"] not in ("이하", "이상"):
            raise ValueError("규칙의 매매·조건을 확인하세요.")
        if dec(rule["기준가격"]) <= 0 or q <= 0 or q != q.to_integral_value():
            raise ValueError("규칙 가격은 양수, 수량은 양의 정수여야 합니다.")
    position = Position(shares, average, cash, path[0], costs, core, recycle)
    records, journal, used = [], [], set()
    peak = position.initial_equity
    mdd = Decimal(0)
    for step, price in enumerate(path):
        if step:
            for idx, rule in enumerate(rules):
                if idx in used:
                    continue
                trigger = dec(rule["기준가격"])
                hit = price <= trigger if rule["조건"] == "이하" else price >= trigger
                if not hit:
                    continue
                used.add(idx)
                try:
                    position.trade(rule["매매"], rule["수량"], price)
                    status = "체결"
                except ValueError as exc:
                    status = f"미체결: {exc}"
                journal.append({"단계": step, "규칙": idx + 1, **rule,
                                "관측가격": float(price), "결과": status, **position.snapshot(price)})
        snap = position.snapshot(price)
        equity = position.cash + position.shares * price
        peak = max(peak, equity)
        mdd = min(mdd, equity / peak - 1)
        snap.update({"단계": step, "단순보유 총자산": float(position.initial_cash + position.initial_shares * price),
                     "최대낙폭(%)": float(mdd * 100)})
        records.append(snap)
    return records, journal


SCENARIOS = {
    "지속 상승": [1, 1.05, 1.12, 1.20, 1.30],
    "상승 후 눌림": [1, 1.15, 1.05, 1.22, 1.12, 1.30],
    "박스권": [1, 1.10, .98, 1.08, .96, 1.12],
    "급락": [1, .95, .85, .70, .75],
    "V자 회복": [1, .85, .70, .90, 1.10, 1.30],
}
