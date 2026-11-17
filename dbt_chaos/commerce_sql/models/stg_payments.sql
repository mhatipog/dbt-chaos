{{ config(materialized='view') }}
{% if var('logic_fault', 'none') == 'skip_payment_dedup' %}
select payment_id, order_id, kind, amount_cents
from {{ source('raw', 'payments') }}
where amount_cents is not null and amount_cents >= 0
  and kind in ('capture', 'refund')
{% else %}
with ranked as (
  select *, row_number() over (
    partition by payment_id order by version desc, row_id desc
  ) as rank_id
  from {{ source('raw', 'payments') }}
)
select payment_id, order_id, kind, amount_cents
from ranked where rank_id = 1
  and amount_cents is not null and amount_cents >= 0
  and kind in ('capture', 'refund')
{% endif %}
