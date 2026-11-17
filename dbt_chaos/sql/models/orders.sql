{{ config(materialized='incremental', incremental_strategy='delete+insert', unique_key='order_id') }}
{% set strategy = var('strategy', 'strict') %}
{% set lookback = var('lookback', 10) %}
with ranked as (
    select event_id, order_id, source_version, event_time, amount_cents, op,
           arrival_seq,
           row_number() over (
               partition by order_id
               order by source_version desc, event_id desc
           ) as rn
    from {{ source('raw', 'events') }}
),
latest as (
    select event_id, order_id, source_version, event_time, amount_cents, op, arrival_seq
    from ranked where rn = 1
)
select latest.order_id, latest.source_version, latest.event_time,
       latest.amount_cents, latest.op, latest.event_id, latest.arrival_seq
from latest
where 1 = 1
{% if is_incremental() %}
  {% if strategy == 'strict' %}
    and latest.event_time > (select coalesce(max(event_time), -1000001) from {{ this }})
  {% elif strategy == 'inclusive' %}
    and latest.event_time >= (select coalesce(max(event_time), -1000001) from {{ this }})
  {% elif strategy == 'lookback' %}
    and latest.event_time >= (select coalesce(max(event_time), -1000001) - {{ lookback | int }} from {{ this }})
  {% elif strategy == 'offset' %}
    and latest.arrival_seq > (select coalesce(max(arrival_seq), 0) from {{ this }})
  {% elif strategy == 'cdc' %}
    and not exists (
      select 1 from {{ this }} current
      where current.order_id = latest.order_id
        and (
          current.source_version > latest.source_version
          or (current.source_version = latest.source_version and current.event_id >= latest.event_id)
        )
    )
  {% elif strategy == 'full' %}
    {# full is run with --full-refresh; filters deliberately omitted. #}
  {% else %}
    {{ exceptions.raise_compiler_error('unsupported synthetic strategy') }}
  {% endif %}
{% endif %}
