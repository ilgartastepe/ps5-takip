// PS5 takip — Telegram komutları (Cloudflare Worker, webhook)
// Telegram -> POST / (X-Telegram-Bot-Api-Secret-Token doğrulanır) -> komut işlenir -> cevap
// Kurulum: GET /setup?key=<WEBHOOK_SECRET> webhook'u ve komut menüsünü ayarlar.
//
// Gizli değerler: TELEGRAM_BOT_TOKEN, CHAT_ID, WEBHOOK_SECRET,
//                 GITHUB_TOKEN (sadece bu depo: Actions + Variables yazma) — /esik, /kontrol, /durdur, /devam için

const TZ = "America/New_York";
const MIN_INTERVAL_MIN = 12; // tracker.py ile aynı: kaynaklara en fazla ~15 dk'da bir gidilir

const COMMANDS = [
  { command: "durum", description: "Sistem durumu ve en düşük fiyat" },
  { command: "fiyatlar", description: "Son 24 saatte mağaza mağaza en düşük fiyatlar" },
  { command: "son", description: "Son bildirilen fırsatlar" },
  { command: "kontrol", description: "Şimdi kontrol et" },
  { command: "esik", description: "Fiyat eşiğini göster/değiştir: /esik 450" },
  { command: "durdur", description: "Takibi duraklat" },
  { command: "devam", description: "Takibi yeniden başlat" },
];

const HELP = [
  "<b>Komutlar</b>",
  "/durum — sistem durumu, son kontrol, en düşük fiyat",
  "/fiyatlar — son 24 saatte mağaza mağaza en düşük fiyatlar",
  "/son — son bildirilen fırsatlar",
  "/kontrol — beklemeden şimdi kontrol et",
  "/esik — eşiği göster; /esik 450 — eşiği 450 $ yap",
  "/durdur — takibi duraklat (konsolu aldığında)",
  "/devam — takibi yeniden başlat",
].join("\n");

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/setup") {
      if (url.searchParams.get("key") !== env.WEBHOOK_SECRET) return new Response("forbidden", { status: 403 });
      const r1 = await tg(env, "setWebhook", {
        url: `${url.origin}/`, secret_token: env.WEBHOOK_SECRET, allowed_updates: ["message"], drop_pending_updates: true,
      });
      const r2 = await tg(env, "setMyCommands", { commands: COMMANDS });
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

    let reply;
    try {
      reply = await handle(env, (msg.text || "").trim());
    } catch (e) {
      reply = `🔴 Komut işlenirken hata oluştu: ${esc(e.message)}`;
    }
    await tg(env, "sendMessage", { chat_id: env.CHAT_ID, text: reply, parse_mode: "HTML", disable_web_page_preview: true });
    return new Response("ok");
  },
};

async function handle(env, text) {
  const m = text.toLowerCase().match(/^\/?([a-zçğıöşü]+)(?:@\w+)?(?:\s+(.*))?$/);
  const cmd = m ? m[1] : "";
  const arg = m && m[2] ? m[2].trim() : "";
  switch (cmd) {
    case "durum": case "status": return statusMessage(env);
    case "fiyatlar": case "fiyat": return pricesMessage(env);
    case "son": return recentMessage(env);
    case "kontrol": return checkNow(env);
    case "esik": case "eşik": return threshold(env, arg);
    case "durdur": return setPaused(env, true);
    case "devam": return setPaused(env, false);
    default: return HELP;
  }
}

// ------------------------------------------------------------------ yardımcılar
async function tg(env, method, body) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
  return r.json();
}

