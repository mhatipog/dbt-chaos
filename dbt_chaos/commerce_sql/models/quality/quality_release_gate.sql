{{ config(materialized='table', enabled=var('enable_quality_models', false)) }}
with counts as (
    select
        count(*) as quarantine_rows,
        sum(case when quarantine_reason in (
            'missing_order', 'conflicting_same_version'
        ) then 1 else 0 end) as global_risks,
        sum(case when quarantine_reason not in (
            'exact_delivery_replay', 'missing_order',
            'conflicting_same_version'
        ) then 1 else 0 end) as local_risks
    from {{ ref('quality_quarantine_payments') }}
)
select
    case
        when global_risks > 0 then 'withheld_all'
        when local_risks > 0 then 'partial'
        else 'published'
    end as publication_status,
    quarantine_rows,
    global_risks,
    local_risks
from counts
