-- ACR-PD
SELECT column_name, 
    data_type,
    col_description((table_schema || '.' || table_name)::regclass::oid, ordinal_position) AS column_comment
FROM information_schema.columns as c
WHERE table_schema = 'reference'
  AND table_name = 'securities'

select i.* 
from reference.issuers as i
where issuer_id = 4683;

select * 
from reference.exchanges as ex;

select * 
from reference.securities
where issuer_id = 4683;

select * from raw.ticker_profile where ticker = 'ACR-PD';