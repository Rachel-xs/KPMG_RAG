-- Round 1 corpus: the 21 frozen filings (10 companies), from Data's freeze list round1_filings.csv.
-- Run in DBeaver (sec_filings DB) -> File > Export Data > CSV (UTF-8, header row, "," delimiter)
-- Save as  exports/round1_21.csv  then run  bash scripts/build_round1.sh exports/round1_21.csv
--
-- 19 filings are legacy processing sets (sec.filing_processing_sets); NKE 10-Q and NTAP 10-Q are
-- source sets (sec.source_processing_sets, primary document only). Both are selected by processing_set_id,
-- so the export is pinned to the frozen versions even if Data later changes the preferred set.

-- Step 0 (sanity): expect 21 rows, one per filing
-- SELECT ticker, accession_number, form, count(*) FROM (<the query below>) q GROUP BY 1,2,3 ORDER BY 1,3;

WITH sel AS (
  SELECT p.id AS processing_set_id, p.set_key, p.report_id, p.chunking_version
  FROM sec.filing_processing_sets p
  WHERE p.id IN (
    '5e2bbc3a-3dcb-4098-b8a7-e9e8ea7922e4',
    '8ba87c04-3452-4aa8-baee-006e9f05c868',
    '2cad9283-dc98-49fb-968d-54f1767bfec5',
    '52d64e69-7083-4f76-8f8c-8e5dc91f6fbc',
    'dd2aa6d6-8dde-4850-87b4-3c82aa8993b1',
    'd50d66d9-96a6-4279-b501-4374c0095ba2',
    '530f3c45-dfa7-43f5-a4e3-6a53adef370f',
    'f9308d50-f40e-4728-b2d2-3a697433258a',
    '3716f46d-b588-4f15-86e0-db8def5871ee',
    'b141f956-436d-42ce-8f5a-80e5f3196ef4',
    '7f7614ef-8e07-4d49-ba49-404730ef85ff',
    '34b7d537-34f4-43e0-98ef-6a83d34bdc09',
    '2e5c71a8-46b7-422d-bb64-6577ba4bc0c8',
    'b2141339-4c5e-4735-ad95-02544923e19f',
    '7c7d931b-5f2d-40c3-a257-c5bdda25acde',
    '30b73b43-9aeb-488c-a909-bfa8c8b23c35',
    '5da99929-e34d-40cd-97b0-10608923b675',
    'a575330a-da5b-455a-9eba-5bbab9e8091c',
    'aa4b57de-7cac-43ea-aa89-22402bef503a')
  UNION ALL
  SELECT rc.processing_set_id, rc.set_key, rc.report_id, rc.chunking_version
  FROM sec.source_report_catalog rc
  WHERE rc.is_primary AND rc.processing_set_id IN (
    '53aa8e89-d013-4040-ad3a-4892206b66ec',
    '3a047a1c-f436-4623-aead-3a104cc1099b')
)
SELECT cc.chunk_id, cc.accession_number, cc.form, cc.filing_date, cc.reporting_period_end,
       cc.cik, cc.company_name, cc.ticker, cc.chunk_index, ch.section_id, rs.section_type, rs.original_title,
       cc.chunking_version, cc.extraction_version, cc.source_url, cc.sha256, cc.offset_start, cc.offset_end,
       sel.processing_set_id, sel.set_key, cc.filing_id, cc.report_id, cc.text
FROM sel
JOIN sec.chunk_citations cc ON cc.report_id = sel.report_id AND cc.chunking_version = sel.chunking_version
JOIN sec.chunks ch ON ch.id = cc.chunk_id
LEFT JOIN sec.report_sections rs ON rs.id = ch.section_id
ORDER BY cc.ticker, cc.filing_date, cc.chunk_index;
