"""CSUF public (guest) class search: look up one course and report each section's status."""
import re
import requests
from bs4 import BeautifulSoup

URL = "https://cmsweb.fullerton.edu/psc/CFULPRD/EMPLOYEE/SA/c/SA_LEARNER_SERVICES.CLASS_SEARCH.GBL?&public"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def _form(html):
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    data = {}
    for i in form.find_all("input"):
        n = i.get("name")
        if not n:
            continue
        if i.get("type") in ("checkbox", "radio") and not i.has_attr("checked"):
            continue
        if i.get("type") in ("button", "submit", "image", "reset"):
            continue
        data[n] = i.get("value", "")
    for s in form.find_all("select"):
        n = s.get("name")
        if not n:
            continue
        sel = s.find("option", selected=True)
        data[n] = sel.get("value", "") if sel else ""
    return soup, form, data


def _find(names, *patterns):
    for n in names:
        if all(re.search(p, n, re.I) for p in patterns):
            return n
    return None


def _post(s, action, data, debug, step):
    data = dict(data)
    data["ICAJAX"] = "1"
    data["ICNAVTYPEDROPDOWN"] = "0"
    r = s.post(action, data=data, timeout=60)
    body = r.text
    frags = re.findall(r"<!\[CDATA\[(.*?)\]\]>", body, re.S)
    html = "\n".join(frags) if frags else body
    if debug is not None:
        debug.setdefault("steps", []).append({"step": step, "action": action, "status": r.status_code,
                                              "len": len(body), "head": body[:600],
                                              "msgs": re.findall(r"(?is)PSERROR[^>]*>([^<]{0,300})", body)[:5]})
    return html, body


def search(term_label, subject, catalog, debug=None):
    s = requests.Session()
    s.headers["User-Agent"] = UA
    r = s.get(URL, timeout=30)
    soup, form, data = _form(r.text)
    action = requests.compat.urljoin(r.url, form.get("action") or r.url)

    # term
    term_sel = None
    for sel in form.find_all("select"):
        if any(term_label.lower() in (o.get_text() or "").lower() for o in sel.find_all("option")):
            term_sel = sel
            break
    if not term_sel:
        raise RuntimeError("term not found: " + term_label)
    tval = next(o["value"] for o in term_sel.find_all("option") if term_label.lower() in o.get_text().lower())
    data[term_sel["name"]] = tval
    if debug is not None:
        debug["action"] = action
        debug["term"] = (term_sel["name"], tval)
        debug["fields"] = sorted(data)

    # selecting the term can trigger a page refresh in PeopleSoft: post it first
    data["ICAction"] = term_sel["name"]
    html, body = _post(s, action, data, debug, "term")
    m = re.search(r"ICStateNum[^0-9]{1,40}(\d+)", body)
    data["ICStateNum"] = m.group(1) if m else str(int(data.get("ICStateNum", "1")) + 1)
    data[term_sel["name"]] = tval
    names = list(data)

    subj = _find(names, "SUBJECT_SRCH") or _find(names, "SUBJECT")
    cat = _find(names, "CATALOG_NBR")
    if subj:
        data[subj] = subject
    if cat:
        data[cat] = catalog
    # catalog match type "exactly" (E) if present
    for n in names:
        if re.search(r"SSR_EXACT_MATCH1", n):
            data[n] = "E"
    # undergraduate career (required by CSUF's search)
    car = _find(names, "ACAD_CAREER")
    if car:
        data[car] = "UGRD"
    # show all classes, not only open ones
    for n in list(data):
        if re.search(r"OPEN_ONLY\$chk", n):
            data[n] = "N"
        elif re.search(r"OPEN_ONLY", n):
            data.pop(n)
    btn = _find(names, "SSR_PB_CLASS_SRCH") or "CLASS_SRCH_WRK2_SSR_PB_CLASS_SRCH"
    data["ICAction"] = btn
    if debug is not None:
        debug["subj_field"], debug["cat_field"], debug["button"] = subj, cat, btn
    html, body = _post(s, action, data, debug, "search")
    # confirm dialog for large result sets
    if "exceed" in html.lower() and "#ICSave" in html:
        _, form, data = _form(html)
        data["ICAction"] = "#ICSave"
        html, body = _post(s, action, data, debug, "confirm")
    if debug is not None:
        debug["result_html"] = html[:200000]
        debug["alerts"] = re.findall(r"alert\(([^)]{0,300})", html)[:5]
    return parse(html)


def parse(html):
    """Return {class_nbr: {"section": str, "status": "Open"|"Closed"|"Wait List"|?}}"""
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for a in soup.find_all(id=re.compile(r"MTG_CLASS_NBR\$\d+")):
        idx = re.search(r"\$(\d+)", a["id"]).group(1)
        nbr = a.get_text(strip=True)
        sec = soup.find(id=f"MTG_CLASSNAME${idx}")
        img = soup.find(id=re.compile(rf"win0divDERIVED_CLSRCH_SSR_STATUS_LONG\${idx}$"))
        status = "?"
        if img:
            im = img.find("img")
            status = (im.get("alt") if im else img.get_text(strip=True)) or "?"
        out[nbr] = {"section": sec.get_text(" ", strip=True) if sec else "", "status": status}
    return out
