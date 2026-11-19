{{ config(materialized='table', enabled=var('enable_reconciliation_models', false)) }}
with baseline as (
    select count(*) as report_groups from {{ ref('gold_daily_revenue') }}
), held as (
    select count(*) as withheld_groups from {{ ref('rec_held_groups') }}
), pay as (
    select
      sum(case when reconciliation_status not in (
              'provider_matched','pending_provider') then 1 else 0 end) as disputes,
      sum(case when reconciliation_status in (
              'source_payment_missing','order_unresolvable') then 1 else 0 end) as unlocalized,
      sum(case when reconciliation_status = 'pending_provider' then 1 else 0 end) as pending_payments
    from {{ ref('rec_payment_evidence') }}
), bank as (
    select
       sum(case when reconciliation_status in (
           'bank_missing_after_sla','independent_bank_balance_mismatch'
       ) then 1 else 0 end) as disputes,
       sum(case when reconciliation_status = 'pending_bank'
                then 1 else 0 end) as pending_batches
    from {{ ref('rec_bank_evidence') }}
)
select
 case
     when coalesce(pay.unlocalized,0)>0
       or (baseline.report_groups > 0 and held.withheld_groups >= baseline.report_groups)
       then 'withheld_all'
     when held.withheld_groups > 0 then 'partial'
     else 'published'
 end as publication_status,
 baseline.report_groups, held.withheld_groups,
 coalesce(pay.disputes,0)+coalesce(bank.disputes,0) as dispute_count,
 coalesce(pay.pending_payments,0)+coalesce(bank.pending_batches,0) as pending_count
from baseline cross join held cross join pay cross join bank
