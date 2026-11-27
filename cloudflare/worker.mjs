const NOT_READY = "Güncel araştırma henüz hazır değil. Bir sonraki veri yenilemesini bekle.";
const SYMBOL = /^[A-Z0-9]{2,12}$/;
const COMMANDS = new Set(["start", "komutlar", "sektor", "portfoy", "tara", "haber", "yonetim"]);
const PROFILES = { dengeli: "Dengeli", kalite: "Güçlü bilanço", buyume: "Büyüme" };

function selectionButtons(command, argument, index) {
  const rows = [];
  const portfolioRow = Object.entries(PROFILES).map(([key, text]) => ({ text, callback_data: `portfolio:${key}` }));
  if (["start", "komutlar", "portfoy"].includes(command)) rows.push(portfolioRow);
  if (["start", "komutlar"].includes(command) || (command === "sektor" && !argument)) {
    const sectors = Object.entries(index?.sectors || {}).filter(([key]) => key);
    for (let position = 0; position < sectors.length; position += 2) {
      rows.push(sectors.slice(position, position + 2).map(([key, entry]) => ({
        text: entry.label || key, callback_data: `sector:${key}:1`,
      })));
    }
  } else if (command === "sektor") {
    const match = argument.match(/(?:^|\s+)sayfa\s+([0-9]{1,4})$/i);
    const name = normalized(match ? argument.slice(0, match.index) : argument);
    const page = match ? Number(match[1]) : 1;
    const key = index?.sectorAliases?.[name] || name;
    const entry = Object.hasOwn(index?.sectors || {}, key) && index.sectors[key];
    const navigation = [];
    if (entry && page > 1 && page <= entry.pages) navigation.push({ text: "‹ Önceki", callback_data: `sector:${key}:${page - 1}` });
    if (entry && page >= 1 && page < entry.pages) navigation.push({ text: "Sonraki ›", callback_data: `sector:${key}:${page + 1}` });
    if (navigation.length) rows.push(navigation);
  }
  if (["sektor", "portfoy"].includes(command)) {
    rows.push([
      { text: "Sektörler", callback_data: "menu:sektor" },
      { text: "Portföyler", callback_data: "menu:portfoy" },
      { text: "Ana menü", callback_data: "menu:komutlar" },
    ]);
  }
  return rows.length ? { inline_keyboard: rows } : undefined;
}

