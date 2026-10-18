#!/usr/bin/env python3
"""VC Pulse data updater.

Pulls free public RSS feeds (TechCrunch, Crunchbase News, VentureBeat, SiliconANGLE,
Google News queries), extracts AI funding rounds from headlines with rule-based parsing,
dedupes, merges with the previous data.json (rolling window), and writes data.json.

Standard library only, so it runs anywhere (including GitHub Actions) with no installs.
"""
import json, re, sys, html, hashlib, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "data.json"  # funding rounds only; never data/key_voices.json
WINDOW_DAYS = 45          # keep this many days of history
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126 Safari/537.36 VCPulse/1.0")

def gnews(q):
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})

# (name, url, ai_by_default)  ai_by_default=True means every item is treated as AI-related
SOURCES = [
    ("TechCrunch Venture", "https://techcrunch.com/category/venture/feed/", False),
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", True),
    ("Crunchbase News", "https://news.crunchbase.com/feed/", False),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/", True),
    ("VentureBeat (Feedburner)", "https://feeds.feedburner.com/venturebeat/SZYF", False),
    ("SiliconANGLE AI", "https://siliconangle.com/category/ai/feed/", True),
    ("Google News: AI Series A", gnews('AI startup raises "Series A" when:14d'), False),
    ("Google News: AI Series B", gnews('AI startup "Series B" funding when:14d'), False),
    ("Google News: AI seed round", gnews('AI startup raises seed round when:14d'), False),
    ("Google News: AI Series C+", gnews('AI raises "Series C" OR "Series D" OR "Series E" when:14d'), False),
]

AI_RE = re.compile(r"\b(AI|A\.I\.|artificial intelligence|agentic|agents?|LLMs?|GenAI|generative|"
                   r"machine learning|ML|foundation model|copilot|chatbot|neural|inference|GPU)\b", re.I)
RAISE_RE = re.compile(r"\b(raises?|raised|raising|lands?|landed|secures?|secured|closes?|closed|nabs?|"
                      r"bags?|snags?|gets|banks?|scores?|pulls in|picks up|collects?|announces?|unveils?)\b", re.I)
AMOUNT_RE = re.compile(r"(?:US)?\$\s?(\d{1,4}(?:[.,]\d{1,3})?)\s*(billion|million|bn|mn|mil|[BMK])\b", re.I)
EUR_RE = re.compile(r"(€|£)\s?(\d{1,4}(?:[.,]\d{1,3})?)\s*(billion|million|bn|mn|mil|[BMK])\b", re.I)
STAGE_RE = re.compile(r"\b(pre-seed|seed|series\s+[a-h](?:\+|-?\d)?|growth round|growth funding|"
                      r"strategic round|bridge round|extension)\b", re.I)
# Digest headlines name several deals (or a valuation) in one title. The first
# dollar figure is often not a round, e.g. "Weekly AI Funding: TypeSafe AI Hits $7.5B".
ROUNDUP_RE = re.compile(
    r"\bweekly\b.{0,80}?\bfunding\b"
    r"|\bplus\s+\d+\s+more\b"
    r"|\bdeals to know\b"
    r"|\bfunding\s+round-?ups?\b"
    r"|\bround-?ups?\b"
    r"|\bdigests?\b",
    re.I)
LED_RE = re.compile(r"\b(?:led by|co-led by|from|backed by|with participation from)\s+"
                    r"([A-Z][\w&.'’\-]*(?:\s+(?:[A-Z][\w&.'’\-]*|and|&|of))*(?:,\s*[A-Z][\w&.'’\-]*(?:\s+[A-Z][\w&.'’\-]*)*)*)")

