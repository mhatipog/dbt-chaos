{{ config(materialized='incremental', unique_key='order_id', incremental_strategy='delete+insert') }}
with ranked as (
    select order_id, amount_cents, updated_at,
           row_number() over (
               partition by order_id order by updated_at desc, arrival_seq desc
           ) as rn
    from {{ source('raw', 'events') }}
)
select order_id, amount_cents, updated_at
from ranked
where rn = 1
{% if is_incremental() and var('watermark', true) %}
  and updated_at > (select coalesce(max(updated_at), -1) from {{ this }})
{% endif %}
