select customer_id, version
from {{ source('raw', 'customers') }}
group by 1,2 having count(*) > 1
