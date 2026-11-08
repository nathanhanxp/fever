"""Live web research for Plan — look up how to modernize INTO the user's target stack.

No canned guidance. Results are fetched at Plan time and injected into Nemotron.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.core.config import DATA_DIR

CACHE = Path(DATA_DIR) / "web_research_cache"
CACHE.mkdir(parents=True, exist_ok=True)
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}

# Reject these — classic planner boilerplate that does not name a real stack
BANNED_GUIDANCE = re.compile(
    r"(dependency order ensures|repository boundary|cascading failures|"
    r"unauthorized access during the transition|validated foundation|"
    r"minimizes risk by addressing critical|"
    r"security constraints (are )?validated before|"
    r"wrapping datasets only after)",
    re.I,
)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self.depth = 0
        self.SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header"}

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        elif tag in {"p", "li", "h1", "h2", "h3", "h4", "td", "br", "div"}:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth:
            self.out.append(data)


def _cache_path(key: str, suffix: str) -> Path:
    return CACHE / (hashlib.sha1(key.encode()).hexdigest() + suffix)


def _unwrap_ddg_href(href: str) -> str:
    if "uddg=" in href:
        qs = parse_qs(urlparse(href).query)
        if qs.get("uddg"):
            return unquote(qs["uddg"][0])
    return href


_DOC_HOSTS = (
    "learn.microsoft.com", "docs.microsoft.com", "docs.oracle.com", "docs.spring.io",
    "quarkus.io", "jakarta.ee", "www.postgresql.org", "www.sqlite.org", "grpc.io",
    "en.cppreference.com", "isocpp.org", "owasp.org", "cheatsheetseries.owasp.org",
    "docs.aws.amazon.com", "kubernetes.io", "go.dev", "doc.rust-lang.org", "docs.rs",
    "fastapi.tiangolo.com", "docs.sqlalchemy.org", "docs.nestjs.com", "nodejs.org",
    "dev.mysql.com", "nextjs.org", "developer.mozilla.org", "github.com",
    "raw.githubusercontent.com", "baeldung.com", "refactoring.guru",
)

_BAD_URL = (
    "java.com/en/download", "oracle.com/java/technologies/downloads",
    "facebook.com", "twitter.com", "pinterest.", "youtube.com/shorts",
    "amazon.com/dp/", "play.google.com", "apps.apple.com",
    "merriam-webster.com", "dictionary.com", "cambridge.org/dictionary",
    "thesaurus.com", "vocabulary.com", "wiktionary.org", "britannica.com",
    "en.m.wikipedia.org/wiki/Spring_(season)", "wikipedia.org/wiki/Spring_(season)",
    "wikipedia.org/wiki/Migrate", "wikipedia.org/wiki/Persistence",
    "simple.wikipedia.org", "go.dev/dl", "PayloadsAllTheThings",
    "spring-framework/docs/3.", "spring-framework/docs/4.",
)

_JUNK_TITLE = re.compile(
    r"\b(definition|dictionary|thesaurus|synonym|pronunciation|season|"
    r"psychology|personality trait)\b",
    re.I,
)


def _is_doc_host(url: str) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return any(host.endswith(h) or h in host for h in _DOC_HOSTS)

# Always fetch these for the matching target — search is additive, not the only source
_SEED_DOCS: list[tuple[re.Pattern[str], list[dict]]] = [
    (re.compile(r"c\+\+|cpp", re.I), [
        {"title": "gRPC C++ authentication", "url": "https://grpc.io/docs/guides/auth/"},
        {"title": "gRPC C++ quick start", "url": "https://grpc.io/docs/languages/cpp/quickstart/"},
        {"title": "OWASP SQL Injection Prevention", "url": "https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html"},
    ]),
    (re.compile(r"quarkus", re.I), [
        {"title": "Quarkus — Spring API compatibility", "url": "https://quarkus.io/guides/spring-di"},
        {"title": "Quarkus Security OIDC", "url": "https://quarkus.io/guides/security-oidc-bearer-token-authentication"},
        {"title": "Quarkus Hibernate ORM", "url": "https://quarkus.io/guides/hibernate-orm"},
    ]),
    (re.compile(r"spring|java\s*21|\bjava\b", re.I), [
        {"title": "Spring Boot 3 migration guide", "url": "https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-3.0-Migration-Guide"},
        {"title": "Spring Security authorize requests", "url": "https://docs.spring.io/spring-security/reference/servlet/authorization/authorize-http-requests.html"},
        {"title": "Jakarta Persistence", "url": "https://jakarta.ee/specifications/persistence/3.1/"},
    ]),
    (re.compile(r"azure\s*sql|asp\.net|c#|\.net", re.I), [
        {"title": "Migrate from Java to .NET", "url": "https://learn.microsoft.com/en-us/dotnet/core/porting/java-to-csharp"},
        {"title": "Azure SQL connectivity / TLS", "url": "https://learn.microsoft.com/en-us/azure/azure-sql/database/connectivity-settings"},
        {"title": "ASP.NET Core authentication", "url": "https://learn.microsoft.com/en-us/aspnet/core/security/authentication/"},
    ]),
    (re.compile(r"postgres", re.I), [
        {"title": "PostgreSQL SSL connections", "url": "https://www.postgresql.org/docs/current/ssl-tcp.html"},
        {"title": "PostgreSQL numeric types", "url": "https://www.postgresql.org/docs/current/datatype-numeric.html"},
    ]),
    (re.compile(r"\bgo\b|golang", re.I), [
        {"title": "Go database/sql", "url": "https://go.dev/doc/database/"},
        {"title": "gRPC Go authentication", "url": "https://grpc.io/docs/guides/auth/"},
    ]),
    (re.compile(r"python|fastapi", re.I), [
        {"title": "FastAPI security", "url": "https://fastapi.tiangolo.com/tutorial/security/"},
        {"title": "SQLAlchemy 2.0 migration", "url": "https://docs.sqlalchemy.org/en/20/changelog/migration_20.html"},
    ]),
    (re.compile(r"typescript|node|nestjs|express", re.I), [
        {"title": "NestJS authentication", "url": "https://docs.nestjs.com/security/authentication"},
        {"title": "Node.js security best practices", "url": "https://nodejs.org/en/learn/getting-started/security-best-practices"},
    ]),
    (re.compile(r"mysql|maria", re.I), [
        {"title": "MySQL prepared statements", "url": "https://dev.mysql.com/doc/refman/8.4/en/sql-prepared-statements.html"},
        {"title": "MySQL SSL connections", "url": "https://dev.mysql.com/doc/refman/8.4/en/using-encrypted-connections.html"},
    ]),
    (re.compile(r"rust|axum", re.I), [
        {"title": "Axum docs", "url": "https://docs.rs/axum/latest/axum/"},
        {"title": "SQLx Rust", "url": "https://docs.rs/sqlx/latest/sqlx/"},
    ]),
]


def _score_hit(url: str, title: str, query: str) -> int:
    score = 0
    if _is_doc_host(url):
        score += 5
    else:
        score -= 3  # prefer official/docs hosts only
    if any(bad in url.lower() for bad in _BAD_URL):
        score -= 20
    if _JUNK_TITLE.search(title or ""):
        score -= 15
    if "wikipedia.org" in url.lower() and "cppreference" not in url.lower():
        score -= 6  # encyclopedia intros ≠ migration docs
    if "download" in (title or "").lower() or "download" in url.lower():
        score -= 4
    qbits = [w for w in re.findall(r"[a-z0-9+#]{3,}", query.lower()) if w not in {"the", "and", "for", "with"}]
    blob = f"{title} {url}".lower()
    score += sum(1 for w in qbits if w in blob)
    return score


def _ddgs_search(query: str, limit: int = 5) -> list[dict]:
    """Prefer duckduckgo_search / ddgs; fall back to HTML scrape."""
    try:
        try:
            from ddgs import DDGS  # type: ignore
        except ImportError:
            from duckduckgo_search import DDGS  # type: ignore

        rows = []
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=max(limit * 2, 8)):
                rows.append({
                    "title": item.get("title") or "",
                    "url": item.get("href") or item.get("link") or "",
                    "snippet": item.get("body") or item.get("snippet") or "",
                })
        rows = [r for r in rows if r.get("url")]
        rows.sort(key=lambda r: -_score_hit(r["url"], r.get("title") or "", query))
        rows = [r for r in rows if _score_hit(r["url"], r.get("title") or "", query) >= 0][:limit]
        if rows:
            return rows
    except Exception:
        pass

    try:
        with httpx.Client(timeout=20, follow_redirects=True, headers=UA) as client:
            r = client.post("https://html.duckduckgo.com/html/", data={"q": query})
            r.raise_for_status()
            html = r.text
    except Exception:
        return []

    rows = []
    for m in re.finditer(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        html,
        re.I | re.S,
    ):
        url = _unwrap_ddg_href(m.group(1))
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not url.startswith("http"):
            continue
        rows.append({"title": title, "url": url, "snippet": ""})
        if len(rows) >= limit:
            break
    # snippets
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)', html, re.I | re.S)
    for i, sn in enumerate(snippets[: len(rows)]):
        rows[i]["snippet"] = re.sub(r"<[^>]+>", "", sn).strip()
    return rows


def _page_passage(url: str, keywords: list[str], max_chars: int = 500) -> str:
    path = _cache_path(url, ".txt")
    if path.exists() and time.time() - path.stat().st_mtime < 7 * 86400:
        text = path.read_text(errors="replace")
    else:
        try:
            with httpx.Client(timeout=12, follow_redirects=True, headers=UA) as client:
                r = client.get(url)
                r.raise_for_status()
                raw = r.text
        except Exception:
            return ""
        if url.endswith(".md") or "raw.githubusercontent" in url:
            text = re.sub(r"[#*`>\[\]|]", " ", raw)
        else:
            parser = _Text()
            try:
                parser.feed(raw)
            except Exception:
                return ""
            text = "".join(parser.out)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        path.write_text(text[:80_000], errors="replace")

    best, score = "", 0
    for block in text.split("\n"):
        for sent in re.split(r"(?<=[.!?])\s+", block.strip()):
            s = sent.strip()
            if not (60 <= len(s) <= 360):
                continue
            low = s.lower()
            sc = sum(1 for k in keywords if k and k.lower() in low)
            if sc > score:
                best, score = s, sc
    if best:
        return best[:max_chars]
    # fallback: first decent paragraph
    for block in text.split("\n"):
        b = block.strip()
        if len(b) > 120:
            return b[:max_chars]
    return text[:max_chars]


def _queries(source_kind: str, label: str, repo: str) -> list[str]:
    blob = f"{label} {repo}".lower()
    src = "Java VRaptor Hibernate" if "java" in source_kind.lower() else "COBOL CICS VSAM"
    qs: list[str] = []
    if "c++" in blob or "cpp" in blob:
        qs = [
            "site:grpc.io C++ server authentication",
            "site:en.cppreference.com C++",
            "site:owasp.org SQL injection prepared statements",
            f"migrate {src} to C++ REST gRPC",
        ]
    elif "quarkus" in blob:
        qs = [
            "site:quarkus.io migrate from Spring",
            "site:quarkus.io security OIDC JWT",
            "site:quarkus.io Hibernate ORM Panache",
        ]
    elif re.search(r"\bjava\b|spring", blob):
        qs = [
            "site:docs.spring.io Spring Boot 3 migration guide",
            "site:docs.spring.io Spring Security authorizeHttpRequests",
            "site:jakarta.ee persistence javax jakarta",
            "site:baeldung.com Spring Boot modernization",
        ]
    elif "azure sql" in blob or "c#" in blob or ".net" in blob or "asp.net" in blob:
        qs = [
            "site:learn.microsoft.com migrate Java to .NET",
            "site:learn.microsoft.com Entity Framework Core Azure SQL",
            "site:learn.microsoft.com ASP.NET Core authentication",
            "site:learn.microsoft.com Azure SQL connectivity TLS",
        ]
    elif "postgres" in blob:
        qs = [
            "site:www.postgresql.org ssl tcp",
            "site:www.postgresql.org datatype numeric",
            f"{src} to PostgreSQL migration",
        ]
    elif "mysql" in blob or "maria" in blob:
        qs = [
            "site:dev.mysql.com prepared statements",
            "site:dev.mysql.com encrypted connections SSL",
        ]
    elif re.search(r"\bgo\b", blob) or "golang" in blob:
        qs = [
            "site:go.dev database sql",
            "site:grpc.io go authentication",
            "site:owasp.org SQL injection",
        ]
    elif "rust" in blob or "axum" in blob:
        qs = [
            "site:docs.rs axum",
            "site:docs.rs sqlx",
        ]
    elif "python" in blob or "fastapi" in blob:
        qs = [
            "site:fastapi.tiangolo.com security",
            "site:docs.sqlalchemy.org migration",
        ]
    elif "typescript" in blob or "nestjs" in blob or "node" in blob:
        qs = [
            "site:docs.nestjs.com authentication",
            "site:nodejs.org security best practices",
        ]
    else:
        # Arbitrary one-word / one-DB target — still force live search
        qs = [
            f"{label} official documentation authentication database migration",
            f"migrate {src} application to {label}",
            f"site:owasp.org {label}",
            f"{label} prepared statements TLS connection security",
        ]
    out, seen = [], set()
    for q in qs:
        k = q.lower()
        if k not in seen:
            seen.add(k)
            out.append(q)
    return out[:4]


def research_stack(
    *,
    source_kind: str,
    target_label: str,
    repo: str = "",
    limit_hits: int = 6,
) -> dict:
    """Search the public web for how to move this codebase to the chosen target."""
    started = time.time()
    queries = _queries(source_kind, target_label, repo)
    keywords = re.findall(r"[A-Za-z0-9+#.]{3,}", f"{source_kind} {target_label}")[:12]

    hits: list[dict] = []
    seen_urls: set[str] = set()

    # Seed official docs first so Plan always has real target material
    for pat, seeds in _SEED_DOCS:
        if pat.search(target_label):
            for s in seeds:
                url = s["url"]
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                hits.append({**s, "snippet": "", "query": "seed-docs"})
            break

    for q in queries:
        for row in _ddgs_search(q, limit=5):
            url = (row.get("url") or "").split("#")[0]
            if not url or url in seen_urls:
                continue
            title = row.get("title") or ""
            if any(bad in url.lower() for bad in _BAD_URL):
                continue
            if _JUNK_TITLE.search(title):
                continue
            # Only keep doc hosts from search — encyclopedias/dictionaries never enter Plan
            if not _is_doc_host(url):
                continue
            if _score_hit(url, title, q) < 2:
                continue
            seen_urls.add(url)
            hits.append({**row, "url": url, "query": q})
            if len(hits) >= limit_hits + 3:
                break
        if len(hits) >= limit_hits + 3:
            break

    # Fetch passages for top hits in parallel
    enriched = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {
            pool.submit(_page_passage, h["url"], keywords): h
            for h in hits[:8]
        }
        for fut in as_completed(futs):
            h = futs[fut]
            try:
                passage = fut.result() or h.get("snippet") or ""
            except Exception:
                passage = h.get("snippet") or ""
            if not passage and h.get("query") != "seed-docs":
                continue
            enriched.append({
                "title": h.get("title") or h["url"],
                "url": h["url"],
                "query": h.get("query"),
                "passage": (passage or "")[:480],
            })

    # Prefer seed docs in seed order, then other doc hosts
    seed_rank = {h["url"]: i for i, h in enumerate(hits) if h.get("query") == "seed-docs"}
    enriched.sort(
        key=lambda r: (
            0 if r.get("query") == "seed-docs" else 1,
            seed_rank.get(r.get("url") or "", 99),
            r.get("title") or "",
        )
    )
    enriched = enriched[:limit_hits]
    packet = {
        "queries": queries,
        "sources": enriched,
        "latency_s": round(time.time() - started, 2),
        "claim": "Measured web fetch",
    }
    path = _cache_path(f"{source_kind}|{target_label}|{repo}", ".json")
    path.write_text(json.dumps(packet))
    return packet


def research_prompt_block(packet: dict) -> str:
    sources = packet.get("sources") or []
    if not sources:
        return (
            "WEB RESEARCH: no live hits (network blocked). "
            "Still name the target stack explicitly; do not invent vendor docs.\n"
        )
    lines = [
        "WEB RESEARCH (fetched live for THIS target — cite these URLs in why/fix when relevant):",
    ]
    for i, s in enumerate(sources[:6], 1):
        lines.append(
            f"{i}. {s.get('title')} — {s.get('url')}\n"
            f"   Passage: {s.get('passage') or '(snippet only)'}"
        )
    lines.append(
        "You MUST ground guidance + step titles in these sources and the repo evidence. "
        "Name the target stack. Forbidden: generic filler about dependency order / repository boundaries "
        "that could apply to any migration."
    )
    return "\n".join(lines) + "\n"


def is_banned_guidance(text: str | None) -> bool:
    return bool(text and BANNED_GUIDANCE.search(text))
