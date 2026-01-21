# Base proposal symbol sampling (amendments with no inferred base)

Command:

```bash
PYTHONPATH=src python - <<'PY'
from pathlib import Path
from mandate_pipeline.static_generator import classify_doc_type, infer_base_proposal_symbol, filename_to_symbol
from mandate_pipeline.extractor import extract_text

pdfs = sorted(Path('data/pdfs').glob('*.pdf'))
results = []
for pdf in pdfs:
    symbol = filename_to_symbol(pdf.stem)
    text = extract_text(pdf)
    doc_type = classify_doc_type(symbol, text)
    base = infer_base_proposal_symbol(symbol, doc_type, text)
    if doc_type == 'amendment' and base is None:
        results.append((symbol, doc_type, base))

for symbol, doc_type, base in results[:10]:
    print(f"{symbol}\t{doc_type}\t{base}")

print(f"Total amendments with no base found: {len(results)}")
PY
```

Sample output (first 10):

```text
A/C.2/80/L.62	amendment	None
A/C.2/80/L.63	amendment	None
A/C.3/80/L.56	amendment	None
A/C.3/80/L.57	amendment	None
A/C.3/80/L.58	amendment	None
A/C.3/80/L.61	amendment	None
A/C.3/80/L.62	amendment	None
A/C.3/80/L.63	amendment	None
A/C.3/80/L.64	amendment	None
A/C.3/80/L.65	amendment	None
Total amendments with no base found: 11
```
