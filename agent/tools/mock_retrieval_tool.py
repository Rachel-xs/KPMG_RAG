"""
Mock retrieval tool for Agent integration testing.

This file provides a temporary retrieve() function before the real
RAG retriever is available. It returns sample evidence passages from
a Microsoft 10-Q filing.

Important:
- This is a mock tool, not the production retriever.
- It uses simple keyword matching.
- It does not use an LLM, embeddings, BM25, or a vector database.
- Gold-set questions and reference answers are not included.
"""

import re
from math import sqrt
from time import perf_counter


SOURCE_URL = (
    "https://www.sec.gov/Archives/edgar/data/"
    "789019/000119312526191507/msft-20260331.htm"
)

DOCUMENT_ID = "sec:0000789019:0001193125-26-191507"


MOCK_CHUNKS = [
    {
        "text": (
            "For the three months ended March 31, 2026, Microsoft "
            "reported total revenue of USD 82,886 million and net "
            "income of USD 31,778 million. For the same three-month "
            "period in 2025, total revenue was USD 70,066 million "
            "and net income was USD 25,824 million."
        ),
        "ticker": "MSFT",
        "company_name": "Microsoft Corporation",
        "cik": "0000789019",
        "form_type": "10-Q",
        "accession_number": "0001193125-26-191507",
        "filing_date": "2026-04-29",
        "fiscal_period": "three_months_ended_2026-03-31",
        "section": "Part I Item 1 - Income Statements",
        "document_id": DOCUMENT_ID,
        "chunk_id": DOCUMENT_ID + ":chunk:0001",
        "source_url": SOURCE_URL,
    },
    {
        "text": (
            "Microsoft's reportable segments are Productivity and "
            "Business Processes, Intelligent Cloud, and More Personal "
            "Computing. LinkedIn is included in Productivity and "
            "Business Processes. Azure and other cloud services are "
            "included in Intelligent Cloud. Xbox is included in More "
            "Personal Computing."
        ),
        "ticker": "MSFT",
        "company_name": "Microsoft Corporation",
        "cik": "0000789019",
        "form_type": "10-Q",
        "accession_number": "0001193125-26-191507",
        "filing_date": "2026-04-29",
        "fiscal_period": "three_months_ended_2026-03-31",
        "section": "Note 16 - Segment Information",
        "document_id": DOCUMENT_ID,
        "chunk_id": DOCUMENT_ID + ":chunk:0002",
        "source_url": SOURCE_URL,
    },
    {
        "text": (
            "Net cash from operations was USD 127,494 million for "
            "the nine months ended March 31, 2026. Net cash from "
            "operations was USD 93,515 million for the corresponding "
            "nine-month period in 2025."
        ),
        "ticker": "MSFT",
        "company_name": "Microsoft Corporation",
        "cik": "0000789019",
        "form_type": "10-Q",
        "accession_number": "0001193125-26-191507",
        "filing_date": "2026-04-29",
        "fiscal_period": "nine_months_ended_2026-03-31",
        "section": "Part I Item 1 - Cash Flow Statements",
        "document_id": DOCUMENT_ID,
        "chunk_id": DOCUMENT_ID + ":chunk:0003",
        "source_url": SOURCE_URL,
    },
    {
        "text": (
            "Microsoft Cloud revenue includes Microsoft 365 "
            "Commercial cloud, Azure and other cloud services, "
            "the commercial portion of LinkedIn, and Dynamics 365. "
            "These amounts are already included in Microsoft's "
            "product and service revenue categories."
        ),
        "ticker": "MSFT",
        "company_name": "Microsoft Corporation",
        "cik": "0000789019",
        "form_type": "10-Q",
        "accession_number": "0001193125-26-191507",
        "filing_date": "2026-04-29",
        "fiscal_period": "three_months_ended_2026-03-31",
        "section": "Note 16 - Microsoft Cloud Revenue",
        "document_id": DOCUMENT_ID,
        "chunk_id": DOCUMENT_ID + ":chunk:0004",
        "source_url": SOURCE_URL,
    },
    {
        "text": (
            "Revenue allocated to remaining performance obligations "
            "includes unearned revenue and amounts expected to be "
            "invoiced and recognized as revenue in future periods. "
            "Remaining performance obligations were USD 633 billion "
            "as of March 31, 2026."
        ),
        "ticker": "MSFT",
        "company_name": "Microsoft Corporation",
        "cik": "0000789019",
        "form_type": "10-Q",
        "accession_number": "0001193125-26-191507",
        "filing_date": "2026-04-29",
        "fiscal_period": "as_of_2026-03-31",
        "section": "Note 11 - Remaining Performance Obligations",
        "document_id": DOCUMENT_ID,
        "chunk_id": DOCUMENT_ID + ":chunk:0005",
        "source_url": SOURCE_URL,
    },
]


