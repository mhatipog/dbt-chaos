{{ config(materialized='view') }}
{% if var('logic_fault', 'none') == 'skip_customer_dedup' %}
select customer_id, segment from {{ source('raw', 'customers') }}
{% else %}
with ranked as (
  select *, row_number() over (
    partition by customer_id order by version desc, row_id desc
  ) as rank_id
  from {{ source('raw', 'customers') }}
)
select customer_id, segment from ranked where rank_id = 1
{% endif %}
