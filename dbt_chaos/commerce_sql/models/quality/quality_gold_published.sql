{{ config(materialized='table', enabled=var('enable_quality_models', false)) }}
-- This is the actual publication surface. The old gold model is retained for
-- comparison, but downstream readers must query quality_gold_published.
select g.order_day, g.segment, g.revenue_cents
from {{ ref('gold_daily_revenue') }} g
cross join {{ ref('quality_release_gate') }} gate
where gate.publication_status != 'withheld_all'
  and not exists (
      select 1 from {{ ref('quality_held_groups') }} hold
      where hold.order_day = g.order_day and hold.segment = g.segment
  )