def tokenize(text):
    """
    Convert text into a set of lowercase words.

    Example:
    'Microsoft Revenue' becomes {'microsoft', 'revenue'}.
    """

    return set(re.findall(r"[a-z0-9]+", text.lower()))


def calculate_mock_score(query, passage):
    """
    Calculate a simple keyword-overlap score.

    This score is only for mock testing. It is not a production
    retrieval score.
    """

    query_words = tokenize(query)
    passage_words = tokenize(passage)

    if not query_words or not passage_words:
        return 0.0

    shared_words = query_words.intersection(passage_words)

    score = len(shared_words) / sqrt(
        len(query_words) * len(passage_words)
    )

    return round(score, 4)


def retrieve(
    query,
    ticker=None,
    cik=None,
    form_type=None,
    fiscal_period=None,
    section=None,
    top_k=5,
):
    """
    Return mock financial-document passages for Agent testing.

    Parameters
    ----------
    query:
        The user's question.

    ticker:
        Optional stock ticker filter, such as "MSFT".

    cik:
        Optional 10-digit SEC CIK filter, such as "0000789019".

    form_type:
        Optional filing-type filter, such as "10-Q".

    fiscal_period:
        Optional normalized period filter, such as
        "three_months_ended_2026-03-31".

    section:
        Optional section-name filter.

    top_k:
        Maximum number of passages to return.

    Returns
    -------
    A list of result dictionaries ordered by mock relevance score.
    """

    start_time = perf_counter()

    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")

    if not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be a positive integer")

    candidates = MOCK_CHUNKS.copy()

    if ticker is not None:
        normalized_ticker = str(ticker).upper()

        candidates = [
            item
            for item in candidates
            if item["ticker"] == normalized_ticker
        ]

    if cik is not None:
        normalized_cik = str(cik).zfill(10)

        candidates = [
            item
            for item in candidates
            if item["cik"] == normalized_cik
        ]

    if form_type is not None:
        normalized_form_type = str(form_type).upper()

        candidates = [
            item
            for item in candidates
            if item["form_type"] == normalized_form_type
        ]

    if fiscal_period is not None:
        candidates = [
            item
            for item in candidates
            if item["fiscal_period"] == fiscal_period
        ]

    if section is not None:
        normalized_section = str(section).lower()

        candidates = [
            item
            for item in candidates
            if normalized_section in item["section"].lower()
        ]

    scored_candidates = []

    for item in candidates:
        score = calculate_mock_score(query, item["text"])
        scored_candidates.append((score, item))

    scored_candidates.sort(
        key=lambda result: result[0],
        reverse=True,
    )

    selected_candidates = scored_candidates[:top_k]

    latency_ms = round(
        (perf_counter() - start_time) * 1000,
        2,
    )

    results = []

    for rank, (score, item) in enumerate(
        selected_candidates,
        start=1,
    ):
        result = item.copy()
        result["rank"] = rank
        result["score"] = score
        result["latency_ms"] = latency_ms
        result["retrieval_method"] = "mock_keyword_overlap"
        results.append(result)

    return results


if __name__ == "__main__":
    test_results = retrieve(
        query="What was Microsoft's total revenue?",
        ticker="MSFT",
        form_type="10-Q",
        fiscal_period="three_months_ended_2026-03-31",
        top_k=3,
    )

    print("Mock retrieval results")
    print("-" * 60)

    for result in test_results:
        print("Rank:", result["rank"])
        print("Score:", result["score"])
        print("Chunk ID:", result["chunk_id"])
        print("Section:", result["section"])
        print("Text:", result["text"])
        print()
