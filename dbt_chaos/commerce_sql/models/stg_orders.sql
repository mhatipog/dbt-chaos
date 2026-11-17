{{ config(materialized='view') }}
with ranked as (
  select *, row_number() over (
    partition by order_id order by version desc, row_id desc
  ) as rank_id
  from {{ source('raw', 'orders') }}
)
select order_id, customer_id, order_day, gross_cents, status, currency
from ranked where rank_id = 1
