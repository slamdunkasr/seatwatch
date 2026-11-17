"""Turns the class search results the watcher saw into a PNG (watched sections highlighted),
so each phone notification can show the actual CSUF page."""
import io

JS = r"""
(nbrs) => {
  document.body.style.fontFamily = 'Arial, sans-serif';
  document.body.style.background = '#fff';
  const cells = [...document.querySelectorAll('[id^="MTG_CLASS_NBR$"]')];
  if (!cells.length) return null;
  for (const el of cells) {
    if (!nbrs.includes(el.textContent.trim())) continue;
    let blk = el.closest('tr');
    while (blk && !(blk.textContent.includes('Status') && blk.textContent.includes(el.textContent.trim())))
      blk = blk.parentElement.closest('tr');
    blk = blk || el.closest('table');
    blk.style.background = '#fff3a3';
    blk.style.outline = '3px solid #e8a100';
  }
  const top = [...document.querySelectorAll('span,div,td')]
    .find(e => /CSU Fullerton \|/.test(e.textContent) && e.children.length === 0) || cells[0];
  const t = top.getBoundingClientRect();
  const b = cells[cells.length - 1].closest('tr').getBoundingClientRect();
  return {x: 0, y: Math.max(0, t.top - 10 + window.scrollY), width: 1300, height: b.bottom - t.top + 30};
}
"""


def render(pages):
    """pages: list of (result_html, [class_nbrs_to_highlight]). Returns PNG bytes, or None."""
    try:
        from playwright.sync_api import sync_playwright
        from PIL import Image
    except Exception as e:
        print("snapshot unavailable:", e)
        return None
    shots = []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1300, "height": 900}, device_scale_factor=1.5)
            for html, nbrs in pages:
                if not html:
                    continue
                pg.set_content(html, wait_until="domcontentloaded")
                clip = pg.evaluate(JS, list(nbrs))
                if clip:
                    shots.append(Image.open(io.BytesIO(pg.screenshot(clip=clip, full_page=True))))
            b.close()
    except Exception as e:
        print("snapshot failed:", e)
        return None
    if not shots:
        return None
    w = max(s.width for s in shots)
    gap = 24
    out = Image.new("RGB", (w, sum(s.height for s in shots) + gap * (len(shots) - 1)), "white")
    y = 0
    for s in shots:
        out.paste(s, (0, y))
        y += s.height + gap
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()
