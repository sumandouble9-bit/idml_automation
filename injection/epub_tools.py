import os
import re
import html
import zipfile


def _strip_tags(s: str) -> str:
    # Strip HTML tags and unescape entities, returning plain text.
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = html.unescape(s)
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_epub(epub_path: str, images_out_dir: str):
    """Extract images and build the caption map for one EPUB.

    Returns (image_count, caption_map) where caption_map is
    { 'imageNNN.jpg': 'caption text', ... } for figures that have a <figcaption>.
    Images are written to images_out_dir (created if needed).
    """
    os.makedirs(images_out_dir, exist_ok=True)
    caption_map = {}
    image_count = 0

    with zipfile.ZipFile(epub_path, "r") as z:
        names = z.namelist()

        img_exts = (".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".bmp", ".webp")
        for n in names:
            if n.lower().endswith(img_exts):
                base = os.path.basename(n)
                if not base:
                    continue
                with z.open(n) as src:
                    data = src.read()
                with open(os.path.join(images_out_dir, base), "wb") as out:
                    out.write(data)
                image_count += 1

        doc_names = [n for n in names if n.lower().endswith((".xhtml", ".html", ".htm"))]
        for n in doc_names:
            try:
                content = z.read(n).decode("utf-8", "replace")
            except Exception:
                continue
            for fig in re.findall(r"(?is)<figure\b.*?</figure>", content):
                m_img = re.search(r'(?is)<img\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', fig)
                m_cap = re.search(r"(?is)<figcaption\b[^>]*>(.*?)</figcaption>", fig)
                if not m_img or not m_cap:
                    continue
                img_base = os.path.basename(m_img.group(1)).strip()
                caption = _strip_tags(m_cap.group(1))
                if img_base and caption:
                    caption_map[img_base] = caption

    return image_count, caption_map


def build_caption_map(epub_path: str):
    """Return only the { image_basename: caption } map (no image extraction)."""
    caption_map = {}
    with zipfile.ZipFile(epub_path, "r") as z:
        for n in z.namelist():
            if not n.lower().endswith((".xhtml", ".html", ".htm")):
                continue
            try:
                content = z.read(n).decode("utf-8", "replace")
            except Exception:
                continue
            for fig in re.findall(r"(?is)<figure\b.*?</figure>", content):
                m_img = re.search(r'(?is)<img\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', fig)
                m_cap = re.search(r"(?is)<figcaption\b[^>]*>(.*?)</figcaption>", fig)
                if not m_img or not m_cap:
                    continue
                img_base = os.path.basename(m_img.group(1)).strip()
                caption = _strip_tags(m_cap.group(1))
                if img_base and caption:
                    caption_map[img_base] = caption
    return caption_map


if __name__ == "__main__":
    import sys
    ep = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "epub_input_files", "18239.epub")
    out = os.path.join(os.path.dirname(__file__), "extracted_images",
                       os.path.splitext(os.path.basename(ep))[0])
    cnt, cap = extract_epub(ep, out)
    print(f"images extracted: {cnt}")
    print(f"captions found: {len(cap)}")
    for k in list(cap)[:10]:
        print(f"  {k} -> {cap[k][:60]}")
