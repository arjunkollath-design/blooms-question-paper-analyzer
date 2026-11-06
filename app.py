"""
Bloom's Question Paper Analyzer – Streamlit dashboard
Run:  streamlit run app.py
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analyzer import (
    LEVELS, LEVEL_COLORS, LEVEL_LABELS, UNSET_LABEL, VERBS, SAMPLE_PAPER,
    parse_paper, read_upload, to_dataframe, summarise, checks, suggestions,
    excel_report,
)

# ---- Edit these for your institution -------------------------------------
INSTITUTION = "Vidya Academy of Science & Technology"
DEPARTMENTS = ["CSE", "ECE", "EEE", "ME", "CE", "AI & DS",
               "Science & Humanities", "Other"]
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Bloom's Question Paper Analyzer", page_icon="🎓",
                   layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 2rem; max-width: 1300px;}
h1 {letter-spacing: -0.01em;}
div[data-testid="stMetricValue"] {font-size: 1.7rem;}
</style>
""", unsafe_allow_html=True)

# ---- Session state ---------------------------------------------------------
ss = st.session_state
ss.setdefault("paper_text", "")
ss.setdefault("base_df", None)
ss.setdefault("editor_version", 0)
ss.setdefault("papers", [])          # list of dicts: id, department, code, name, exam, df

# ---- Sidebar ---------------------------------------------------------------
with st.sidebar:
    st.header("Targets")
    weigh = st.radio("Weigh by", ["Marks", "Questions"], horizontal=True,
                     help="Share of total marks, or share of the number of questions.")
    lower_max = st.slider("Lower order (L1–L2), at most %", 0, 100, 40)
    higher_min = st.slider("Higher order (L4–L6), at least %", 0, 100, 20)
    co_count = st.number_input("Course outcomes per course", 1, 10, 5)
    st.caption("Set these to your department or university norms. "
               "The defaults are only a starting point.")
    st.divider()
    st.caption(f"Built for faculty of {INSTITUTION}. Levels follow the revised "
               "Bloom's taxonomy (Anderson & Krathwohl) and are suggestions to "
               "check, not a final classification.")

weigh_by_marks = weigh == "Marks"

st.title("Bloom's question paper analyzer")
st.caption(f"{INSTITUTION} · question paper quality dashboard")

tab_paper, tab_dept, tab_verbs = st.tabs(
    ["Analyse a paper", "Department dashboard", "Verb lists"])


# ---- Charts ----------------------------------------------------------------
def ladder_chart(s):
    labels = [f"L{k} {LEVELS[k][0]}" for k in range(1, 7)]
    values = [s.share[k] for k in range(1, 7)]
    text = [f"{v:.1f}%  ({s.counts[k]} q, {s.marks[k]:g} m)" for k, v in zip(range(1, 7), values)]
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h", text=text, textposition="outside",
        marker_color=[LEVEL_COLORS[k] for k in range(1, 7)], cliponaxis=False,
        hovertemplate="%{y}: %{x:.1f}%<extra></extra>"))
    fig.update_layout(height=320, margin=dict(l=10, r=90, t=10, b=10),
                      xaxis=dict(range=[0, max(values + [10]) * 1.25], ticksuffix="%",
                                 showgrid=True), yaxis=dict(title=None))
    return fig


def band_chart(s, lower_max, higher_min):
    fig = go.Figure()
    for name, val, color in [("Lower order (L1–L2)", s.lower, LEVEL_COLORS[2]),
                             ("Apply (L3)", s.apply, LEVEL_COLORS[3]),
                             ("Higher order (L4–L6)", s.higher, LEVEL_COLORS[5])]:
        fig.add_bar(x=[val], y=[""], orientation="h", name=f"{name} {val:.1f}%",
                    marker_color=color, hovertemplate=f"{name}: %{{x:.1f}}%<extra></extra>")
    fig.add_vline(x=lower_max, line_width=2, line_dash="dot",
                  annotation_text=f"Lower limit {lower_max}%", annotation_position="top")
    fig.add_vline(x=100 - higher_min, line_width=2, line_dash="dot",
                  annotation_text=f"Higher from {100 - higher_min}%",
                  annotation_position="bottom")
    fig.update_layout(barmode="stack", height=170, margin=dict(l=10, r=10, t=30, b=30),
                      xaxis=dict(range=[0, 100], ticksuffix="%"),
                      legend=dict(orientation="h", y=-0.6))
    return fig


def co_chart(s):
    keys = list(s.co_share)
    fig = go.Figure(go.Bar(
        x=keys, y=[s.co_share[k] for k in keys],
        marker_color=["#B0500C" if s.co_share[k] == 0 else "#2449A8" for k in keys],
        text=[f"{s.co_share[k]:.0f}%" for k in keys], textposition="outside",
        cliponaxis=False))
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=20, b=10),
                      yaxis=dict(ticksuffix="%", title=None))
    return fig


