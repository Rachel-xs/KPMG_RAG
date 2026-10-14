-- Run in DBeaver (sec_filings DB). Step 1: what is loaded and usable?
SELECT ticker, company_name, form, accession_number, filing_date, reporting_period_end, set_key, validation_status
FROM sec.filing_overview
WHERE ticker IN ('MSFT','AAPL','GOOGL','AMZN','NVDA','META')
ORDER BY ticker, filing_date DESC;

-- Step 2: export chunks for Experiment 1 -> File > Export Data > CSV (UTF-8, header row, "," delimiter)
-- Corpus = the MSFT 10-Q that Gold Set v0 uses + distractors (other MSFT filings, peer tech 10-Qs),
-- so that metadata filters actually have something to filter out.
SELECT chunk_id, accession_number, form, filing_date, reporting_period_end,
       cik, company_name, ticker, chunk_index, section_id, section_type, original_title,
       section_topic, chunking_version, extraction_version, source_url, sha256, offset_start, offset_end, text
FROM sec.chunk_catalog
WHERE ticker IN ('MSFT','AAPL','GOOGL','AMZN','NVDA','META')
  AND form IN ('10-Q','10-K')
  AND filing_date >= DATE '2025-01-01'
ORDER BY ticker, filing_date, chunk_index;

-- If Step 2 returns nothing for a filing (no preferred processing set yet), ask Michael to run
-- `sec-db prefer-validated`, or as a stopgap pull ONE chunking version per filing from chunk_citations:
-- SELECT DISTINCT ON (accession_number, chunk_index) chunk_id, accession_number, form, filing_date, reporting_period_end,
--        cik, company_name, ticker, chunk_index, section AS section_id, NULL AS section_type, NULL AS original_title,
--        NULL AS section_topic, chunking_version, extraction_version, source_url, sha256, offset_start, offset_end, text
-- FROM sec.chunk_citations WHERE ticker = 'MSFT'
-- ORDER BY accession_number, chunk_index, chunking_version DESC;
