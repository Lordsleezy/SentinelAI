/**
 * Netlify Function: log download to Supabase, then redirect to installer.
 * Configure in netlify.toml:
 *   /api/download/sentinelai -> download-sentinelai
 */
require("dotenv").config({ path: require("path").join(__dirname, "../../.env") });

const downloadHandler = require("../../lib/download_handler");
const { clientIpFromNetlifyEvent } = require("../../lib/client_ip");

exports.handler = async (event) => {
  const ip = clientIpFromNetlifyEvent(event);
  const userAgent = event.headers["user-agent"] || event.headers["User-Agent"] || "";
  const referrer = event.headers.referer || event.headers.referrer || "";
  const params = event.queryStringParameters || {};
  const version = params.version || "";

  try {
    const target = await downloadHandler.handleDownloadRequest({
      ip,
      userAgent,
      referrer,
      version,
      channel: params.channel || "windows",
    });
    return {
      statusCode: 302,
      headers: {
        Location: target.downloadUrl,
        "Cache-Control": "no-store",
      },
      body: "",
    };
  } catch (e) {
    console.error("[download-sentinelai]", e);
    const fallback =
      process.env.DOWNLOAD_REDIRECT_URL ||
      "https://github.com/Lordsleezy/SentinelAI/releases/latest/download/SentinelAISetup.exe";
    return {
      statusCode: 302,
      headers: { Location: fallback, "Cache-Control": "no-store" },
      body: "",
    };
  }
};
