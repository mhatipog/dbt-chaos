-- An intentionally unfamiliar project: independently authored transformation.
select
    order_id,
    sum(case when kind = 'refund' then -amount_cents else amount_cents end) as revenue_cents
from {{ ref('payments') }}
group by order_id
