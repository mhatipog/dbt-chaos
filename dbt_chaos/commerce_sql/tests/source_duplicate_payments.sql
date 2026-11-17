select payment_id, version
from {{ source('raw', 'payments') }}
group by 1,2 having count(*) > 1
