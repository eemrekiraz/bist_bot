from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from math import exp, isfinite, log, sqrt
from statistics import mean, pstdev
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .data_quality import inspect_price_quality
from .db import connect, init_db
from .engines import FundamentalEngine, NumericEngine
from .financial_quality import inspect_financial_freshness
from .market_calendar import market_session
from .report_snapshot import load_report_snapshot, save_report_snapshot
from .repositories import MarketRepository


ISTANBUL = ZoneInfo("Europe/Istanbul")
SNAPSHOT_KEY = "public-research"
SNAPSHOT_MAX_AGE = 7 * 24 * 3600
# Bump whenever eligibility, scoring or portfolio selection rules change, so the
# recommendation ledger can tell which method produced each recommendation.
METHOD_NAME = "public_financial_technical_portfolio"
METHOD_VERSION = "2026.11.1"
CONTEXT = "Genel araştırma • Kişiye özel yatırım tavsiyesi değildir."
PORTFOLIO_LABELS = {"dengeli": "Dengeli", "kalite": "Finansal kalite", "buyume": "Büyüme"}
PUBLIC_COMMANDS = {
    "portfoy": "Örnek portföyler — dengeli, kalite veya büyüme",
    "sektor": "Sektör liderleri — örnek: /sektor banka",
    "tara": "Şirket özeti — örnek: /tara THYAO",
    "haber": "Makro gündem veya KAP — örnek: /haber THYAO",
}
SYMBOL_PATTERN = re.compile(r"[A-Z0-9]{2,12}")
UNKNOWN_SECTORS = {"", "bilinmiyor", "bilinmeyen", "diger", "-", "sektor bilgisi yok"}
SECTOR_PAGE_PATTERN = re.compile(r"(?:^|\s+)sayfa\s+([0-9]{1,4})$", re.IGNORECASE)
MAIN_SECTORS = {
    "finans": ("Finans", ("banka", "sigorta", "finans", "faktoring", "araci kurum", "leasing", "varlik yonetim", "menkul kiymet", "girisim sermaye")),
    "holding": ("Holding", ("holding", "yatirim sirket")),
    "enerji": ("Enerji", ("enerji", "elektrik gaz", "buhar", "ham petrol", "dogal gaz")),
    "teknoloji": ("Teknoloji", ("teknoloji", "bilisim", "bilgi hizmet", "telekom", "yazilim")),
    "maden": ("Madencilik", ("madencilik", "maden", "metal cevher", "komur", "linyit", "tas ocak")),
    "gida": ("Gıda ve tarım", ("gida", "tarim", "hayvancilik", "balikcilik", "su urun", "tutun")),
    "perakende": ("Ticaret", ("perakende", "toptan", "ticaret", "magaza")),
    "ulasim": ("Ulaşım", ("ulastirma", "ulasim", "lojistik", "depolama", "havacilik")),
    "gayrimenkul": ("Gayrimenkul", ("gayrimenkul", "insaat", "bayindirlik", "gyo")),
    "saglik": ("Sağlık", ("insan sagligi", "saglik", "hastane")),
    "sanayi": ("Sanayi", ("sanayi", "imalat", "otomotiv", "kimya", "ilac", "kagit", "metal", "tekstil", "orman urun", "mobilya", "tas ve topra", "savunma", "makine", "elektrikli cihaz", "cimento")),
    "hizmet": ("Turizm ve hizmetler", ("turizm", "konaklama", "seyahat", "hizmet", "buro", "spor", "eglence", "sanat", "reklam", "hukuk", "muhasebe", "mimarlik", "muhendislik", "yayimcilik", "yiyecek", "icecek", "hizmetler")),
}


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold().replace("ı", "i"))
    return " ".join("".join(char for char in text if not unicodedata.combining(char)).split())


def sector_key(value: str) -> str:
    term = normalize(value)
    if term in MAIN_SECTORS:
        return term
    if "metal esya" in term:
        return "sanayi"
    for key, (label, terms) in MAIN_SECTORS.items():
        if term == normalize(label) or any(part in term for part in terms):
            return key
    return ""


def sector_aliases(companies: list[dict]) -> dict[str, str]:
    available = _sector_names(companies)
    aliases = {str(index): key for index, key in enumerate(available, start=1)}
    for key in available:
        label, terms = MAIN_SECTORS[key]
        for alias in (key, normalize(label), *terms):
            aliases[alias] = key
    for company in companies:
        key = sector_key(company["sector"])
        if key:
            aliases[normalize(company["sector"])] = key
    return aliases


