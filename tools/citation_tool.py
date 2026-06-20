"""
Academic citation helper — Phase 5E.
resolve_doi()  — fetches structured metadata from CrossRef API for any DOI.
Claude uses the returned metadata to format APA / MLA / Chicago citations.
For web URLs (non-DOI), use the existing fetch_page tool and let Claude extract metadata.
"""

import re


def resolve_doi(doi: str) -> str:
    """
    Fetch publication metadata for a DOI via the CrossRef API.
    Returns structured metadata for Claude to format as APA, MLA, or Chicago.

    doi — bare DOI (10.1000/xyz) or full URL (https://doi.org/10.1000/xyz)
    """
    try:
        import httpx
    except ImportError:
        return "[httpx not installed]"

    # Normalise — strip URL prefix
    doi = doi.strip()
    for prefix in ["https://doi.org/", "http://doi.org/", "doi.org/"]:
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
            break

    if not re.match(r"10\.\d{4,}/", doi):
        return (
            f"'{doi}' does not look like a valid DOI (should start with 10.XXXX/).\n"
            f"For a web URL, use fetch_page instead and extract the metadata manually."
        )

    try:
        resp = httpx.get(
            f"https://api.crossref.org/works/{doi}",
            timeout=10,
            headers={"User-Agent": "ElFager/1.0 (academic-assistant)"},
        )
    except Exception as e:
        return f"[CrossRef request failed: {e}]"

    if resp.status_code == 404:
        return f"DOI not found in CrossRef: {doi}"
    if resp.status_code != 200:
        return f"CrossRef returned HTTP {resp.status_code} for DOI: {doi}"

    data = resp.json().get("message", {})

    # Authors
    authors = []
    for a in data.get("author", []):
        family = a.get("family", "")
        given  = a.get("given", "")
        if family:
            authors.append(f"{family}, {given}" if given else family)

    # Publication year
    pub = data.get("published", data.get("published-print", data.get("created", {})))
    date_parts = pub.get("date-parts", [[]])
    year = str(date_parts[0][0]) if date_parts and date_parts[0] else "n.d."

    # Title
    titles = data.get("title", [])
    title  = titles[0] if titles else "Untitled"

    # Source
    container = data.get("container-title", [])
    journal   = container[0] if container else ""
    publisher = data.get("publisher", "")
    source    = journal or publisher

    volume  = data.get("volume", "")
    issue   = data.get("issue", "")
    pages   = data.get("page", "")
    doi_url = f"https://doi.org/{doi}"

    lines = [
        f"Metadata for DOI: {doi}",
        f"Title:     {title}",
        f"Authors:   {'; '.join(authors) or 'Unknown'}",
        f"Year:      {year}",
        f"Source:    {source}",
    ]
    if volume:
        lines.append(f"Volume:    {volume}")
    if issue:
        lines.append(f"Issue:     {issue}")
    if pages:
        lines.append(f"Pages:     {pages}")
    lines.append(f"DOI URL:   {doi_url}")
    lines.append(
        "\nUse this metadata to generate the citation in the requested style "
        "(APA, MLA, or Chicago)."
    )

    return "\n".join(lines)
