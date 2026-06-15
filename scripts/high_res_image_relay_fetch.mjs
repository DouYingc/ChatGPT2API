import http from "node:http";
import https from "node:https";
import tls from "node:tls";

const chunks = [];

for await (const chunk of process.stdin) {
  chunks.push(chunk);
}

function write(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

const startedAt = Date.now();
let proxyUsed = false;

function buildJsonBody(input) {
  const body = Buffer.from(JSON.stringify(input.body || {}));
  return {
    body,
    headers: {
      "Content-Type": "application/json",
      "Content-Length": body.length,
    },
  };
}

function buildMultipartBody(input) {
  const boundary = `----chatgpt2api-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const chunks = [];
  const append = (value) => chunks.push(Buffer.isBuffer(value) ? value : Buffer.from(String(value)));
  const data = input.data && typeof input.data === "object" ? input.data : {};
  for (const [key, value] of Object.entries(data)) {
    if (value === undefined || value === null) continue;
    append(`--${boundary}\r\n`);
    append(`Content-Disposition: form-data; name="${String(key).replaceAll('"', "%22")}"\r\n\r\n`);
    append(`${String(value)}\r\n`);
  }
  const imageField = String(input.imageField || "image[]");
  const images = Array.isArray(input.images) ? input.images : [];
  images.forEach((encoded, index) => {
    const image = Buffer.from(String(encoded || ""), "base64");
    append(`--${boundary}\r\n`);
    append(`Content-Disposition: form-data; name="${imageField.replaceAll('"', "%22")}"; filename="image_${index + 1}.png"\r\n`);
    append("Content-Type: image/png\r\n\r\n");
    append(image);
    append("\r\n");
  });
  append(`--${boundary}--\r\n`);
  const body = Buffer.concat(chunks);
  return {
    body,
    headers: {
      "Content-Type": `multipart/form-data; boundary=${boundary}`,
      "Content-Length": body.length,
    },
  };
}

class HttpProxyAgent extends https.Agent {
  constructor(proxyUrl) {
    super({ keepAlive: false });
    this.proxyUrl = new URL(proxyUrl);
  }

  createConnection(options, callback) {
    const targetHost = String(options.host || options.hostname || "");
    const targetPort = Number(options.port || 443);
    let done = false;
    const finish = (error, socket) => {
      if (done) return;
      done = true;
      callback(error, socket);
    };
    const connectReq = http.request({
      host: this.proxyUrl.hostname,
      port: Number(this.proxyUrl.port || 80),
      method: "CONNECT",
      path: `${targetHost}:${targetPort}`,
      headers: {
        Host: `${targetHost}:${targetPort}`,
      },
    });

    connectReq.once("connect", (res, socket) => {
      if (res.statusCode !== 200) {
        socket.destroy();
        finish(new Error(`Proxy CONNECT failed: HTTP ${res.statusCode}`));
        return;
      }
      const tlsSocket = tls.connect({ socket, servername: targetHost });
      tlsSocket.once("secureConnect", () => finish(null, tlsSocket));
      tlsSocket.once("error", (error) => finish(error));
    });
    connectReq.once("error", (error) => finish(error));
    connectReq.end();
  }
}

function requestWithHttps(input, timeoutMs) {
  return new Promise((resolve, reject) => {
    const targetUrl = new URL(input.url);
    const built = input.multipart ? buildMultipartBody(input) : buildJsonBody(input);
    const proxy = String(input.proxy || "").trim();
    const options = {
      method: "POST",
      headers: {
        Authorization: `Bearer ${input.apiKey}`,
        Accept: input.multipart && String(input.data?.stream || "").toLowerCase() === "true"
          ? "text/event-stream, application/json;q=0.9, */*;q=0.8"
          : "application/json, text/plain, */*",
        ...built.headers,
      },
      timeout: timeoutMs,
      agent: proxy ? new HttpProxyAgent(proxy) : undefined,
    };
    const req = https.request(targetUrl, options, (response) => {
      const responseChunks = [];
      response.on("data", (chunk) => responseChunks.push(chunk));
      response.once("end", () => {
        const text = Buffer.concat(responseChunks).toString("utf8");
        let json = null;
        if (text) {
          try {
            json = JSON.parse(text);
          } catch {
            json = null;
          }
        }
        resolve({
          ok: response.statusCode >= 200 && response.statusCode < 300,
          status: response.statusCode || 0,
          statusText: response.statusMessage || "",
          contentType: response.headers["content-type"] || "",
          json,
          text: json === null ? text : "",
          durationMs: Date.now() - startedAt,
          proxyUsed: Boolean(proxy),
        });
      });
    });
    req.once("timeout", () => {
      req.destroy(new Error("request timeout"));
    });
    req.once("error", reject);
    req.end(built.body);
  });
}

try {
  const input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  const controller = new AbortController();
  const timeoutMs = Number(input.timeoutMs || 600000);
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const proxy = String(input.proxy || "").trim();
    if (proxy || input.multipart) {
      proxyUsed = Boolean(proxy);
      write(await requestWithHttps(input, timeoutMs));
    } else {
      const response = await fetch(input.url, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${input.apiKey}`,
          "Content-Type": "application/json",
        },
        cache: "no-store",
        body: JSON.stringify(input.body || {}),
        signal: controller.signal,
      });

      const contentType = response.headers.get("content-type") || "";
      const text = await response.text();
      let json = null;
      if (text) {
        try {
          json = JSON.parse(text);
        } catch {
          json = null;
        }
      }

      write({
        ok: response.ok,
        status: response.status,
        statusText: response.statusText,
        contentType,
        json,
        text: json === null ? text : "",
        durationMs: Date.now() - startedAt,
        proxyUsed,
      });
    }
  } finally {
    clearTimeout(timer);
  }
} catch (error) {
  write({
    ok: false,
    status: 0,
    networkError: error instanceof Error ? error.message : String(error),
    errorName: error instanceof Error ? error.name : "",
    cause: error instanceof Error && error.cause ? String(error.cause) : "",
    causeCode: error instanceof Error && error.cause && typeof error.cause === "object" && "code" in error.cause ? String(error.cause.code) : "",
    durationMs: Date.now() - startedAt,
    proxyUsed,
  });
}