SECTORS = [
    ("Fintech", r"fintech|payments?|banking|bank|lending|mortgage|treasury|insurance|insurtech|credit|wealth|trading|accounting|tax|crypto|stablecoin|finance"),
    ("Health & Wellness", r"health|healthcare|medical|clinic|clinical|patient|biotech|drug|pharma|wellness|mental|therapy|hospital|doctor|nurse|care\\b|radiology"),
    ("Future of Work", r"hiring|recruit|talent|workforce|employee|HR\b|payroll|productivity|workflow|enterprise agents?|agentic|back[- ]office|staffing|knowledge work|meeting"),
    ("Energy & AI infrastructure", r"climate|energy|carbon|battery|solar|grid|nuclear|fusion|ev\b|electric vehicle|sustainab|emissions"),
    ("Dev Tools & Infra", r"developer|devtool|coding|code\b|software engineer|infra|infrastructure|cloud|database|data center|datacenter|compute|chip|semiconductor|gpu|inference|model|open[- ]source|api"),
    ("Security", r"security|cyber|fraud|identity|threat|soc\b|compliance"),
    ("Legal & Gov", r"legal|law firm|lawyer|contract|government|defense|defence|public sector"),
    ("Robotics & Industrial", r"robot|robotics|humanoid|manufactur|industrial|factory|supply chain|logistics|warehouse|construction|drone|autonomous"),
    ("Consumer", r"consumer|shopping|retail|e-?commerce|creator|social|dating|music|video|gaming|game|travel|food|fashion|beauty"),
    ("Sales & Marketing", r"sales|marketing|advertis|customer support|customer service|crm|go-to-market|gtm"),
]
SECTOR_RES = [(n, re.compile(r"\b(?:" + p + ")", re.I)) for n, p in SECTORS]

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()

def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()

def parse_date(s):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None

def parse_feed(raw):
    root = ET.fromstring(raw)
    items = []
    for it in root.iter("item"):
        g = lambda tag: (it.findtext(tag) or "").strip()
        src = it.find("source")
        items.append({"title": strip_tags(g("title")), "link": g("link"), "date": parse_date(g("pubDate")),
                      "summary": strip_tags(g("description"))[:600],
                      "publisher": (src.text.strip() if src is not None and src.text else None)})
    return items

def to_musd(num, unit, cur="$"):
    n = float(num.replace(",", "")) if "," in num and len(num.split(",")[-1]) == 3 else float(num.replace(",", "."))
    u = unit.lower()
    mult = {"billion": 1000, "bn": 1000, "b": 1000, "million": 1, "mn": 1, "mil": 1, "m": 1, "k": 0.001}[u]
    fx = {"$": 1.0, "€": 1.08, "£": 1.27}[cur]   # rough FX for ranking only; flagged as approx
    return round(n * mult * fx, 2)

def norm_stage(s):
    s = s.lower().strip()
    if s.startswith("pre-seed"): return "Pre-Seed"
    if s.startswith("seed"): return "Seed"
    m = re.match(r"series\s+([a-h])", s)
    if m: return "Series " + m.group(1).upper()
    if "growth" in s: return "Growth"
    return "Other"

LEAD_WORDS = re.compile(r"^(?:exclusive:?|breaking:?|report:?|the|a|an|how|why|ai|[\w\-]+-based|"
                        r"(?:[A-Z][\w\-]*\s)?(?:startup|start-up|company|firm|platform|unicorn|maker|developer))\s+", re.I)

DESCRIPTORS = {"ai", "agent", "agents", "agentic", "startup", "start-up", "platform", "solution", "infrastructure",
               "inference", "clinical", "native", "robot", "robotics", "data", "music", "production", "cybersecurity",
               "security", "fintech", "healthtech", "edtech", "exclusive", "report", "breaking", "company", "unicorn",
               "cloud", "software", "saas", "voice", "legal", "health", "medical"}

def clean_company(name):
    name = re.sub(r"\s+(?:Reportedly|Officially|Quietly|Now)$", "", name)
    if re.search(r"\b(?:Founder|Co-?founder|CEO|CTO|Veterans?|Alums?)$", name, re.I):
        return None
    name = re.sub(r"^\S+-(?:backed|based)\s+", "", name, flags=re.I)
    name = re.sub(r"^[A-Z][\w.\-]*(?:\s[A-Z][\w.\-]*)?['’]s\s+", "", name)   # "Japan's Mujin", "Palo Alto's X"
    m = list(re.finditer(r"\b(?:Startup|Start-up|Company|Firm)\s+", name, re.I))
    if m:
        name = name[m[-1].end():]
    toks = name.split()
    while len(toks) > 1 and (toks[0].lower() in DESCRIPTORS or re.match(r"^[\w]+-native$", toks[0], re.I)):
        toks.pop(0)
    return " ".join(toks) or None

