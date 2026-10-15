import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from src.crispdm.db import engine  # noqa: E402

sql = (PROJECT_ROOT / "sql" / "schema.sql").read_text()


def _split_statements(sql_text):
    """Split SQL on statement terminators, ignoring semicolons inside quotes
    and ``--`` / ``/* */`` comments.

    Several COMMENT values carry an embedded ``;`` (e.g. ``'dei:TradingSymbol;
    listed ticker symbol, ...'``), and schema comments may too, so a naive
    ``split(";")`` would feed the server an unterminated string or a bare
    comment fragment.
    """
    statements = []
    current = []
    in_string = False
    dollar_quote = None
    index = 0
    while index < len(sql_text):
        char = sql_text[index]
        if dollar_quote is not None:
            if sql_text.startswith(dollar_quote, index):
                current.append(dollar_quote)
                index += len(dollar_quote) - 1
                dollar_quote = None
            else:
                current.append(char)
        elif char == "'":
            if in_string and index + 1 < len(sql_text) and sql_text[index + 1] == "'":
                current.append("''")
                index += 1
            else:
                in_string = not in_string
                current.append(char)
        elif not in_string and char == "$":
            match = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", sql_text[index:])
            if match:
                dollar_quote = match.group(0)
                current.append(dollar_quote)
                index += len(dollar_quote) - 1
            else:
                current.append(char)
        elif not in_string and sql_text.startswith("--", index):
            newline = sql_text.find("\n", index)
            if newline == -1:
                break
            if current:
                current.append(" ")
            index = newline
        elif not in_string and sql_text.startswith("/*", index):
            end = sql_text.find("*/", index + 2)
            if end == -1:
                break
            current.append(" ")
            index = end + 2
        elif char == ";" and not in_string:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)
        index += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def ensure_database_exists():
    target_url = engine.url
    database_name = target_url.database
    if not database_name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", database_name):
        raise SystemExit("DATABASE_URL must contain a simple PostgreSQL database name")

    admin_url = target_url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                {"database_name": database_name},
            ).scalar()
            if not exists:
                connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    finally:
        admin_engine.dispose()


