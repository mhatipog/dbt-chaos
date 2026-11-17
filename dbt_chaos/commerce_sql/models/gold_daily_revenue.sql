{{ config(materialized='table') }}
{% set f = var('logic_fault', 'none') %}
with payment_totals as (
  select order_id, sum(
    case when kind = 'capture' then {% if f == 'invert_capture_sign' %}-amount_cents{% else %}amount_cents{% endif %}
    when kind = 'refund' then {% if f == 'ignore_refunds' %}0{% else %}-amount_cents{% endif %}
    else 0 end
  ) as net_cents
  from {{ ref('stg_payments') }}
  group by order_id
),
gold_rows as (
  select o.order_day, c.segment, coalesce(p.net_cents,0) as net_cents
  from {{ ref('stg_orders') }} o
  inner join {{ ref('stg_customers') }} c
    on {% if f == 'wrong_customer_join' %}o.order_id{% else %}o.customer_id{% endif %} = c.customer_id
  left join payment_totals p
    on p.order_id = {% if f == 'wrong_payment_join' %}o.customer_id{% else %}o.order_id{% endif %}
  where o.gross_cents is not null and o.gross_cents > 0
    {% if f != 'include_cancelled' %}and o.status = 'completed'{% endif %}
    {% if f != 'ignore_currency' %}and o.currency = 'EUR'{% endif %}
),
totals as (
{% if f == 'wrong_grain' %}
  select order_day, 'ALL' as segment, sum(net_cents) as revenue_cents
  from gold_rows group by order_day
{% else %}
  select order_day, segment, sum(net_cents) as revenue_cents
  from gold_rows group by order_day, segment
{% endif %}
)
select order_day, segment, revenue_cents from totals where revenue_cents <> 0
