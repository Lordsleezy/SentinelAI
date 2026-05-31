const crypto = require("crypto");
const path = require("path");
const express = require("express");
const nodemailer = require("nodemailer");
const sqlite3 = require("sqlite3").verbose();
require("dotenv").config();

const app = express();
const port = process.env.PORT || 3000;
const stripe = process.env.STRIPE_SECRET_KEY ? require("stripe")(process.env.STRIPE_SECRET_KEY) : null;
const db = new sqlite3.Database(process.env.SQLITE_PATH || path.join(__dirname, "activation_codes.sqlite"));
const publicBaseUrl = process.env.PUBLIC_BASE_URL || "https://sentinelprime.org";
const seoPages = [
  { route: "/", file: "index.html", loc: `${publicBaseUrl}/` },
  { route: "/products", file: "products.html", loc: `${publicBaseUrl}/products.html` },
  { route: "/sentinel-drive", file: "sentinel-drive.html", loc: `${publicBaseUrl}/sentinel-drive.html` },
  { route: "/pricing", file: "pricing.html", loc: `${publicBaseUrl}/pricing.html` },
  { route: "/download", file: "download.html", loc: `${publicBaseUrl}/download.html` },
  { route: "/about", file: "about.html", loc: `${publicBaseUrl}/about.html` },
  { route: "/contact", file: "contact.html", loc: `${publicBaseUrl}/contact.html` }
];

db.serialize(() => {
  db.run(`CREATE TABLE IF NOT EXISTS activation_codes (
    code TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    machine_id TEXT
  )`);
  db.run(`CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    email TEXT,
    subject TEXT,
    message TEXT,
    created_at TEXT NOT NULL
  )`);
  db.run(`CREATE TABLE IF NOT EXISTS drive_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
  )`);
});

function sendMail({ to, subject, html, text }) {
  if (!process.env.SMTP_HOST) return Promise.resolve(false);
  const transporter = nodemailer.createTransport({
    host: process.env.SMTP_HOST,
    port: Number(process.env.SMTP_PORT || 587),
    secure: Number(process.env.SMTP_PORT || 587) === 465,
    auth: process.env.SMTP_USER ? { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS } : undefined
  });
  return transporter.sendMail({
    from: process.env.SMTP_FROM || process.env.SMTP_USER || "paul@sentinelprime.org",
    to,
    subject,
    html,
    text
  });
}

function createActivationCode(email) {
  const code = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    db.run(
      "INSERT INTO activation_codes(code, email, created_at) VALUES (?, ?, ?)",
      [code, email, new Date().toISOString()],
      err => err ? reject(err) : resolve(code)
    );
  });
}

async function sendActivationEmail(email, code) {
  return sendMail({
    to: email,
    subject: "Your SentinelAI Pro Activation Code",
    text: `Your SentinelAI Pro activation code is ${code}. Download SentinelAI, open setup, and enter this code to unlock Pro.`,
    html: `<div style="font-family:Arial,sans-serif;background:#000005;color:#fff;padding:28px"><h1>Your SentinelAI Pro Activation Code</h1><p style="font-size:22px;letter-spacing:2px"><strong>${code}</strong></p><p>Download SentinelAI, open setup, and enter this code to unlock Pro.</p><p>No subscriptions. No cloud. No compromise.</p></div>`
  });
}

app.use((req, res, next) => {
  if (req.originalUrl === "/api/stripe/webhook") return next();
  express.json()(req, res, next);
});
app.use((req, res, next) => {
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
  if (req.path.endsWith(".html") || seoPages.some(page => page.route === req.path)) {
    const htmlPath = req.path === "/" ? "/" : req.path.replace(/\.html$/, "");
    const seoPage = seoPages.find(page => page.route === htmlPath);
    if (seoPage) res.setHeader("Link", `<${seoPage.loc}>; rel="canonical"`);
  }
  next();
});
app.use(express.static(__dirname));

seoPages.forEach(page => {
  if (page.route !== "/") {
    app.get(page.route, (req, res) => res.sendFile(path.join(__dirname, page.file)));
  }
});

app.get("/sitemap.xml", (req, res) => {
  res.type("application/xml");
  res.send(`<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${seoPages.map(page => `  <url><loc>${page.loc}</loc></url>`).join("\n")}
</urlset>`);
});