def canon(name):
    c = re.sub(r"(?:\s|\.)ai$", "", (name or "").lower().strip())
    return re.sub(r"[^a-z0-9]", "", c)

def extract_company(title):
    t = re.sub(r"\s+[-–|]\s+[^-–|]{2,60}$", "", title)  # drop " - Publisher" suffix
    m = RAISE_RE.search(t)
    if not m:
        return None
    head = t[:m.start()].strip(" ,:;-–")
    head = re.split(r"[:|–—]\s*", head)[-1]               # text after a colon e.g. "Exclusive: X raises"
    head = re.sub(r"[’']s$", "", head)
    # descriptors like "AI coding startup Foo" -> "Foo": take trailing capitalised tokens
    toks = head.split()
    out = []
    for tok in reversed(toks):
        if tok[:1].isupper() or tok[:1].isdigit() or re.match(r"^[a-z]+[A-Z.]", tok):
            out.insert(0, tok)
        else:
            break
    name = " ".join(out).strip(" ,.'\"’")
    name = clean_company(name)
    if not name or len(name) > 40 or len(name) < 2 or name.lower() in {"it", "this", "startup", "company"}:
        return None
    return name

def extract_investors(text):
    m = LED_RE.search(text)
    if not m:
        return None
    inv = re.split(r"\s+(?:to|in|at|for|as|with|on|after|amid)\s+", m.group(1))[0]
    inv = re.split(r"\.\s", inv)[0]
    inv = re.sub(r"(?:,|\s+and|\s+&)\s*$", "", inv.strip(" ,.")).strip(" ,.")
    if re.fullmatch(r"(?i)(leading|top|new|existing|strategic|several|global|prominent)\s+investors?|investors?", inv):
        return None
    return inv[:80] if 2 < len(inv) else None

def tag_sector(title, summary=""):
    tags = [n for n, rx in SECTOR_RES if rx.search(title)]
    if not tags:
        tags = [n for n, rx in SECTOR_RES if rx.search(summary)]
    return tags[:2] or ["Horizontal AI"]

def key_for(company, amount):
    return f"{canon(company)}|{round(amount or 0)}"

def classify(item, ai_default):
    title, text = item["title"], item["title"] + " " + item["summary"]
    is_ai = ai_default or bool(AI_RE.search(title)) or bool(AI_RE.search(item["summary"][:300]))
    amt = AMOUNT_RE.search(title)
    cur = "$"
    if amt:
        musd = to_musd(amt.group(1), amt.group(2)); approx = False
    else:
        e = EUR_RE.search(title)
        musd = to_musd(e.group(2), e.group(3), e.group(1)) if e else None; approx = bool(e)
        if e: cur = e.group(1)
    stage_m = STAGE_RE.search(title) or (STAGE_RE.search(item["summary"][:400]) if musd else None)
    raise_m = RAISE_RE.search(title)
    is_round = bool(raise_m and (musd or stage_m)) or bool(stage_m and musd)
    # Filter out non-round money headlines (funds raised by VCs, acquisitions, revenue)
    if is_round and re.search(r"\b(fund [IVX0-9]+|new fund|closes? .*fund\b|acquir|acquisition|revenue|valuation talks|ARR|IPO|layoffs?)\b", title, re.I) \
            and not stage_m:
        is_round = False
    # Weekly roundups and "plus N more" digests are not a single round.
    if is_round and ROUNDUP_RE.search(title):
        is_round = False
    return is_ai, is_round, musd, approx, cur, (norm_stage(stage_m.group(1)) if stage_m else "Undisclosed")

