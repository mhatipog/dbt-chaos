{{ config(materialized='table', enabled=var('enable_quality_models', false)) }}
-- Real warehouse-side quarantine table. This model sees raw source only, never
-- process-ledger truth. Impossible-to-localize errors trigger a release gate.
with p as (
    select raw.*,
        row_number() over (
            partition by payment_id, version order by row_id asc
        ) as delivery_rank,
        count(*) over (
            partition by payment_id, version
        ) as delivery_copies,
        first_value(order_id) over (
            partition by payment_id, version order by row_id asc
        ) as initial_order_id,
        first_value(kind) over (
            partition by payment_id, version order by row_id asc
        ) as initial_kind,
        first_value(amount_cents) over (
            partition by payment_id, version order by row_id asc
        ) as initial_amount_cents
    from {{ source('raw', 'payments') }} raw
), latest_orders as (
    select order_id
    from (
        select order_id, row_number() over(
            partition by order_id order by version desc, row_id desc
        ) as rn
        from {{ source('raw', 'orders') }}
    ) where rn = 1
), classified as (
    select p.row_id, p.payment_id, p.order_id, p.version,
           p.kind, p.amount_cents,
        case
            when p.delivery_copies > 1 and (
                 p.order_id is distinct from p.initial_order_id
                 or p.kind is distinct from p.initial_kind
                 or p.amount_cents is distinct from p.initial_amount_cents
            ) then 'conflicting_same_version'
            when p.delivery_rank > 1 and p.delivery_copies > 1
                 then 'exact_delivery_replay'
            when o.order_id is null then 'missing_order'
            when p.amount_cents is null or p.amount_cents < 0
                 or p.kind not in ('capture', 'refund')
                 then 'invalid_payment_fields'
            else null
        end as quarantine_reason
    from p
    left join latest_orders o on p.order_id = o.order_id
)
select * from classified where quarantine_reason is not null
