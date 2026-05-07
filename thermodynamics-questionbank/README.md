# Thermodynamics Question Bank

This workspace turns the saved PaperPlainz thermodynamics page into a reusable local question bank.

## Layout

- `data/questions.json`: main structured bank
- `data/index.json`: summary counts and lookup info
- `data/question_index.md`: readable inventory of all questions
- `images/`: copied image assets referenced by the questions and answers
- `scripts/extract_level10.py`: extraction script
- `scripts/build_test.py`: PDF builder for later custom exports
- `exports/`: reserved for generated PDFs and manifests

## Design

The source of truth is `data/questions.json`, not PDF or LaTeX.

Each item gets a stable ID:

- `P1-Q..` for Paper 1 multiple-choice questions
- `P2-Q..` for Paper 2 structured questions

Paper 2 answers are stored by subpart when available.

## Rebuild

Run:

```powershell
python .\scripts\extract_level10.py
```

This refreshes the JSON files and recopies referenced images.

## Later PDF Builds

When you are ready to generate custom PDFs, use:

```powershell
python .\scripts\build_test.py --name thermo_sample --title "Thermodynamics Sample Test" --ids P1-Q01 P1-Q05 P2-Q01
```
