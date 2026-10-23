"""Stock post-analysis app.

Run with:  streamlit run app.py
"""

import streamlit as st

st.set_page_config(page_title="Stock Post-Analysis", layout="wide")
st.navigation([
    st.Page("views/sell_analysis.py", title="Sell analysis", icon="📈", default=True),
    st.Page("views/stock_parameters.py", title="Stock parameters", icon="📊"),
]).run()
