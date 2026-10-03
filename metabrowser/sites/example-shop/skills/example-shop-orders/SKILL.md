---
name: example-shop-orders
description: Answer questions about orders in the Example Shop merchant back-office (find orders, customer order history, order status, totals) and build order reports.
model-activation: advisory
---

# Example Shop — orders

Tools (load with ToolSearch): `browser__site_example_shop_orders_list`,
`browser__site_example_shop_order_detail`, `browser__auth_ensure_login`.

1. Call `browser__auth_ensure_login` with `{"site": "example_shop"}` first. If it says
   `login_required`, ask the user to log in in that tab — never handle credentials.
2. Use `orders_list` (optionally `query`) for lists; it returns records or a CSV path.
3. Use `order_detail` for one order.
4. Refunds are **irreversible** and need user approval; only refund when the user explicitly
   asked for that specific order and amount.
5. Customer names are personal data: save reports only under `~/MetaBrowser/outputs`.
