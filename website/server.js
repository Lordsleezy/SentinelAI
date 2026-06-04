const path = require("path");
const express = require("express");
const nodemailer = require("nodemailer");
require("dotenv").config();

const account = require("./lib/account_store");
const analytics = require("./lib/analytics_store");
const billing = require("./lib/stripe_billing");
const github = require("./lib/github_releases");
const downloadHandler = require("./lib/download_handler");
const { clientIp } = require("./lib/client_ip");

const app = express();
const port = process.env.PORT || 3000;
const publicBaseUrl = process.env.PUBLIC_BASE_URL || "https://sentinelprime.org";

const seoPages = [
  { route: "/", file: "index.html", loc: `${publicBaseUrl}/` },
  { route: "/products", file: "products.html", loc: `${publicBaseUrl}/products.html` },
  { route: "/sentinel-drive", file: "sentinel-drive.html", loc: `${publicBaseUrl}/sentinel-drive.html` },
  { route: "/pricing", file: "pricing.html", loc: `${publicBaseUrl}/pricing.html` },
  { route: "/download", file: "download.html", loc: `${publicBaseUrl}/download.html` },
  { route: "/about", file: "about.html", loc: `${publicBaseUrl}/about.html` },
  { route: "/contact", file: "contact.html", loc: `${publicBaseUrl}/contact.html` },
  { route: "/signup", file: "signup.html", loc: `${publicBaseUrl}/signup.html` },
  { route: "/login", file: "login.html", loc: `${publicBaseUrl}/login.html` },
  { route: "/dashboard", file: "dashboard.html", loc: `${publicBaseUrl}/dashboard.html` },
  { route: "/admin", file: "admin.html", loc: `${publicBaseUrl}/admin.html` },
];

function sendMail({ to, subject, html, text }) {
  if (!process.env.SMTP_HOST) return Promise.resolve(false);
  const transporter = nodemailer.createTransport({
    host: process.env.SMTP_HOST,
    port: Number(process.env.SMTP_PORT || 587),
    secure: Number(process.env.SMTP_PORT || 587) === 465,
    auth: process.env.SMTP_USER ? { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS } : undefined,
  });
  return transporter.sendMail({
    from: process.env.SMTP_FROM || process.env.SMTP_USER || "paul@sentinelprime.org",
    to,
    subject,
    html,
    text,
  });
}

async function sendActivationEmail(email, code, plan = "pro") {
  return sendMail({
    to: email,
    subject: "Your SentinelAI License Key",
    text: `Your SentinelAI license key is ${code}. Plan: ${plan}. Download SentinelAI and enter this key in setup.`,
    html: `<div style="font-family:Arial,sans-serif;background:#000005;color:#fff;padding:28px">
      <h1>Your SentinelAI License</h1>
      <p style="font-size:22px;letter-spacing:2px"><strong>${code}</strong></p>
      <p>Plan: <strong>${plan}</strong></p>
      <p>Download from <a href="${publicBaseUrl}/download.html" style="color:#0f8">sentinelprime.org/download</a> and activate in the setup wizard.</p>
    </div>`,
  });
}

app.use((req, res, next) => {
  if (req.originalUrl === "/api/stripe/webhook") return next();
  express.json()(req, res, next);
});

app.use((req, res, next) => {
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
  next();
});

app.use(express.static(__dirname));

seoPages.forEach(page => {
  if (page.route !== "/") {
    app.get(page.route, (req, res) => res.sendFile(path.join(__dirname, page.file)));
  }
});

app.get("/api/health", (req, res) => {
  res.json({ ok: true, account_backend: account.useSupabase() ? "supabase" : "sqlite" });
});

app.get("/api/stripe/config", (req, res) => {
  res.json({
    publishableKey: process.env.STRIPE_PUBLISHABLE_KEY || "",
    plans: Object.keys(billing.PLANS),
  });
});

