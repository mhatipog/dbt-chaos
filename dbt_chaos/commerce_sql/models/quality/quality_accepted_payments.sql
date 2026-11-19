{{ config(materialized='table', enabled=var('enable_quality_models', false)) }}
-- Actual accepted data source for stg_payments when the native gate is enabled.
select p.*
from {{ source('raw', 'payments') }} p
left join {{ ref('quality_quarantine_payments') }} q
    on p.row_id = q.row_id
where q.row_id is null
