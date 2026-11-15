// Yerel test: node bot/test-worker.mjs  (gerçek ağ isteği atmaz)
import { readFileSync } from "node:fs";
import worker from "./worker.js";

const state = readFileSync(new URL("../state.json", import.meta.url), "utf8");
const env = { TELEGRAM_BOT_TOKEN: "TEST", CHAT_ID: "111", WEBHOOK_SECRET: "s3cret", STATE_URL: "https://example.invalid/state.json" };
const sent = [];
globalThis.fetch = async (url, init) => {
  if (String(url).startsWith(env.STATE_URL)) return new Response(state, { status: 200 });
  if (String(url).includes("api.telegram.org")) { sent.push(JSON.parse(init.body)); return Response.json({ ok: true }); }
  throw new Error("beklenmeyen istek " + url);
};

const call = (body, secret = env.WEBHOOK_SECRET) => worker.fetch(new Request("https://w.example/", {
  method: "POST", headers: { "X-Telegram-Bot-Api-Secret-Token": secret, "content-type": "application/json" },
  body: JSON.stringify(body),
}), env);

let fail = 0;
const check = (name, cond) => { console.log((cond ? "✓ " : "✗ ") + name); if (!cond) fail++; };

let r = await call({ message: { chat: { id: 111 }, text: "/durum" } });
check("sahibin /durum komutuna cevap verilir", r.status === 200 && sent.length === 1 && sent[0].text.includes("Son kontrol"));
console.log("\n--- örnek cevap ---\n" + (sent[0] && sent[0].text) + "\n-------------------\n");

sent.length = 0;
await call({ message: { chat: { id: 999 }, text: "/durum" } });
check("başka sohbet yok sayılır", sent.length === 0);

r = await call({ message: { chat: { id: 111 }, text: "/durum" } }, "yanlis");
check("yanlış gizli anahtar reddedilir (403)", r.status === 403 && sent.length === 0);

await call({ message: { chat: { id: 111 }, text: "merhaba" } });
check("bilinmeyen mesaja yardım metni", sent.length === 1 && sent[0].text.includes("/durum"));

process.exit(fail ? 1 : 0);