async function gh(env, method, path, body) {
  if (!env.GITHUB_TOKEN) throw new Error("GitHub anahtarı (GITHUB_TOKEN) tanımlı değil");
  const r = await fetch(`https://api.github.com/repos/${env.REPO}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "ps5-takip-bot",
      "content-type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    const hint = r.status === 401 || r.status === 403 ? " (anahtar geçersiz, süresi dolmuş ya da yetkisi eksik)" : "";
    throw new Error(`GitHub ${r.status}${hint}`);
  }
  return r.status === 204 ? null : r.json();
}

async function getVar(env, name) {
  const v = await gh(env, "GET", `/actions/variables/${name}`);
  return v.value;
}

async function setVar(env, name, value) {
  await gh(env, "PATCH", `/actions/variables/${name}`, { name, value: String(value) });
}

async function isPaused(env) {
  try {
    return ["1", "true", "evet", "yes"].includes(String(await getVar(env, "PAUSED")).toLowerCase());
  } catch {
    return null; // bilinmiyor (anahtar yok vb.)
  }
}

async function loadState(env) {
  const r = await fetch(`${env.STATE_URL}?t=${Date.now()}`, { cf: { cacheTtl: 0 } });
  if (!r.ok) throw new Error(`durum dosyası okunamadı (HTTP ${r.status})`);
  return r.json();
}

function esc(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function minutesSince(iso) {
  return (Date.now() - new Date(iso).getTime()) / 60000;
}

function ago(iso) {
  const min = Math.round(minutesSince(iso));
  if (min < 1) return "az önce";
  if (min < 60) return `${min} dk önce`;
  if (min < 48 * 60) return `${Math.floor(min / 60)} sa ${min % 60} dk önce`;
  return `${Math.floor(min / 1440)} gün önce`;
}

function localTime(iso) {
  return new Date(iso).toLocaleString("tr-TR", {
    timeZone: TZ, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

const money = (p) => `$${Number(p).toFixed(2)}`;

// ------------------------------------------------------------------ komutlar
async function statusMessage(env) {
  let s;
  try {
    s = await loadState(env);
  } catch (e) {
    return `🔴 <b>Durum okunamadı</b> (${esc(e.message)}). GitHub'a ulaşılamıyor olabilir; birkaç dakika sonra tekrar dene.`;
  }
  const paused = await isPaused(env);
  const lines = [];
  const lastIso = (s.last_run && s.last_run.ts) || s.last_check;
  const healthy = lastIso ? minutesSince(lastIso) <= 35 : false;
  const errors = Object.entries(s.errors || {});
  const broken = errors.filter(([, e]) => e.count > 0);

  lines.push(
    paused ? "⏸️ <b>Takip duraklatıldı</b> — yeniden başlatmak için /devam"
      : !healthy ? "🔴 <b>Uyarı: son kontrol çok eski, sistem durmuş olabilir</b>"
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
    lines.push(`<b>Son 24 saatte en düşük:</b> ${money(best.price)} — ${esc(best.store)}`);
    lines.push(`<a href="${esc(best.link)}">${esc(best.title.slice(0, 90))}</a>`);
  } else {
    lines.push("<b>Son 24 saatte en düşük:</b> filtreye uyan fiyat görülmedi");
  }
  lines.push(`<b>Eşik:</b> $${Number(s.price_limit == null ? 500 : s.price_limit).toFixed(0)}`);

  const notified = sortedNotified(s);
  lines.push(notified.length
    ? `<b>Son bildirilen fırsat:</b> ${notified[0].price != null ? money(notified[0].price) + " — " : ""}${esc(notified[0].title.slice(0, 80))} (${ago(notified[0].ts)})`
    : "<b>Bildirilen fırsat:</b> henüz yok");
  lines.push("", "<i>Veri birkaç dakika gecikmeli olabilir. Tüm komutlar için /yardim</i>");
  return lines.join("\n");
}

function sortedNotified(s) {
  return Object.values(s.notified || {}).sort((a, b) => (a.ts < b.ts ? 1 : -1));
}

