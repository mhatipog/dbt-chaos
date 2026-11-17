select * from {{ ref('orders') }} where amount_cents < 0
