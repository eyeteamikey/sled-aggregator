# HAR evidence intake

Place newly recorded HAR files in this directory for local processing. Every file in this
directory except this README is ignored by Git. HARs are temporary source evidence: never force-add
them, archive them into Git, or include them in a pull request.

## Workflow

1. Start from an up-to-date feature branch based on `origin/master`. Do not work directly on
   `master`.
2. Copy the new HAR into `sled-har-evidence/` and compute its SHA-256 hash.
3. Import it into the ignored `.sled-validation/` workspace:

   ```powershell
   $env:PYTHONPATH = "src"
   python -m sled_aggregator.validation import-har `
     --source <source-id> `
     --input .\sled-har-evidence\<capture>.har `
     --workspace .\.sled-validation
   ```

4. Run the exact scan, analyze, report, approval, fixture-extraction, and dry-run ingestion commands
   printed by the importer. Review every scanner finding. Public procurement contacts and publicly
   disclosed vendor/bidder information are domain data; authentication, session, browser, and
   telemetry values are not.
5. Run ingestion only after explicit review and a clean dry run:

   ```powershell
   python -m sled_aggregator.validation ingest `
     .\.sled-validation\evidence\<capture>-approved.json `
     --dry-run --confirm

   python -m sled_aggregator.validation ingest `
     .\.sled-validation\evidence\<capture>-approved.json `
     --confirm
   ```

6. Copy only reviewed minimal fixtures into `tests/fixtures/`. Implement evidence-backed connector
   corrections and tests. Never copy the complete HAR, cookies, session tokens, ViewState, CSRF,
   telemetry, or binary attachment bodies into tracked files.
7. Run the repository validation suite and sensitive-data scan. Confirm `git status` contains only
   intended tracked code, tests, fixtures, documentation, and coverage changes. Confirm no `.har`
   or HAR archive is staged.
8. Commit, push the feature branch, and open a draft pull request targeting `master`. Merge only
   after review and passing checks.
9. After the pull request has merged and the ingested/derived functionality is confirmed on
   `master`, delete only the processed HAR from this directory. Keep this directory and README for
   future captures. The ignored `.sled-validation/` reports may be retained locally when useful.

Deleting a HAR is the final step, never a prerequisite for review. If ingestion or validation is
incomplete, preserve the HAR here and do not claim the evidence has been incorporated.
