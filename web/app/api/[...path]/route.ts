// Server-side proxy to the hackfront API (FastAPI). The browser only ever talks to this same-origin route; the API
// token (HACKFRONT_API_TOKEN) is added here on the server and never reaches the browser. Streams SSE responses.
export const maxDuration = 300; // syncs and investigations stream for minutes (platform default is much shorter)

const BASE = (process.env.HACKFRONT_API ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
const TOKEN = process.env.HACKFRONT_API_TOKEN;

async function proxy(req: Request, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const { path } = await ctx.params;
  const target = `${BASE}/api/${path.map(encodeURIComponent).join("/")}${new URL(req.url).search}`;

  const headers = new Headers();
  for (const name of ["content-type", "accept"]) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (TOKEN) headers.set("authorization", `Bearer ${TOKEN}`);

  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? req.body : undefined,
      // @ts-expect-error `duplex` is required to stream a request body in Node's fetch but is missing from the DOM types
      duplex: "half",
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return Response.json({ detail: "The backend is unreachable" }, { status: 502 });
  }

  const out = new Headers({ "cache-control": "no-store", "x-accel-buffering": "no" });
  const type = upstream.headers.get("content-type");
  if (type) out.set("content-type", type);
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as DELETE };
