select o.order_id
from {{ source('raw', 'orders') }} o
left join {{ source('raw', 'customers') }} c on c.customer_id = o.customer_id
where c.customer_id is null
  or o.currency <> 'EUR'
  or o.status not in ('completed','cancelled')
  or o.gross_cents is null or o.gross_cents <= 0
