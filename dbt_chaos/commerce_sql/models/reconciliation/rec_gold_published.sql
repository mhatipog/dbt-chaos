{{ config(materialized='table', enabled=var('enable_reconciliation_models', false)) }}
-- This table, not gold_daily_revenue, is the only claimed publication surface.
-- No guessed amounts or silent zero-fill for held groups.
{% if var('enable_quality_models', false) %}
    {% set gold_relation = ref('quality_gold_published') %}
{% else %}
    {% set gold_relation = ref('gold_daily_revenue') %}
{% endif %}
select g.order_day,g.segment,g.revenue_cents
from {{ gold_relation }} g
cross join {{ ref('rec_release_gate') }} release
where release.publication_status <> 'withheld_all'
  and not exists (
    select 1 from {{ ref('rec_held_groups') }} hold
    where hold.order_day = g.order_day
      and hold.segment = g.segment
  )
