// PS5 takip — Telegram /durum komutu (Cloudflare Worker, webhook)
// Telegram -> POST / (X-Telegram-Bot-Api-Secret-Token doğrulanır) -> state.json okunur -> cevap
// Kurulum: GET /setup?key=<WEBHOOK_SECRET> Telegram webhook'unu bu adrese bağlar.

const TZ = "America/New_York";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/setup") {
      if (url.searchParams.get("key") !== env.WEBHOOK_SECRET) return new Response("forbidden", { status: 403 });
      const r1 = await tg(env, "setWebhook", {
        url: `${url.origin}/`,
        secret_token: env.WEBHOOK_SECRET,
        allowed_updates: ["message"],
        drop_pending_updates: true,
      });
      const r2 = await tg(env, "setMyCommands", {
        commands: [{ command: "durum", description: "Sistem durumu ve en düşük fiyat" }],
      });
      return Response.json({ webhook: r1.ok, commands: r2.ok, description: r1.description });
    }

    if (request.method !== "POST") return new Response("ok");
    if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("ok");
    }
    const msg = update.message;
    // Sadece sahibin sohbeti; diğer herkes sessizce yok sayılır.
    if (!msg || String(msg.chat && msg.chat.id) !== String(env.CHAT_ID)) return new Response("ok");

    const text = (msg.text || "").trim().toLowerCase();
    const reply = /^\/?(durum|status)(@\w+)?$/.test(text)
      ? await statusMessage(env)
      : "Komutlar:\n/durum — sistem durumu, son kontrol zamanı ve görülen en düşük fiyat";
    await tg(env, "sendMessage", {
      chat_id: env.CHAT_ID, text: reply, parse_mode: "HTML", disable_web_page_preview: true,
    });
    return new Response("ok");
  },
};

async function tg(env, method, body) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

function esc(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function ago(iso) {
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return "az önce";
  if (min < 60) return `${min} dk önce`;
  return `${Math.floor(min / 60)} sa ${min % 60} dk önce`;
}

function localTime(iso) {
  return new Date(iso).toLocaleString("tr-TR", {
    timeZone: TZ, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

async function statusMessage(env) {
  let s;
  try {
    const r = await fetch(`${env.STATE_URL}?t=${Date.now()}`, { cf: { cacheTtl: 0 } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    s = await r.json();
  } catch (e) {
    return `🔴 <b>Durum okunamadı</b> (${esc(e.message)}). GitHub'a ulaşılamıyor olabilir; birkaç dakika sonra tekrar dene.`;
  }

  const lines = [];
  const lastIso = (s.last_run && s.last_run.ts) || s.last_check;
  const ageMin = lastIso ? (Date.now() - new Date(lastIso).getTime()) / 60000 : Infinity;
  const healthy = ageMin <= 35;
  const errors = Object.entries(s.errors || {});
  const broken = errors.filter(([, e]) => e.count > 0);

  lines.push(
    !healthy ? "🔴 <b>Uyarı: son kontrol çok eski, sistem durmuş olabilir</b>"
      : broken.length ? "🟡 <b>Sistem çalışıyor, bazı kaynaklarda sorun var</b>"
      : "🟢 <b>Sistem çalışıyor</b>",
  );
  lines.push("");
  lines.push(lastIso ? `<b>Son kontrol:</b> ${localTime(lastIso)} (${ago(lastIso)})` : "<b>Son kontrol:</b> bilinmiyor");
  if (s.last_run) lines.push(`<b>Son çalışma:</b> ${s.last_run.deals} ilan incelendi, ${s.last_run.sent} bildirim`);

  if (errors.length) {
    lines.push("", "<b>Kaynaklar:</b>");
    for (const [name, e] of errors) {
      lines.push(`${e.count === 0 ? "✅" : "⚠️"} ${esc(name)}${e.count ? ` — ${e.count} hata (${esc(e.last)})` : ""}`);
    }
  }

  lines.push("");
  const obs = s.observations || [];
  if (obs.length) {
    const best = obs.reduce((a, b) => (b.price < a.price ? b : a));
    lines.push(`<b>Son 24 saatte en düşük:</b> $${best.price.toFixed(2)} — ${esc(best.store)}`);
    lines.push(`<a href="${esc(best.link)}">${esc(best.title.slice(0, 90))}</a>`);
  } else {
    lines.push("<b>Son 24 saatte en düşük:</b> filtreye uyan fiyat görülmedi");
  }
  lines.push(`<b>Eşik:</b> $${Number(s.price_limit == null ? 500 : s.price_limit).toFixed(0)}`);

  const notified = Object.values(s.notified || {}).sort((a, b) => (a.ts < b.ts ? 1 : -1));
  if (notified.length) {
    const n = notified[0];
    const p = n.price != null ? `$${n.price.toFixed(2)} — ` : "";
    lines.push(`<b>Son bildirilen fırsat:</b> ${p}${esc(n.title.slice(0, 80))} (${ago(n.ts)})`);
  } else {
    lines.push("<b>Bildirilen fırsat:</b> henüz yok");
  }
  lines.push("", "<i>Veri birkaç dakika gecikmeli olabilir.</i>");
  return lines.join("\n");
}