# ---- Tab 1: analyse one paper ---------------------------------------------
def load_sample():
    ss.paper_text = SAMPLE_PAPER
    ss.meta_code, ss.meta_name = "SAMPLE", "Programming in C"


with tab_paper:
    c1, c2, c3, c4 = st.columns([1.2, 1, 2, 1.4])
    department = c1.selectbox("Department", DEPARTMENTS, key="meta_dept")
    code = c2.text_input("Course code", key="meta_code", placeholder="CST 102")
    name = c3.text_input("Course name", key="meta_name", placeholder="Programming in C")
    exam = c4.text_input("Exam", key="meta_exam", placeholder="Series Test 1")

    src = st.radio("Question paper", ["Paste text", "Upload file (.docx, .pdf, .txt)"],
                   horizontal=True, label_visibility="collapsed")
    upload = None
    if src == "Paste text":
        st.text_area(
            "Paste the question paper", key="paper_text", height=260,
            help="Number questions as 1., 2 a), (b) or Q3. Marks like (6) or [6 marks] and "
                 "outcomes like CO2 are picked up automatically. Headings such as Part A, "
                 "Module 2 and OR are skipped.")
    else:
        upload = st.file_uploader("Upload the question paper", type=["docx", "pdf", "txt"])
        st.caption("Word papers laid out as tables (question, marks, CO columns) work well. "
                   "Scanned PDFs have no text to read; paste the text instead.")

    b1, b2, _ = st.columns([1, 1, 4])
    analyse = b1.button("Analyse paper", type="primary", width="stretch")
    b2.button("Load sample paper", on_click=load_sample, width="stretch")

    if analyse:
        if upload is not None:
            raw = read_upload(upload.name, upload.getvalue())
            if not name:
                ss.meta_name_hint = Path(upload.name).stem
        else:
            raw = ss.paper_text
        qs = parse_paper(raw)
        if not qs:
            st.warning("No questions were found. Put each question on its own line, "
                       "starting with its number.")
            ss.base_df = None
        else:
            df = to_dataframe(qs)
            df["CO"] = df["CO"].replace("", None)
            ss.base_df = df
            ss.editor_version += 1
            found_cos = [int(c[2:]) for c in df["CO"].dropna() if str(c)[2:].isdigit()]
            if found_cos and max(found_cos) > co_count:
                st.info(f"This paper uses up to CO{max(found_cos)}. "
                        "Raise “Course outcomes per course” in the sidebar to match.")

    if ss.base_df is not None:
        st.subheader("Questions")
        st.caption("Levels are suggested from each question's leading action verb. "
                   "Check every one and correct the level, CO or marks where needed; "
                   "the dashboard updates as you edit.")
        edited = st.data_editor(
            ss.base_df,
            key=f"editor_{ss.editor_version}",
            num_rows="dynamic",
            width="stretch",
            hide_index=True,
            column_config={
                "Q": st.column_config.TextColumn(width="small"),
                "Question": st.column_config.TextColumn(width="large"),
                "Level": st.column_config.SelectboxColumn(
                    options=LEVEL_LABELS + [UNSET_LABEL], required=True, width="medium"),
                "Detected verb": st.column_config.TextColumn(disabled=True, width="small"),
                "CO": st.column_config.SelectboxColumn(
                    options=[f"CO{i}" for i in range(1, max(int(co_count), 10) + 1)],
                    width="small"),
                "Marks": st.column_config.NumberColumn(min_value=0, step=0.5, width="small"),
            },
        )
        s = summarise(edited, weigh_by_marks, int(co_count))

        st.subheader("Level profile")
        if weigh_by_marks and not s.by_marks:
            st.warning("No marks found, so the profile counts questions. "
                       "Add marks in the table to weigh by marks.")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Questions", s.n_questions)
        m2.metric("Total marks", f"{s.total_marks:g}")
        m3.metric("Lower order", f"{s.lower:.1f}%",
                  delta=f"{s.lower - lower_max:+.1f} vs limit", delta_color="inverse")
        m4.metric("Apply", f"{s.apply:.1f}%")
        m5.metric("Higher order", f"{s.higher:.1f}%",
                  delta=f"{s.higher - higher_min:+.1f} vs minimum")

        left, right = st.columns([3, 2])
        with left:
            st.plotly_chart(ladder_chart(s), width="stretch")
            st.plotly_chart(band_chart(s, lower_max, higher_min), width="stretch")
        with right:
            st.markdown("**Checks**")
            for ok, msg in checks(s, lower_max, higher_min, int(co_count)):
                (st.success if ok else st.warning)(msg, icon="✅" if ok else "⚠️")
            st.markdown("**Course outcome coverage**")
            st.plotly_chart(co_chart(s), width="stretch")

        st.markdown("**Suggestions**")
        for a in suggestions(edited, s, lower_max, higher_min, int(co_count)):
            st.markdown(f"- {a}")

        meta = {"department": department, "code": code,
                "name": name or ss.get("meta_name_hint", ""), "exam": exam}
        fname = "_".join(x for x in [code, exam] if x).replace(" ", "_") or "paper"
        d1, d2, d3 = st.columns(3)
        d1.download_button(
            "Download Excel report",
            excel_report(edited, s, meta, lower_max, higher_min, int(co_count)),
            file_name=f"blooms_{fname}.xlsx", type="primary", width="stretch",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        d2.download_button("Download questions (CSV)", edited.to_csv(index=False).encode(),
                           file_name=f"blooms_{fname}.csv", mime="text/csv", width="stretch")
        if d3.button("Add to department dashboard", width="stretch"):
            ss.papers.append({"id": uuid.uuid4().hex[:8], **meta, "df": edited.copy()})
            st.toast(f"Added {meta['code'] or meta['name'] or 'paper'} to the dashboard.")


# ---- Tab 2: department dashboard ------------------------------------------
def papers_to_csv(papers) -> bytes:
    frames = []
    for p in papers:
        d = p["df"].copy()
        d.insert(0, "Exam", p["exam"]); d.insert(0, "Course name", p["name"])
        d.insert(0, "Course code", p["code"]); d.insert(0, "Department", p["department"])
        d.insert(0, "Paper ID", p["id"])
        frames.append(d)
    return pd.concat(frames).to_csv(index=False).encode() if frames else b""


def csv_to_papers(data: bytes):
    df = pd.read_csv(io.BytesIO(data), dtype={"Q": str})
    out = []
    for pid, g in df.groupby("Paper ID", sort=False):
        first = g.iloc[0]
        qdf = g[["Q", "Question", "Level", "Detected verb", "CO", "Marks"]].reset_index(drop=True)
        qdf["CO"] = qdf["CO"].where(qdf["CO"].notna(), None)
        out.append({"id": str(pid), "department": str(first["Department"]),
                    "code": "" if pd.isna(first["Course code"]) else str(first["Course code"]),
                    "name": "" if pd.isna(first["Course name"]) else str(first["Course name"]),
                    "exam": "" if pd.isna(first["Exam"]) else str(first["Exam"]), "df": qdf})
    return out


with tab_dept:
    st.caption("Collect papers from a department or the whole college and compare them "
               "against the same targets, for exam-cell scrutiny, IQAC or NBA files.")

    with st.expander("Add papers", expanded=not ss.papers):
        a1, a2 = st.columns([2, 1])
        files = a1.file_uploader("Upload several question papers at once",
                                 type=["docx", "pdf", "txt"], accept_multiple_files=True,
                                 key="bulk_files")
        bulk_dept = a2.selectbox("Department for these papers", DEPARTMENTS, key="bulk_dept")
        bulk_exam = a2.text_input("Exam", key="bulk_exam", placeholder="End semester, Nov 2026")
        if st.button("Add uploaded papers", type="primary", disabled=not files):
            added, failed = 0, []
            for f in files:
                qs = parse_paper(read_upload(f.name, f.getvalue()))
                if not qs:
                    failed.append(f.name)
                    continue
                df = to_dataframe(qs)
                df["CO"] = df["CO"].replace("", None)
                ss.papers.append({"id": uuid.uuid4().hex[:8], "department": bulk_dept,
                                  "code": "", "name": Path(f.name).stem,
                                  "exam": bulk_exam, "df": df})
                added += 1
            if added:
                st.success(f"Added {added} paper(s). Check their levels in "
                           "“Analyse a paper” before relying on the figures.")
            if failed:
                st.warning("No questions found in: " + ", ".join(failed))
        st.divider()
        st.markdown("**Save or reload the dashboard.** Data lives only in this browser "
                    "session, so download it before closing and upload it next time.")
        r1, r2 = st.columns(2)
        saved = r1.file_uploader("Load saved dashboard (CSV)", type=["csv"], key="saved_csv")
        if saved is not None and r1.button("Load dashboard"):
            try:
                ss.papers = csv_to_papers(saved.getvalue())
                st.success(f"Loaded {len(ss.papers)} paper(s).")
            except Exception as e:  # noqa: BLE001
                st.error(f"That file isn't a dashboard export: {e}")
        r2.download_button("Download dashboard data (CSV)", papers_to_csv(ss.papers),
                           file_name="blooms_dashboard.csv", mime="text/csv",
                           disabled=not ss.papers)

    if not ss.papers:
        st.info("No papers yet. Analyse a paper and select “Add to department dashboard”, "
                "or upload several papers above.")
    else:
        rows = []
        for p in ss.papers:
            s = summarise(p["df"], weigh_by_marks, int(co_count))
            covered = sum(1 for i in range(1, int(co_count) + 1) if s.co_share.get(f"CO{i}", 0) > 0)
            meets = s.lower <= lower_max and s.higher >= higher_min
            rows.append({
                "id": p["id"], "Department": p["department"],
                "Paper": " ".join(x for x in [p["code"], p["name"]] if x) or p["id"],
                "Exam": p["exam"], "Questions": s.n_questions, "Marks": s.total_marks,
                **{f"L{k}": round(s.share[k], 1) for k in range(1, 7)},
                "Lower %": round(s.lower, 1), "Apply %": round(s.apply, 1),
                "Higher %": round(s.higher, 1),
                "COs covered": f"{covered}/{int(co_count)}",
                "Meets targets": "Yes" if meets else "No",
            })
        summary = pd.DataFrame(rows)

        depts = st.multiselect("Departments", sorted(summary["Department"].unique()),
                               default=sorted(summary["Department"].unique()))
        view = summary[summary["Department"].isin(depts)]

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Papers", len(view))
        k2.metric("Meet targets", f"{(view['Meets targets'] == 'Yes').sum()} of {len(view)}")
        k3.metric("Average lower order", f"{view['Lower %'].mean():.1f}%" if len(view) else "–")
        k4.metric("Average higher order", f"{view['Higher %'].mean():.1f}%" if len(view) else "–")

        if len(view):
            st.subheader("Level profile of each paper")
            v = view.sort_values("Higher %")
            fig = go.Figure()
            for k in range(1, 7):
                fig.add_bar(y=v["Paper"] + " · " + v["Exam"].fillna(""), x=v[f"L{k}"],
                            orientation="h", name=f"L{k} {LEVELS[k][0]}",
                            marker_color=LEVEL_COLORS[k],
                            hovertemplate="%{y}<br>" + f"L{k} {LEVELS[k][0]}: " + "%{x:.1f}%<extra></extra>")
            fig.add_vline(x=lower_max, line_dash="dot", line_width=2)
            fig.add_vline(x=100 - higher_min, line_dash="dot", line_width=2)
            fig.update_layout(barmode="stack", height=max(260, 46 * len(v) + 120),
                              margin=dict(l=10, r=10, t=10, b=10),
                              xaxis=dict(range=[0, 100], ticksuffix="%"),
                              legend=dict(orientation="h", y=-0.12))
            st.plotly_chart(fig, width="stretch")
            st.caption("Dotted lines mark the targets: lower-order bars should end before the "
                       "first line, and higher-order bars should start before the second.")

            st.subheader("By department")
            dep = view.groupby("Department")[[f"L{k}" for k in range(1, 7)]].mean().reset_index()
            fig2 = go.Figure()
            for k in range(1, 7):
                fig2.add_bar(x=dep["Department"], y=dep[f"L{k}"], name=f"L{k} {LEVELS[k][0]}",
                             marker_color=LEVEL_COLORS[k])
            fig2.update_layout(barmode="stack", height=360, margin=dict(l=10, r=10, t=10, b=10),
                               yaxis=dict(range=[0, 100], ticksuffix="%", title="Average share"))
            st.plotly_chart(fig2, width="stretch")

            st.subheader("All papers")
            st.dataframe(view.drop(columns=["id"]), hide_index=True, width="stretch")
            st.download_button("Download this table (CSV)",
                               view.drop(columns=["id"]).to_csv(index=False).encode(),
                               file_name="blooms_paper_summary.csv", mime="text/csv")

        with st.expander("Remove papers"):
            labels = {r["id"]: f"{r['Paper']} ({r['Department']}, {r['Exam'] or 'no exam'})"
                      for r in rows}
            drop = st.multiselect("Papers to remove", list(labels), format_func=labels.get)
            if st.button("Remove selected", disabled=not drop):
                ss.papers = [p for p in ss.papers if p["id"] not in drop]
                st.rerun()


# ---- Tab 3: verb lists -----------------------------------------------------
with tab_verbs:
    st.caption("A question's level is taken from the earliest of these phrases in it. "
               "When two match at the same place, the longer phrase wins, so "
               "“Explain the difference” counts as Analyse. In “State and prove”, the "
               "higher of the two verbs counts. Edit VERBS in analyzer.py to change them.")
    cols = st.columns(3)
    for i, (k, verbs) in enumerate(VERBS.items()):
        with cols[i % 3]:
            st.markdown(f"<div style='border-left:6px solid {LEVEL_COLORS[k]};padding-left:10px'>"
                        f"<b>L{k} {LEVELS[k][0]}</b><br><span style='opacity:.75'>{LEVELS[k][1]}</span></div>",
                        unsafe_allow_html=True)
            st.write(", ".join(v.lstrip("^") for v in verbs))
            st.write("")
