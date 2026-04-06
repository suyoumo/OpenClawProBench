# Checkout Incident Runbook

- During a payment outage, do not create new orders that would require later charge capture.
- During inventory readonly mode, do not reserve or decrement stock.
- The synchronous API response can carry the customer's primary status immediately.
- When notification queueing still works, a delayed follow-up notification is allowed after the synchronous response.
