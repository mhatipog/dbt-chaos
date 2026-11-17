select order_day, segment
from {{ ref('gold_daily_revenue') }}
group by 1,2 having count(*) > 1
