/* Sentinel renderer auth shim.
 *
 * Loaded by every renderer HTML page BEFORE any business JS. Reads the auth
 * token from one of two sources (depending on the window's webPreferences):
 *   - window.sentinelAuth.token  (contextIsolation: true, exposed by preload)
 *   - process.env.SENTINELAI_AUTH_TOKEN  (nodeIntegration: true, contextIsolation: false)
 *
 * Wraps window.fetch and XMLHttpRequest.send so every call to the Sentinel
 * backend automatically attaches "Authorization: Bearer <token>". Also patches
 * window.io (Socket.IO client) so the websocket handshake carries the token
 * via auth payload — server-side gate accepts the same token.
 *
 * Same-origin / non-Sentinel URLs are left alone.
 */
(function () {
  'use strict';

  var token = '';
  try {
    if (window.sentinelAuth && window.sentinelAuth.token) {
      token = String(window.sentinelAuth.token);
    } else if (typeof process !== 'undefined' && process.env && process.env.SENTINELAI_AUTH_TOKEN) {
      token = String(process.env.SENTINELAI_AUTH_TOKEN);
    }
  } catch (_) {}

  if (!token) {
    console.warn('[auth_shim] no SENTINELAI_AUTH_TOKEN available — API calls will return 401');
  }

  window.__SENTINEL_AUTH__ = token;

  // ── fetch wrapper ────────────────────────────────────────────────────────
  var SENTINEL_HOSTS = ['127.0.0.1:5001', 'localhost:5001'];

  function isSentinelUrl(u) {
    if (!u) return false;
    var s = String(u);
    if (s.startsWith('/')) return true;            // same-origin (Flask template)
    for (var i = 0; i < SENTINEL_HOSTS.length; i++) {
      if (s.indexOf('://' + SENTINEL_HOSTS[i]) !== -1) return true;
    }
    return false;
  }

  var origFetch = window.fetch ? window.fetch.bind(window) : null;
  if (origFetch) {
    window.fetch = function (input, init) {
      try {
        var url = (typeof input === 'string') ? input : (input && input.url) || '';
        if (!isSentinelUrl(url) || !token) {
          return origFetch(input, init);
        }
        init = init || {};
        var headers = new Headers(init.headers || (input && input.headers) || {});
        if (!headers.has('Authorization')) {
          headers.set('Authorization', 'Bearer ' + token);
        }
        init.headers = headers;
        return origFetch(input, init);
      } catch (e) {
        return origFetch(input, init);
      }
    };
  }

  // ── XHR wrapper ──────────────────────────────────────────────────────────
  var XHR = window.XMLHttpRequest;
  if (XHR && XHR.prototype && XHR.prototype.open) {
    var origOpen = XHR.prototype.open;
    var origSend = XHR.prototype.send;
    XHR.prototype.open = function (method, url) {
      this.__sentinelUrl = url;
      return origOpen.apply(this, arguments);
    };
    XHR.prototype.send = function (body) {
      try {
        if (token && isSentinelUrl(this.__sentinelUrl)) {
          this.setRequestHeader('Authorization', 'Bearer ' + token);
        }
      } catch (_) {}
      return origSend.apply(this, arguments);
    };
  }

  // ── Socket.IO wrapper ────────────────────────────────────────────────────
  // socket.io client is loaded later via <script src="/socket.io/socket.io.js">.
  // We wait until window.io exists and wrap it so connect options carry the token.
  function wrapIO() {
    if (typeof window.io !== 'function') return false;
    if (window.io.__sentinelWrapped) return true;
    var origIO = window.io;
    var wrapped = function (uri, opts) {
      if (typeof uri === 'object' && uri !== null && opts === undefined) {
        opts = uri;
        uri = undefined;
      }
      opts = opts || {};
      if (token) {
        opts.auth = opts.auth || {};
        if (!opts.auth.token) opts.auth.token = token;
        opts.extraHeaders = opts.extraHeaders || {};
        if (!opts.extraHeaders.Authorization) {
          opts.extraHeaders.Authorization = 'Bearer ' + token;
        }
      }
      return (uri === undefined) ? origIO(opts) : origIO(uri, opts);
    };
    wrapped.__sentinelWrapped = true;
    // Preserve attached properties (io.connect, io.Manager, etc.)
    for (var k in origIO) {
      if (Object.prototype.hasOwnProperty.call(origIO, k)) wrapped[k] = origIO[k];
    }
    window.io = wrapped;
    return true;
  }

  if (!wrapIO()) {
    var tries = 0;
    var iv = setInterval(function () {
      tries += 1;
      if (wrapIO() || tries > 100) clearInterval(iv);
    }, 50);
  }
})();
