import assert from "node:assert/strict";
import test from "node:test";
import worker from "./worker.mjs";

const origin = "https://radar.example.workers.dev";
const secret = "test-webhook-secret";
const assets = new Map([
  ["/index.json", {
    help: "/sektor banka", status: "Son tarama",
    priceExpires: "2100-01-01T00:00:00Z",
    newsExpires: "2100-01-01T00:00:00Z",
    sectors: { "": { id: 0, pages: 1 }, finans: { id: 1, pages: 2, label: "Finans" } },
    sectorAliases: { banka: "finans", bankalar: "finans", "1": "finans" },
  }],
  ["/sector/0/1.json", "ANA SEKTÖRLER"],
  ["/sector/1/1.json", "Finans şirketleri"],
  ["/sector/1/2.json", "Bankalar ikinci sayfa"],
  ["/company/THYAO.json", { report: "THYAO analizi", news: "THYAO KAP" }],
  ["/portfolio/buyume.json", "Büyüme portföyü"],
  ["/portfolio/dengeli.json", "Dengeli portföy"],
  ["/portfolio/kalite.json", "Kaliteli portföy"],
]);

const env = {
  TELEGRAM_WEBHOOK_SECRET: secret,
  TELEGRAM_CHAT_ID: "99",
  REPORTS: {
    async fetch(request) {
      const path = new URL(request.url).pathname;
      return assets.has(path)
        ? Response.json(assets.get(path)) : new Response(null, { status: 404 });
    },
  },
};

function request(text, id = 123, header = secret, type = "private") {
  return new Request(origin + "/telegram", {
    method: "POST",
    headers: { "X-Telegram-Bot-Api-Secret-Token": header },
    body: JSON.stringify({ message: { chat: { id, type }, from: { id }, text } }),
  });
}

function callbackRequest(data, id = 123, type = "private", sender = id) {
  return new Request(origin + "/telegram", {
    method: "POST",
    headers: { "X-Telegram-Bot-Api-Secret-Token": secret },
    body: JSON.stringify({ callback_query: {
      id: "test-query", from: { id: sender }, data,
      message: { message_id: 42, chat: { id, type } },
    } }),
  });
}

test("rejects unauthorized webhook and direct report requests", async () => {
  assert.equal((await worker.fetch(request("/komutlar", 123, "wrong"), env)).status, 403);
  assert.equal((await worker.fetch(new Request(origin + "/index.json"), env)).status, 404);
});

test("serves public commands from the generated reports", async () => {
  for (const [command, text] of [
    ["/komutlar", "/sektor banka"],
    ["/sektor banka sayfa 2", "Bankalar ikinci sayfa"],
    ["/sektör 1", "Finans şirketleri"],
    ["/portfoy BÜYÜME", "Büyüme portföyü"],
    ["/haber THYAO.IS", "THYAO KAP"],
    ["/tara@bist_bot THYAO", "THYAO analizi"],
  ]) {
    const reply = await (await worker.fetch(request(command), env)).json();
    assert.equal(reply.method, "sendMessage");
    assert.equal(reply.chat_id, 123);
    assert.equal(reply.text, text);
  }
});

test("offers inline sector and portfolio choices without exposing the owner panel", async () => {
  for (const command of ["/start", "/komutlar", "/sektor"]) {
    const reply = await (await worker.fetch(request(command), env)).json();
    const buttons = reply.reply_markup.inline_keyboard.flat();
    assert.ok(buttons.some(button => button.text === "Finans" && button.callback_data === "sector:finans:1"));
    if (command !== "/sektor") assert.ok(buttons.some(button => button.callback_data === "portfolio:buyume"));
    assert.ok(!JSON.stringify(reply.reply_markup).includes("yonetim"));
    assert.ok(buttons.every(button => Buffer.byteLength(button.callback_data) <= 64));
  }
});

test("opens sector, page and portfolio reports directly from inline buttons", async () => {
  for (const [data, expected] of [
    ["sector:finans:1", "Finans şirketleri"],
    ["sector:finans:2", "Bankalar ikinci sayfa"],
    ["portfolio:buyume", "Büyüme portföyü"],
    ["portfolio:kalite", "Kaliteli portföy"],
    ["portfolio:dengeli", "Dengeli portföy"],
    ["menu:komutlar", "/sektor banka"],
  ]) {
    const reply = await (await worker.fetch(callbackRequest(data), env)).json();
    assert.equal(reply.method, "editMessageText");
    assert.equal(reply.chat_id, 123);
    assert.equal(reply.message_id, 42);
    assert.equal(reply.text, expected);
    assert.ok(reply.reply_markup.inline_keyboard.length);
  }
  const first = await (await worker.fetch(callbackRequest("sector:finans:1"), env)).json();
  assert.ok(first.reply_markup.inline_keyboard.flat().some(button => button.callback_data === "sector:finans:2"));
});

test("shows portfolio selector for the command and return button", async () => {
  for (const input of [request("/portfoy"), callbackRequest("menu:portfoy")]) {
    const reply = await (await worker.fetch(input, env)).json();
    assert.match(reply.text, /PORTFÖY SEÇ/);
    assert.deepEqual(reply.reply_markup.inline_keyboard[0].map(button => button.callback_data),
      ["portfolio:dengeli", "portfolio:kalite", "portfolio:buyume"]);
  }
});

test("rejects forged, unknown and non-private button actions", async () => {
  for (const input of [
    callbackRequest("sector:unknown:1"), callbackRequest("sector:finans:9999"),
    callbackRequest("menu:yonetim"), callbackRequest("portfolio:../secret"),
    callbackRequest("sector:finans:1", 123, "group"),
    callbackRequest("sector:finans:1", 123, "private", 456),
  ]) assert.equal((await worker.fetch(input, env)).status, 204);
});

test("acknowledges button presses through the background context", async () => {
  const originalFetch = globalThis.fetch;
  const tasks = [];
  let called = false;
  globalThis.fetch = async (url, options) => {
    called = true;
    assert.equal(url, "https://api.telegram.org/bot123:test/answerCallbackQuery");
    assert.deepEqual(JSON.parse(options.body), { callback_query_id: "test-query" });
    return Response.json({ ok: true });
  };
  try {
    await worker.fetch(callbackRequest("portfolio:buyume"), { ...env, TELEGRAM_BOT_TOKEN: "123:test" }, {
      waitUntil(task) { tasks.push(task); },
    });
    await Promise.all(tasks);
    assert.equal(called, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("restricts the management panel and rejects group messages", async () => {
  assert.equal((await worker.fetch(request("/yonetim"), env)).status, 204);
  assert.equal((await worker.fetch(request("/yonetim", 99, secret, "group"), env)).status, 204);
  const response = await worker.fetch(request("/yonetim", 99), env);
  assert.match((await response.json()).text, /Yönetim/);
});

test("refuses stale closing reports while leaving the command list available", async () => {
  const original = assets.get("/index.json");
  assets.set("/index.json", { ...original, priceExpires: "2000-01-01T00:00:00Z" });
  try {
    const market = await worker.fetch(request("/tara THYAO"), env);
    assert.match((await market.json()).text, /hazır değil/);
    const help = await worker.fetch(request("/komutlar"), env);
    assert.equal((await help.json()).text, "/sektor banka");
    const sectors = await worker.fetch(request("/sektor"), env);
    assert.match((await sectors.json()).text, /ANA SEKTÖRLER/);
    const callback = await (await worker.fetch(callbackRequest("sector:finans:1"), env)).json();
    assert.match(callback.text, /hazır değil/);
  } finally {
    assets.set("/index.json", original);
  }
});