async function acknowledgeCallback(id, env) {
  if (!env.TELEGRAM_BOT_TOKEN) return;
  try {
    await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/answerCallbackQuery`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ callback_query_id: id }), signal: AbortSignal.timeout(5000),
    });
  } catch {
    console.warn("Button acknowledgement could not be delivered.");
  }
}

function sameSecret(actual, expected) {
  if (!expected || actual.length !== expected.length) return false;
  let difference = 0;
  for (let index = 0; index < actual.length; index++) {
    difference |= actual.charCodeAt(index) ^ expected.charCodeAt(index);
  }
  return difference === 0;
}

function normalized(value) {
  return value.toLowerCase().replaceAll("ı", "i").normalize("NFKD")
    .replace(/\p{M}/gu, "").trim().replace(/\s+/g, " ");
}

async function reportAsset(env, requestUrl, path) {
  const response = await env.REPORTS.fetch(new Request(new URL(`/${path}.json`, requestUrl)));
  return response.ok ? response.json() : null;
}

async function sectorReport(argument, index, env, url) {
  const match = argument.match(/(?:^|\s+)sayfa\s+([0-9]{1,4})$/i);
  const name = normalized(match ? argument.slice(0, match.index) : argument);
  const page = match ? Number(match[1]) : 1;
  const alias = Object.hasOwn(index.sectorAliases || {}, name) ? index.sectorAliases[name] : name;
  let sector = Object.hasOwn(index.sectors, alias) ? index.sectors[alias] : null;
  if (!sector) {
    const matches = Object.entries(index.sectors).filter(([key]) => key.includes(name));
    if (matches.length === 0) {
      return "Bu sektör bulunamadı. Sektör adlarını görmek için /komutlar yaz.";
    }
    if (matches.length > 1) {
      return "Bir sektör seç:\n" + matches.map(([, entry]) => `/sektor ${entry.label}`).join("\n");
    }
    sector = matches[0][1];
  }
  if (page < 1 || page > sector.pages) {
    return `Sayfa ${page} bulunamadı. Toplam ${sector.pages} sayfa var.`;
  }
  return reportAsset(env, url, `sector/${sector.id}/${page}`);
}

async function replyText(command, argument, env, url) {
  const index = await reportAsset(env, url, "index");
  if (!index) return NOT_READY;
  if (command === "start" || command === "komutlar") return index.help;
  if (command === "yonetim") return `Yönetim • Veri durumu\n\n${index.status}`;
  if (command === "sektor" && !argument.trim()) {
    return "ANA SEKTÖRLER\n\nGörmek istediğin sektöre aşağıdaki düğmelerden dokun.\n\n• Finans; banka, sigorta ve diğer finans şirketlerini kapsar.";
  }
  if (command === "portfoy" && !argument.trim()) {
    return "PORTFÖY SEÇ\n\n• Dengeli: farklı sektörlerden genel denge\n• Güçlü bilanço: finansal kalite odaklı\n• Büyüme: büyüyen şirketler odaklı\n\nGörmek istediğin portföye aşağıdan dokun.";
  }
  const expires = Date.parse(command === "haber" ? index.newsExpires : index.priceExpires);
  if (!Number.isFinite(expires) || Date.now() >= expires) return NOT_READY;
  if (command === "portfoy") {
    const profile = normalized(argument) || "dengeli";
    if (!["dengeli", "kalite", "buyume"].includes(profile)) {
      return "Kullanım: /portfoy [dengeli | kalite | buyume]";
    }
    return reportAsset(env, url, `portfolio/${profile}`);
  }
  if (command === "sektor") return sectorReport(argument, index, env, url);
  if (command === "haber" && !argument) return reportAsset(env, url, "macro");
  const symbol = argument.toUpperCase().replace(/\.IS$/, "");
  if (!SYMBOL.test(symbol)) return `Kullanım: /${command} THYAO`;
  const company = await reportAsset(env, url, `company/${symbol}`);
  if (!company) return "Bu hisse araştırma evreninde bulunamadı.";
  return command === "haber" ? company.news : company.report;
}

export default {
  async fetch(request, env, context) {
    const url = new URL(request.url);
    if (url.pathname === "/health" && request.method === "GET") {
      const index = await reportAsset(env, url, "index");
      const ready = Boolean(index && env.TELEGRAM_WEBHOOK_SECRET);
      return Response.json({ ready }, { status: ready ? 200 : 503 });
    }
    if (url.pathname !== "/telegram" || request.method !== "POST") {
      return new Response(null, { status: 404 });
    }
    const header = request.headers.get("X-Telegram-Bot-Api-Secret-Token") || "";
    if (!sameSecret(header, env.TELEGRAM_WEBHOOK_SECRET)) {
      return new Response(null, { status: 403 });
    }
    let update;
    try {
      update = await request.json();
    } catch {
      return new Response(null, { status: 400 });
    }
    const callback = update?.callback_query;
    const message = callback ? callback.message : update?.message;
    if (message?.chat?.type !== "private" || !Number.isSafeInteger(message.chat.id)) {
      return new Response(null, { status: 204 });
    }
    let command;
    let argument;
    if (callback) {
      if (callback.from?.id !== message.chat.id || !Number.isSafeInteger(message.message_id)
        || typeof callback.id !== "string" || !callback.id || callback.id.length > 256) {
        return new Response(null, { status: 204 });
      }
      const action = typeof callback.data === "string" && callback.data.match(/^(?:sector:([a-z]{1,24}):([1-9][0-9]{0,3})|portfolio:(dengeli|kalite|buyume)|menu:(sektor|portfoy|komutlar))$/);
      if (!action) return new Response(null, { status: 204 });
      if (action[1]) {
        const index = await reportAsset(env, url, "index");
        const sector = Object.hasOwn(index?.sectors || {}, action[1]) && index.sectors[action[1]];
        if (!sector || Number(action[2]) > sector.pages) return new Response(null, { status: 204 });
        command = "sektor";
        argument = `${action[1]} sayfa ${action[2]}`;
      } else if (action[3]) {
        command = "portfoy";
        argument = action[3];
      } else {
        command = action[4];
        argument = "";
      }
      if (context?.waitUntil) context.waitUntil(acknowledgeCallback(callback.id, env));
    } else {
      const match = typeof message.text === "string" &&
        message.text.trim().match(/^\/([\p{L}]+)(?:@[a-z0-9_]+)?(?:\s+([\s\S]*))?$/iu);
      command = match && normalized(match[1]);
      argument = match ? (match[2] || "").trim() : "";
    }
    if (!COMMANDS.has(command)) return new Response(null, { status: 204 });
    if (command === "yonetim" && (
      String(message.chat.id) !== env.TELEGRAM_CHAT_ID || message.from?.id !== message.chat.id
    )) return new Response(null, { status: 204 });
    const text = await replyText(command, argument, env, url);
    const index = await reportAsset(env, url, "index");
    const replyMarkup = selectionButtons(command, argument, index);
    return Response.json({
      method: callback ? "editMessageText" : "sendMessage",
      chat_id: message.chat.id,
      ...(callback ? { message_id: message.message_id } : {}),
      text: text || NOT_READY,
      link_preview_options: { is_disabled: true },
      ...(replyMarkup ? { reply_markup: replyMarkup } : {}),
    });
  },
};