def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=WINDOW_DAYS)
    prev = {}
    if OUT.exists():
        try: prev = json.loads(OUT.read_text())
        except Exception: prev = {}
    rounds = {r["id"]: r for r in prev.get("rounds", [])}
    news = {n["id"]: n for n in prev.get("news", [])}
    status = []
    for name, url, ai_default in SOURCES:
        try:
            items = parse_feed(fetch(url))
        except Exception as ex:
            status.append({"source": name, "ok": False, "items": 0, "rounds": 0, "error": str(ex)[:120]})
            continue
        n_rounds = 0; n_items = 0
        for it in items:
            if not it["title"] or not it["date"] or it["date"] < cutoff:
                continue
            is_ai, is_round, musd, approx, cur, stage = classify(it, ai_default)
            if not is_ai:
                continue
            n_items += 1
            publisher = it["publisher"] or name.split(":")[0].replace(" (Feedburner)", "")
            clean_title = re.sub(r"\s+-\s+" + re.escape(it["publisher"]) + r"$", "", it["title"]) if it["publisher"] else it["title"]
            company = extract_company(clean_title) if is_round else None
            if is_round and company:
                rid = key_for(company, musd)
                # also dedupe same company within ±2 days regardless of amount parse
                cc = canon(company)
                dup = next((k for k, r in rounds.items()
                            if abs((datetime.fromisoformat(r["date"]) - it["date"]).days) <= 7 and
                            (canon(r["company"]) == cc or ((cc in canon(r["company"]) or canon(r["company"]) in cc)
                             and min(len(cc), len(canon(r["company"]))) >= 4 and musd and r.get("amount_musd") == musd))), None)
                rec = {"id": rid, "company": company, "stage": stage, "amount_musd": musd,
                       "amount_approx": approx, "currency": cur,
                       "investors": extract_investors(clean_title + ". " + it["summary"][:400]),
                       "sectors": tag_sector(clean_title, it["summary"][:300]),
                       "date": it["date"].isoformat(), "title": clean_title, "link": it["link"],
                       "source": publisher, "feed": name}
                if dup:
                    old = rounds[dup]
                    # keep the richer record; prefer explicit stage/investors/amount
                    if len(company) < len(old["company"]) and canon(company) == canon(old["company"]):
                        old["company"] = company
                    for f in ("stage", "amount_musd", "investors"):
                        if (old.get(f) in (None, "Undisclosed")) and rec.get(f) not in (None, "Undisclosed"):
                            old[f] = rec[f]
                    old.setdefault("also_reported_by", [])
                    if publisher != old["source"] and publisher not in old["also_reported_by"]:
                        old["also_reported_by"].append(publisher)
                else:
                    rounds[rid] = rec
                n_rounds += 1
            nid = hashlib.md5(re.sub(r"\W", "", clean_title.lower())[:90].encode()).hexdigest()[:12]
            if nid not in news:
                news[nid] = {"id": nid, "title": clean_title, "link": it["link"], "date": it["date"].isoformat(),
                             "source": publisher, "is_round": bool(is_round and company),
                             "sectors": tag_sector(clean_title, it["summary"][:300])}
        status.append({"source": name, "ok": True, "items": n_items, "rounds": n_rounds})
    rounds = [r for r in rounds.values() if datetime.fromisoformat(r["date"]) >= cutoff]
    news = [n for n in news.values() if datetime.fromisoformat(n["date"]) >= cutoff]
    rounds.sort(key=lambda r: r["date"], reverse=True)
    news.sort(key=lambda n: n["date"], reverse=True)
    data = {"generated_at": now.isoformat(timespec="seconds"), "window_days": WINDOW_DAYS,
            "sources": status, "rounds": rounds, "news": news[:150],
            "notes": "Rule-based extraction from public headlines; amounts in USD millions (non-USD converted approximately). "
                     "Verify any figure against the linked source before relying on it."}
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    ok = sum(s["ok"] for s in status)
    print(f"Wrote {OUT.name}: {len(rounds)} rounds, {len(news[:150])} news items; {ok}/{len(status)} sources OK")
    for s in status:
        print(f"  {'OK ' if s['ok'] else 'ERR'} {s['source']}: {s['items']} AI items, {s['rounds']} rounds {s.get('error','')}")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
