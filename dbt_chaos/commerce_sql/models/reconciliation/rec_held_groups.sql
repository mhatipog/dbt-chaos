{{ config(materialized='table', enabled=var('enable_reconciliation_models', false)) }}
-- Publication guard: a pending source is NOT corruption, but a report
-- requiring dual external evidence must wait until it is reconciled.
select distinct business_day as order_day, segment
from {{ ref('rec_payment_evidence') }}
where reconciliation_status <> 'provider_matched'
  and business_day is not null and segment is not null
union
select distinct g.order_day, g.segment
from {{ ref('gold_daily_revenue') }} g
inner join {{ ref('rec_bank_evidence') }} bank
    on bank.batch_day = g.order_day
where bank.reconciliation_status <> 'bank_matched'
