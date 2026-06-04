# Stripe Validation — Monthly, Annual, Lifetime

**Module:** `website/lib/stripe_billing.js`  
**Webhook:** `POST /api/stripe/webhook`  
**Checkout:** `POST /api/checkout/session`

## Plans

| Plan | Mode | Default amount (if no Price ID) |
|------|------|----------------------------------|
| `monthly` | subscription | $19.99 / month |
| `annual` | subscription | $199 / year |
| `lifetime` | one-time payment | $499 |

Configure Stripe Price IDs in `.env`:

```
STRIPE_PRICE_MONTHLY=price_...
STRIPE_PRICE_ANNUAL=price_...
STRIPE_PRICE_LIFETIME=price_...
```

## Checkout flow

1. User selects plan on `pricing.html` → `checkout.html?plan=...`
2. Client calls `POST /api/checkout/session` with `plan`, `email`, optional `user_id`
3. Redirect to Stripe Checkout
4. Success → `success.html` (existing or default success URL)

## Webhook events handled

| Event | Action |
|-------|--------|
| `checkout.session.completed` | Create license, sync subscription, record payment, email license |
| `customer.subscription.updated` | Update subscription status in account store |
| `customer.subscription.deleted` | Mark subscription canceled |
| `invoice.payment_succeeded` | Append payment_history |
| `payment_intent.succeeded` | Legacy one-time path (backward compatible) |

## Subscription sync

Stored in unified account DB:

- `subscriptions` table — `stripe_subscription_id`, `plan`, `status`, `current_period_end`
- `product_licenses` — activation key for desktop
- `payment_history` — audit trail

Desktop validation (`GET /api/validate`) rejects if subscription `status === canceled`.

## Local test

```bash
cd website
cp .env.example .env
# Set STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_WEBHOOK_SECRET
npm start
stripe listen --forward-to localhost:3000/api/stripe/webhook
```

1. Open `http://localhost:3000/pricing.html`
2. Checkout monthly → complete test card `4242...`
3. Confirm webhook logs `handled: true`
4. Confirm email/license in dashboard

## Automated

E2E marks Stripe live paths as **manual** when keys absent. With keys, run Checkout + webhook before beta.

## Status

| Item | Status |
|------|--------|
| Monthly subscription Checkout | Implemented |
| Annual subscription Checkout | Implemented |
| Lifetime one-time Checkout | Implemented |
| Webhook + license email | Implemented |
| Live Stripe test | Manual (requires keys) |
