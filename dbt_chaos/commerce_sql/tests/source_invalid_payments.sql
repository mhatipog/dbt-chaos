select payment_id
from {{ source('raw', 'payments') }}
where amount_cents is null or amount_cents < 0
  or kind not in ('capture','refund')
