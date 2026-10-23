"""MediScope - New York hospital inpatient discharges dashboard (SPARCS 2021).

An interactive dashboard for hospital administrators, clinicians and operations managers:
length of stay, cost, severity, payers and hospital utilisation across 2.1 million stays.

Run locally:        streamlit run app.py
Rebuild the data:   python scripts/prepare_data.py   (needs the raw CSV in data/raw/)
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src import analysis as A
from src import charts as C
from src.config import AGE_ORDER, DATA_SOURCE_URL, DROP_COLUMNS, SEVERITY_ORDER
from src.data_cleaning import load_cleaning_log, load_processed

st.set_page_config(page_title="MediScope · NY Inpatient Discharges 2021", page_icon="🏥",
                   layout="wide", initial_sidebar_state="expanded")

PLOT_CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
STATEWIDE = (False,)  # filter key meaning "no filters, outliers kept"
FILTER_KEYS = {col: f"f_{col}" for col in A.FILTER_COLUMNS}


# ======================================================================================
# Data access: the dataset loads once per server; every analysis result is cached per
# filter combination, so moving back to an earlier view is instant.
# ======================================================================================
@st.cache_resource(show_spinner="Loading 2.1 million discharge records…")
def get_data() -> pd.DataFrame:
    return load_processed()


@st.cache_resource(max_entries=3, show_spinner=False)  # each entry can be a large slice of 2.1M rows
def get_filtered(filter_key: tuple) -> pd.DataFrame:
    *pairs, hide_outliers = filter_key
    return A.apply_filters(get_data(), {col: list(values) for col, values in pairs}, hide_outliers)


@st.cache_data(max_entries=256, show_spinner="Crunching the numbers…")
def compute(name: str, filter_key: tuple, **kwargs):
    """Run an analysis function from src.analysis on the filtered data (cached)."""
    return getattr(A, name)(get_filtered(filter_key), **kwargs)


@st.cache_data(show_spinner=False)
def options_by_frequency(column: str) -> list[str]:
    counts = get_data()[column].value_counts()
    return [str(c) for c in counts.index if c != "Redacted" and counts[c] > 0]


@st.cache_data(show_spinner=False)
def county_options(service_areas: tuple[str, ...]) -> list[str]:
    pairs = get_data()[["county", "service_area"]].drop_duplicates()
    pairs = pairs[pairs["county"] != "Redacted"]
    if service_areas:
        pairs = pairs[pairs["service_area"].isin(service_areas)]
    return sorted(pairs["county"].astype(str).unique())


@st.cache_data(max_entries=8, show_spinner=False)  # ~5 MB per entry
def filtered_csv(filter_key: tuple, max_rows: int = 25_000) -> bytes:
    data = get_filtered(filter_key)
    if len(data) > max_rows:
        data = data.sample(max_rows, random_state=42).sort_index()
    return data.to_csv(index=False).encode("utf-8")


@st.cache_data(show_spinner=False)
def get_cleaning_log() -> pd.DataFrame:
    return load_cleaning_log()


# ======================================================================================
# Small presentation helpers
# ======================================================================================
def active_theme() -> C.Theme:
    theme = getattr(st.context, "theme", None)
    return C.get_theme(getattr(theme, "type", None))


def pct(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}%}"


def usd(value: float) -> str:
    """Money for markdown text. '$' is escaped, otherwise Streamlit reads '$...$' as a formula."""
    return C.money(value).replace("$", r"\$")


def plot(fig, key: str) -> None:
    st.plotly_chart(fig, theme="streamlit", width="stretch", key=key, config=PLOT_CONFIG)


def show_table(table: pd.DataFrame, key: str, column_config: dict | None = None) -> None:
    """Every chart has a table twin: the same numbers, readable without the chart."""
    with st.expander("View the data behind this chart", icon=":material/table_view:"):
        st.dataframe(table, hide_index=True, width="stretch", column_config=column_config, key=key)


def reset_filters() -> None:
    for key in FILTER_KEYS.values():
        st.session_state[key] = []
    st.session_state["f_hide_outliers"] = False


def correlation_strength(rho: float) -> str:
    size = abs(rho)
    return "strong" if size >= 0.5 else "moderate" if size >= 0.3 else "weak" if size >= 0.1 else "negligible"


MONEY = st.column_config.NumberColumn(format="dollar")
DAYS = st.column_config.NumberColumn(format="%.1f days")
COUNT = st.column_config.NumberColumn(format="localized")


# ======================================================================================
# Sidebar filters
# ======================================================================================
def sidebar_filters() -> tuple:
    for key in FILTER_KEYS.values():
        st.session_state.setdefault(key, [])
    st.session_state.setdefault("f_hide_outliers", False)

    with st.sidebar:
        st.markdown("## :material/local_hospital: MediScope")
        st.caption("Hospital inpatient discharges · New York State · 2021")

        with st.expander("Location", icon=":material/location_on:", expanded=True):
            st.multiselect("Hospital service area", options_by_frequency("service_area"),
                           key="f_service_area", placeholder="All service areas")
            valid_counties = county_options(tuple(st.session_state["f_service_area"]))
            st.session_state["f_county"] = [c for c in st.session_state["f_county"] if c in valid_counties]
            st.multiselect("County", valid_counties, key="f_county", placeholder="All counties")

        with st.expander("Patient", icon=":material/person:", expanded=True):
            st.multiselect("Age group", AGE_ORDER, key="f_age_group", placeholder="All ages")
            st.multiselect("Gender", ["Female", "Male", "Unknown"], key="f_gender", placeholder="All genders")

        with st.expander("Clinical", icon=":material/stethoscope:", expanded=True):
            st.multiselect("Severity of illness", SEVERITY_ORDER, key="f_severity", placeholder="All levels")
            st.multiselect("Type of admission", options_by_frequency("admission_type"),
                           key="f_admission_type", placeholder="All admission types")
            st.multiselect("Diagnosis category", options_by_frequency("dx_category"),
                           key="f_dx_category", placeholder="All diagnosis categories")

        with st.expander("Billing", icon=":material/payments:", expanded=True):
            st.multiselect("Payment type", options_by_frequency("payment_type"),
                           key="f_payment_type", placeholder="All payers")
            st.toggle("Hide extreme-charge outliers", key="f_hide_outliers",
                      help="Removes stays whose charges are outliers for their severity level "
                           "(Tukey's 1.5 × IQR rule on log charges) - about 1.2% of stays.")

        st.button("Reset all filters", icon=":material/restart_alt:", on_click=reset_filters, width="stretch")
        st.caption(f"Source: [NYS DOH SPARCS de-identified inpatient discharges, 2021]({DATA_SOURCE_URL}).")

    pairs = tuple((col, tuple(st.session_state[key])) for col, key in FILTER_KEYS.items()
                  if st.session_state[key])
    return pairs + (bool(st.session_state["f_hide_outliers"]),)


def active_filter_badges(filter_key: tuple) -> None:
    *pairs, hide_outliers = filter_key
    if not pairs and not hide_outliers:
        st.badge("Statewide view · no filters", icon=":material/public:", color="gray")
        return
    with st.container(horizontal=True, gap="small"):
        for column, values in pairs:
            shown = ", ".join(values[:3]) + (f" +{len(values) - 3}" if len(values) > 3 else "")
            st.badge(f"{A.FILTER_COLUMNS[column]}: {shown}", icon=":material/filter_alt:", color="blue")
        if hide_outliers:
            st.badge("Charge outliers hidden", icon=":material/visibility_off:", color="orange")


# ======================================================================================
# KPI tiles
# ======================================================================================
def kpi_row(k: dict, base: dict, filtered: bool) -> None:
    def vs_state(diff: str) -> str | None:
        return f"{diff} vs NY" if filtered else None

    cols = st.columns(6)
    cols[0].metric("Discharges", f"{k['discharges']:,}",
                   f"{k['discharges'] / base['discharges']:.1%} of NY total" if filtered else None,
                   delta_color="off", delta_arrow="off", border=True,
                   help="Inpatient stays that ended in 2021 and match the filters.")
    cols[1].metric("Average stay", f"{k['avg_los']:.1f} days",
                   vs_state(f"{k['avg_los'] - base['avg_los']:+.1f} d"), delta_color="inverse", border=True,
                   help=f"Mean length of stay. The median is {k['median_los']:.0f} days.")
    cols[2].metric("Median charge", C.money(k["median_charge"]),
                   vs_state(f"{k['median_charge'] / base['median_charge'] - 1:+.0%}"),
                   delta_color="inverse", border=True,
                   help="Half of stays were billed more than this. Charges are list prices, not payments.")
    cols[3].metric("Total billed", C.money(k["total_charges"]), border=True,
                   help=f"Sum of total charges across {k['bed_days']:,} bed-days.")
    cols[4].metric("Mark-up", f"{k['markup']:.2f}×",
                   vs_state(f"{k['markup'] - base['markup']:+.2f}×"), delta_color="inverse", border=True,
                   help="Charge-to-cost ratio: total charges ÷ total estimated costs. 3× means \\$3 billed "
                        "for every \\$1 it cost the hospital to provide the care.")
    cols[5].metric("Mortality", pct(k["mortality_rate"]),
                   vs_state(f"{(k['mortality_rate'] - base['mortality_rate']) * 100:+.1f} pts"),
                   delta_color="inverse", border=True,
                   help="In-hospital mortality: share of stays where the patient died in hospital "
                        "(disposition 'Expired').")


# ======================================================================================
# Tab: Overview
# ======================================================================================
def render_overview(fk: tuple, k: dict, theme: C.Theme) -> None:
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("How long do patients stay?")
        split_label = st.segmented_control("Colour the bars by", ["None", "Severity", "Admission type"],
                                           default="None", key="hist_split")
        split = {"Severity": "severity", "Admission type": "admission_type"}.get(split_label)
        dist = compute("los_distribution", fk, split=split)
        plot(C.los_histogram(dist, theme, split, mean=k["avg_los"], median=k["median_los"]), "los_hist")
        st.caption(
            f"Stays are **right-skewed**: half of patients leave within **{k['median_los']:.0f} days**, "
            f"but the mean is **{k['avg_los']:.1f} days** because a minority of very long stays pull it up. "
            f"**{pct(k['share_over_30_days'])}** of stays last more than 30 days - drag or zoom out on the "
            "chart to see them (SPARCS caps the longest stays at 120 days).")
        show_table(dist, "t_hist", {"discharges": COUNT})
    with right:
        st.subheader("Who pays for the stay?")
        mix = compute("payer_mix", fk)
        plot(C.payer_donut(mix, theme), "payer_donut")
        top = mix.iloc[0]
        payers = compute("billing_by_payer", fk)
        public = payers.loc[payers["payment_type"].isin(["Medicare", "Medicaid"]), "discharges"].sum()
        st.caption(f"**{top['payment_type']}** is the primary payer for **{pct(top['share'])}** of stays; "
                   f"Medicare and Medicaid together cover **{pct(public / payers['discharges'].sum())}**. "
                   "Smaller payers are grouped as *Other* - **Payers & billing** lists every payer.")
        show_table(mix.assign(share=mix["share"] * 100), "t_mix",
                   {"discharges": COUNT, "share": st.column_config.NumberColumn("share", format="%.1f%%")})

    st.subheader("Headlines for the current selection")
    longest = compute("los_by_group", fk, by="dx_description", min_discharges=1_000, top_n=1)
    bed_days = compute("top_bed_day_users", fk, by="dx_description", n=2)
    effect = compute("severity_effect", fk)
    regions = compute("region_summary", fk)
    cards = st.columns(4)
    with cards[0].container(border=True, height="stretch"):
        st.markdown("**:material/bed: Biggest users of beds**")
        if not bed_days.empty:
            st.markdown(" and ".join(f"{g} (**{pct(s)}**)" for g, s in zip(bed_days["group"], bed_days["share"]))
                        + " of all bed-days.")
    with cards[1].container(border=True, height="stretch"):
        st.markdown("**:material/timer: Longest stays (common diagnoses)**")
        if not longest.empty:
            row = longest.iloc[0]
            st.markdown(f"{row['dx_description']}: **{row['avg_los']:.1f} days** on average "
                        f"({row['discharges']:,} stays; diagnoses with 1,000+ stays).")
        else:
            st.markdown("No diagnosis has 1,000+ stays in this selection.")
    with cards[2].container(border=True, height="stretch"):
        st.markdown("**:material/trending_up: Severity drives cost**")
        if effect and pd.notna(effect.get("extreme_vs_minor")):
            st.markdown(f"An *Extreme* case is billed **{effect['extreme_vs_minor']:.1f}×** a *Minor* one "
                        f"(median {usd(effect['medians']['Extreme'])} vs "
                        f"{usd(effect['medians']['Minor'])}).")
        else:
            st.markdown("Select more than one severity level to compare.")
    with cards[3].container(border=True, height="stretch"):
        st.markdown("**:material/map: Regional price gap**")
        if len(regions) >= 2:
            hi, lo = regions.iloc[0], regions.iloc[-1]
            st.markdown(f"Median bill in **{hi['region']}** is **{hi['median_charge'] / lo['median_charge']:.1f}×** "
                        f"{lo['region']} - mark-up {hi['markup']:.1f}× vs {lo['markup']:.1f}×.")
        else:
            st.markdown("Select more than one region to compare.")


# ======================================================================================
# Tab: Length of stay (Q1 and Q4)
# ======================================================================================
def render_length_of_stay(fk: tuple, theme: C.Theme) -> None:
    st.subheader("Q1 · Which diagnoses are linked to the longest stays?")
    c1, c2, c3, c4 = st.columns([2.4, 1.3, 1.6, 1.3], vertical_alignment="bottom")
    labels = list(A.GROUP_LABELS.values())
    group_label = c1.segmented_control("Group by", labels, default=labels[0], key="los_group") or labels[0]
    by = {label: col for col, label in A.GROUP_LABELS.items()}[group_label]
    stat = "median" if c2.segmented_control("Measure", ["Average", "Median"], default="Average",
                                            key="los_stat") == "Median" else "mean"
    top_n = c3.slider("Show top", 5, 30, 15, key="los_top")
    min_n = c4.number_input("Min. discharges", min_value=10, max_value=10_000, value=100, step=10,
                            key="los_min", help="Groups with fewer stays are hidden: averages of a "
                                                "handful of patients are too noisy to rank.")
    table = compute("los_by_group", fk, by=by, stat=stat, min_discharges=int(min_n), top_n=int(top_n))
    if table.empty:
        st.info("No group has enough discharges for these filters. Lower the minimum or widen the filters.")
    else:
        plot(C.los_bar(table, theme, stat), "los_bar")
        first = table.iloc[0]
        leaders = compute("top_bed_day_users", fk, by=by, n=2)
        value = first["avg_los"] if stat == "mean" else first["median_los"]
        text = (f"**{first['label']}** has the longest {'average' if stat == 'mean' else 'median'} stay: "
                f"**{value:.1f} days** across {first['discharges']:,} discharges. Bed capacity, though, depends "
                f"on volume × length: **{leaders['group'].iloc[0]}** uses **{pct(leaders['share'].iloc[0])}** "
                "of all bed-days")
        if len(leaders) > 1:
            text += f", and **{leaders['group'].iloc[1]}** another **{pct(leaders['share'].iloc[1])}**"
        st.caption(text + ".")
        show_table(table.drop(columns=["label"]), "t_los",
                   {"avg_los": DAYS, "median_los": DAYS, "median_charge": MONEY, "discharges": COUNT,
                    "bed_days": COUNT,
                    "bed_day_share": st.column_config.NumberColumn("share of bed-days", format="percent")})

    st.divider()
    st.subheader("Q4 · Are there counties or hospitals with longer stays?")
    c1, c2 = st.columns([1.4, 2], vertical_alignment="bottom")
    rows = c1.segmented_control("Rows", ["Counties", "Hospitals"], default="Counties", key="hm_rows") or "Counties"
    top = c2.slider("Number of rows (largest by discharges)", 5, 40, 20, key="hm_top")
    avg, count = compute("los_heatmap", fk, rows="facility" if rows == "Hospitals" else "county", top_n=int(top))
    if avg.empty or avg["All"].isna().all():
        st.info("Too few located stays for these filters: each heatmap cell needs at least 30 stays.")
        return
    plot(C.los_heatmap(avg, count, theme), "los_heatmap")
    longest_overall = avg["All"].idxmax()
    name = " · ".join(longest_overall) if isinstance(longest_overall, tuple) else longest_overall
    caption = (f"Numbers are average stays in days. Colour compares each cell with the average of its own "
               f"column - **red = longer, blue = shorter** - so every county or hospital is judged against patients "
               f"**of the same severity**. Longest overall: **{name}** ({avg['All'].max():.1f} days). ")
    if "Extreme" in avg.columns and avg["Extreme"].notna().any():
        ext = avg["Extreme"].idxmax()
        caption += (f"Longest for *Extreme* cases: **{' · '.join(ext) if isinstance(ext, tuple) else ext}** "
                    f"({avg['Extreme'].max():.1f} days). ")
    st.caption(caption + "Blank cells have fewer than 30 stays - too few for a reliable average.")
    show_table(avg.round(2).reset_index(), "t_heat")


# ======================================================================================
# Tab: Cost & severity (Q3 and Q2)
# ======================================================================================
def render_cost(fk: tuple, theme: C.Theme) -> None:
    st.subheader("Q3 · How does severity of illness affect total cost?")
    log_scale = st.toggle("Logarithmic scale", value=True, key="box_log",
                          help="Charges range from \\$100 to \\$18M. On a log scale every box is visible and "
                               "outliers are judged relative to the typical bill.")
    box = compute("charge_box_stats", fk, log_scale=log_scale)
    effect = compute("severity_effect", fk)
    plot(C.charge_box(box, theme, log_scale), "charge_box")
    if effect and pd.notna(effect.get("extreme_vs_minor")):
        st.caption(
            f"Each box holds the middle 50% of bills; the line is the median and the dashed line the mean. "
            f"The median bill climbs from **{usd(effect['medians']['Minor'])}** (Minor) to "
            f"**{usd(effect['medians']['Extreme'])}** (Extreme) - **{effect['extreme_vs_minor']:.1f}×**. "
            f"Spearman's rank correlation between severity and charges is **ρ = {effect['rho_charges']:.2f}** "
            f"({correlation_strength(effect['rho_charges'])}), and **ρ = {effect['rho_los']:.2f}** with length "
            f"of stay. Whiskers use Tukey's 1.5 × IQR rule; **{int(box['outliers'].sum()):,}** stays "
            f"({box['outliers'].sum() / box['discharges'].sum():.1%}) fall beyond them.")
    show_table(box, "t_box", {c: MONEY for c in ["lower_whisker", "q1", "median", "q3", "upper_whisker",
                                                  "mean", "max"]}
               | {"outlier_share": st.column_config.NumberColumn(format="percent"), "discharges": COUNT})

    reg = compute("cost_per_extra_day", fk)
    if reg:
        c1, c2, c3 = st.columns(3)
        c1.metric("Charges added per extra day", C.money(reg["slope"]), border=True,
                  help="Slope of a least-squares line: total charges = slope × days + intercept.")
        c2.metric("Variance explained (R²)", f"{reg['r_squared']:.2f}", border=True,
                  help="Share of the variation in charges that length of stay alone explains.")
        k = compute("summary_kpis", fk)
        c3.metric("Median estimated cost per stay", C.money(k["median_cost"]), border=True,
                  help="Costs are the hospital's estimated expense, derived from its cost-to-charge ratio.")

    st.divider()
    st.subheader("Q2 · Which age groups incur the highest charges?")
    stat = (st.segmented_control("Statistic", ["Median", "Mean"], default="Median", key="ag_stat") or "Median")
    table = compute("charges_by_age_gender", fk, stat=stat.lower())
    if table.empty:
        st.info("No stays with a recorded gender match these filters.")
        return
    plot(C.age_gender_bars(table, theme, stat.lower()), "age_gender")
    by_age = compute("charges_by_age", fk, stat=stat.lower())
    if len(by_age) >= 2:
        text = (f"{stat} charge per stay is highest for **{by_age.idxmax()}** ({usd(by_age.max())}) "
                f"and lowest for **{by_age.idxmin()}** ({usd(by_age.min())}). ")
    else:
        text = f"{stat} charge per stay for **{by_age.index[0]}**: {usd(by_age.iloc[0])}. "
    young = table[table["age_group"] == "18 to 29"].set_index("gender")["value"]
    if {"Female", "Male"} <= set(young.index):
        text += (f"Among 18-29 year olds, men are billed **{young['Male'] / young['Female'] - 1:+.0%}** more than "
                 "women: most young women's stays are routine childbirth, which is short and relatively cheap.")
    st.caption(text)
    show_table(table, "t_age", {"value": MONEY, "avg_los": DAYS, "discharges": COUNT})


# ======================================================================================
# Tab: Payers & billing (Q5)
# ======================================================================================
def render_payers(fk: tuple, theme: C.Theme) -> None:
    st.subheader("Q5 · How do payment types affect the final bill?")
    billing = compute("billing_by_payer", fk)
    if billing.empty:
        st.info("No stays match these filters.")
        return
    plot(C.payer_billing(billing, theme), "payer_billing")
    named = billing.set_index("payment_type")
    text = "Bars show the median **billed** charge, diamonds the median **estimated cost** - the gap is mark-up. "
    if {"Medicare", "Medicaid"} <= set(named.index):
        mc, md = named.loc["Medicare"], named.loc["Medicaid"]
        text += (f"Medicare stays are billed a median **{usd(mc['median_charge'])}** vs "
                 f"**{usd(md['median_charge'])}** for Medicaid. ")
        if mc["share_70_plus"] - md["share_70_plus"] > 0.2:
            text += (f"Much of that gap is case mix: **{pct(mc['share_70_plus'], 0)}** of Medicare patients are "
                     f"70+ (Medicaid: {pct(md['share_70_plus'], 0)}) and their average severity is "
                     f"{mc['avg_severity']:.2f} vs {md['avg_severity']:.2f}.")
    st.caption(text)
    show_table(billing, "t_billing",
               {c: MONEY for c in ["median_charge", "mean_charge", "median_cost", "median_charge_per_day",
                                   "total_charges", "total_costs"]}
               | {"avg_los": DAYS, "discharges": COUNT,
                  "share_70_plus": st.column_config.NumberColumn(format="percent")})

    left, right = st.columns([3, 2], gap="large", vertical_alignment="center")
    with left:
        st.markdown("##### Same severity, different payer")
        pivot = compute("payer_severity_pivot", fk)
        plot(C.payer_severity_lines(pivot, theme), "payer_lines")
    with right:
        caption = "Comparing payers **within** each severity level removes the age-and-sickness effect. "
        main = pivot.reindex([p for p in C.PAYER_SLOTS if p in pivot.index])
        overall = billing.set_index("payment_type")["median_charge"].reindex(main.index)
        if "Extreme" in main.columns and main["Extreme"].notna().any() and overall.notna().any():
            top_extreme, top_overall = main["Extreme"].idxmax(), overall.idxmax()
            caption += (f"For *Extreme* cases the highest median bill is **{top_extreme}** "
                        f"({usd(main['Extreme'].max())}). ")
            if top_extreme != top_overall:
                caption += (f"Overall, **{top_overall}** looked most expensive: the ranking flips once severity "
                            "is held constant - a confounding effect known as Simpson's paradox.")
        st.markdown(caption)
        show_table(pivot.round(0).reset_index(), "t_payer_sev")

    st.markdown("##### Region × payer (pivot table)")
    choice = st.segmented_control("Value", ["Median charge", "Average stay", "Mark-up"],
                                  default="Median charge", key="pivot_value") or "Median charge"
    value, aggfunc, fmt, title = {
        "Median charge": ("total_charges", "median", "money", "Median $"),
        "Average stay": ("length_of_stay", "mean", "days", "Avg days"),
        "Mark-up": ("charge_to_cost_ratio", "median", "ratio", "Charge ÷ cost"),
    }[choice]
    pivot2 = compute("region_payer_pivot", fk, value=value, aggfunc=aggfunc)
    if pivot2.empty:
        st.info("No located stays match these filters.")
        return
    plot(C.value_heatmap(pivot2, theme, fmt, title, x_labels=C.PAYER_SHORT), "region_payer")
    caption = "Built with `pandas.pivot_table` (service area × primary payer), sorted high to low. "
    if len(pivot2) >= 2:
        caption += (f"Highest typical value: **{pivot2.index[0]}**; lowest: **{pivot2.index[-1]}** - read down "
                    "a column to compare the same payer across areas. ")
    st.caption(caption + "Cells with fewer than 30 stays are blank.")
    show_table(pivot2.round(2).reset_index(), "t_region_payer")


# ======================================================================================
# Tab: Hospitals
# ======================================================================================
def render_hospitals(fk: tuple, theme: C.Theme) -> None:
    st.subheader("Which hospitals keep patients longer than expected, and what do they charge?")
    min_n = st.slider("Only hospitals with at least this many discharges", 100, 10_000, 1_000, step=100,
                      key="fac_min")
    fac = compute("facility_summary", fk, min_discharges=int(min_n))
    if fac.empty:
        st.info("No hospital reaches that volume for these filters - lower the minimum.")
        return
    plot(C.facility_scatter(fac, theme), "facility_scatter")
    worst = fac.sort_values("los_index", ascending=False).iloc[0]
    st.caption(
        "The **length-of-stay index** divides a hospital's average stay by the average stay statewide for "
        "patients with the same diagnosis *and* severity. 1.0 means typical; 1.3 means patients stay 30% longer "
        f"than similar patients elsewhere. Highest: **{worst['facility']}** ({worst['los_index']:.2f}; "
        f"in-hospital mortality {pct(worst['mortality_rate'])}). Indices far above 1 usually mark specialist "
        "hospitals (rehabilitation, palliative care, psychiatry) rather than inefficiency.")

    st.markdown("##### Highest-utilisation hospitals (ranked by bed-days)")
    top = fac.sort_values("bed_days", ascending=False).head(15).copy()
    top["mortality_rate"] *= 100
    st.dataframe(
        top[["facility", "county", "discharges", "bed_days", "avg_los", "los_index", "median_charge",
             "markup", "mortality_rate"]],
        hide_index=True, width="stretch", key="t_fac_top",
        column_config={
            "facility": st.column_config.TextColumn("Hospital", width="large"),
            "county": st.column_config.TextColumn("County"),
            "discharges": st.column_config.NumberColumn("Discharges", format="localized"),
            "bed_days": st.column_config.ProgressColumn(
                "Bed-days", format="localized", min_value=0, max_value=float(top["bed_days"].max())),
            "avg_los": st.column_config.NumberColumn("Avg stay", format="%.1f d"),
            "los_index": st.column_config.NumberColumn(
                "LOS index", format="%.2f", help="Observed ÷ expected stay for the same diagnosis and severity"),
            "median_charge": st.column_config.NumberColumn("Median charge", format="dollar"),
            "markup": st.column_config.NumberColumn("Mark-up", format="%.2f×"),
            "mortality_rate": st.column_config.NumberColumn("Mortality", format="%.1f%%"),
        })
    show_table(fac, "t_fac_all", {"median_charge": MONEY, "total_charges": MONEY, "total_costs": MONEY,
                                  "avg_los": DAYS, "expected_los": DAYS, "discharges": COUNT})


# ======================================================================================
# Tab: Insights
# ======================================================================================
def render_insights(fk: tuple) -> None:
    st.subheader("Answers to the five research questions")
    st.caption("Numbers update with the sidebar filters.")
    k = compute("summary_kpis", fk)
    dx = compute("los_by_group", fk, by="dx_description", min_discharges=100, top_n=3)
    beds = compute("top_bed_day_users", fk, by="dx_description", n=2)
    ages = compute("charges_by_age", fk, stat="median")
    effect = compute("severity_effect", fk)
    heat, heat_count = compute("los_heatmap", fk, rows="county", top_n=20)
    billing = compute("billing_by_payer", fk).set_index("payment_type")
    regions = compute("region_summary", fk)

    common = compute("los_by_group", fk, by="dx_description", min_discharges=10_000, top_n=1)

    answers = []
    if not dx.empty:
        text = ("Longest average stays (diagnoses with 100+ stays): "
                + ", ".join(f"**{r.dx_description}** ({r.avg_los:.1f} d)" for r in dx.itertuples()) + ". ")
        if not common.empty:
            text += (f"Among common diagnoses (10,000+ stays) the longest is **{common['dx_description'].iloc[0]}** "
                     f"({common['avg_los'].iloc[0]:.1f} d). ")
        answers.append(("Q1 · Which diagnoses are linked to long stays?",
                        text + f"By total bed-days, **{beds['group'].iloc[0]}** ({pct(beds['share'].iloc[0])}) "
                               "dominates."))
    if len(ages) >= 2:
        trend = "rises steadily" if ages.is_monotonic_increasing else "varies"
        answers.append(("Q2 · Which age groups incur the highest charges?",
                        f"The median bill {trend} with age, from **{usd(ages.iloc[0])}** ({ages.index[0]}) to "
                        f"**{usd(ages.iloc[-1])}** ({ages.index[-1]}); the highest group is **{ages.idxmax()}** "
                        f"at {ages.max() / ages.min():.1f}× the lowest (**{ages.idxmin()}**)."))
    if effect and pd.notna(effect.get("extreme_vs_minor")):
        answers.append(("Q3 · How does severity affect total cost?",
                        f"Strongly and monotonically: Extreme cases are billed **{effect['extreme_vs_minor']:.1f}×** "
                        f"Minor ones (Spearman ρ = {effect['rho_charges']:.2f}), and stay longer "
                        f"(ρ = {effect['rho_los']:.2f})."))
    if not heat.empty and heat["All"].notna().sum() >= 2:
        top = heat["All"].idxmax()
        levels = [s for s in SEVERITY_ORDER if s in heat.columns and heat[s].notna().any()]
        benchmark = A.weighted_column_average(heat, heat_count)  # same benchmark as the heatmap colours
        above = [s for s in levels if heat.loc[top, s] > 1.05 * benchmark[s]]
        answers.append(("Q4 · Are there counties with longer average stays?",
                        f"Yes: **{top}** averages {heat['All'].max():.1f} days vs {heat['All'].min():.1f} in "
                        f"**{heat['All'].idxmin()}** among the 20 busiest counties. {top} is more than 5% above "
                        f"the county average in **{len(above)} of {len(levels)}** severity levels "
                        f"({', '.join(above) or 'none'}), so "
                        + ("the gap is not just sicker patients." if len(above) >= len(levels) - 1
                           else "part of the gap reflects a sicker case mix.")))
    if {"Medicare", "Medicaid"} <= set(billing.index):
        answers.append(("Q5 · How do payment types affect the final bill?",
                        f"Medicare stays carry the highest median bill of the big payers "
                        f"(**{usd(billing.loc['Medicare', 'median_charge'])}** vs "
                        f"{usd(billing.loc['Medicaid', 'median_charge'])} for Medicaid) because its patients "
                        "are older and sicker. Within the same severity the order changes, so payer type mostly "
                        "reflects case mix rather than pricing."))
    for question, answer in answers:
        with st.container(border=True):
            st.markdown(f"**{question}**")
            st.markdown(answer)

    st.subheader("Recommendations for hospital leaders")
    state_beds = compute("top_bed_day_users", STATEWIDE, by="dx_description", n=2)
    state_regions = compute("region_summary", STATEWIDE)
    seventy = compute("disposition_by_age", STATEWIDE).loc["70 or Older"]
    longest_dept = compute("los_by_group", STATEWIDE, by="department", min_discharges=1_000, top_n=1).iloc[0]
    recs = [
        f"**Target the bed-day giants.** {state_beds['group'].iloc[0]} and {state_beds['group'].iloc[1]} use "
        f"{pct(state_beds['share'].sum())} of all bed-days statewide. Early-recognition sepsis bundles and "
        "standardised respiratory pathways free the most capacity.",
        f"**Plan discharges early for older patients.** {pct(seventy['Nursing / rehab facility'], 0)} of patients "
        f"aged 70+ leave for a nursing or rehab facility and {pct(seventy['Home with services'], 0)} need home "
        "health services - arranging these from day one shortens waits for a post-acute bed.",
        "**Benchmark on the case-mix-adjusted index, not raw averages.** General hospitals with a length-of-stay "
        "index above about 1.2 deserve a review of their long-stay cases (see the Hospitals tab).",
        f"**Budget with costs, not charges.** Downstate mark-ups reach "
        f"{state_regions['markup'].max():.1f}× vs {state_regions['markup'].min():.1f}× upstate, so list-price "
        "charges overstate the real resource gap between regions.",
        f"**Protect {longest_dept['department'].lower()} capacity.** {longest_dept['department']} has the longest "
        f"average stay of any department ({longest_dept['avg_los']:.1f} days), so community step-down places "
        "would relieve inpatient units.",
    ]
    st.caption("Recommendations use statewide figures, whatever the filters.")
    for rec in recs:
        st.markdown(f"- {rec}")

    st.subheader("Statistical evidence")
    reg = compute("cost_per_extra_day", fk)
    region_test = compute("group_test", fk, value="total_charges", by="region")
    payer_test = compute("group_test", fk, value="length_of_stay", by="payment_type")
    rows = []
    if effect:
        rows += [
            ("Spearman rank correlation", "Severity vs total charges", f"ρ = {effect['rho_charges']:.3f}",
             f"{correlation_strength(effect['rho_charges']).capitalize()} positive monotonic relationship"),
            ("Spearman rank correlation", "Severity vs length of stay", f"ρ = {effect['rho_los']:.3f}",
             f"{correlation_strength(effect['rho_los']).capitalize()} positive monotonic relationship"),
        ]
    if reg:
        rows.append(("Least-squares regression", "Charges = a + b × days",
                     f"b = {C.money(reg['slope'])}/day, R² = {reg['r_squared']:.2f}",
                     "Each extra day adds roughly this much to the bill"))
    for test, label in ((region_test, "Charges across regions"), (payer_test, "Length of stay across payers")):
        if test:
            size = ("large" if test["eta_squared"] >= 0.14 else "moderate" if test["eta_squared"] >= 0.06
                    else "small" if test["eta_squared"] >= 0.01 else "negligible")
            rows.append(("Kruskal-Wallis H-test", label, f"H = {test['H']:,.0f}, η²(H) = {test['eta_squared']:.3f}",
                         f"Groups differ (p < 0.001) with a {size} effect "
                         "(η² thresholds: 0.01 small, 0.06 moderate, 0.14 large)"))
    if rows:
        st.dataframe(pd.DataFrame(rows, columns=["Test", "Variables", "Result", "Interpretation"]),
                     hide_index=True, width="stretch", key="t_stats")
    st.caption("With millions of rows almost every difference is 'statistically significant', so the effect "
               "sizes (ρ, R², η²) matter more than p-values. Tests on more than 200,000 rows use a fixed "
               "random sample of 200,000.")

    st.subheader("Limitations")
    st.markdown(
        "- **No readmission flag.** The de-identified file has no patient ID, so readmission rates cannot be "
        "measured; in-hospital mortality and length of stay are used as outcome measures instead.\n"
        "- **Charges are not payments.** They are list prices before discounts; costs are estimates from each "
        "hospital's cost-to-charge ratio.\n"
        "- **Capped and redacted values.** Stays of 120+ days are recorded as 120, and 10,629 sensitive "
        "pregnancy-related stays have no hospital or county.\n"
        "- **2021 was a COVID-19 year.** COVID-19 alone accounts for about 82,600 stays, which shifts "
        "lengths of stay and mortality compared with a typical year.")


# ======================================================================================
# Tab: Data & methods
# ======================================================================================
FEATURES = pd.DataFrame([
    ("los_capped", "True where SPARCS recorded '120 +' days"),
    ("los_band", "Length of stay grouped: 1, 2-3, 4-7, 8-14, 15-30, 31+ days"),
    ("dx_category", "CCSR diagnosis code prefix mapped to one of 20 body systems"),
    ("department", "APR major diagnostic category with a short service-line name"),
    ("region", "Service area folded into New York City / NYC suburbs / Upstate"),
    ("disposition_group", "19 discharge destinations grouped into 8 outcomes"),
    ("died_in_hospital", "True when disposition is 'Expired'"),
    ("charge_per_day / cost_per_day", "Total charges or costs ÷ length of stay"),
    ("charge_to_cost_ratio", "Total charges ÷ total costs (hospital mark-up)"),
    ("expected_los", "Statewide mean stay for the same diagnosis and severity (case-mix benchmark)"),
    ("charge_outlier", "Tukey 1.5 × IQR rule on log10(charges) within each severity level"),
], columns=["Feature", "How it is built"])


def render_data(fk: tuple, df: pd.DataFrame) -> None:
    st.subheader("Data source")
    st.markdown(
        f"[Hospital Inpatient Discharges (SPARCS De-Identified): 2021]({DATA_SOURCE_URL}) - New York State "
        f"Department of Health. One row per inpatient stay that ended in 2021: **{len(df):,}** stays after "
        f"cleaning, from **{df['facility'].nunique() - 1}** hospitals in **{df['county'].nunique() - 1}** counties.")

    st.subheader("Cleaning log")
    st.caption("Produced by `scripts/prepare_data.py` → `src/data_cleaning.py`. Each rule records the rows it "
               "removed or the values it changed.")
    log = get_cleaning_log()
    st.dataframe(log, hide_index=True, width="stretch", key="t_log",
                 column_config={"step": st.column_config.TextColumn("Step"),
                                "rule": st.column_config.TextColumn("Rule", width="large"),
                                "note": st.column_config.TextColumn("Note", width="large"),
                                "rows_before": st.column_config.NumberColumn("Rows before", format="localized"),
                                "rows_after": st.column_config.NumberColumn("Rows after", format="localized"),
                                "rows_removed": st.column_config.NumberColumn("Rows removed", format="localized"),
                                "values_changed": st.column_config.NumberColumn("Values changed",
                                                                                format="localized")})

    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Columns dropped")
        st.dataframe(pd.DataFrame(DROP_COLUMNS.items(), columns=["Column", "Why it was dropped"]),
                     hide_index=True, width="stretch", key="t_dropped")
    with right:
        st.subheader("Engineered features")
        st.dataframe(FEATURES, hide_index=True, width="stretch", key="t_features")

    st.subheader("Filtered records")
    data = get_filtered(fk)
    st.dataframe(data.head(500), hide_index=True, width="stretch", key="t_preview",
                 column_config={"total_charges": MONEY, "total_costs": MONEY})
    st.download_button(
        f"Download filtered records as CSV ({min(len(data), 25_000):,} rows)", filtered_csv(fk),
        file_name="mediscope_filtered_discharges.csv", mime="text/csv", icon=":material/download:",
        help="Up to 25,000 rows; larger selections are a random sample.")


# ======================================================================================
# Page
# ======================================================================================
def main() -> None:
    df = get_data()
    fk = sidebar_filters()
    theme = active_theme()

    st.title("New York hospital inpatient discharges, 2021")
    st.markdown("Length of stay, cost, severity and payer patterns across every inpatient stay in New York "
                "State - built for hospital administrators, clinicians and operations managers.")
    active_filter_badges(fk)

    if get_filtered(fk).empty:
        st.warning("No discharges match these filters. Widen the selection or press **Reset all filters**.")
        st.stop()

    k = compute("summary_kpis", fk)
    kpi_row(k, compute("summary_kpis", STATEWIDE), filtered=fk != STATEWIDE)

    names = [":material/dashboard: Overview", ":material/bed: Length of stay",
             ":material/monitoring: Cost & severity", ":material/payments: Payers & billing",
             ":material/local_hospital: Hospitals", ":material/lightbulb: Insights",
             ":material/database: Data & methods"]
    tabs = st.tabs(names, key="main_tabs", on_change="rerun")
    renderers = [
        lambda: render_overview(fk, k, theme),
        lambda: render_length_of_stay(fk, theme),
        lambda: render_cost(fk, theme),
        lambda: render_payers(fk, theme),
        lambda: render_hospitals(fk, theme),
        lambda: render_insights(fk),
        lambda: render_data(fk, df),
    ]
    for tab, render in zip(tabs, renderers):
        with tab:
            if tab.open:  # only the visible tab does its work
                render()


main()
