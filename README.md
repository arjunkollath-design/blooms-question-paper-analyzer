# Bloom's Question Paper Analyzer

A Streamlit dashboard that checks engineering question papers against the revised Bloom's taxonomy. Paste or upload a paper and it splits it into questions, suggests a cognitive level (L1 Remember to L6 Create) for each from its action verb, reads the marks and course outcomes (COs), and shows whether the paper meets your department's targets for lower-order and higher-order questions.

Built for faculty of **Vidya Academy of Science & Technology** by **[Your Name], Department of [Your Department]**. It works for every department, because it reads the wording of questions rather than their subject.

## What it does

**Analyse a paper.** Paste text or upload a `.docx`, `.pdf` or `.txt` paper. Question numbers such as `1.`, `11 a)`, `(b)` and `Q3`, marks such as `(6)` or `[6 marks]`, and outcomes such as `CO2` are detected automatically, including Word papers laid out as tables. Every suggested level, CO and mark can be corrected in an editable table, and the charts update as you edit. The page shows the level profile, the lower/apply/higher split against your targets, CO coverage, and suggestions for which questions to reword. Download an Excel report (summary, questions, level chart, CO coverage) for the course file.

**Department dashboard.** Add papers one at a time or upload a whole set. Compare every paper's level profile against the targets, see department averages, and download the summary table. Save the dashboard as a CSV and load it again later.

**Verb lists.** Shows the action verbs used for each level. Edit `VERBS` in `analyzer.py` to adapt them to your university.

Typical uses are question paper scrutiny before series tests and end-semester exams, NBA and IQAC documentation, and faculty development sessions on outcome-based assessment.

## Run it on your computer

You need Python 3.10 or newer.

```bash
git clone https://github.com/<your-username>/blooms-question-paper-analyzer.git
cd blooms-question-paper-analyzer
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The app opens at http://localhost:8501. Select **Load sample paper**, then **Analyse paper** to try it.

## Put it online for free (Streamlit Community Cloud)

1. Create a GitHub repository and upload all the files in this folder (keep the `.streamlit` folder).
2. Go to https://share.streamlit.io and sign in with GitHub.
3. Select **Create app**, choose your repository, set the main file to `app.py`, and deploy.
4. Share the link with colleagues. Each person's data stays in their own browser session.

To run it on a college server instead: `streamlit run app.py --server.port 8501 --server.address 0.0.0.0`.

## Customise

At the top of `app.py`, change `INSTITUTION` and the `DEPARTMENTS` list. Targets (lower-order maximum, higher-order minimum, number of COs) are set in the sidebar. Level colours and verb lists are in `analyzer.py`.

## How levels are suggested

The earliest action phrase in a question sets its level. When two phrases start at the same place, the longer one wins, so "Explain the difference between" counts as Analyse. In pairs such as "State and prove", the higher verb counts. Mathematical uses such as "Evaluate the integral" and "Differentiate y with respect to x" are counted as Apply. These are suggestions to review, not a final classification: always check the table before using the figures.

## Project structure

```
app.py               Streamlit dashboard
analyzer.py          Parsing, classification, summaries, Excel report (no Streamlit)
tests/               pytest tests for analyzer.py
sample_paper.txt     Example paper
.streamlit/          Theme and upload settings
requirements.txt
```

Run the tests with `pip install pytest` and then `pytest`.

## Limitations

Scanned PDFs contain images rather than text, so paste the text of those papers instead. Unusual numbering schemes may need small edits before pasting. Questions with no recognised verb are marked "Not set" for you to classify.

## Licence

MIT. See `LICENSE`.
