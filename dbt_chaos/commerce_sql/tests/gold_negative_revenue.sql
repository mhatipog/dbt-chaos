select order_day, segment
from {{ ref('gold_daily_revenue') }}
where revenue_cents < 0
