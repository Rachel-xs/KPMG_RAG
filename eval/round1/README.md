Pinned copies from https://github.com/thomassong0604-oss/kpmg-eval @ 41823f9 (Week 8, 11/9):
- benchmark_v2.jsonl      Week 8/data/benchmark_v2.jsonl (Gold Set v2, 155 questions, sha256_16 ed4b42db6fc25ee5)
- rag_anchor_fixes.csv    Week 8/results/rag_anchor_fixes.csv
Run: python scripts/run_round1_eval.py --index data/round1/index_C1
- benchmark_v2_1.jsonl    Week 8/data/benchmark_v2_1.jsonl @ e224deb (Gold Set v2.1, sha256_16 1e104c626c6c9833).
                          Same 155 questions and answers as v2; Eval re-anchored 25 questions (22 automatic "region"
                          anchors from Gold v0 + 3 figure anchors), after RAG's 11/9 run flagged 4 of them.
Run on v2.1: python scripts/run_round1_eval.py --index data/round1/index_C1 --gold eval/round1/benchmark_v2_1.jsonl --out eval/results/round1_v2_1