app.get("/robots.txt", (req, res) => {
  res.type("text/plain");
  res.send(`User-agent: *
Allow: /
Disallow: /checkout.html
Disallow: /success.html

Sitemap: ${publicBaseUrl}/sitemap.xml
`);
});

app.get("/api/stripe/config", (req, res) => {
  res.json({ publishableKey: process.env.STRIPE_PUBLISHABLE_KEY || "" });
});

app.post("/api/create-payment-intent", async (req, res) => {
  if (!stripe) return res.status(503).json({ error: "Stripe is not configured" });
  try {
    const { email } = req.body || {};
    const intent = await stripe.paymentIntents.create({
      amount: 19900,
      currency: "usd",
      receipt_email: email || undefined,
      automatic_payment_methods: { enabled: true },
      metadata: { product: "sentinelai-pro", email: email || "" }
    });
    res.json({ clientSecret: intent.client_secret });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post("/api/stripe/webhook", express.raw({ type: "application/json" }), async (req, res) => {
  if (!stripe || !process.env.STRIPE_WEBHOOK_SECRET) return res.status(503).send("Webhook not configured");
  let event;
  try {
    event = stripe.webhooks.constructEvent(req.body, req.headers["stripe-signature"], process.env.STRIPE_WEBHOOK_SECRET);
  } catch (error) {
    return res.status(400).send(`Webhook Error: ${error.message}`);
  }
  if (event.type === "payment_intent.succeeded") {
    const intent = event.data.object;
    const email = intent.receipt_email || intent.metadata?.email;
    if (email) {
      const code = await createActivationCode(email);
      await sendActivationEmail(email, code);
    }
  }
  res.json({ received: true });
});

app.post("/api/activate", (req, res) => {
  const { code, machine_id } = req.body || {};
  if (!code || !machine_id) return res.json({ valid: false });
  db.get("SELECT * FROM activation_codes WHERE code = ?", [code], (err, row) => {
    if (err || !row) return res.json({ valid: false });
    if (row.machine_id && row.machine_id !== machine_id) return res.json({ valid: false });
    const activatedAt = row.activated_at || new Date().toISOString();
    db.run("UPDATE activation_codes SET activated_at = ?, machine_id = ? WHERE code = ?", [activatedAt, machine_id, code]);
    res.json({ valid: true, tier: "pro" });
  });
});

app.get("/api/validate", (req, res) => {
  const { code, machine_id } = req.query || {};
  if (!code || !machine_id) return res.json({ valid: false });
  db.get("SELECT * FROM activation_codes WHERE code = ?", [code], (err, row) => {
    if (err || !row) return res.json({ valid: false });
    res.json({ valid: !row.machine_id || row.machine_id === machine_id, tier: "pro", activated: Boolean(row.activated_at) });
  });
});

app.post("/api/contact", async (req, res) => {
  const { name, email, subject, message } = req.body || {};
  if (!name || !email || !subject || !message) return res.status(400).json({ error: "Missing fields" });
  db.run(
    "INSERT INTO contacts(name, email, subject, message, created_at) VALUES (?, ?, ?, ?, ?)",
    [name, email, subject, message, new Date().toISOString()]
  );
  await sendMail({
    to: process.env.CONTACT_TO || "paul@sentinelprime.org",
    subject: `SentinelPrime Contact: ${subject}`,
    text: `${name} <${email}>\n\n${message}`,
    html: `<p><strong>${name}</strong> &lt;${email}&gt;</p><p>${String(message).replace(/\n/g, "<br>")}</p>`
  });
  res.json({ ok: true });
});

app.post("/api/drive-notify", async (req, res) => {
  const { email } = req.body || {};
  if (!email) return res.status(400).json({ error: "Email is required" });
  db.run(
    "INSERT OR IGNORE INTO drive_notifications(email, created_at) VALUES (?, ?)",
    [email, new Date().toISOString()]
  );
  await sendMail({
    to: process.env.CONTACT_TO || "paul@sentinelprime.org",
    subject: "Sentinel Drive launch notification signup",
    text: `${email} wants to be notified about Sentinel Drive.`,
    html: `<p>${email} wants to be notified about Sentinel Drive.</p>`
  });
  res.json({ ok: true });
});

app.listen(port, () => {
  console.log(`SentinelPrime site running on http://localhost:${port}`);
});
