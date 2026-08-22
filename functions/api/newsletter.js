// Cloudflare Pages Function: newsletter signup proxy.
// Receives POST {email}, forwards to MailerLite API with the server-side
// token (MAILERLITE_API_TOKEN Pages env var), returns JSON. The browser
// never sees the token.
export async function onRequestPost(context) {
  const { request, env } = context;
  const token = env.MAILERLITE_API_TOKEN;
  if (!token) {
    return new Response(JSON.stringify({ ok: false, error: "not configured" }), {
      status: 500, headers: { "Content-Type": "application/json" },
    });
  }
  let email = "";
  try {
    const body = await request.json();
    email = String(body.email || "").trim().toLowerCase();
  } catch {
    // fall through
  }
  if (!email || !email.includes("@")) {
    return new Response(JSON.stringify({ ok: false, error: "invalid email" }), {
      status: 400, headers: { "Content-Type": "application/json" },
    });
  }
  const groupId = env.MAILERLITE_GROUP_ID || "";
  const payload = { email };
  if (groupId) payload.groups = [groupId];
  try {
    const r = await fetch("https://connect.mailerlite.com/api/subscribers", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
        "Accept": "application/json",
      },
      body: JSON.stringify(payload),
    });
    const data = await r.json();
    if (!r.ok) {
      return new Response(JSON.stringify({ ok: false, error: data.message || "MailerLite error" }), {
        status: r.status, headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ ok: true, id: (data.data || {}).id }), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  } catch (e) {
    return new Response(JSON.stringify({ ok: false, error: String(e && e.message || e) }), {
      status: 502, headers: { "Content-Type": "application/json" },
    });
  }
}
