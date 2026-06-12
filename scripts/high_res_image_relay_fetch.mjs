const chunks = [];

for await (const chunk of process.stdin) {
  chunks.push(chunk);
}

function write(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

const startedAt = Date.now();

try {
  const input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  const controller = new AbortController();
  const timeoutMs = Number(input.timeoutMs || 600000);
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
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
    });
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
  });
}
