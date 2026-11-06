"""
Core logic for the Bloom's Question Paper Analyzer.

Parses a question paper into questions, suggests a revised Bloom's taxonomy
level for each from its leading action verb, picks up marks and course
outcomes (COs), and summarises a paper against department targets.

Nothing here depends on Streamlit, so it can be tested and reused on its own.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field, asdict

import pandas as pd

# --------------------------------------------------------------------------
# Taxonomy
# --------------------------------------------------------------------------
LEVELS = {
    1: ("Remember", "Recall facts"),
    2: ("Understand", "Explain ideas"),
    3: ("Apply", "Use in new situations"),
    4: ("Analyse", "Break down, compare"),
    5: ("Evaluate", "Judge, justify"),
    6: ("Create", "Design, build"),
}
LEVEL_COLORS = {
    1: "#9CB3D2", 2: "#5A84BE", 3: "#24917F",
    4: "#C98F0C", 5: "#CC6216", 6: "#AE2F5B",
}
UNSET_LABEL = "Not set"
LEVEL_LABELS = [f"L{k} {v[0]}" for k, v in LEVELS.items()]

UPGRADE_VERBS = {
    3: "Calculate, Solve, Apply, Determine",
    4: "Compare, Analyse, Differentiate, Examine",
    5: "Justify, Evaluate, Assess, Recommend",
    6: "Design, Develop, Propose, Formulate",
}

# A leading "^" means the phrase only counts at the start of a question.
VERBS: dict[int, list[str]] = {
    1: ["define", "list", "state", "name", "recall", "label", "mention", "enumerate",
        "recognize", "recognise", "reproduce", "memorize", "identify", "expand",
        "what is", "what are", "^who", "^when", "^where", "^which"],
    2: ["explain", "describe", "discuss", "summarize", "summarise", "interpret",
        "illustrate", "outline", "classify", "paraphrase", "infer", "predict",
        "represent", "draw", "sketch", "elaborate", "briefly", "indicate", "express",
        "give an example", "give examples", "give reasons", "give reason",
        "short note", "short notes", "write a note", "write notes",
        "what is meant by", "what do you mean by", "why", "how"],
    3: ["apply", "calculate", "compute", "solve", "determine", "find", "use",
        "implement", "execute", "demonstrate", "derive", "prove", "show that",
        "verify", "obtain", "simplify", "convert", "plot", "estimate", "measure",
        "construct", "trace", "modify", "realize", "realise", "minimize", "minimise",
        "perform", "carry out", "write a program", "write a c program",
        "write a python program", "write a java program", "write an algorithm",
        "write a function", "write the code", "write code", "write a query",
        "write an sql", "write a script"],
    4: ["analyze", "analyse", "differentiate", "distinguish", "compare", "contrast",
        "examine", "investigate", "categorize", "categorise", "deduce", "break down",
        "inspect", "debug", "find the error", "find the errors", "identify the error",
        "identify the errors", "what is the difference", "explain the difference",
        "explain the differences", "difference between", "compare and contrast",
        "differentiate between"],
    5: ["evaluate", "justify", "assess", "critique", "criticize", "criticise",
        "critically", "judge", "defend", "recommend", "argue", "appraise",
        "select the best", "choose", "prioritize", "prioritise", "conclude",
        "validate", "comment on", "which is better", "which is more", "do you agree",
        "suggest", "decide"],
    6: ["design", "develop", "create", "formulate", "propose", "compose", "devise",
        "invent", "prepare a plan", "synthesize", "synthesise", "generate", "build",
        "construct a model", "come up with"],
}


def _compile():
    out = []
    for lvl, verbs in VERBS.items():
        for v in verbs:
            start = v.startswith("^")
            word = v[1:] if start else v
            body = r"\s+".join(re.escape(p) for p in word.split())
            prefix = r"^\s*" if start else r"(?<![a-z])"
            out.append((lvl, re.compile(prefix + "(" + body + r")(?![a-z])"), start))
    return out


_COMPILED = _compile()

# Maths usage where the "higher" verb is really a computation (Apply level).
_SPECIALS = [
    re.compile(r"(?<![a-z])evaluate\s+(?:the\s+)?(?:following\s+)?(?:definite\s+|improper\s+)?"
               r"(?:integral|integrals|expression|expressions|value|values|limit|limits|"
               r"determinant|sum|series|function|polynomial)"),
    re.compile(r"(?<![a-z])differentiate(?!\s+between)"
               r"(?=[^.?]*?(?:with respect to|w\.?\s?r\.?\s?t|d/d|\bf\s*\(|the function))"),
]


@dataclass
class Classification:
    level: int          # 0 means no verb was recognised
    verb: str
    start: int
    length: int


def classify(text: str) -> Classification:
    """Suggest a Bloom's level from the question's leading action verb."""
    t = text.lower()
    found = []  # (idx, length, level)
    for lvl, rx, start in _COMPILED:
        if start:
            m = rx.match(t)
            if m:
                found.append([m.start(1), len(m.group(1)), lvl])
        else:
            for m in rx.finditer(t):
                found.append([m.start(1), len(m.group(1)), lvl])
    if not found:
        return Classification(0, "", -1, 0)

    for rx in _SPECIALS:
        for m in rx.finditer(t):
            for f in found:
                if f[0] == m.start():
                    f[2] = 3

    # Earliest phrase wins; at the same position, the longer phrase wins.
    found.sort(key=lambda f: (f[0], -f[1], -f[2]))
    best = found[0]

    # "State and prove", "Define and explain": the second verb counts if higher.
    after = best[0] + best[1]
    m = re.match(r"\s*(?:,|and|&|/)\s*(?:and\s+)?", t[after:])
    if m:
        pos = after + m.end()
        nxt = sorted((f for f in found if f[0] == pos), key=lambda f: -f[1])
        if nxt and nxt[0][2] > best[2]:
            best = nxt[0]
    return Classification(best[2], text[best[0]:best[0] + best[1]], best[0], best[1])


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
_RE_Q = re.compile(r"^\s*Q(?:uestion)?\s*\.?\s*(\d{1,2})\s*[.):\-]?\s*"
                   r"(?:\(([a-h])\)(?=\s)|([a-h])\s*[.)](?=\s))?\s*(.*)$", re.I | re.S)
_RE_NUM = re.compile(r"^\s*(\d{1,2})(?:\s*[.):](?!\d)|\t|\s{2,}|\s+(?=\(?[a-h]\s*[.)]\s))\s*"
                     r"(?:\(([a-h])\)(?=\s)|([a-h])\s*[.)](?=\s))?\s*(.*)$", re.I | re.S)
_RE_SUB = re.compile(r"^\s*(?:\(([a-h])\)|([a-h])[.)])\s+(.*)$", re.I | re.S)
_RE_ROM = re.compile(r"^\s*\(?(i{1,3}|iv|vi{0,3}|ix|x)\)\s+(.*)$", re.I | re.S)
_RE_SKIP = re.compile(r"^\s*(?:part|module|section|unit)\b|^\s*\(?\s*or\s*\)?\s*$|"
                      r"^\s*(?:answer|attempt|time\s*:|duration|max(?:imum)?\.?\s*marks|"
                      r"reg\.?\s*no|qp\s*code|page\s+\d)", re.I)


def extract_meta(text: str):
    """Strip trailing marks and CO columns from a question; return (text, marks, co)."""
    marks, co, col_strip = None, "", False
    m = re.search(r"[(\[]\s*CO\s*-?\s*(\d{1,2})\s*[)\]]", text, re.I)
    if m and not re.search(r"[(\[]\s*CO\s*-?\s*\d{1,2}\s*[)\]]\s*$", text, re.I):
        co = f"CO{int(m.group(1))}"
        text = text.replace(m.group(0), " ", 1)
    for _ in range(6):
        m = re.search(r"(?:^|[\s,;(\[])\(?\[?\s*CO\s*-?\s*(\d{1,2})\s*[)\]]?\s*$", text, re.I)
        if m:
            co = co or f"CO{int(m.group(1))}"
            text, col_strip = text[:m.start()], True
            continue
        if marks is None:
            m = re.search(r"(?:^|[\s.?:;,])[(\[]\s*(\d{1,2}(?:\.\d)?)\s*(?:marks?|m)?\s*[)\]]\s*$", text, re.I)
            if m:
                marks = float(m.group(1))
                text = text[:m.start() + (1 if re.match(r"[\s.?:;,]", m.group(0)) else 0)]
                continue
            m = re.search(r"\s+(\d{1,2}(?:\.\d)?)\s*marks?\s*$", text, re.I)
            if m:
                marks, text = float(m.group(1)), text[:m.start()]
                continue
            rx = r"\s+(\d{1,2}(?:\.\d)?)\s*$" if col_strip else r"(?:\t|\s{2,})(\d{1,2}(?:\.\d)?)\s*$"
            m = re.search(rx, text)
            if m:
                marks, text = float(m.group(1)), text[:m.start()]
                continue
        break
    return re.sub(r"\s+", " ", text).strip(), marks, co


@dataclass
class Question:
    q: str
    question: str
    level: int
    verb: str
    co: str
    marks: float | None


def parse_paper(raw: str) -> list[Question]:
    """Split pasted or extracted paper text into questions."""
    lines = raw.splitlines()
    qs: list[dict] = []
    cur = None
    last_num = last_base = None

    def start(qid, text):
        nonlocal cur
        cur = {"id": qid, "text": text or ""}
        qs.append(cur)

    for line in lines:
        if not line.strip():
            continue
        if _RE_SKIP.search(line):
            cur = None
            continue
        m = _RE_Q.match(line) or _RE_NUM.match(line)
        if m:
            last_num = m.group(1)
            last_base = last_num + (m.group(2) or m.group(3) or "").lower()
            start(last_base, m.group(4))
            continue
        m = _RE_ROM.match(line)
        if m:
            start(f"{last_base or ''}({m.group(1).lower()})", m.group(2))
            continue
        m = _RE_SUB.match(line)
        if m:
            last_base = (last_num or "") + (m.group(1) or m.group(2)).lower()
            start(last_base, m.group(3))
            continue
        if cur is not None:
            cur["text"] += "\n" + line

    if not qs:  # no numbering at all: one question per line
        n = 0
        for line in lines:
            if line.strip() and not _RE_SKIP.search(line):
                n += 1
                qs.append({"id": str(n), "text": line})

    out = []
    for q in qs:
        joiner = "\t" if "\t" in q["text"] else "  "
        text, marks, co = extract_meta(q["text"].replace("\n", joiner))
        if not text:
            continue
        c = classify(text)
        out.append(Question(q["id"], text, c.level, c.verb, co, marks))
    return out


# --------------------------------------------------------------------------
# Reading uploaded files
# --------------------------------------------------------------------------
def read_upload(name: str, data: bytes) -> str:
    """Extract text from a .txt, .docx or .pdf question paper."""
    lower = name.lower()
    if lower.endswith(".docx"):
        from docx import Document
        doc = Document(io.BytesIO(data))
        parts = []
        # Paragraphs and tables in document order
        body = doc.element.body
        for child in body.iterchildren():
            tag = child.tag.split("}")[-1]
            if tag == "p":
                txt = "".join(n.text or "" for n in child.iter() if n.tag.endswith("}t"))
                if txt.strip():
                    parts.append(txt)
            elif tag == "tbl":
                from docx.table import Table
                for row in Table(child, doc).rows:
                    cells, prev = [], None
                    for cell in row.cells:
                        t = cell.text.strip().replace("\n", " ")
                        if t and t != prev:  # merged cells repeat their text
                            cells.append(t)
                        prev = t
                    if cells:
                        parts.append("\t".join(cells))
        return "\n".join(parts)
    if lower.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    return data.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------
# Tables and summaries
# --------------------------------------------------------------------------
def level_label(level: int) -> str:
    return f"L{level} {LEVELS[level][0]}" if level in LEVELS else UNSET_LABEL


def label_to_level(label) -> int:
    m = re.match(r"L(\d)", str(label or ""))
    return int(m.group(1)) if m else 0


def to_dataframe(questions: list[Question]) -> pd.DataFrame:
    df = pd.DataFrame([asdict(q) for q in questions],
                      columns=["q", "question", "level", "verb", "co", "marks"])
    df["level"] = df["level"].map(level_label)
    return df.rename(columns={"q": "Q", "question": "Question", "level": "Level",
                              "verb": "Detected verb", "co": "CO", "marks": "Marks"})


@dataclass
class Summary:
    n_questions: int
    total_marks: float
    by_marks: bool
    share: dict = field(default_factory=dict)      # level -> %
    counts: dict = field(default_factory=dict)     # level -> questions
    marks: dict = field(default_factory=dict)      # level -> marks
    co_share: dict = field(default_factory=dict)   # CO -> %
    lower: float = 0.0
    apply: float = 0.0
    higher: float = 0.0
    unclassified: int = 0
    missing_marks: int = 0


def summarise(df: pd.DataFrame, weigh_by_marks: bool = True, co_count: int = 5) -> Summary:
    d = df.copy()
    d["lvl"] = d["Level"].map(label_to_level)
    d["m"] = pd.to_numeric(d["Marks"], errors="coerce")
    total_marks = float(d["m"].fillna(0).sum())
    by_marks = weigh_by_marks and total_marks > 0
    d["w"] = d["m"].fillna(0) if by_marks else 1.0
    total = float(d["w"].sum()) or 1.0

    s = Summary(len(d), total_marks, by_marks)
    for k in range(0, 7):
        sel = d[d["lvl"] == k]
        s.share[k] = 100 * float(sel["w"].sum()) / total
        s.counts[k] = int(len(sel))
        s.marks[k] = float(sel["m"].fillna(0).sum())
    cos = [f"CO{i}" for i in range(1, co_count + 1)]
    extra = sorted({c for c in d["CO"].fillna("") if c and c not in cos},
                   key=lambda c: int(re.sub(r"\D", "", c) or 0))
    for c in cos + extra:
        s.co_share[c] = 100 * float(d.loc[d["CO"] == c, "w"].sum()) / total
    unassigned = float(d.loc[d["CO"].fillna("") == "", "w"].sum())
    if unassigned:
        s.co_share["No CO"] = 100 * unassigned / total
    s.lower = s.share[1] + s.share[2]
    s.apply = s.share[3]
    s.higher = s.share[4] + s.share[5] + s.share[6]
    s.unclassified = s.counts[0]
    s.missing_marks = int(d["m"].isna().sum())
    return s


def checks(s: Summary, lower_max: float, higher_min: float, co_count: int):
    """Return a list of (passed, message)."""
    out = [
        (s.lower <= lower_max,
         f"Lower order (L1–L2) is {s.lower:.1f}%, "
         f"{'within' if s.lower <= lower_max else 'above'} the {lower_max:.0f}% limit."),
        (s.higher >= higher_min,
         f"Higher order (L4–L6) is {s.higher:.1f}%, "
         f"{'meeting' if s.higher >= higher_min else 'below'} the {higher_min:.0f}% minimum."),
    ]
    missing = [f"CO{i}" for i in range(1, co_count + 1) if s.co_share.get(f"CO{i}", 0) == 0]
    out.append((not missing, "Every course outcome is assessed." if not missing
                else f"{', '.join(missing)} {'have' if len(missing) > 1 else 'has'} no questions."))
    if s.unclassified:
        out.append((False, f"{s.unclassified} question(s) need a level. Choose one in the table."))
    if s.by_marks and s.missing_marks:
        out.append((False, f"{s.missing_marks} question(s) have no marks and count as zero."))
    return out


def suggestions(df: pd.DataFrame, s: Summary, lower_max: float, higher_min: float,
                co_count: int) -> list[str]:
    adv = []
    ok_lower, ok_higher = s.lower <= lower_max, s.higher >= higher_min
    if not (ok_lower and ok_higher):
        d = df.copy()
        d["lvl"] = d["Level"].map(label_to_level)
        d["m"] = pd.to_numeric(d["Marks"], errors="coerce").fillna(0)
        low = d[d["lvl"].isin([1, 2])].sort_values("m", ascending=False).head(3)
        if len(low):
            items = [f"Q{r['Q']} (“{r['Detected verb'] or 'no verb'}”, {r['m']:g} marks)"
                     for _, r in low.iterrows()]
            adv.append("To shift weight upward, consider reframing " + ", ".join(items)
                       + ". These carry the most marks at lower levels.")
        if not ok_higher:
            adv.append(f"Higher-order stems: {UPGRADE_VERBS[4]} (analyse); "
                       f"{UPGRADE_VERBS[5]} (evaluate); {UPGRADE_VERBS[6]} (create).")
        else:
            adv.append(f"Apply-level stems are often the easiest swap: {UPGRADE_VERBS[3]}.")
    if s.share[5] == 0 and s.share[6] == 0 and s.n_questions >= 6:
        adv.append("Nothing reaches Evaluate or Create. One design or justification "
                   "question in Part B usually fixes this.")
    missing = [f"CO{i}" for i in range(1, co_count + 1) if s.co_share.get(f"CO{i}", 0) == 0]
    if missing:
        adv.append(f"Add or retag a question for {', '.join(missing)}, or lower the "
                   "outcome count if this exam covers fewer outcomes.")
    if not adv:
        adv.append("This paper meets your targets. Check the detected verbs once more, "
                   "then download the report for your course file.")
    return adv


# --------------------------------------------------------------------------
# Excel report
# --------------------------------------------------------------------------
def excel_report(df: pd.DataFrame, s: Summary, meta: dict, lower_max: float,
                 higher_min: float, co_count: int) -> bytes:
    from openpyxl.chart import BarChart, Reference
    from openpyxl.styles import Font, PatternFill, Alignment

    level_rows = [{"Level": f"L{k}", "Name": LEVELS[k][0], "Questions": s.counts[k],
                   "Marks": s.marks[k], "Share %": round(s.share[k], 1)} for k in range(1, 7)]
    co_rows = [{"CO": c, "Share %": round(v, 1)} for c, v in s.co_share.items()]
    chk = [{"Check": msg, "Status": "OK" if ok else "Review"}
           for ok, msg in checks(s, lower_max, higher_min, co_count)]
    info = [
        ("Department", meta.get("department", "")),
        ("Course code", meta.get("code", "")),
        ("Course name", meta.get("name", "")),
        ("Exam", meta.get("exam", "")),
        ("Weighted by", "Marks" if s.by_marks else "Questions"),
        ("Total marks", s.total_marks),
        ("Questions", s.n_questions),
        ("Lower order (L1–L2) %", round(s.lower, 1)),
        ("Apply (L3) %", round(s.apply, 1)),
        ("Higher order (L4–L6) %", round(s.higher, 1)),
        ("Target: lower order max %", lower_max),
        ("Target: higher order min %", higher_min),
    ]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame(info, columns=["Item", "Value"]).to_excel(xw, sheet_name="Summary", index=False)
        pd.DataFrame(chk).to_excel(xw, sheet_name="Summary", index=False, startrow=len(info) + 2)
        df.to_excel(xw, sheet_name="Questions", index=False)
        pd.DataFrame(level_rows).to_excel(xw, sheet_name="Levels", index=False)
        pd.DataFrame(co_rows).to_excel(xw, sheet_name="CO coverage", index=False)

        wb = xw.book
        head_fill = PatternFill("solid", fgColor="2449A8")
        for ws in wb.worksheets:
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = head_fill
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 70)
        qs = wb["Questions"]
        for row in qs.iter_rows(min_row=2):
            row[1].alignment = Alignment(wrap_text=True, vertical="top")

        lv = wb["Levels"]
        for i, k in enumerate(range(1, 7), start=2):
            lv.cell(i, 1).fill = PatternFill("solid", fgColor=LEVEL_COLORS[k].lstrip("#"))
        chart = BarChart()
        chart.type = "bar"
        chart.title = "Share by Bloom's level (%)"
        chart.legend = None
        chart.add_data(Reference(lv, min_col=5, min_row=1, max_row=7), titles_from_data=True)
        chart.set_categories(Reference(lv, min_col=2, min_row=2, max_row=7))
        chart.height, chart.width = 8, 16
        lv.add_chart(chart, "G2")
    return buf.getvalue()


SAMPLE_PAPER = """PART A (Answer all questions, 3 marks each)
1. Define an algorithm. List its characteristics. (3) CO1
2. Differentiate between a compiler and an interpreter. (3) CO1
3. Explain the use of the break statement with an example. (3) CO2
4. What is a pointer? (3) CO3
5. Write a program to find the largest of three numbers. (3) CO2
6. Compare call by value and call by reference. (3) CO3
PART B
Module 1
7 a) Draw a flowchart to find the sum of the digits of a number. (6) CO1
b) Explain the structure of a C program. (8) CO1
OR
8 a) Describe the different data types in C with their sizes. (8) CO1
b) Evaluate the expression 5 + 3 * 2 % 4 - 1 and show each step. (6) CO1
Module 2
9 a) Write a program to sort an array using bubble sort. (8) CO2
b) Trace the execution of the program for the input 5 3 8 1. (6) CO2
OR
10 a) Explain nested loops with a suitable example. (7) CO2
b) Justify the choice of a while loop over a for loop when the number of iterations is unknown. (7) CO2
Module 3
11 a) Design a structure to store student records and write functions to read and display them. (14) CO4
OR
12 a) Analyse the following code segment and identify the errors. (8) CO3
b) Explain dynamic memory allocation using malloc() and free(). (6) CO3
"""
