/* ticker like 'LFMD%'--'%ACR-%'*/

SELECT column_name, 
    data_type,
    col_description((table_schema || '.' || table_name)::regclass::oid, ordinal_position) AS column_comment
FROM information_schema.columns as c
WHERE table_schema = 'reference'
  AND table_name = 'securities'
LIMIT 100;

SELECT * from raw.company_ticker order by cik asc;

SELECT * 
FROM raw.ticker_profile AS tp
order by tp.ticker asc;

select * from raw.companyfacts as cf;
select * from raw.sec_documents as sd;
select * from raw.sec_submissions as ss;
select * from raw.company_taxonomy
SELECT * from raw.dividend_data as dd 

select * from raw.market_data as md 


--'%ACR-%' 'LFMD%'


SELECT * /*
ticker, -- dei:TradingSymbol Ticker symbol example: ACR, ACR-PC, ACR-PD,
       cik, --0001332551
       security_id, 
       issuer_id, -- 4683
       issuer_name, --dei:EntityRegistrantName ACRES Commercial Realty Corp. (join reference.issuers.issuer_name via issuer_id/cik; no longer stored on securities)
       security_name, -- dei:SecurityTitle (or dei:Security12bTitle) Common Stock, $0.001 par value, 8.625% Fixed-to-Floating Series C Cumulative Redeemable Preferred Stock, 7.875% Series D Cumulative Redeemable Preferred Stock
       security_type, -- Common Stock, ,Fixed-to-Floating Cumulative Redeemable Preferred Stock, Cumulative Redeemable Preferred Stock
       cusip,  --us-gaap:CUSIP / us-gaap:DebtInstrumentCusip 9-character alphanumeric CUSIP code assigned to each specific class/series.
       isin,  -- us-gaap:ISIN / srt:ISIN
       exchange_id, -- Exchange identifier reference.exchanges table (1 = NYAW 	New York Stock Exchange,2 = NASDAQ)
       coupon_rate,  -- 8.5% 
       dividend,   security_type, -- Common Stock, ,Fixed-to-Floating Cumulative Redeemable Preferred Stock, Cumulative Redeemable Preferred Stock
       currency, -- Currency code (e.g., USD, EUR)
       liquidation_preference,  -- 25
       call_date,  -- Date when the security can be called or redeemed by the issuer
       cusip,  --us-gaap:CUSIP / us-gaap:DebtInstrumentCusip 9-character alphanumeric CUSIP code assigned to each specific class/series.
       isin,  -- us-gaap:ISIN / srt:ISIN        
       created_at,
       updated_at,
       sec_data_status */
FROM reference.securities
where ticker = 'ACR-PD';

select * from preferred.contract_terms as ct
where ct.security_id = '59272c3f-48be-523e-a845-a928d4709414';
select * from preferred.security_terms as st
where st.security_id = '59272c3f-48be-523e-a845-a928d4709414';
select * from preferred.dividend_snapshot as ds
where ds.security_id = '59272c3f-48be-523e-a845-a928d4709414';
