{{ config(materialized='table', enabled=var('enable_reconciliation_models', false)) }}
-- Bank-like independent aggregate bucket. Simplified synthetic settlement:
-- no fees, FX, payout drift, clearing calendar or cross-day netting.
with latest_orders as (
    select order_id, order_day from (
        select *, row_number() over (
            partition by order_id order by version desc, row_id desc
        ) as rn
        from {{ source('raw', 'orders') }}
    ) where rn = 1
), latest_payments as (
    select payment_id, order_id, kind, amount_cents from (
        select *, row_number() over (
            partition by payment_id order by version desc, row_id desc
        ) as rn
        from {{ source('raw', 'payments') }}
    ) where rn = 1
), source_daily as (
    select o.order_day as batch_day,
           sum(case when p.kind = 'refund' then -p.amount_cents
                    when p.kind = 'capture' then p.amount_cents
                    else 0 end) as operational_net_cents
    from latest_payments p
    join latest_orders o on p.order_id = o.order_id
    group by o.order_day
), available_bank as (
    select batch_day, net_cents
    from {{ source('raw', 'bank_batches') }}
    where available_after_days <= {{ var('reconciliation_as_of_lag_days', 5) }}
), all_days as (
    select batch_day from source_daily
    union
    select batch_day from available_bank
), joined as (
    select d.batch_day, o.operational_net_cents, b.net_cents as bank_net_cents,
           b.batch_day is not null as bank_available
    from all_days d
    left join source_daily o on d.batch_day = o.batch_day
    left join available_bank b on d.batch_day = b.batch_day
)
select *,
       case
           when not bank_available and
                {{ var('reconciliation_as_of_lag_days', 5) }} < 4
                then 'pending_bank'
           when not bank_available then 'bank_missing_after_sla'
           when coalesce(operational_net_cents,0) <> coalesce(bank_net_cents,0)
                then 'independent_bank_balance_mismatch'
           else 'bank_matched'
       end as reconciliation_status
from joined