def last_completed_session(now: datetime) -> date:
    day = now.date()
    session = market_session(day)
    if session.close_time is None or now.time() < session.close_time:
        day -= timedelta(days=1)
    while not market_session(day).is_open:
        day -= timedelta(days=1)
    return day


def _oldest_price_day(now: datetime) -> date:
    day = last_completed_session(now) - timedelta(days=1)
    while not market_session(day).is_open:
        day -= timedelta(days=1)
    return day


def _safe_link(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    return value if parsed.scheme == "https" and parsed.hostname and not parsed.username else ""


def _headline(value: str, limit: int = 124) -> str:
    text = " ".join(value.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def price_scenarios(bars: list) -> dict | None:
    history = bars[-61:]
    if len(history) < 41:
        return None
    closes = [bar.close for bar in history]
    price = history[-1].trade_close
    if not all(isfinite(value) and value > 0 for value in [price, *closes]):
        return None
    returns = [log(current) - log(previous) for previous, current in zip(closes, closes[1:])]
    if sum(abs(value) > 1e-10 for value in returns) < 10:
        return None
    annual_volatility = pstdev(returns) * sqrt(252)
    if not isfinite(annual_volatility) or not 0 < annual_volatility <= 2:
        return None
    return {
        "price": price, "lower": price * exp(-annual_volatility),
        "base": price, "upper": price * exp(annual_volatility),
        "sessions": len(returns), "horizon": 252,
        "method": "historical_volatility_zero_log_drift",
    }


def _scenario_lines(company: dict, *, compact: bool) -> list[str]:
    scenario = company.get("price_scenario")
    if not scenario:
        return ["", "12 aylık senaryo:", "• Hesaplama için yeterli ve güvenilir fiyat hareketi yok."]

    def amount(value: float) -> str:
        return f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".") + " TL"

    lines = ["", "12 aylık fiyat senaryosu:", f"• Son kapanış: {amount(scenario['price'])}"]
    lines.append(f"• Aşağı senaryo: {amount(scenario['lower'])}")
    if not compact:
        lines.append(f"• Yatay senaryo: {amount(scenario['base'])}")
    lines.append(f"• Yukarı senaryo: {amount(scenario['upper'])}")
    if not compact:
        lines.extend([
            f"• Dayanak: son {scenario['sessions']} seansın fiyat oynaklığı.",
            "• Hedef değer veya eğitilmiş model tahmini değildir.",
            "• Fiyat bu seviyelerin dışına çıkabilir; bu yıl içinde görülecek en düşük/en yüksek fiyat değildir.",
        ])
    else:
        lines.append("• Oynaklık senaryosudur; fiyat hedefi değildir.")
    return lines


def _kap_highlights(repository: MarketRepository, symbol: str, now: datetime) -> list[dict]:
    highlights: list[dict] = []
    seen: set[str] = set()
    for item in repository.recent_news(symbol, limit=16):
        published = item.published_at
        published = (
            published.replace(tzinfo=ISTANBUL)
            if published.tzinfo is None else published.astimezone(ISTANBUL)
        )
        link = _safe_link(item.source_url)
        if not now - timedelta(days=14) <= published <= now or not link:
            continue
        title = normalize(item.title)
        summary = normalize(item.body[:500])
        event = f"{title} {summary}"
        risk = any(term in event for term in (
            "faaliyet durdurma", "konkordato", "iflas", "temerrut", "sozlesme iptali",
            "bedelli sermaye", "idari para cezasi",
        ))
        material = risk or any(term in event for term in (
            "yeni is iliskisi", "sozlesme", "ihale", "yatirim", "kapasite artisi", "finansal rapor",
            "kar payi", "geri alim", "kredi derecelendirme",
        ))
        if not material or link in seen:
            continue
        seen.add(link)
        highlights.append({
            "date": published.date().isoformat(),
            "title": _headline(item.title),
            "url": link,
            "risk": risk,
        })
    return sorted(highlights, key=lambda item: item["risk"], reverse=True)[:2]


def _company(repository: MarketRepository, symbol: str, now: datetime) -> dict:
    sector = repository.company_sector(symbol).strip()
    bars = [
        bar for bar in repository.latest_bars(symbol, limit=125)
        if bar.day <= last_completed_session(now)
    ]
    row = {
        "symbol": symbol,
        "title": repository.company_title(symbol),
        "sector": sector or "Sektör bilgisi yok",
        "news": _kap_highlights(repository, symbol, now),
        "day": bars[-1].day.isoformat() if bars else "",
        "close": bars[-1].trade_close if bars else None,
        "period": "",
        "eligible": False,
        "reasons": [],
        "risk": "Yeterli güncel veri yok.",
        "price_scenario": None,
    }
    if (
        len(bars) < 60
        or bars[-1].day < _oldest_price_day(now)
        or any(
            not isfinite(value) or value <= 0
            for bar in bars for value in (bar.close, bar.trade_close)
        )
        or not inspect_price_quality(bars).passed
    ):
        return row
    row["price_scenario"] = price_scenarios(bars)
    if normalize(sector) in UNKNOWN_SECTORS:
        row["risk"] = "Sektör sınıflaması eksik."
        return row
    financials = [
        item for item in repository.financial_snapshots(symbol)
        if item.published_at is None or item.published_at.date() <= now.date()
    ]
    freshness = inspect_financial_freshness(financials, now.date(), max_age_days=180)
    if (
        not freshness.available or freshness.age_days is None
        or not 0 <= freshness.age_days <= 180
    ):
        row["risk"] = "Güncel bilanço verisi eksik."
        return row
    row["period"] = freshness.latest_period
    analysis = FundamentalEngine().analyze(financials, bars[-1].trade_close, sector)
    if analysis is None:
        row["risk"] = "Finansal kaliteyi değerlendirecek veri eksik."
        return row
    turnover = mean(bar.trade_close * bar.volume for bar in bars[-20:])
    closes = [bar.close for bar in bars]
    volatility = pstdev(b / a - 1 for a, b in zip(closes[-21:-1], closes[-20:]))
    trend_score, _ = NumericEngine().score(bars)
    growth = analysis.revenue_growth
    reasons = []
    if growth is not None and growth > 0:
        reasons.append(f"Raporlanan ciro büyümesi %{growth * 100:.0f}")
    if analysis.roe is not None and analysis.roe > 0:
        reasons.append(f"Özkaynak kârlılığı %{analysis.roe * 100:.0f}")
    if analysis.free_cash_flow_margin is not None and analysis.free_cash_flow_margin > 0:
        reasons.append("Pozitif serbest nakit akışı marjı")
    if analysis.strength_score >= 0.60:
        reasons.append("Bilanço ve borçluluk dengesi olumlu")
    if closes[-1] >= mean(closes[-50:]):
        reasons.append("Fiyat, 50 günlük ortalamasının üzerinde")
    risk_news = any(item["risk"] for item in row["news"])
    risks = []
    if risk_news:
        risks.append("KAP bildiriminde incelenmesi gereken risk başlığı")
    if turnover < 15_000_000:
        risks.append("düşük işlem likiditesi")
    if volatility >= 0.035:
        risks.append("yüksek fiyat oynaklığı")
    if analysis.strength_score < 0.50:
        risks.append("zayıf finansal güç")
    if not risks and closes[-1] < mean(closes[-50:]):
        risks.append("kısa vadeli trend zayıf")
    score = 0.75 * analysis.score + 0.25 * trend_score - min(volatility, 0.08)
    row.update(
        eligible=(
            analysis.score >= 0.58 and analysis.profitability_score >= 0.50
            and analysis.strength_score >= 0.45 and turnover >= 15_000_000
            and len(reasons) >= 2 and not risk_news
        ),
        reasons=reasons[:3],
        risk="; ".join(risks) if risks else "Bilanço ve piyasa koşulları değişebilir.",
        scores={
            "dengeli": score,
            "kalite": 0.65 * analysis.profitability_score + 0.35 * analysis.strength_score - volatility,
            "buyume": 0.55 * analysis.growth_score + 0.45 * score,
        },
    )
    return row


def publish_public_snapshot(now: datetime | None = None) -> None:
    checked_at = now or datetime.now(ISTANBUL)
    init_db()
    with connect() as connection:
        repository = MarketRepository(connection)
        companies = [
            _company(repository, symbol, checked_at) for symbol in repository.universe_symbols()
            if SYMBOL_PATTERN.fullmatch(symbol)
        ]
        macro = []
        for item in repository.latest_macro_news(limit=80):
            age = (checked_at.date() - item.published_at.date()).days
            link = _safe_link(item.link)
            if 0 <= age <= 7 and link:
                macro.append({
                    "source": item.source,
                    "date": item.published_at.date().isoformat(),
                    "title": _headline(item.title),
                    "url": link,
                })
    payload = {"updated": checked_at.isoformat(timespec="minutes"), "companies": companies, "macro": macro}
    save_report_snapshot(SNAPSHOT_KEY, json.dumps(payload, ensure_ascii=False))


def _company_summary(
    company: dict, *, include_news: bool = True, show_score: bool = False,
    score_profile: str = "dengeli",
) -> str:
    name = company["title"]
    lines = [company["symbol"]]
    if name and name != company["symbol"]:
        lines.append(_headline(name, 65))
    group = sector_key(company["sector"])
    lines.append(f"• Sektör: {MAIN_SECTORS[group][0] if group else 'Sınıflama bekleniyor'}")
    if show_score and company.get("scores"):
        score = max(0.0, min(1.0, company["scores"][score_profile]))
        lines.append(f"• Tarama puanı {score * 100:.1f}/100".replace(".", ",", 1))
    lines.extend(["", "Neden:", *[f"• {reason}" for reason in company["reasons"]]])
    if not company["reasons"]:
        lines.append("• Değerlendirme için yeterli veri yok.")
    lines.extend(["", "Dikkat:", *[
        f"• {risk.strip()}" for risk in company["risk"].split(";") if risk.strip()
    ]])
    lines.extend(_scenario_lines(company, compact=not include_news))
    if include_news and company["day"] and company["period"]:
        lines.extend(["", f"• Kapanış verisi: {company['day']}", f"• Bilanço dönemi: {company['period']}"])
    if include_news and company["news"]:
        item = company["news"][0]
        lines.extend(["", "Son önemli KAP:", f"• {item['title']}", f"• Tarih: {item['date']}", item["url"]])
    return "\n".join(lines)


def _sector_names(companies: list[dict]) -> dict[str, str]:
    available = {sector_key(company["sector"]) for company in companies}
    return {key: label for key, (label, _) in MAIN_SECTORS.items() if key in available}


def public_sector_directory() -> str:
    raw = load_report_snapshot(SNAPSHOT_KEY, SNAPSHOT_MAX_AGE)
    try:
        sectors = _sector_names(json.loads(raw)["companies"]) if raw else {}
    except (KeyError, TypeError, ValueError):
        sectors = {}
    return _format_sector_directory(sectors)


def _format_sector_directory(sectors: dict[str, str]) -> str:
    if not sectors:
        return "Sektör listesi ilk veri taramasından sonra burada görünecek."
    return (
        "ANA SEKTÖRLER\n\n"
        + "\n".join(f"{index}. {label} → /sektor {key}" for index, (key, label) in enumerate(sectors.items(), start=1))
        + "\n\nKısa ad veya numara yeterli. Örnek: /sektor 1\n"
        "Finans; banka, sigorta ve diğer finans şirketlerini kapsar."
    )


def build_public_help(sectors: str, *, interactive: bool = False) -> str:
    if interactive:
        return (
            "BİST ARAŞTIRMA BOTU\n\n"
            "SEKTÖRLER VE PORTFÖYLER\n"
            "• Aşağıdaki isimlere dokunarak doğrudan açabilirsin.\n"
            "• Sektörler: ilgili alanda öne çıkan şirketler\n"
            "• Dengeli: farklı sektörlerden genel denge\n"
            "• Güçlü bilanço: finansal kalite odaklı\n"
            "• Büyüme: büyüyen şirketler odaklı\n\n"
            "ŞİRKET VE HABER\n"
            "• /tara THYAO — şirketin güçlü yanları ve riskleri\n"
            "• /haber THYAO — şirkete ait önemli KAP bildirimleri\n"
            "• /haber — Türkiye ve dünya gündemi\n\n"
            "• /sektor — sektör seçim ekranı\n"
            "• /portfoy — portföy seçim ekranı\n"
            "• /komutlar — bu menüye dön\n\n"
            "Fiyatlar son kapanışa aittir; anlık değildir.\n"
            f"{CONTEXT}"
        )
    commands = "\n\n".join(f"/{name}\n• {description}" for name, description in PUBLIC_COMMANDS.items())
    return (
        "BİST Araştırma Botu\n\n"
        f"{commands}\n\n"
        "PORTFÖY TERCİHLERİ\n"
        "• /portfoy dengeli — genel denge\n"
        "• /portfoy kalite — güçlü bilanço\n"
        "• /portfoy buyume — büyüyen şirketler\n\n"
        f"{sectors}\n\n"
        "• Fiyatlar son kapanışa aittir; anlık değildir.\n"
        "• Puan, kazanç ihtimali değil karşılaştırma puanıdır.\n"
        f"• {CONTEXT}"
    )


def _sector_report(
    companies: list[dict], candidates: list[dict], argument: str, header: str,
) -> str:
    page_match = SECTOR_PAGE_PATTERN.search(argument)
    page = int(page_match[1]) if page_match else 1
    query = argument[:page_match.start()].strip() if page_match else argument
    pages = sector_report_pages(companies, candidates, query, header)
    if not 1 <= page <= len(pages):
        command = "/sektor" + (f" {query}" if query else "")
        return f"Sayfa {page} bulunamadı. Toplam {len(pages)} sayfa var. İlk sayfa için {command} yaz."
    return pages[page - 1]


def sector_report_pages(
    companies: list[dict], candidates: list[dict], query: str, header: str,
) -> list[str]:
    sector_names = _sector_names(companies)
    term = normalize(query)
    if not term:
        return [_format_sector_directory(sector_names)]
    key = sector_aliases(companies).get(term) or sector_key(term)
    if key not in sector_names:
        return ["Bu sektör bulunamadı. Sektör adlarını görmek için /komutlar yaz."]
    title = f"SEKTÖR • {sector_names[key]}"
    selected = sorted(
        (item for item in candidates if sector_key(item["sector"]) == key),
        key=lambda item: (-item["scores"]["dengeli"], item["symbol"]),
    )
    if not selected:
        return [f"{title}\n\n{header}\nGüncel verisi yeterli ve ölçütleri geçen şirket bulunamadı."]
    cards = [
        _company_summary(company, include_news=False, show_score=True)
        for company in selected
    ]
    pages = [""]
    for card in cards:
        if not pages[-1]:
            pages[-1] = card
        elif len(pages[-1]) + len(card) + 16 <= 3000:
            pages[-1] += "\n\n──────────\n\n" + card
        else:
            pages.append(card)
    command = "/sektor" + (f" {query}" if query else "")
    results = []
    for page, text in enumerate(pages, start=1):
        navigation = []
        if page > 1:
            navigation.append(f"Önceki • {command} sayfa {page - 1}")
        if page < len(pages):
            navigation.append(f"Sonraki • {command} sayfa {page + 1}")
        results.append("\n\n".join([
            f"{title}\n\n• {header}\n• {len(selected)} aday\n• Sayfa {page}/{len(pages)}\n• Yüksek puandan düşüğe sıralı",
            text,
            "• Puan, bilanço ve fiyat eğilimini karşılaştırır; kazanç garantisi değildir.",
            *navigation,
            CONTEXT,
        ]))
    return results


def public_snapshot_status() -> str:
    raw = load_report_snapshot(SNAPSHOT_KEY, SNAPSHOT_MAX_AGE)
    if raw is None:
        return "Hazır araştırma taraması yok."
    snapshot = json.loads(raw)
    return snapshot_status(snapshot, datetime.now(ISTANBUL))


def snapshot_status(snapshot: dict, now: datetime) -> str:
    companies = snapshot["companies"]
    oldest = _oldest_price_day(now).isoformat()
    return (
        f"Son tarama {snapshot['updated'].replace('T', ' ')}\n"
        f"Aktif evren: {len(companies)} şirket\n"
        f"Güncel kapanış: {sum(item['day'] >= oldest for item in companies)} şirket\n"
        f"Uygun aday: {sum(item['eligible'] and item['day'] >= oldest for item in companies)}\n"
        f"Son tamamlanan seans: {last_completed_session(now)}"
    )


def public_report(command: str, args: list[str], now: datetime | None = None) -> str:
    argument = " ".join(args).strip()
    profile = normalize(argument) or "dengeli"
    symbol = argument.upper().removesuffix(".IS")
    if command == "portfoy" and profile not in PORTFOLIO_LABELS:
        return "Kullanım: /portfoy [dengeli | kalite | buyume]"
    if (command == "tara" or (command == "haber" and argument)) and not SYMBOL_PATTERN.fullmatch(symbol):
        return f"Kullanım: /{command} THYAO"
    raw = load_report_snapshot(SNAPSHOT_KEY, SNAPSHOT_MAX_AGE)
    if raw is None:
        return "Güncel araştırma henüz hazır değil. Bir sonraki planlı veri yenilemesini bekle."
    try:
        snapshot = json.loads(raw)
    except ValueError:
        return "Araştırma verisi şu anda okunamıyor."
    return render_public_report(snapshot, command, argument, now or datetime.now(ISTANBUL))


def eligible_candidates(companies: list[dict], checked_at: datetime) -> list[dict]:
    oldest = _oldest_price_day(checked_at).isoformat()
    return [item for item in companies if item["eligible"] and item["day"] >= oldest]


def select_portfolio(candidates: list[dict], profile: str, size: int = 5) -> list[dict]:
    """Highest-scoring candidates, at most one per main sector."""
    ordered = sorted(candidates, key=lambda item: (-item["scores"][profile], item["symbol"]))
    selected = []
    sectors = set()
    for item in ordered:
        sector = sector_key(item["sector"]) or normalize(item["sector"])
        if sector in sectors:
            continue
        selected.append(item)
        sectors.add(sector)
        if len(selected) == size:
            break
    return selected


def render_public_report(snapshot: dict, command: str, argument: str, checked_at: datetime) -> str:
    profile = normalize(argument) or "dengeli"
    symbol = argument.upper().removesuffix(".IS")
    header = f"Son tarama {snapshot['updated'].replace('T', ' ')}"
    companies = snapshot["companies"]
    if command == "haber":
        if argument:
            company = next((item for item in companies if item["symbol"] == symbol), None)
            if not company:
                return "Bu hisse araştırma evreninde bulunamadı."
            cutoff = (checked_at.date() - timedelta(days=14)).isoformat()
            news = [item for item in company["news"] if item["date"] >= cutoff]
            title = f"{symbol} • Öne çıkan KAP"
        else:
            cutoff = (checked_at.date() - timedelta(days=7)).isoformat()
            recent = [item for item in snapshot["macro"] if item["date"] >= cutoff]
            news = []
            for item in recent:
                if not any(entry["source"] == item["source"] for entry in news):
                    news.append(item)
            title = "Türkiye ve dünya • Makro gündem"
        lines = [
            f"{index}. {item['title']}\n• Kaynak: {item.get('source', 'KAP')}\n• Tarih: {item['date']}\n{item['url']}"
            for index, item in enumerate(news[:5], start=1)
        ]
        return "\n\n".join([title, header, *lines] if lines else [title, header, "Yeni kayıt yok."])

    oldest = _oldest_price_day(checked_at).isoformat()
    if command == "tara":
        company = next((item for item in companies if item["symbol"] == symbol), None)
        if company is None:
            return "Bu hisse araştırma evreninde bulunamadı."
        if company["day"] < oldest:
            return f"{symbol} • Güncel kapanış verisi bekleniyor. KAP için /haber {symbol}."
        return "\n\n".join([_company_summary(company, show_score=True), f"• {header}", CONTEXT])

    candidates = [item for item in companies if item["eligible"] and item["day"] >= oldest]
    if command == "sektor":
        return _sector_report(companies, candidates, argument, header)
    selected = select_portfolio(candidates, profile)
    title = f"Örnek portföy • {PORTFOLIO_LABELS[profile]}"
    coverage = f"• İncelenen: {len(companies)} şirket\n• Ölçütleri geçen: {len(candidates)} şirket\n• Seçim: farklı ana sektörler"
    lines = [f"{index}. " + _company_summary(item, include_news=False, show_score=True, score_profile=profile)
             for index, item in enumerate(selected, start=1)]
    if not lines:
        lines = ["Güncel verisi yeterli ve ölçütleri geçen şirket bulunamadı."]
    return "\n\n──────────\n\n".join([f"{title}\n\n• {header}\n{coverage}", *lines, CONTEXT])