app.post("/api/checkout/session", async (req, res) => {
  try {
    const { plan, email, user_id } = req.body || {};
    if (!plan || !billing.PLANS[plan]) return res.status(400).json({ error: "plan required: monthly|annual|lifetime" });
    const session = await billing.createCheckoutSession({
      plan,
      email,
      userId: user_id,
    });
    res.json(session);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post("/api/create-payment-intent", async (req, res) => {
  try {
    const stripe = billing.getStripe();
    if (!stripe) return res.status(503).json({ error: "Stripe not configured" });
    const { email, plan = "lifetime" } = req.body || {};
    const cfg = billing.PLANS[plan] || billing.PLANS.lifetime;
    const intent = await stripe.paymentIntents.create({
      amount: cfg.fallbackAmount,
      currency: "usd",
      receipt_email: email || undefined,
      metadata: { plan, email: email || "", product: "sentinelai-pro" },
      automatic_payment_methods: { enabled: true },
    });
    res.json({ clientSecret: intent.client_secret, plan });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post("/api/stripe/webhook", express.raw({ type: "application/json" }), async (req, res) => {
  const stripe = billing.getStripe();
  if (!stripe || !process.env.STRIPE_WEBHOOK_SECRET) return res.status(503).send("Webhook not configured");
  let event;
  try {
    event = stripe.webhooks.constructEvent(req.body, req.headers["stripe-signature"], process.env.STRIPE_WEBHOOK_SECRET);
  } catch (e) {
    return res.status(400).send(`Webhook Error: ${e.message}`);
  }
  try {
    const result = await billing.handleWebhookEvent(event);
    if (result.licenseKey && result.email) {
      await sendActivationEmail(result.email, result.licenseKey, result.plan || "pro");
    }
    res.json({ received: true, ...result });
  } catch (e) {
    console.error("webhook handler", e);
    res.status(500).json({ error: e.message });
  }
});

app.post("/api/auth/signup", async (req, res) => {
  try {
    const { email, password, full_name } = req.body || {};
    const out = await account.signUp(email, password, full_name);
    res.json({ ok: true, ...out });
  } catch (e) {
    res.status(400).json({ error: e.message });
  }
});

app.post("/api/auth/login", async (req, res) => {
  try {
    const { email, password } = req.body || {};
    const out = await account.signIn(email, password);
    res.json({ ok: true, ...out });
  } catch (e) {
    res.status(401).json({ error: e.message });
  }
});

app.get("/api/dashboard", async (req, res) => {
  try {
    const userId = req.query.user_id || req.headers["x-user-id"];
    if (!userId) return res.status(400).json({ error: "user_id required" });
    const data = await account.getDashboard(userId);
    res.json({ ok: true, ...data });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

async function logLicenseEvent(req, eventType, code, machineId) {
  const install_id = req.body?.install_id || req.query?.install_id || null;
  let email = null;
  if (code) {
    const lic = await account.getLicenseByKey(code);
    if (lic?.user_id) {
      const profile = await account.getProfileById(lic.user_id);
      email = profile?.email || null;
    }
  }
  analytics.recordLicenseEvent({
    install_id,
    license_key: code,
    email,
    event_type: eventType,
    machine_id: machineId,
  });
}

app.post("/api/activate", async (req, res) => {
  const { code, machine_id } = req.body || {};
  if (!code || !machine_id) return res.json({ valid: false });
  const result = await account.activateLicense(code, machine_id);
  if (result.valid) logLicenseEvent(req, "activation", code, machine_id);
  res.json({ ...result, valid: result.valid });
});

app.get("/api/validate", async (req, res) => {
  const { code, machine_id } = req.query || {};
  if (!code || !machine_id) return res.json({ valid: false });
  const result = await account.validateLicense(code, machine_id);
  logLicenseEvent(req, "validation", code, machine_id);
  res.json({
    ...result,
    valid: result.valid,
    subscription_valid: result.valid,
    policy: { restricted_mode: false },
  });
});

app.post("/api/validate", async (req, res) => {
  const { key, code, machine_id, install_id } = req.body || {};
  const licenseCode = code || key;
  if (!licenseCode || !machine_id) return res.json({ valid: false });
  const result = await account.validateLicense(licenseCode, machine_id);
  logLicenseEvent({ body: { install_id }, query: {} }, "validation", licenseCode, machine_id);
  if (!result.valid && req.method === "POST" && key) {
    const activated = await account.activateLicense(licenseCode, machine_id);
    if (activated.valid) logLicenseEvent({ body: { install_id }, query: {} }, "activation", licenseCode, machine_id);
    return res.json({
      ...activated,
      valid: activated.valid,
      subscription_valid: activated.valid,
      policy: { restricted_mode: false },
    });
  }
  res.json({
    ...result,
    valid: result.valid,
    subscription_valid: result.valid,
    policy: { restricted_mode: false },
  });
});

app.get("/api/download/sentinelai", async (req, res) => {
  try {
    const target = await downloadHandler.handleDownloadRequest({
      ip: clientIp(req),
      userAgent: req.headers["user-agent"] || "",
      referrer: req.headers.referer || req.headers.referrer || "",
      version: req.query.version,
      channel: req.query.channel || "windows",
    });
    res.redirect(302, target.downloadUrl);
  } catch (e) {
    console.error("download redirect", e);
    res.redirect(
      302,
      process.env.DOWNLOAD_REDIRECT_URL ||
        "https://github.com/Lordsleezy/SentinelAI/releases/latest/download/SentinelAISetup.exe"
    );
  }
});

app.post("/api/telemetry/install", async (req, res) => {
  const { install_id, version, os, arch, timestamp, trial_start } = req.body || {};
  if (!install_id) return res.status(400).json({ error: "install_id required" });
  await analytics.recordInstall({
    install_id,
    version,
    os,
    arch,
    installed_at: timestamp,
    trial_start: Boolean(trial_start),
  });
  res.json({ ok: true });
});

app.post("/api/telemetry/trial", async (req, res) => {
  const { install_id, started_at } = req.body || {};
  if (!install_id) return res.status(400).json({ error: "install_id required" });
  await analytics.recordTrialStart({ install_id, started_at });
  res.json({ ok: true });
});

app.post("/api/telemetry", async (req, res) => {
  res.json({ ok: true, received: (req.body?.events || []).length });
});

app.post("/api/contact", async (req, res) => {
  const { name, email, subject, message } = req.body || {};
  if (!name || !email || !subject || !message) return res.status(400).json({ error: "Missing fields" });
  await account.run(
    "INSERT INTO contacts(name, email, subject, message, created_at) VALUES (?, ?, ?, ?, ?)",
    [name, email, subject, message, new Date().toISOString()]
  );
  await sendMail({
    to: process.env.CONTACT_TO || "paul@sentinelprime.org",
    subject: `SentinelPrime Contact: ${subject}`,
    text: `${name} <${email}>\n\n${message}`,
    html: `<p><strong>${name}</strong> &lt;${email}&gt;</p><p>${String(message).replace(/\n/g, "<br>")}</p>`,
  });
  res.json({ ok: true });
});

app.get("/api/beta/release", async (req, res) => {
  const gh = await github.fetchLatestRelease();
  const fallback = {
    version: process.env.BETA_VERSION || "1.0.0-beta.1",
    channel: "beta",
    releaseNotes: process.env.BETA_RELEASE_NOTES || "",
    requirements: { os: "Windows 10/11 x64", ram_gb: 16, disk_gb: 20, gpu: "8GB VRAM recommended" },
    downloadUrl: process.env.BETA_INSTALLER_URL || "https://github.com/Lordsleezy/SentinelAI/releases/latest",
    installerName: "SentinelAISetup.exe",
  };
  if (gh.ok) {
    return res.json({
      ...fallback,
      version: gh.version || fallback.version,
      releaseNotes: gh.body || fallback.releaseNotes,
      downloadUrl: gh.downloadUrl,
      installerName: gh.installerName,
      published_at: gh.published_at,
      github: true,
    });
  }
  res.json({ ...fallback, github: false, github_error: gh.error });
});

function requireAdmin(req, res, next) {
  const token = req.headers["x-admin-token"] || req.query.token;
  if (!process.env.ADMIN_TOKEN || token !== process.env.ADMIN_TOKEN) {
    return res.status(401).json({ error: "Unauthorized" });
  }
  next();
}

app.get("/api/admin/users", requireAdmin, async (req, res) => {
  try {
    const users = await account.all(
      `SELECT p.id, p.email, p.created_at, l.license_key, l.machine_id, l.activated_at, s.plan, s.status
       FROM profiles p
       LEFT JOIN product_licenses l ON l.user_id = p.id
       LEFT JOIN subscriptions s ON s.user_id = p.id
       ORDER BY p.created_at DESC LIMIT 200`
    );
    res.json({ users });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get("/api/admin/subscriptions", requireAdmin, async (req, res) => {
  const rows = await account.all("SELECT * FROM subscriptions ORDER BY created_at DESC LIMIT 200");
  res.json({ subscriptions: rows });
});

app.get("/api/admin/payments", requireAdmin, async (req, res) => {
  const rows = await account.all("SELECT * FROM payment_history ORDER BY created_at DESC LIMIT 200");
  res.json({ payments: rows });
});

app.get("/api/admin/licenses", requireAdmin, async (req, res) => {
  const rows = await account.all("SELECT * FROM product_licenses ORDER BY created_at DESC LIMIT 200");
  res.json({ licenses: rows });
});

app.get("/api/admin/audit", requireAdmin, async (req, res) => {
  const rows = await account.all("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 200");
  res.json({ audit: rows });
});

app.get("/api/admin/analytics", requireAdmin, async (req, res) => {
  try {
    const stats = await analytics.getAdminAnalytics();
    res.json({ ok: true, ...stats });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post("/api/admin/grant-license", requireAdmin, async (req, res) => {
  const { email, plan = "lifetime" } = req.body || {};
  if (!email) return res.status(400).json({ error: "email required" });
  const userId = await account.resolveUserIdForEmail(email);
  const code = await account.createLicense({ userId, email, plan });
  await sendActivationEmail(email, code, plan);
  res.json({ ok: true, email, code_sent: Boolean(process.env.SMTP_HOST) });
});

app.post("/api/drive-notify", async (req, res) => {
  const { email } = req.body || {};
  if (!email) return res.status(400).json({ error: "Email is required" });
  await account.run("INSERT OR IGNORE INTO drive_notifications(email, created_at) VALUES (?, ?)", [
    email,
    new Date().toISOString(),
  ]);
  res.json({ ok: true });
});

Promise.all([account.init(), analytics.init()]).then(([info]) => {
  console.log(`Account backend: ${info.backend}`);
  app.listen(port, () => {
    console.log(`SentinelPrime site running on http://localhost:${port}`);
  });
}).catch(err => {
  console.error("Account init failed", err);
  process.exit(1);
});
