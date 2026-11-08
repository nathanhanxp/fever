"""Primary sources: deep-linked pages, passages quoted live from the page text, and the live CISA KEV feed."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

import httpx

from app.core.config import DATA_DIR

CACHE = Path(DATA_DIR) / "source_cache"
CACHE.mkdir(parents=True, exist_ok=True)
KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
KEV_TTL = 12 * 3600
UA = {"User-Agent": "Mozilla/5.0 ModSwarm source verifier"}

LIBRARY: list[dict] = [
    {"id": "owasp-api2", "title": "OWASP API Security Top 10 2023 — API2: Broken Authentication", "publisher": "OWASP",
     "url": "https://owasp.org/API-Security/editions/2023/en/0xa2-broken-authentication/", "topics": ["api-auth"]},
    {"id": "owasp-api1", "title": "OWASP API Security Top 10 2023 — API1: Broken Object Level Authorization", "publisher": "OWASP",
     "url": "https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/", "topics": ["api-authz"]},
    {"id": "owasp-api3", "title": "OWASP API Security Top 10 2023 — API3: Broken Object Property Level Authorization", "publisher": "OWASP",
     "url": "https://owasp.org/API-Security/editions/2023/en/0xa3-broken-object-property-level-authorization/", "topics": ["api-authz", "card-data"]},
    {"id": "owasp-api8", "title": "OWASP API Security Top 10 2023 — API8: Security Misconfiguration", "publisher": "OWASP",
     "url": "https://owasp.org/API-Security/editions/2023/en/0xa8-security-misconfiguration/", "topics": ["misconfig", "transit"]},
    {"id": "owasp-api9", "title": "OWASP API Security Top 10 2023 — API9: Improper Inventory Management", "publisher": "OWASP",
     "url": "https://owasp.org/API-Security/editions/2023/en/0xa9-improper-inventory-management/", "topics": ["service", "refactor"]},
    {"id": "owasp-microservices", "title": "OWASP Microservices Security Cheat Sheet", "publisher": "OWASP Cheat Sheet Series",
     "url": "https://cheatsheetseries.owasp.org/cheatsheets/Microservices_Security_Cheat_Sheet.html", "topics": ["api-auth", "service"]},
    {"id": "owasp-input", "title": "OWASP Input Validation Cheat Sheet", "publisher": "OWASP Cheat Sheet Series",
     "url": "https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html", "topics": ["input"]},
    {"id": "owasp-tls", "title": "OWASP Transport Layer Security Cheat Sheet", "publisher": "OWASP Cheat Sheet Series",
     "url": "https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html", "topics": ["transit"]},
    {"id": "owasp-crypto", "title": "OWASP Cryptographic Storage Cheat Sheet", "publisher": "OWASP Cheat Sheet Series",
     "url": "https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html", "topics": ["card-data"]},
    {"id": "owasp-secrets", "title": "OWASP Secrets Management Cheat Sheet", "publisher": "OWASP Cheat Sheet Series",
     "url": "https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html", "topics": ["secrets"]},
    {"id": "owasp-errors", "title": "OWASP Error Handling Cheat Sheet", "publisher": "OWASP Cheat Sheet Series",
     "url": "https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html", "topics": ["errors"]},
    {"id": "owasp-mass-assign", "title": "OWASP Mass Assignment Cheat Sheet", "publisher": "OWASP Cheat Sheet Series",
     "url": "https://cheatsheetseries.owasp.org/cheatsheets/Mass_Assignment_Cheat_Sheet.html", "topics": ["api-authz", "input"]},
    {"id": "nist-800-52", "title": "NIST SP 800-52 Rev. 2 — Guidelines for TLS Implementations", "publisher": "NIST",
     "url": "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-52r2.pdf", "topics": ["transit"]},
    {"id": "nist-800-57", "title": "NIST SP 800-57 Part 1 Rev. 5 — Key Management", "publisher": "NIST",
     "url": "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-57pt1r5.pdf", "topics": ["secrets", "card-data"]},
    {"id": "cisa-kev", "title": "CISA Known Exploited Vulnerabilities Catalog", "publisher": "CISA",
     "url": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog", "topics": ["misconfig", "service"]},
    {"id": "pci-dss-4", "title": "PCI DSS v4.0 — Requirement 4 (Protect CHD during transmission)", "publisher": "PCI SSC",
     "url": "https://docs-prv.pcisecuritystandards.org/PCI%20DSS/Standard/PCI-DSS-v4_0.pdf", "topics": ["card-data", "transit"]},
    {"id": "carddemo-readme", "title": "AWS CardDemo README — COBOL/CICS credit-card demo", "publisher": "AWS Samples (GitHub)",
     "url": "https://raw.githubusercontent.com/aws-samples/aws-mainframe-modernization-carddemo/main/README.md",
     "link": "https://github.com/aws-samples/aws-mainframe-modernization-carddemo#readme", "topics": ["carddemo"]},
    {"id": "aws-m2-refactor", "title": "AWS Mainframe Modernization — Automated refactoring", "publisher": "AWS Documentation",
     "url": "https://docs.aws.amazon.com/m2/latest/userguide/refactoring-app.html", "topics": ["carddemo", "refactor"]},
    {"id": "aws-m2-security", "title": "AWS Mainframe Modernization — Security", "publisher": "AWS Documentation",
     "url": "https://docs.aws.amazon.com/m2/latest/userguide/security.html", "topics": ["secrets", "transit", "refactor"]},
    {"id": "spring-jwt", "title": "Spring Security — OAuth 2.0 Resource Server JWT", "publisher": "Spring",
     "url": "https://docs.spring.io/spring-security/reference/servlet/oauth2/resource-server/jwt.html", "topics": ["api-auth"], "stack": "java"},
    {"id": "spring-authz", "title": "Spring Security — Authorize HttpServletRequests", "publisher": "Spring",
     "url": "https://docs.spring.io/spring-security/reference/servlet/authorization/authorize-http-requests.html", "topics": ["api-authz"], "stack": "java"},
    {"id": "spring-csrf", "title": "Spring Security — CSRF protection when modernizing form apps", "publisher": "Spring",
     "url": "https://docs.spring.io/spring-security/reference/servlet/exploits/csrf.html", "topics": ["input", "misconfig"], "stack": "java"},
    {"id": "pg-ssl", "title": "PostgreSQL — Secure TCP/IP Connections with SSL", "publisher": "PostgreSQL Documentation",
     "url": "https://www.postgresql.org/docs/current/ssl-tcp.html", "topics": ["transit"], "stack": "postgres"},
    {"id": "pg-libpq-ssl", "title": "PostgreSQL — libpq SSL Support (sslmode=verify-full)", "publisher": "PostgreSQL Documentation",
     "url": "https://www.postgresql.org/docs/current/libpq-ssl.html#LIBPQ-SSL-PROTECTION", "topics": ["transit"], "stack": "postgres"},
    {"id": "pg-numeric", "title": "PostgreSQL — Numeric Types (avoid float for money)", "publisher": "PostgreSQL Documentation",
     "url": "https://www.postgresql.org/docs/current/datatype-numeric.html#DATATYPE-NUMERIC-DECIMAL", "topics": ["precision"], "stack": "postgres"},
    {"id": "aspnet-auth", "title": "ASP.NET Core — Overview of authentication", "publisher": "Microsoft Learn",
     "url": "https://learn.microsoft.com/en-us/aspnet/core/security/authentication/", "topics": ["api-auth"], "stack": "dotnet"},
    {"id": "aspnet-secrets", "title": "ASP.NET Core — Safe storage of app secrets", "publisher": "Microsoft Learn",
     "url": "https://learn.microsoft.com/en-us/aspnet/core/security/app-secrets", "topics": ["secrets"], "stack": "dotnet"},
    {"id": "azure-sql-conn", "title": "Azure SQL — Connectivity settings (minimum TLS)", "publisher": "Microsoft Learn",
     "url": "https://learn.microsoft.com/en-us/azure/azure-sql/database/connectivity-settings", "topics": ["transit"], "stack": "azure"},
    {"id": "quarkus-security", "title": "Quarkus — Security architecture overview", "publisher": "Quarkus",
     "url": "https://quarkus.io/guides/security-overview", "topics": ["api-auth"], "stack": "quarkus"},
    {"id": "quarkus-oidc", "title": "Quarkus — OpenID Connect Bearer token auth", "publisher": "Quarkus",
     "url": "https://quarkus.io/guides/security-oidc-bearer-token-authentication", "topics": ["api-auth", "api-authz"], "stack": "quarkus"},
]

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "api-auth": ["authentication", "unauthenticated", "token", "jwt", "credential", "bearer", "validate"],
    "api-authz": ["authorization", "object", "access", "user", "permission", "record", "id"],
    "misconfig": ["tls", "misconfigur", "encrypt", "transport", "header"],
    "service": ["service", "authentication", "microservice", "token", "mutual"],
    "input": ["validation", "input", "allowlist", "length", "type", "server"],
    "transit": ["tls", "encrypt", "transit", "certificate", "plaintext", "ssl", "connection"],
    "card-data": ["sensitive data", "encrypt", "at rest", "stored", "protect", "minimi"],
    "secrets": ["secret", "password", "hardcoded", "source code", "credential", "vault"],
    "errors": ["error", "exception", "handling", "stack trace", "information", "leak"],
    "precision": ["numeric", "precision", "decimal", "exact", "monetary", "rounding"],
    "carddemo": ["mainframe", "cobol", "cics", "vsam", "migration", "modernization", "application"],
    "refactor": ["refactor", "mainframe", "modernization", "cobol", "migrate"],
}

EDGE_TOPICS = {
    "TRANS": ["api-auth", "api-authz"], "SCREEN": ["input", "api-authz"], "LINK": ["service", "api-auth"],
    "XCTL": ["api-auth", "service"], "FILE": ["transit", "precision"], "JOB": ["secrets", "transit"],
    "COPY": ["precision", "card-data"], "CALL": ["errors"],
}

KEV_PRODUCTS = {
    "java": ["spring", "tomcat", "log4j", "java se", "jackson", "struts"],
    "postgres": ["postgresql"],
    "dotnet": [".net", "asp.net", "iis"],
    "azure": ["azure"],
    "quarkus": ["red hat", "undertow", "jboss"],
    "legacy": ["websphere", "cics", "z/os", "ibm mq"],
}


class _Text(HTMLParser):
    SKIP = {"script", "style", "nav", "header", "footer", "noscript", "svg", "aside"}

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.out: list[str] = []

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


def _cache_file(url: str) -> Path:
    return CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".txt")


def _page_text(url: str) -> str:
    path = _cache_file(url)
    if path.exists():
        return path.read_text()
    try:
        r = httpx.get(url, timeout=10, follow_redirects=True, headers=UA)
        r.raise_for_status()
        raw = r.text
    except Exception:  # noqa: BLE001
        return ""
    if url.endswith(".md"):
        text = re.sub(r"[#*`>\[\]|]", " ", raw)
    else:
        parser = _Text()
        parser.feed(raw)
        text = "".join(parser.out)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    path.write_text(text)
    return text


def _best_passage(text: str, keywords: list[str]) -> str:
    best, best_score = "", 0.0
    for block in text.split("\n"):
        for sent in re.split(r"(?<=[.!?])\s+", block.strip()):
            s = sent.strip()
            if not (70 <= len(s) <= 340) or s.count(" ") < 8 or s[-1] not in ".!?" or not s[0].isupper():
                continue
            low = s.lower()
            score = sum(1 for k in keywords if k in low) + (0.3 if low[0].isalpha() else 0)
            if score > best_score:
                best, best_score = s, score
    return best


def _stack_tags(stack: dict | None) -> set[str]:
    blob = " ".join(str(v).lower() for v in (stack or {}).values() if v)
    tags = set()
    if any(k in blob for k in ("java", "spring", "kotlin")):
        tags.add("java")
    if "quarkus" in blob:
        tags |= {"quarkus", "java"}
    if "postgres" in blob:
        tags.add("postgres")
    if any(k in blob for k in (".net", "c#", "asp", "dotnet")):
        tags.add("dotnet")
    if "azure" in blob:
        tags.add("azure")
    return tags


def warm(stack: dict | None = None) -> None:
    urls = [d["url"] for d in LIBRARY]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(_page_text, urls))
    kev_feed()


def warm_async() -> None:
    threading.Thread(target=warm, daemon=True).start()


def sources_for(
    topics: list[str],
    stack: dict | None = None,
    limit: int = 3,
    *,
    source_java: bool | None = None,
) -> list[dict]:
    tags = _stack_tags(stack)
    # When the SOURCE repo is Java, never surface COBOL/CardDemo or ASP.NET overview pages
    blocked_ids = set()
    if source_java:
        blocked_ids = {
            "carddemo-readme", "aws-m2-refactor", "aws-m2-security", "pci-dss-4",
            "aspnet-auth", "aspnet-secrets", "azure-sql-conn",
        }
    picked: list[tuple[dict, str]] = []
    for topic in dict.fromkeys(topics):
        docs = []
        for d in LIBRARY:
            if topic not in d["topics"] or d["id"] in blocked_ids:
                continue
            st = d.get("stack")
            if source_java:
                # Java source cards: java stack or language-agnostic OWASP/NIST only
                if st and st not in {"java", "postgres"}:
                    continue
            elif st and st not in tags:
                continue
            url = (d.get("url") or "").rstrip("/")
            if url.endswith(("/security/authentication", "/guides", "/aspnet/core", "/docs/current")):
                continue
            docs.append(d)
        def _rank(d: dict) -> tuple:
            if source_java:
                if d.get("stack") == "java":
                    return (0,)
                if not d.get("stack"):
                    return (1,)
                return (2,)
            return (0 if d.get("stack") else 1,)

        docs.sort(key=_rank)
        for d in docs[:2]:
            if all(d["id"] != p[0]["id"] for p in picked):
                picked.append((d, topic))
    with ThreadPoolExecutor(6) as pool:
        texts = list(pool.map(lambda p: _page_text(p[0]["url"]), picked))
    out = []
    for (d, topic), text in zip(picked, texts):
        passage = _best_passage(text, TOPIC_KEYWORDS.get(topic, []))
        if not passage:
            continue
        out.append({"id": d["id"], "title": d["title"], "source": d["publisher"], "url": d.get("link") or d["url"], "passage": passage, "topic": topic})
        if len(out) >= limit:
            break
    return out


_KEV_LOCK = threading.Lock()


def kev_feed() -> dict:
    path = CACHE / "kev.json"
    with _KEV_LOCK:
        if path.exists() and time.time() - path.stat().st_mtime < KEV_TTL:
            return json.loads(path.read_text())
        try:
            r = httpx.get(KEV_URL, timeout=20, headers=UA)
            r.raise_for_status()
            path.write_text(r.text)
            return r.json()
        except Exception:  # noqa: BLE001
            return json.loads(path.read_text()) if path.exists() else {}


def kev_for(stack: dict | None, limit: int = 4) -> dict:
    feed = kev_feed()
    vulns = feed.get("vulnerabilities") or []
    tags = _stack_tags(stack) | {"legacy"}
    terms = [t for tag in tags for t in KEV_PRODUCTS.get(tag, [])]
    hits = [
        v for v in vulns
        if any(t in f"{v.get('vendorProject', '')} {v.get('product', '')}".lower() for t in terms)
    ]
    hits.sort(key=lambda v: v.get("dateAdded", ""), reverse=True)
    return {
        "catalog_version": feed.get("catalogVersion"),
        "date_released": feed.get("dateReleased"),
        "total": len(vulns),
        "matched": len(hits),
        "terms": terms,
        "url": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
        "items": [
            {
                "cve": v.get("cveID"),
                "name": v.get("vulnerabilityName"),
                "product": f"{v.get('vendorProject')} {v.get('product')}",
                "date_added": v.get("dateAdded"),
                "ransomware": v.get("knownRansomwareCampaignUse") == "Known",
                "description": (v.get("shortDescription") or "")[:220],
                "url": f"https://nvd.nist.gov/vuln/detail/{v.get('cveID')}",
            }
            for v in hits[:limit]
        ],
    }


def topics_for_finding(title: str) -> list[str]:
    low = (title or "").lower()
    if "password" in low or "secret" in low or "credential" in low:
        return ["secrets"]
    if "resp" in low or "nohandle" in low or "error" in low:
        return ["errors"]
    if any(k in low for k in ("card", "pan", "cvv", "ssn", "sensitive")):
        return ["card-data"]
    return []


def topics_for_step(step: dict, findings: list[str]) -> list[str]:
    topics: list[str] = []
    for f in findings:
        topics += topics_for_finding(f)
    for r in step.get("removals") or []:
        topics += EDGE_TOPICS.get(r.get("type") or "", [])
    verb = step.get("verb") or ""
    if not topics:
        topics = ["refactor"] if "migrate" in verb or "retire" in verb else ["carddemo"]
    return list(dict.fromkeys(topics))
