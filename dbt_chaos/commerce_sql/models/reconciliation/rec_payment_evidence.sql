{{ config(materialized='table', enabled=var('enable_reconciliation_models', false)) }}
-- Only delivered operational rows and external upstream evidence are visible.
-- Latest event versions are used; GL shares an operational provenance root.
with latest_orders as (
    select order_id, customer_id, order_day from (
        select *, row_number() over (
            partition by order_id order by version desc, row_id desc
        ) as rn
        from {{ source('raw', 'orders') }}
    ) where rn = 1
), latest_customers as (
    select customer_id, segment from (
        select *, row_number() over (
            partition by customer_id order by version desc, row_id desc
        ) as rn
        from {{ source('raw', 'customers') }}
    ) where rn = 1
), operational as (
    select payment_id, order_id, kind, amount_cents from (
        select *, row_number() over (
            partition by payment_id order by version desc, row_id desc
        ) as rn
        from {{ source('raw', 'payments') }}
    ) where rn = 1
), provider as (
    select payment_id, order_id, kind, amount_cents, batch_day
    from {{ source('raw', 'provider_transactions') }}
    where available_after_days <= {{ var('reconciliation_as_of_lag_days', 5) }}
), journal as (
    select payment_id, signed_cents
    from {{ source('raw', 'accounting_journal') }}
    where available_after_days <= {{ var('reconciliation_as_of_lag_days', 5) }}
), identities as (
    select payment_id from operational
    union
    select payment_id from provider
), matched as (
    select i.payment_id,
           o.payment_id is not null as operational_present,
           p.payment_id is not null as provider_present,
           coalesce(o.order_id, p.order_id) as order_id,
           coalesce(o.kind, p.kind) as kind,
           o.amount_cents as operational_cents,
           p.amount_cents as provider_cents,
           j.signed_cents as journal_signed_cents,
           orders.order_day as business_day,
           customers.segment as segment,
           case
               when o.kind = 'refund' then -o.amount_cents
               else o.amount_cents
           end as operational_signed_cents,
           o.order_id is distinct from p.order_id
             or o.kind is distinct from p.kind
             or o.amount_cents is distinct from p.amount_cents
             or orders.order_day is distinct from p.batch_day
             as provider_disagrees
    from identities i
    left join operational o on i.payment_id = o.payment_id
    left join provider p on i.payment_id = p.payment_id
    left join journal j on i.payment_id = j.payment_id
    left join latest_orders orders
       on coalesce(o.order_id, p.order_id) = orders.order_id
    left join latest_customers customers
       on orders.customer_id = customers.customer_id
)
select *,
       case
           when not operational_present then 'source_payment_missing'
           when business_day is null or segment is null then 'order_unresolvable'
           when not provider_present and
              {{ var('reconciliation_as_of_lag_days', 5) }} >= 2
               then 'provider_missing_after_sla'
           when not provider_present then 'pending_provider'
           when provider_disagrees then 'provider_transaction_mismatch'
           when journal_signed_cents is not null
               and journal_signed_cents <> operational_signed_cents
               then 'correlated_internal_gl_mismatch'
           else 'provider_matched'
       end as reconciliation_status
from matched
