select order_id, version
from {{ source('raw', 'orders') }}
group by 1,2 having count(*) > 1
