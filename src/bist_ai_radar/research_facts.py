from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .models import NewsItem


@dataclass(frozen=True)
class CompanyResearchFact:
    symbol: str
    fact_type: str
    published_at: str
    disclosure_index: int | None
    value_text: str
    numeric_value: float | None
    unit: str
    source_url: str


FACT_PATTERNS = {
    "ORDER_BACKLOG": ("siparis bakiyesi", "backlog", "yeni siparis", "sozlesme bedeli"),
    "GUIDANCE": ("beklenti", "ongoru", "guidance", "hedef ciro", "hedef satis"),
    "DIVIDEND": ("temettu", "kar payi", "karpayi"),
    "BUYBACK": ("pay geri alim", "geri alim programi", "geri alinan pay"),
    "CAPITAL_INCREASE": (
        "bedelli sermaye",
        "tahsisli sermaye",
        "sermaye artirimi",
        "yeni pay alma hakki",
    ),
    "SHARE_SALE": ("ortak pay satisi", "pay satis bilgi formu", "borsada islem gorebilir"),
    "MANAGEMENT_CHANGE": (
        "yonetim kurulu degisikligi",
        "genel mudur atamasi",
        "ust yonetim degisikligi",
        "gorevinden ayril",
    ),
    "OWNERSHIP": ("pay alimi", "pay satimi", "ortaklik yapisi", "sermayedeki pay"),
    "SEGMENT": ("faaliyet bolumu", "segment", "bolum geliri", "bolum satislari"),
    "CAPACITY": ("kapasite artisi", "kapasite kullanim", "uretim kapasitesi"),
    "INVESTMENT": ("yatirim tesvik", "yeni yatirim", "fabrika", "yeni tesis"),
    "EXPORT": ("ihracat", "yurt disi satis", "yurtdisi satis", "doviz geliri"),
    "DEBT_RISK": ("temerrut", "borc yeniden yapilandirma", "kredi sozlesmesi ihlali"),
    "LEGAL_RISK": ("idari para cezasi", "faaliyet durdurma", "dava karsiligi", "ruhsat iptali"),
    "RELATED_PARTY": ("iliskili taraf", "iliskili kisi", "yaygin ve sureklilik arz eden"),
    "REPORTING_DOCUMENT": ("faaliyet raporu", "yatirimci sunumu", "surdurulebilirlik raporu"),
}


def extract_company_research_facts(item: NewsItem) -> tuple[CompanyResearchFact, ...]:
    text = " ".join(f"{item.title} {item.body}".split())
    normalized = _normalize(text)
    facts: list[CompanyResearchFact] = []
    for fact_type, patterns in FACT_PATTERNS.items():
        if not any(pattern in normalized for pattern in patterns):
            continue
        numeric_value, unit = _first_amount(text)
        facts.append(
            CompanyResearchFact(
                symbol=item.symbol,
                fact_type=fact_type,
                published_at=item.published_at.isoformat(),
                disclosure_index=item.disclosure_index,
                value_text=text[:700],
                numeric_value=numeric_value,
                unit=unit,
                source_url=item.source_url,
            )
        )
    return tuple(facts)


def _first_amount(text: str) -> tuple[float | None, str]:
    match = re.search(
        r"(?<!\d)(\d{1,3}(?:[. ]\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)\s*"
        r"(milyar|milyon|bin)?\s*(TL|TRY|USD|EUR|%)?",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None, ""
    raw = match.group(1).replace(" ", "")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(".") > 1:
        raw = raw.replace(".", "")
    try:
        value = float(raw)
    except ValueError:
        return None, ""
    scale_name = (match.group(2) or "").lower()
    value *= {"bin": 1_000, "milyon": 1_000_000, "milyar": 1_000_000_000}.get(
        scale_name,
        1,
    )
    return value, (match.group(3) or scale_name).upper()


def _normalize(value: str) -> str:
    translated = value.casefold().translate(str.maketrans({"\u0131": "i"}))
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", translated)
        if not unicodedata.combining(character)
    )
