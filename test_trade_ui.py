"""Offline Streamlit interaction checks: python test_trade_ui.py."""
from pathlib import Path
from streamlit.testing.v1 import AppTest


def verify(at):
    assert not at.exception, [x.message for x in at.exception]


at = AppTest.from_string("from trade_lab import render_trade_lab\nrender_trade_lab()", default_timeout=30).run()
verify(at)
at.button(key="tl_calc").click().run()
verify(at)
assert len(at.dataframe) >= 3
at.button(key="tl_sim").click().run()
verify(at)
assert any(len(d.value) == 15 for d in at.dataframe)
at.number_input(key="tl_shares").set_value(0).run()
verify(at)
at.button(key="tl_sim").click().run()
verify(at)
at.number_input(key="tl_cash").set_value(0.0).run()
verify(at)
assert any("초기 총자산" in x.value for x in at.info)
app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=30).run()
verify(app)
menu = next(r for r in app.radio if "🧮 Trade Lab" in r.options)
menu.set_value("🧮 Trade Lab").run()
verify(app)
assert any("Trade Lab" in h.value for h in app.header)
print("Trade Lab UI and main-menu integration checks passed")