# CREATE TABLE IF NOT EXISTS does not evolve an already initialized database.
# Keep this small compatibility migration here until a versioned migration
# system is introduced.
migrations = [
    """
    ALTER TABLE raw.sec_documents
        ADD COLUMN IF NOT EXISTS concept_groups JSONB NOT NULL DEFAULT '{}'::jsonb;
    CREATE UNIQUE INDEX IF NOT EXISTS ux_sec_documents_security
        ON raw.sec_documents(security_id) WHERE security_id IS NOT NULL;
    ALTER TABLE IF EXISTS raw.sec_documents DROP CONSTRAINT IF EXISTS sec_documents_content_hash_key;
    CREATE INDEX IF NOT EXISTS ix_sec_documents_content_hash
        ON raw.sec_documents(content_hash);
    CREATE INDEX IF NOT EXISTS ix_sec_documents_cik
        ON raw.sec_documents(cik);
    CREATE INDEX IF NOT EXISTS ix_securities_dividend_active
        ON reference.securities (ticker)
        WHERE dividend = TRUE AND active = TRUE;
    """,
    """
    CREATE TABLE IF NOT EXISTS raw.ticker_profile (
        security_id UUID PRIMARY KEY REFERENCES reference.securities(security_id),
        ticker VARCHAR(32) NOT NULL,
        provider VARCHAR(64) NOT NULL DEFAULT 'OPENBB_YFINANCE',
        sector TEXT,
        industry TEXT,
        security_type TEXT,
        coupon_type VARCHAR(32),
        coupon_rate NUMERIC,
        fixed_period_end DATE,
        floating_spread NUMERIC,
        tax_status VARCHAR(32),
        call_date DATE,
        liquidation_preference NUMERIC,
        raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    ALTER TABLE raw.ticker_profile
        ADD COLUMN IF NOT EXISTS coupon_type VARCHAR(32),
        ADD COLUMN IF NOT EXISTS fixed_period_end DATE,
        ADD COLUMN IF NOT EXISTS floating_spread NUMERIC,
        ADD COLUMN IF NOT EXISTS tax_status VARCHAR(32),
        DROP COLUMN IF EXISTS company_name,
        DROP COLUMN IF EXISTS dividend_coupon,
        DROP COLUMN IF EXISTS annual_dividend,
        DROP COLUMN IF EXISTS dividend_yield,
        DROP COLUMN IF EXISTS current_price,
        DROP COLUMN IF EXISTS ex_dividend_date
    """,
    """
        CREATE TABLE IF NOT EXISTS raw.sec_submissions (
            security_id UUID PRIMARY KEY REFERENCES reference.securities(security_id),
            cik VARCHAR(20) NOT NULL,
            company_name TEXT,
            raw_payload JSONB NOT NULL,
            content_hash VARCHAR(64) NOT NULL,
            provider VARCHAR(64) NOT NULL DEFAULT 'SEC_SUBMISSIONS',
            retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    "ALTER TABLE raw.companyfacts DROP COLUMN IF EXISTS concept_count",
    "ALTER TABLE raw.companyfacts DROP COLUMN IF EXISTS dividend_concept_count",
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'raw'
              AND table_name = 'companyfacts'
              AND column_name = 'facts'
        ) AND NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'raw'
              AND table_name = 'companyfacts'
              AND column_name = 'raw_payload'
        ) THEN
            ALTER TABLE raw.companyfacts RENAME COLUMN facts TO raw_payload;
        END IF;
    END $$;
    """,
    "ALTER TABLE reference.securities ADD COLUMN IF NOT EXISTS cik VARCHAR(10)",
    """
        ALTER TABLE reference.securities
                ADD COLUMN IF NOT EXISTS coupon_rate NUMERIC,
                ADD COLUMN IF NOT EXISTS liquidation_preference NUMERIC,
                ADD COLUMN IF NOT EXISTS call_date DATE;

        UPDATE reference.securities s
        SET coupon_rate = COALESCE(
                        s.coupon_rate,
                tp.coupon_rate
                ),
                liquidation_preference = COALESCE(
                        s.liquidation_preference,
                tp.liquidation_preference
                ),
                call_date = COALESCE(s.call_date, tp.call_date),
                updated_at = now()
        FROM raw.ticker_profile tp
        WHERE tp.security_id = s.security_id
            AND tp.provider IS DISTINCT FROM 'SEC_XBRL'
            AND (
                    (s.coupon_rate IS NULL AND (
                            tp.coupon_rate IS NOT NULL
                    ))
                    OR (s.liquidation_preference IS NULL AND (
                            tp.liquidation_preference IS NOT NULL
                    ))
                    OR (s.call_date IS NULL AND tp.call_date IS NOT NULL)
            );
        """,
    """
    -- V0004 issuer_name_consolidation: the issuer-name attribute is
    -- consolidated on reference.issuers (issuer_name, renamed from
    -- legal_name) and the denormalized reference.securities.issuer_name copy
    -- is dropped. Idempotent and guarded so fresh installs (schema.sql already
    -- canonical) and pre-V0004 databases both converge.
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'reference' AND table_name = 'issuers'
              AND column_name = 'legal_name'
        ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'reference' AND table_name = 'issuers'
              AND column_name = 'issuer_name'
        ) THEN
            ALTER TABLE reference.issuers RENAME COLUMN legal_name TO issuer_name;
        END IF;

        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'reference' AND table_name = 'securities'
              AND column_name = 'issuer_name'
        ) THEN
            ALTER TABLE reference.securities DROP COLUMN issuer_name;
        END IF;
    END $$;
    """,
    """
        COMMENT ON COLUMN reference.securities.ticker IS
            'dei:TradingSymbol; listed ticker symbol, for example ACR, ACR-PC, or ACR-PD';
        COMMENT ON COLUMN reference.securities.cik IS
            'SEC Central Index Key, normalized to a zero-padded 10-character value';
        COMMENT ON COLUMN reference.securities.security_id IS
            'Stable identifier for one listed security series';
        COMMENT ON COLUMN reference.securities.issuer_id IS
            'Foreign key to reference.issuers';
        COMMENT ON COLUMN reference.securities.security_name IS
            'Per-class dei:SecurityTitle / dei:Security12bTitle exactly as reported on '
            'the Form 8-K or annual-report cover for THIS registered class, e.g. '
            '"7.875% Series D Cumulative Redeemable Preferred Stock" for ACR-PD; sourced '
            'from raw.sec_instrument_titles (one cover title per ticker), falling back '
            'to the bound dei cover title from the companyfacts payload';
        COMMENT ON COLUMN reference.securities.security_type IS
            'Normalized security classification, such as common_stock or preferred stock';
        COMMENT ON COLUMN reference.securities.cusip IS
            'us-gaap:CUSIP or us-gaap:DebtInstrumentCusip; security CUSIP';
        COMMENT ON COLUMN reference.securities.isin IS
            'us-gaap:ISIN or srt:ISIN; security ISIN';
        COMMENT ON COLUMN reference.securities.exchange_id IS
            'Foreign key to reference.exchanges';
        COMMENT ON COLUMN reference.securities.coupon_rate IS
            'Annual coupon or stated dividend rate, expressed as a percentage';
        COMMENT ON COLUMN reference.securities.dividend IS
            'Whether SEC evidence indicates that the security pays a dividend';
        COMMENT ON COLUMN reference.securities.currency IS
            'Currency code for security amounts, normally USD';
        COMMENT ON COLUMN reference.securities.liquidation_preference IS
            'Preferred security liquidation preference per share';
        COMMENT ON COLUMN reference.securities.call_date IS
            'Date on which the issuer may call or redeem the security';
        COMMENT ON COLUMN reference.securities.created_at IS
            'Timestamp when the canonical security row was created';
        COMMENT ON COLUMN reference.securities.updated_at IS
            'Timestamp when the canonical security row was last updated';
        COMMENT ON COLUMN reference.securities.sec_data_status IS
            'Availability status of SEC data for this security';
        """,
    """
    DO $$
    BEGIN
        ALTER TABLE reference.securities
            ADD COLUMN IF NOT EXISTS dividend BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE reference.securities
            ADD COLUMN IF NOT EXISTS sec_data_status VARCHAR(32) NOT NULL DEFAULT 'unavailable';
        ALTER TABLE reference.securities DROP COLUMN IF EXISTS sec_security_facts;
        ALTER TABLE reference.securities DROP COLUMN IF EXISTS sec_dividend_facts;
    END $$;
    """,
    "ALTER TABLE reference.securities ALTER COLUMN security_type SET DEFAULT 'other'",
    # Historically the primary key was (cik, ticker) and had to be moved onto
    # security_id. On a database built from schema.sql the primary key is
    # already security_id, and dropping it there is not merely a no-op: 17
    # foreign keys reference reference.securities(security_id), so PostgreSQL
    # refuses the DROP with DependentObjectsStillExist and initialization fails.
    # Only swap the constraint when it is genuinely not what we want.
    """
    DO $$
    DECLARE
        pk_name TEXT;
        pk_cols TEXT;
    BEGIN
        SELECT con.conname,
               (SELECT string_agg(att.attname, ',' ORDER BY k.ord)
                  FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                  JOIN pg_attribute att
                    ON att.attrelid = con.conrelid AND att.attnum = k.attnum)
          INTO pk_name, pk_cols
          FROM pg_constraint con
         WHERE con.conrelid = 'reference.securities'::regclass AND con.contype = 'p';

        IF pk_name IS DISTINCT FROM 'securities_pkey' OR pk_cols IS DISTINCT FROM 'security_id' THEN
            ALTER TABLE reference.securities DROP CONSTRAINT IF EXISTS securities_pkey;
            ALTER TABLE reference.securities
                ADD CONSTRAINT securities_pkey PRIMARY KEY (security_id);
        END IF;
    END $$;
    """,
    "DROP INDEX IF EXISTS reference.ux_security_ticker_active",
    """
    DELETE FROM reference.securities duplicate
    USING reference.securities keeper
    WHERE duplicate.ctid < keeper.ctid
      AND duplicate.cik = keeper.cik
      AND duplicate.ticker = keeper.ticker
      AND duplicate.security_type = keeper.security_type
      AND duplicate.dividend = keeper.dividend
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_security_cik_ticker_type_dividend ON reference.securities(cik, ticker, security_type, dividend)",
    "ALTER TABLE raw.company_ticker DROP CONSTRAINT IF EXISTS company_ticker_cik_key",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_company_ticker_ticker_cik ON raw.company_ticker(ticker, cik)",
    "ALTER TABLE reference.securities DROP CONSTRAINT IF EXISTS securities_cik_fkey",
    # Add only when absent: drop-and-re-add resets a validated FK to NOT VALID (see V0046).
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conrelid = 'reference.securities'::regclass
               AND conname = 'fk_securities_company_ticker'
        ) THEN
            ALTER TABLE reference.securities
            ADD CONSTRAINT fk_securities_company_ticker
            FOREIGN KEY (ticker, cik)
            REFERENCES raw.company_ticker(ticker, cik)
            NOT VALID;
        END IF;
    END $$;
    """,
    """
    UPDATE reference.securities s
    SET cik = LPAD(i.cik, 10, '0')
    FROM reference.issuers i
    WHERE s.issuer_id = i.issuer_id
      AND s.cik IS NULL
      AND i.cik IS NOT NULL
    """,
    """
    UPDATE reference.securities s
    SET cik = t.cik
    FROM raw.company_ticker t
    WHERE s.ticker = t.ticker
        AND s.cik IS NULL
    """,
    """
    CREATE TABLE IF NOT EXISTS raw.company_taxonomy (
        security_id UUID PRIMARY KEY REFERENCES reference.securities(security_id),
        cik VARCHAR(20) NOT NULL,
        company_name TEXT,
        taxonomies JSONB NOT NULL DEFAULT '{}'::jsonb,
        concept_groups JSONB NOT NULL DEFAULT '{}'::jsonb,
        raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        content_hash VARCHAR(64) NOT NULL,
        provider VARCHAR(64) NOT NULL DEFAULT 'SEC_XBRL',
        retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS preferred.dividend_snapshot (
        security_id UUID PRIMARY KEY REFERENCES reference.securities(security_id),
        ticker VARCHAR(32) NOT NULL,
        cik VARCHAR(20),
        preferred_flag BOOLEAN NOT NULL DEFAULT FALSE,
        pays_dividend BOOLEAN,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        dividend_evidence_tag TEXT,
        latest_dividend_period_end DATE,
        latest_dividend_filed DATE,
        latest_dividend_form VARCHAR(32),
        retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    -- ---------------------------------------------------------------
    -- De-duplicate issuer-level payloads: raw.companyfacts,
    -- raw.sec_submissions and raw.company_taxonomy used to be keyed by
    -- reference.securities.security_id, which copied the SAME issuer JSON
    -- once per listed security (e.g. BAC/PSA published 17+ copies). All
    -- copies for a CIK share the same content hash, so any survivor is
    -- valid. Each table keeps the smallest ctid per CIK, drops the old
    -- security_id key and foreign key, and re-keys on cik.
    -- ---------------------------------------------------------------
    DELETE FROM raw.companyfacts a
    USING raw.companyfacts b
    WHERE a.cik = b.cik AND a.ctid <> b.ctid AND a.ctid > b.ctid;
    ALTER TABLE raw.companyfacts DROP CONSTRAINT IF EXISTS companyfacts_pkey;
    ALTER TABLE raw.companyfacts DROP CONSTRAINT IF EXISTS companyfacts_security_id_fkey;
    DROP INDEX IF EXISTS raw.ix_companyfacts_cik;
    ALTER TABLE raw.companyfacts DROP COLUMN IF EXISTS security_id;
    ALTER TABLE raw.companyfacts ADD PRIMARY KEY (cik);

    DELETE FROM raw.sec_submissions a
    USING raw.sec_submissions b
    WHERE a.cik = b.cik AND a.ctid <> b.ctid AND a.ctid > b.ctid;
    ALTER TABLE raw.sec_submissions DROP CONSTRAINT IF EXISTS sec_submissions_pkey;
    ALTER TABLE raw.sec_submissions DROP CONSTRAINT IF EXISTS sec_submissions_security_id_fkey;
    DROP INDEX IF EXISTS raw.ix_sec_submissions_cik;
    ALTER TABLE raw.sec_submissions DROP COLUMN IF EXISTS security_id;
    ALTER TABLE raw.sec_submissions ADD PRIMARY KEY (cik);

    DELETE FROM raw.company_taxonomy a
    USING raw.company_taxonomy b
    WHERE a.cik = b.cik AND a.ctid <> b.ctid AND a.ctid > b.ctid;
    ALTER TABLE raw.company_taxonomy DROP CONSTRAINT IF EXISTS company_taxonomy_pkey;
    ALTER TABLE raw.company_taxonomy DROP CONSTRAINT IF EXISTS company_taxonomy_security_id_fkey;
    DROP INDEX IF EXISTS raw.ix_company_taxonomy_cik;
    ALTER TABLE raw.company_taxonomy DROP COLUMN IF EXISTS security_id;
    ALTER TABLE raw.company_taxonomy ADD PRIMARY KEY (cik);
    """,
    """
    -- Compact per-CIK classification cache so stages 1 and 3 can reuse the
    -- classification computed in stage 0 instead of re-downloading the full
    -- companyfacts payload from SEC.
    CREATE TABLE IF NOT EXISTS raw.company_classification (
        cik VARCHAR(20) PRIMARY KEY,
        ticker VARCHAR(32) NOT NULL,
        company_name TEXT,
        security_types JSONB NOT NULL DEFAULT '[]'::jsonb,
        security_titles JSONB NOT NULL DEFAULT '[]'::jsonb,
        security_facts JSONB NOT NULL DEFAULT '[]'::jsonb,
        dividend_facts JSONB NOT NULL DEFAULT '[]'::jsonb,
        dividend BOOLEAN NOT NULL DEFAULT FALSE,
        status VARCHAR(32) NOT NULL DEFAULT 'unavailable',
        content_hash VARCHAR(64),
        retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    -- XBRL attribution comments for the dividend tables (mirrors schema.sql).
    COMMENT ON COLUMN raw.dividend_data.amount IS
      'Per-share dividend amount. XBRL: us-gaap:CommonStockDividendsPerShareDeclared / '
      'us-gaap:PreferredStockDividendsPerShare; aggregate fallbacks (DividendsCommonStockCash, '
      'PaymentsOfDividends, ...) kept only when no per-share declaration was filed';
    COMMENT ON COLUMN raw.dividend_data.ex_dividend_date IS
      'Dividend period. XBRL: fact.end (xbrl:periodEnd) is the proxy; SEC XBRL does not '
      'expose an ex-date fact, iXBRL filing narrative carries the true ex/record/payment dates';
    COMMENT ON COLUMN raw.dividend_data.declaration_date IS
      'Declaration date from iXBRL filing narrative (ix:declarationDate), not a companyfacts fact';
    COMMENT ON COLUMN raw.dividend_data.record_date IS
      'Record date from iXBRL filing narrative (ix:recordDate), not a companyfacts fact';
    COMMENT ON COLUMN raw.dividend_data.payment_date IS
      'Payment date from iXBRL filing narrative (ix:paymentDate); companyfacts fact end is the fallback';
    COMMENT ON COLUMN raw.dividend_data.frequency IS
      'Payment-interval cadence (Monthly/Quarterly/Semi-annual/Annual/Irregular), '
      'inferred from the median gap between consecutive ex-dates across the stored and '
      'incoming series (OpenBB true ex-dates first, SEC period-end proxies as fallback). '
      'One label per security. Informational; the feature build does not key on this column';
    COMMENT ON COLUMN raw.dividend_data.currency IS
      'Currency of the dividend amount, derived from the XBRL unit (e.g. USD per share)';
    COMMENT ON COLUMN raw.ticker_profile.coupon_rate IS
      'Preferred stock coupon / stated dividend rate in percent per annum. '
      'XBRL: us-gaap:PreferredStockDividendRatePercentage (preferred source), '
      'us-gaap:PreferredStockDividendRatePerAnnum; falls back to OpenBB/yfinance or name parse';
    COMMENT ON COLUMN raw.ticker_profile.liquidation_preference IS
      'Preferred stock liquidation preference per share. XBRL: '
      'us-gaap:PreferredStockLiquidationPreferenceValue / PreferredStockLiquidationPreference / '
      'TemporaryEquityLiquidationPreference(Value); falls back to '
      'us-gaap:PreferredStockParOrStatedValuePerShare, then name parse';
    COMMENT ON COLUMN raw.ticker_profile.coupon_type IS
      'fixed | floating | fixed-to-floating; parsed from the security name (dei:SecurityTitle), '
      'not a standalone XBRL fact';
    COMMENT ON COLUMN raw.ticker_profile.fixed_period_end IS
      'End of the fixed-rate period parsed from the security name, not an XBRL us-gaap fact';
    COMMENT ON COLUMN raw.ticker_profile.floating_spread IS
      'Floating-rate spread (percent) parsed from the security name, not an XBRL us-gaap fact';
    COMMENT ON COLUMN raw.ticker_profile.tax_status IS
      'qualified | non-qualified | tax-exempt; parsed from the security name, not an XBRL fact';
    COMMENT ON COLUMN raw.ticker_profile.call_date IS
      'issuer call/redemption date parsed from the security name; XBRL concept '
      'PreferredStockRedemptionPricePerShare supplies the redemption price, not the date';
    COMMENT ON COLUMN preferred.security_terms.dividend_rate IS
      'Preferred dividend rate (percent/amount). XBRL: us-gaap:PreferredStockDividendRatePercentage '
      '(seeded from the latest raw.dividend_data amount when no XBRL rate was filed)';
    COMMENT ON COLUMN preferred.security_terms.liquidation_preference IS
      'XBRL: us-gaap:PreferredStockLiquidationPreferenceValue / PreferredStockLiquidationPreference / '
      'TemporaryEquityLiquidationPreference(Value); fallback PreferredStockParOrStatedValuePerShare';
    COMMENT ON COLUMN preferred.security_terms.preferred_series IS
      'Series label parsed from dei:SecurityTitle (e.g. "Series C Preferred Stock")';
    COMMENT ON COLUMN preferred.dividend_snapshot.dividend_evidence_tag IS
      'XBRL/Inline XBRL tag that supplied the dividend evidence, e.g. '
      'us-gaap:CommonStockDividendsPerShareDeclared';
    """,
    """
    -- Slim preferred.dividend_snapshot: company_name/security_type/
    -- inferred_security_type/latest_dividend_value/latest_dividend_unit are
    -- derivable from reference.securities and raw companyfacts, and
    -- coupon_rate/liquidation_preference live in raw.ticker_profile, so the
    -- snapshot no longer duplicates them.
    ALTER TABLE preferred.dividend_snapshot
        DROP COLUMN IF EXISTS company_name,
        DROP COLUMN IF EXISTS security_type,
        DROP COLUMN IF EXISTS inferred_security_type,
        DROP COLUMN IF EXISTS latest_dividend_value,
        DROP COLUMN IF EXISTS latest_dividend_unit,
        DROP COLUMN IF EXISTS coupon_rate,
        DROP COLUMN IF EXISTS liquidation_preference
    """,
    """
    -- preferred.dividend_snapshot tracks whether a preferred issuer is
    -- actively issuing a dividend. `active` backfills from the old
    -- pays_dividend semantics (evidence inside the lookback window); full
    -- reruns of scripts.sec_xbrl_dividend_tags recompute it exactly.
    ALTER TABLE preferred.dividend_snapshot
        ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;
    UPDATE preferred.dividend_snapshot
        SET active = COALESCE(pays_dividend, FALSE)
        WHERE pays_dividend IS NOT NULL;
    COMMENT ON COLUMN preferred.dividend_snapshot.pays_dividend IS
      'TRUE: the issuer has positive dividend evidence in the stored companyfacts '
      'payload; the snapshot stores only such (preferred) issuers';
    COMMENT ON COLUMN preferred.dividend_snapshot.active IS
      'TRUE: a positive dividend fact was reported within the recent lookback '
      'window (actively issuing); FALSE: historical dividend evidence exists but '
      'the issuer is not actively paying';
    """,
    """
    -- Drop legacy flag/term attributes from preferred.security_terms: flags and
    -- conversion/redemption/legal terms are now carried by reference.securities
    -- and raw.ticker_profile, not stored per security-term.
    ALTER TABLE preferred.security_terms
        DROP COLUMN IF EXISTS preferred_flag,
        DROP COLUMN IF EXISTS cumulative_flag,
        DROP COLUMN IF EXISTS participating_flag,
        DROP COLUMN IF EXISTS convertible_flag,
        DROP COLUMN IF EXISTS redeemable_flag,
        DROP COLUMN IF EXISTS hard_soft_classification,
        DROP COLUMN IF EXISTS conversion_ratio,
        DROP COLUMN IF EXISTS conversion_price,
        DROP COLUMN IF EXISTS redemption_price,
        DROP COLUMN IF EXISTS redemption_date,
        DROP COLUMN IF EXISTS voting_rights,
        DROP COLUMN IF EXISTS seniority,
        DROP COLUMN IF EXISTS ranking,
        DROP COLUMN IF EXISTS protective_provisions
    """,
    """
    ALTER TABLE raw.company_classification
        ADD COLUMN IF NOT EXISTS security_titles JSONB NOT NULL DEFAULT '[]'::jsonb;
    COMMENT ON COLUMN raw.company_classification.security_titles IS
      'dei:SecurityTitle or dei:Security12bTitle values extracted from the '
      'companyfacts payload, used to populate reference.securities.security_name';
    """,
    """
    -- Hardening: reference.securities enforces data-quality guards (zero-padded
    -- digit CIK, ISO currency, normalized security_type) and NOT NULL on the
    -- identity/denomination fields every writer supplies. The UNIQUE(security_id)
    -- index securities_security_id_key is intentionally kept: 13 child FKs
    -- (raw.market_data, raw.dividend_data, model.*, audit.*, ...) reference it
    -- as their parent anchor, so it is load-bearing, not redundant with the PK.
    ALTER TABLE reference.securities
        ALTER COLUMN security_name SET NOT NULL,
        ALTER COLUMN currency SET NOT NULL;
    ALTER TABLE reference.securities
        DROP CONSTRAINT IF EXISTS chk_securities_cik,
        ADD CONSTRAINT chk_securities_cik
            CHECK (cik ~ '^[0-9]{1,10}$');
    ALTER TABLE reference.securities
        DROP CONSTRAINT IF EXISTS chk_securities_security_type,
        ADD CONSTRAINT chk_securities_security_type
            CHECK (security_type IN (
                'common_stock', 'preferred stock', 'debt', 'equity',
                'other_equity', 'other_debt', 'option', 'future',
                'derivative', 'government debt', 'corporate bond',
                'other_debt_and_equity', 'other'
            ));
    ALTER TABLE reference.securities
        DROP CONSTRAINT IF EXISTS chk_securities_currency,
        ADD CONSTRAINT chk_securities_currency
            CHECK (currency ~ '^[A-Z]{3}$');
    """,
    """
    -- P1(8): switch large issuer payload columns to lz4 compression. The
    -- default pglz compression is slower to decompress than lz4 for the
    -- ~1.5 GB of raw.companyfacts JSONB; lz4 gives comparable ratios with
    -- much lower ETL CPU. Requires PostgreSQL >= 14 (project runs 17).
    -- ALTER COLUMN ... SET COMPRESSION rewrites the table once.
    ALTER TABLE raw.companyfacts
        ALTER COLUMN raw_payload SET COMPRESSION lz4;
    ALTER TABLE raw.sec_submissions
        ALTER COLUMN raw_payload SET COMPRESSION lz4;
    ALTER TABLE raw.company_taxonomy
        ALTER COLUMN raw_payload SET COMPRESSION lz4;
    """,
]

try:
    ensure_database_exists()
    with engine.begin() as c:
        for stmt in _split_statements(sql):
            c.execute(text(stmt))
        for stmt in migrations:
            c.execute(text(stmt))
except OperationalError as exc:
    detail = getattr(exc.orig, "diag", None)
    message = getattr(detail, "message_primary", None) or str(exc.orig)
    raise SystemExit(f"Database initialization failed: {message}") from exc

print("Database initialized.")
