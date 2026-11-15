// Yerel test: node bot/test-worker.mjs  (gerçek ağ isteği atmaz; Telegram ve GitHub taklit edilir)
import { readFileSync } from "node:fs";
import worker from "./worker.js";

const realState = JSON.parse(readFileSync(new URL("../state.json", import.meta.url), "utf8"));
const env = {
  TELEGRAM_BOT_TOKEN: "TEST", CHAT_ID: "111", WEBHOOK_SECRET: "s3cret", GITHUB_TOKEN: "ghtest",
  STATE_URL: "https://example.invalid/state.json", REPO: "o/r",
};

let state = realState;
const vars = { PRICE_LIMIT: "500", PAUSED: "false" };
const sent = [];
const dispatches = [];
globalThis.fetch = async (url, init = {}) => {
  url = String(url);
  if (url.startsWith(env.STATE_URL)) return new Response(JSON.stringify(state), { status: 200 });
  if (url.includes("api.telegram.org")) { sent.push(JSON.parse(init.body)); return Response.json({ ok: true }); }
  const m = url.match(/^https:\/\/api\.github\.com\/repos\/o\/r(\/.*)$/);
  if (m) {
    if (init.headers.Authorization !== "Bearer ghtest") return new Response("{}", { status: 401 });
    const v = m[1].match(/^\/actions\/variables\/(\w+)$/);
    if (v && (init.method || "GET") === "GET") return Response.json({ name: v[1], value: vars[v[1]] });
    if (v && init.method === "PATCH") { vars[v[1]] = JSON.parse(init.body).value; return new Response(null, { status: 204 }); }
    if (m[1] === "/actions/workflows/takip.yml/dispatches" && init.method === "POST") {
      dispatches.push(JSON.parse(init.body)); return new Response(null, { status: 204 });
    }
  }
  throw new Error("beklenmeyen istek " + url);
};

const say = async (text, chat = 111, secret = env.WEBHOOK_SECRET) => {
  sent.length = 0;
  const r = await worker.fetch(new Request("https://w.example/", {
    method: "POST", headers: { "X-Telegram-Bot-Api-Secret-Token": secret, "content-type": "application/json" },
    body: JSON.stringify({ message: { chat: { id: chat }, text } }),
  }), env);
  return { status: r.status, text: sent[0] && sent[0].text };
};

let fail = 0;
const check = (name, cond, extra = "") => { console.log((cond ? "✓ " : "✗ ") + name + (cond ? "" : "  → " + extra)); if (!cond) fail++; };

// Güvenlik
check("başka sohbet yok sayılır", (await say("/durdur", 999)).text === undefined && vars.PAUSED === "false");
check("yanlış gizli anahtar reddedilir", (await say("/durdur", 111, "yanlis")).status === 403 && vars.PAUSED === "false");

// Okuma komutları
let r = await say("/durum");
check("/durum", r.text.includes("Son kontrol") && r.text.includes("Sistem çalışıyor"), r.text);
console.log("\n--- /durum ---\n" + r.text);
r = await say("/fiyatlar");
check("/fiyatlar", r.text.includes("mağaza mağaza") || r.text.includes("görülmedi"), r.text);
console.log("\n--- /fiyatlar ---\n" + r.text);
r = await say("/son");
check("/son (boş)", r.text.includes("Henüz"), r.text);
state = { ...realState, notified: { a: { price: 449, ts: new Date().toISOString(), title: "PS5 Slim Disc $449" } } };
r = await say("/son");
check("/son (dolu)", r.text.includes("$449.00"), r.text);
state = realState;

// Eşik
check("/esik (göster)", (await say("/esik")).text.includes("$500"));
check("/esik 450 değiştirir", (await say("/esik 450")).text.includes("$450") && vars.PRICE_LIMIT === "450");
check("/esik saçma değer reddedilir", (await say("/esik 5")).text.includes("100 ile 2000") && vars.PRICE_LIMIT === "450");
check("/eşik $480 (Türkçe karakter ve $)", (await say("/eşik $480")).text.includes("$480") && vars.PRICE_LIMIT === "480");

// Kontrol (12 dk kuralı)
state = { ...realState, last_check: new Date(Date.now() - 3 * 60000).toISOString() };
r = await say("/kontrol");
check("/kontrol 12 dk dolmadan başlatmaz", r.text.includes("dk sonra tekrar dene") && dispatches.length === 0, r.text);
state = { ...realState, last_check: new Date(Date.now() - 20 * 60000).toISOString() };
r = await say("/kontrol");
check("/kontrol başlatır", r.text.includes("başlatıldı") && dispatches.length === 1 && dispatches[0].inputs.mode === "run", r.text);

// Durdur / devam
check("/durdur", (await say("/durdur")).text.includes("duraklatıldı") && vars.PAUSED === "true");
check("/durum duraklatmayı gösterir", (await say("/durum")).text.includes("duraklatıldı"));
check("/kontrol duraklatılmışken çalışmaz", (await say("/kontrol")).text.includes("/devam") && dispatches.length === 1);
check("/devam", (await say("/devam")).text.includes("yeniden başladı") && vars.PAUSED === "false");

// Yardım ve hatalı anahtar
check("bilinmeyen mesaj → yardım", (await say("merhaba")).text.includes("/esik 450"));
const saved = env.GITHUB_TOKEN; env.GITHUB_TOKEN = "yanlis";
r = await say("/esik 400");
check("GitHub anahtarı geçersizse anlaşılır hata", r.text.includes("GitHub 401") && vars.PRICE_LIMIT === "480", r.text);
env.GITHUB_TOKEN = saved;

console.log(fail ? `\n${fail} test BAŞARISIZ` : "\nTüm testler geçti");
process.exit(fail ? 1 : 0);
