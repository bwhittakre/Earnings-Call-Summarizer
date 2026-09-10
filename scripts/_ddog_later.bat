@echo off
cd /d "%~dp0\.."
python -u "Structured Narrative\run_universe_batch.py" --tickers DDOG --stages delta surprise novelty --quarters FY2019-Q4 FY2020-Q1 FY2020-Q2 FY2020-Q3 FY2020-Q4 FY2021-Q3 FY2021-Q4 FY2022-Q1 FY2022-Q2 FY2022-Q3 FY2022-Q4 FY2023-Q1 FY2023-Q2 FY2023-Q3 FY2023-Q4 FY2024-Q1 FY2024-Q2 FY2024-Q3 FY2024-Q4 FY2025-Q1 FY2025-Q2 >> "data\ddog_later.log" 2>> "data\ddog_later.err"