async function pricesMessage(env) {
  const s = await loadState(env);
  const obs = s.observations || [];
  if (!obs.length) return "Son 24 saatte filtreye uyan (sıfır, PS5 Slim, güvenilir mağaza) bir fiyat görülmedi.";
  const byStore = {};
  for (const o of obs) {
    if (!byStore[o.store] || o.price < byStore[o.store].price) byStore[o.store] = o;
  }
  const rows = Object.values(byStore).sort((a, b) => a.price - b.price);
  const limit = Number(s.price_limit == null ? 500 : s.price_limit);
  const lines = ["<b>Son 24 saatte mağaza mağaza en düşük PS5 Slim fiyatları</b>", ""];
  for (const o of rows) {
    const store = o.store === "?" ? "Belirlenemedi" : o.store;
    lines.push(`${o.price <= limit ? "💰" : "•"} <b>${money(o.price)}</b> — ${esc(store)}`);
    lines.push(`   <a href="${esc(o.link)}">${esc(o.title.slice(0, 70))}</a>`);
  }
  lines.push("", `Eşik: $${limit.toFixed(0)}. Eşiğin üstündekiler bildirilmez, sadece bilgi içindir.`);
  return lines.join("\n");
}

async function recentMessage(env) {
  const s = await loadState(env);
  const items = sortedNotified(s).slice(0, 5);
  if (!items.length) return "Henüz bildirilen bir fırsat yok.";
  const lines = ["<b>Son bildirilen fırsatlar</b>", ""];
  for (const n of items) {
    lines.push(`• ${n.price != null ? `<b>${money(n.price)}</b> — ` : ""}${esc(n.title.slice(0, 80))} <i>(${ago(n.ts)})</i>`);
  }
  return lines.join("\n");
}

async function checkNow(env) {
  if (await isPaused(env)) return "⏸️ Takip duraklatılmış. Önce /devam yaz.";
  const s = await loadState(env);
  if (s.last_check && minutesSince(s.last_check) < MIN_INTERVAL_MIN) {
    const wait = Math.ceil(MIN_INTERVAL_MIN - minutesSince(s.last_check));
    return `Son kontrol ${ago(s.last_check)} yapıldı. Mağaza sitelerine fazla istek gitmemesi için en az ${MIN_INTERVAL_MIN} dk aralık var; ${wait} dk sonra tekrar dene. Sıradaki otomatik kontrol zaten yakında.`;
  }
  await gh(env, "POST", "/actions/workflows/takip.yml/dispatches", { ref: "main", inputs: { mode: "run" } });
  return "🔄 Kontrol başlatıldı. Yaklaşık 1 dakika sürer. Uygun fırsat çıkarsa ayrıca bildirim gelir; sonucu /durum ile görebilirsin.";
}

async function threshold(env, arg) {
  if (!arg) {
    const v = await getVar(env, "PRICE_LIMIT");
    return `Şu anki eşik: <b>$${esc(v)}</b> (vergisiz). Değiştirmek için örneğin: /esik 450`;
  }
  const n = Number(arg.replace(/[$,\s]/g, ""));
  if (!Number.isFinite(n) || n < 100 || n > 2000) {
    return "Geçerli bir tutar yaz, 100 ile 2000 arasında. Örnek: /esik 450";
  }
  const value = Math.round(n);
  await setVar(env, "PRICE_LIMIT", value);
  return `✅ Eşik <b>$${value}</b> olarak ayarlandı. Bir sonraki kontrolden itibaren geçerli. Daha önce bildirilmiş fırsatlar tekrar gönderilmez; fiyatı düşerse yine bildirilir.`;
}

async function setPaused(env, paused) {
  await setVar(env, "PAUSED", paused ? "true" : "false");
  return paused
    ? "⏸️ Takip duraklatıldı. Fırsat, günlük durum ve hata mesajları gelmeyecek. Yeniden başlatmak için /devam yaz."
    : "▶️ Takip yeniden başladı. Bir sonraki kontrol en geç 15 dk içinde; hemen istersen /kontrol yaz.";
}
