{{ config(materialized='table', enabled=var('enable_quality_models', false)) }}
-- Invalid payments with identifiable order/customer ancestors require
-- withholding the entire day×segment group rather than publishing a zero.
with latest_orders as (
    select order_id, customer_id, order_day from (
        select *,
            row_number() over(partition by order_id
                              order by version desc, row_id desc) as rn
        from {{ source('raw', 'orders') }}
    ) where rn = 1
), latest_customers as (
    select customer_id, segment from (
        select *,
            row_number() over(partition by customer_id
                              order by version desc, row_id desc) as rn
        from {{ source('raw', 'customers') }}
    ) where rn = 1
)
select distinct o.order_day, c.segment
from {{ ref('quality_quarantine_payments') }} q
inner join latest_orders o on q.order_id = o.order_id
inner join latest_customers c on o.customer_id = c.customer_id
where q.quarantine_reason <> 'exact_delivery_replay'
