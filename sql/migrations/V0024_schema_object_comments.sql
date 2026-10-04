-- =====================================================================
-- V0024 schema_object_comments
-- Complete table/column descriptions for project-owned schemas and describe
-- the database itself. PostgreSQL extension objects are intentionally left to
-- their owning extensions.
-- =====================================================================

DO $comments$
BEGIN
  EXECUTE format(
    'COMMENT ON DATABASE %I IS %L',
    current_database(),
    'Dividend equity research warehouse: SEC filings, security reference data, market/dividend history, fundamentals, model outputs, and ETL audit records.'
  );

  COMMENT ON TABLE audit.model_runs IS
    'One row per model evaluation run, including test metrics, baseline comparisons, and the readiness gate result';
  COMMENT ON TABLE audit.nightly_checks IS
    'Auditable result of each nightly data-health verification pass';
  COMMENT ON TABLE audit.nightly_runs IS
    'Execution summary for each scheduled or manual ETL pipeline run';
  COMMENT ON TABLE audit.source_lineage IS
    'Field-level provenance for security attributes, including source, provider, filing period, and confidence';
  COMMENT ON TABLE fundamentals.periodic_financials IS
    'SEC-reported financial statement facts by security, fiscal period, and filing vintage';
  COMMENT ON TABLE model.features IS
    'Derived model inputs and target label snapshot for one security and as-of date';
  COMMENT ON TABLE model.predictions IS
    'Model output for one security and as-of date, grouped by immutable run and version identifiers';
  COMMENT ON TABLE model.rankings IS
    'Security ordering and published composite score for one screening date';
  COMMENT ON TABLE model.scores IS
    'Component scores, composite score, and market-regime risk adjustments per security and date';
  COMMENT ON TABLE preferred.contract_terms IS
    'Series-specific contractual redemption terms extracted from governing SEC filings with supporting evidence';
  COMMENT ON TABLE preferred.dividend_snapshot IS
    'Per-security snapshot of preferred-stock classification and SEC dividend evidence';
  COMMENT ON TABLE preferred.security_terms IS
    'Preferred-security rate and liquidation terms with their source and review metadata';
  COMMENT ON TABLE raw.contract_documents IS
    'Stored text of SEC certificates and prospectus filings used to extract preferred contractual terms';
  COMMENT ON TABLE raw.dividend_data IS
    'Normalized dividend events per security and provider, including source dates and amounts';
  COMMENT ON TABLE raw.market_data IS
    'Daily security price and volume observations as supplied by market-data providers';
  COMMENT ON TABLE raw.sec_documents IS
    'Indexed SEC filing documents and extracted concept groups associated with listed securities';
  COMMENT ON TABLE raw.sec_instrument_titles IS
    'Latest SEC cover-page security title paired to its issuer CIK and trading ticker';
  COMMENT ON TABLE raw.ticker_profile IS
    'Provider profile and preferred-security terms captured for one listed security';
  COMMENT ON TABLE reference.exchanges IS
    'Canonical exchange codes and display names used by listed securities';
  COMMENT ON TABLE reference.issuers IS
    'Canonical SEC registrants keyed by issuer ID and CIK';
  COMMENT ON TABLE reference.securities IS
    'Canonical listed instruments keyed by security ID, with issuer, classification, and per-security attributes';

  COMMENT ON COLUMN audit.model_runs.balanced_accuracy IS
    'Mean recall across the positive and negative classes on the held-out test data, on a zero-to-one scale';
  COMMENT ON COLUMN audit.model_runs.positive_precision IS
    'Precision for the positive (sustainable-dividend) class on held-out test data';
  COMMENT ON COLUMN audit.model_runs.positive_recall IS
    'Recall for the positive (sustainable-dividend) class on held-out test data';
  COMMENT ON COLUMN audit.model_runs.negative_precision IS
    'Precision for the negative (unsustainable-dividend) class on held-out test data';
  COMMENT ON COLUMN audit.model_runs.negative_support IS
    'Count of negative (unsustainable-dividend) labels in the held-out test data';
  COMMENT ON COLUMN audit.model_runs.positive_support IS
    'Count of positive (sustainable-dividend) labels in the held-out test data';
  COMMENT ON COLUMN audit.model_runs.positive_rate IS
    'Share of positive labels in the evaluated population; also the always-positive baseline PR-AUC';
  COMMENT ON COLUMN audit.model_runs.n_train_rows IS
    'Number of labeled observations used to fit the model in this evaluation';
  COMMENT ON COLUMN audit.model_runs.n_test_rows IS
    'Number of labeled observations in the held-out test set';
  COMMENT ON COLUMN audit.model_runs.n_feature_rows IS
    'Number of feature-matrix observations available to the evaluation before label filtering';
  COMMENT ON COLUMN audit.model_runs.baseline_balanced_accuracy IS
    'Balanced accuracy of the always-predict-sustainable baseline on the same test labels';
  COMMENT ON COLUMN audit.model_runs.baseline_pr_auc IS
    'PR-AUC of the always-predict-sustainable baseline on the same test labels';
  COMMENT ON COLUMN audit.model_runs.gate_passed IS
    'True only when the model acceptance checks and required feature-completeness checks pass';
  COMMENT ON COLUMN audit.model_runs.feature_completeness IS
    'JSONB summary of required-feature coverage and completeness checks used by the readiness gate';

  COMMENT ON COLUMN audit.nightly_checks.check_id IS
    'Surrogate key for one verification record';
  COMMENT ON COLUMN audit.nightly_checks.verified_at IS
    'Timestamp when the verification was completed';
  COMMENT ON COLUMN audit.nightly_checks.run_date IS
    'ET calendar date whose nightly pipeline health was checked';
  COMMENT ON COLUMN audit.nightly_checks.verified_by IS
    'Actor or process that recorded the verification';
  COMMENT ON COLUMN audit.nightly_checks.status IS
    'Overall verification result: ok or attention';
  COMMENT ON COLUMN audit.nightly_checks.findings IS
    'Structured JSON results from the individual health checks';
  COMMENT ON COLUMN audit.nightly_checks.notes IS
    'Optional human-readable context for the verification result';

  COMMENT ON COLUMN audit.nightly_runs.run_id IS
    'Surrogate key for one ETL execution';
  COMMENT ON COLUMN audit.nightly_runs.run_date IS
    'ET calendar date assigned to this nightly execution';
  COMMENT ON COLUMN audit.nightly_runs.trigger IS
    'Execution origin, such as manual, airflow, or systemd';
  COMMENT ON COLUMN audit.nightly_runs.started_at IS
    'Timestamp when the pipeline execution began';
  COMMENT ON COLUMN audit.nightly_runs.finished_at IS
    'Timestamp when the pipeline execution ended; NULL while running';
  COMMENT ON COLUMN audit.nightly_runs.exit_code IS
    'Process exit code; zero indicates success';
  COMMENT ON COLUMN audit.nightly_runs.stages IS
    'JSON object mapping each ETL stage to its status';
  COMMENT ON COLUMN audit.nightly_runs.status IS
    'Overall execution state: running, success, or failed';
  COMMENT ON COLUMN audit.nightly_runs.created_at IS
    'Timestamp when this execution record was created';

  COMMENT ON COLUMN preferred.contract_terms.security_id IS
    'References reference.securities; one contractual-terms row per listed security';
  COMMENT ON COLUMN preferred.contract_terms.optional_redemption IS
    'Whether the governing terms grant the issuer an optional redemption right';
  COMMENT ON COLUMN preferred.contract_terms.source_document_id IS
    'References the stored SEC filing that supplied the extracted terms';
  COMMENT ON COLUMN preferred.contract_terms.confidence IS
    'Mean extraction confidence for the clauses found, on a zero-to-one scale; NULL when no clause was scored';
  COMMENT ON COLUMN preferred.contract_terms.updated_at IS
    'Timestamp when the extracted contract terms were last written';

  COMMENT ON COLUMN raw.contract_documents.document_id IS
    'Surrogate key for one stored filing document';
  COMMENT ON COLUMN raw.contract_documents.security_id IS
    'Listed security associated with the document; NULL when the filing is issuer-wide';
  COMMENT ON COLUMN raw.contract_documents.cik IS
    'SEC CIK of the registrant that filed the document';
  COMMENT ON COLUMN raw.contract_documents.form_type IS
    'SEC filing form, such as 8-K, 424B5, S-1, or S-3';
  COMMENT ON COLUMN raw.contract_documents.filing_date IS
    'Date the filing was submitted to SEC';
  COMMENT ON COLUMN raw.contract_documents.accession_no IS
    'SEC accession number identifying the filing submission';
  COMMENT ON COLUMN raw.contract_documents.primary_document IS
    'Primary filing or exhibit filename stored from the SEC archive';
  COMMENT ON COLUMN raw.contract_documents.exhibit_type IS
    'SEC exhibit designation when the document is a filing exhibit';
  COMMENT ON COLUMN raw.contract_documents.source_url IS
    'SEC archive URL from which the document was retrieved';
  COMMENT ON COLUMN raw.contract_documents.raw_text IS
    'Extracted filing text used by the preferred-contract clause parsers';
  COMMENT ON COLUMN raw.contract_documents.content_hash IS
    'SHA-256 hash of the stored document text for change detection';
  COMMENT ON COLUMN raw.contract_documents.retrieved_at IS
    'Timestamp when the document text was retrieved or stored';

  COMMENT ON COLUMN raw.sec_instrument_titles.cik IS
    'SEC Central Index Key of the issuer filing the cover page';
  COMMENT ON COLUMN raw.sec_instrument_titles.ticker IS
    'Trading symbol paired with the title on the SEC filing cover page';
  COMMENT ON COLUMN raw.sec_instrument_titles.title IS
    'Class-specific dei:SecurityTitle or dei:Security12bTitle value';
  COMMENT ON COLUMN raw.sec_instrument_titles.accession_no IS
    'SEC accession number of the filing instance that supplied the title';
  COMMENT ON COLUMN raw.sec_instrument_titles.filing_date IS
    'Date the title source filing was submitted';
  COMMENT ON COLUMN raw.sec_instrument_titles.form_type IS
    'SEC form type of the title source filing';
  COMMENT ON COLUMN raw.sec_instrument_titles.source_url IS
    'SEC archive URL of the XBRL filing instance';
  COMMENT ON COLUMN raw.sec_instrument_titles.document_hash IS
    'SHA-256 hash of the source filing XBRL instance';
  COMMENT ON COLUMN raw.sec_instrument_titles.content_hash IS
    'SHA-256 hash of the CIK, ticker, title, accession, and source-document hash';
  COMMENT ON COLUMN raw.sec_instrument_titles.retrieved_at IS
    'Timestamp when the filing instance was fetched and parsed';
END
$comments$;