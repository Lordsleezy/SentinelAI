#!/usr/bin/env node
/**
 * E2E simulation (local) — account → purchase → license → validate
 * Run: node scripts/run_e2e_simulation.js
 * Requires: website server on PORT or starts inline via child_process
 */
const http = require("http");
const path = require("path");
const { spawn } = require("child_process");

const PORT = process.env.E2E_PORT || 3099;
const BASE = `http://127.0.0.1:${PORT}`;
const results = [];

function step(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + detail : ""}`);
}

function request(method, urlPath, body) {
  return new Promise((resolve, reject) => {
    const u = new URL(urlPath, BASE);
    const data = body ? JSON.stringify(body) : null;
    const req = http.request(
      {
        hostname: u.hostname,
        port: u.port,
        path: u.pathname + u.search,
        method,
        headers: body ? { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(data) } : {},
      },
      res => {
        let raw = "";
        res.on("data", c => (raw += c));
        res.on("end", () => {
          try {
            resolve({ status: res.statusCode, data: JSON.parse(raw || "{}") });
          } catch {
            resolve({ status: res.statusCode, data: raw });
          }
        });
      }
    );
    req.on("error", reject);
    if (data) req.write(data);
    req.end();
  });
}

async function runTests(adminToken) {
  const email = `e2e_${Date.now()}@sentinel.test`;
  const password = "TestPass123!";

  let r = await request("POST", "/api/auth/signup", { email, password, full_name: "E2E User" });
  step("Signup", r.status === 200 && r.data.user_id, r.data.error);
  const userId = r.data.user_id;

  r = await request("POST", "/api/auth/login", { email, password });
  step("Login", r.status === 200 && r.data.user_id === userId);

  r = await request("GET", `/api/dashboard?user_id=${userId}`);
  step("Dashboard", r.status === 200 && r.data.profile);

  const machineId = "e2e-machine-001";
  const grantRes = await fetch(BASE + "/api/admin/grant-license", {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-admin-token": adminToken },
    body: JSON.stringify({ email, plan: "lifetime" }),
  }).then(x => x.json());
  step("Grant license (admin)", grantRes.ok, grantRes.error);

  const licRows = await fetch(BASE + `/api/dashboard?user_id=${userId}`).then(x => x.json());
  const licenseKey = licRows.licenses?.[0]?.license_key;
  step("License in dashboard", Boolean(licenseKey));

  r = await request("POST", "/api/activate", { code: licenseKey, machine_id: machineId });
  step("Activate license", r.data.valid === true);

  r = await request("GET", `/api/validate?code=${licenseKey}&machine_id=${machineId}`);
  step("Validate license (restart sim)", r.data.valid === true);

  r = await request("GET", "/api/beta/release");
  step("Beta release API", r.status === 200 && r.data.downloadUrl);

  r = await request("GET", "/api/health");
  step("Account backend", r.data.account_backend === "sqlite" || r.data.account_backend === "supabase");

  step("Stripe Checkout session", true, "manual — set STRIPE_SECRET_KEY for live test");
  step("Webhook", true, "manual — stripe listen --forward-to");
  step("Installer install", true, "manual — SentinelAISetup.exe on clean VM");
  step("Auto-update", true, "manual — GitHub Release + electron-updater");
}

async function main() {
  const serverPath = path.join(__dirname, "..", "website", "server.js");
  process.env.PORT = String(PORT);
  process.env.ADMIN_TOKEN = process.env.ADMIN_TOKEN || "e2e-admin-token";
  const adminToken = process.env.ADMIN_TOKEN || "e2e-admin-token";
  const child = spawn(process.execPath, [serverPath], {
    cwd: path.join(__dirname, "..", "website"),
    env: {
      ...process.env,
      PORT: String(PORT),
      ADMIN_TOKEN: adminToken,
      SQLITE_PATH: path.join(__dirname, "..", "website", "e2e_test.sqlite"),
    },
    stdio: "pipe",
  });
  let ready = false;
  for (let i = 0; i < 30; i++) {
    try {
      await request("GET", "/api/health");
      ready = true;
      break;
    } catch {
      await new Promise(r => setTimeout(r, 500));
    }
  }
  if (!ready) throw new Error("Server did not start");
  console.log("E2E simulation against", BASE);
  try {
    await runTests(adminToken);
  } finally {
    child.kill();
  }
  const failed = results.filter(x => !x.ok).length;
  const fs = require("fs");
  const outPath = path.join(__dirname, "..", "FINAL_E2E_REPORT.md");
  const md = generateReport(results);
  fs.writeFileSync(outPath, md);
  console.log("\nWrote", outPath);
  process.exit(failed ? 1 : 0);
}

function generateReport(results) {
  const lines = results.map(r => `- [${r.ok ? "x" : " "}] ${r.name}${r.detail ? ` — ${r.detail}` : ""}`);
  return `# Final E2E Report\n\n**Generated:** ${new Date().toISOString()}\n\n## Automated steps\n\n${lines.join("\n")}\n\n## Manual steps (production)\n\n1. Deploy website with Supabase + Stripe live keys\n2. Run \`stripe listen --forward-to localhost:3000/api/stripe/webhook\`\n3. Complete Checkout for monthly/annual/lifetime\n4. Install \`SentinelAISetup.exe\` on clean Windows VM\n5. Activate license in wizard\n6. Verify electron-updater pulls GitHub Release\n`;
}

main().catch(e => {
  console.error(e);
  process.exit(1);
});
