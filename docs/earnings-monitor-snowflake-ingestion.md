# Snowflake ingestion strategy

## Decision

Keep the existing direct Snowflake query in the latency-sensitive pre-call path
until measurement proves that AWS Glue is faster. Use Glue as the preferred
incremental synchronization path for the consolidated analytical lake.

This separates two workloads:

- **Pre-call decision run:** query only the expected company-quarter directly,
  validate the source timestamp, append it to the cached historical spine, and
  generate the quant email.
- **Historical/dashboard synchronization:** use an AWS Glue `SNOWFLAKE`
  connection and custom-query pushdown to copy incremental rows into S3
  Tables/Iceberg or Parquet for Athena and Streamlit.

Glue must not silently become a required dependency for post-call scoring. If a
Glue job is late, the monitor can still use a validated direct Snowflake
snapshot.

## Required AWS validation

Before creating a job:

1. Authenticate the AWS Data Analytics MCP plug-in or AWS CLI and confirm the
   intended account and region.
2. Confirm an AWS Glue connection of type `SNOWFLAKE` exists and can be tested.
3. Identify the exact source database, schema, views/tables, critical columns,
   and a reliable row-level watermark. `LAST_ALTERED` is not a row watermark.
4. Confirm the target convention already used by the company: S3 Tables,
   standard Iceberg, or raw Parquet. Prefer the existing convention.
5. Store Snowflake credentials in Secrets Manager; never place values in CDK
   context, Compose files, logs, or source.

## Incremental query shape

The Glue job should use a custom Snowflake query, not pull full source tables
and filter in Spark. The production query must reuse the current
point-in-time/fiscal-period rules and filter by:

- allow-listed ticker/company identifier;
- expected fiscal period or release window;
- a reliable `updated_at`/`modified_at` watermark when available.

The watermark and source as-of timestamp belong in operational state and every
published quant snapshot.

## Benchmark gate

Replay the same released quarter through both paths and capture:

- time until the expected row is visible;
- extraction duration and total pre-call completion time;
- Snowflake warehouse usage and AWS Glue cost;
- row counts, null checks on critical fields, and 3-5 sample-row comparisons;
- exact agreement of the resulting quant snapshot and z-scores.

Adopt Glue in the critical path only if it meets the latency target and produces
the same point-in-time result. Otherwise retain it as the analytical-lake sync.

## References

- AWS Glue has built-in Snowflake support in Glue 4.0 and later.
- The Glue Snowflake connector supports custom SQL and query pushdown.
- Incremental ingestion should use a row-level watermark or Snowflake Streams;
  table `LAST_ALTERED` is suitable only for table-level change detection.
