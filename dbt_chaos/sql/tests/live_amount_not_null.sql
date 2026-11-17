select * from {{ ref('orders') }} where op = 'upsert' and amount_cents is null
