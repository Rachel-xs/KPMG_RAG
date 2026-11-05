import csv
import json
import subprocess
import sys
from pathlib import Path


def test_data_snapshot_export_aliases_are_supported(tmp_path):
    csv_path = tmp_path / "snapshot.csv"
    out_path = tmp_path / "chunks.jsonl"
    row = {
        "chunk_id": "chunk-1",
        "accession_number": "0001193125-26-191507",
        "ticker": "MSFT",
        "cik": "789019",
        "form": "10-Q",
        "filing_date": "2026-04-29",
        "reporting_period_end": "2026-03-31",
        "section": "Item 2",
        "section_id": "section-1",
        "section_key": "Part I Item 2",
        "section_title": "Management's Discussion and Analysis",
        "text": "Revenue increased due to Azure growth.",
        "source_url": "https://www.sec.gov/example",
        "chunk_index": "0",
        "offset_start": "0",
        "offset_end": "39",
        "filing_id": "filing-1",
        "report_id": "report-1",
        "processing_set_id": "processing-1",
        "set_key": "filing-import-v1",
        "extraction_version": "report-v1",
        "chunking_version": "paragraph-v1",
    }
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)

    subprocess.run(
        [sys.executable, "scripts/rds_to_chunks.py", str(csv_path), str(out_path), "--fye", "MSFT=0630"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
    )
    chunk = json.loads(out_path.read_text())

    assert chunk["company"] == "MSFT"
    assert chunk["section"] == "Part I Item 2"
    assert chunk["section_title"] == "Management's Discussion and Analysis"
    assert chunk["processing_set_id"] == "processing-1"
    assert chunk["processing_set"] == "filing-import-v1"
    assert chunk["fiscal_year"] == 2026
    assert chunk["fiscal_period"] == "Q3"
