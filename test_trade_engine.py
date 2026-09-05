import unittest
import pandas as pd
from trade_engine import Costs, Position, simulate, target_average, affordable_shares
from technical_engine import _rsi
from calibration_engine import close_drawdown


class TradeTests(unittest.TestCase):
    def test_average_down_preserves_absolute_loss(self):
        p = Position(20, 100, 1400, 70)
        p.trade("매수", 20, 70)
        s = p.snapshot(70)
        self.assertEqual(s["평균단가"], 85)
        self.assertEqual(s["평가손익"], -600)
        self.assertEqual(s["기간수익률(%)"], 0)

    def test_sell_then_rebuy_accounting(self):
        p = Position(100, 180, 0, 200)
        p.trade("매도", 20, 210)
        self.assertEqual(p.snapshot(210)["평균단가"], 180)
        p.trade("매수", 21, 195)
        s = p.snapshot(195)
        self.assertEqual(s["보유수량"], 101)
        self.assertEqual(s["현금"], 105)
        self.assertEqual(s["실현손익"], 600)
        self.assertAlmostEqual(s["청산가정 총손익"], s["평가손익"] + s["실현손익"])

    def test_costs_and_full_exit(self):
        costs = Costs(.001, .002, .003, .01)
        p = Position(10, 100, 1000, 100, costs)
        p.trade("매수", 2, 100)
        self.assertAlmostEqual(float(p.cash), 797.798)
        p.trade("매도", 12, 120)
        s = p.snapshot(120)
        self.assertIsNone(s["평균단가"])
        self.assertIsNone(s["전체투자 본전가"])
        self.assertAlmostEqual(s["청산가정 총손익"], s["실현손익"])

    def test_rejection_is_atomic(self):
        p = Position(10, 100, 0, 100, core=8)
        before = p.snapshot(100)
        for side, q in [("매수", 1), ("매도", 3), ("매도", .5)]:
            with self.assertRaises(ValueError):
                p.trade(side, q, 100)
            self.assertEqual(before, p.snapshot(100))

    def test_cash_recycling_and_once_only(self):
        rules = [{"매매": "매도", "조건": "이상", "기준가격": 110, "수량": 2},
                 {"매매": "매수", "조건": "이하", "기준가격": 100, "수량": 2}]
        yes, log = simulate(10, 80, 0, [100, 120, 90, 120, 90], rules)
        no, _ = simulate(10, 80, 0, [100, 120, 90, 120, 90], rules, recycle=False)
        self.assertEqual(len(log), 2)
        self.assertEqual(yes[-1]["보유수량"], 10)
        self.assertEqual(no[-1]["보유수량"], 8)
        self.assertEqual(log[0]["현금"], 240)  # observed price, not trigger 110

    def test_target_and_affordability(self):
        self.assertEqual(target_average(20, 100, 70, 85), (20, 1400))
        self.assertEqual(target_average(10, 100, 150, 120), (7, 1050))
        with self.assertRaises(ValueError):
            target_average(20, 100, 70, 70)
        self.assertEqual(affordable_shares(100, 33.33, Costs(.001)), 2)

    def test_nonfinite_inputs(self):
        for v in [float("nan"), float("inf"), -1]:
            with self.assertRaises(ValueError):
                Position(10, 100, v, 100)

    def test_drawdown_is_peak_to_trough(self):
        self.assertAlmostEqual(close_drawdown([100, 120, 110]), -100 / 12)
        self.assertEqual(close_drawdown([100, 110, 120]), 0)

    def test_rsi_boundaries(self):
        self.assertEqual(_rsi(pd.Series([1, 2, 3, 4])).iloc[-1], 100)
        self.assertEqual(_rsi(pd.Series([4, 3, 2, 1])).iloc[-1], 0)
        self.assertEqual(_rsi(pd.Series([4, 4, 4, 4])).iloc[-1], 50)

    def test_buy_hold_identical_without_rules(self):
        rows, _ = simulate(10, 80, 100, [100, 120, 90], [])
        for row in rows:
            self.assertEqual(row["총자산"], row["단순보유 총자산"])


if __name__ == "__main__":
    unittest.main()
