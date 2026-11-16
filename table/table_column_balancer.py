import os
import sys
import zipfile
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def get_clean_text(elem):
    if elem is None:
        return ""
    texts = [c.text for c in elem.iter() if c.tag.endswith("Content") and c.text]
    return "".join(texts).strip("\ufeff\u2028\u00a0 \t\r\n")


def get_cell(table, col_idx, row_idx):
    for cell in table.iter():
        if cell.tag.endswith("Cell") and cell.attrib.get("Name") == f"{col_idx}:{row_idx}":
            return cell
    return None


def detect_imbalance(table, num_rows, num_cols, cur_widths):
    tot_w = sum(cur_widths)
    if num_rows < 2 or num_cols < 2 or tot_w <= 0:
        return False, set(), False

    is_all_24 = all(abs(w - 24.0) < 0.5 for w in cur_widths)
    if is_all_24:
        return True, set(), True

    title_rows = set()
    for r in range(min(2, num_rows)):
        c0_text = get_clean_text(get_cell(table, 0, r))
        other_empty = True
        for c in range(1, num_cols):
            if get_clean_text(get_cell(table, c, r)):
                other_empty = False
                break
        if c0_text and len(c0_text) > 10 and other_empty:
            title_rows.add(r)

    if not title_rows:
        return False, set(), False

    col0_ratio = cur_widths[0] / tot_w
    col0_data_lens = []
    for r in range(num_rows):
        if r not in title_rows:
            t = get_clean_text(get_cell(table, 0, r))
            if t:
                col0_data_lens.append(len(t))

    avg_data = sum(col0_data_lens) / len(col0_data_lens) if col0_data_lens else 0
    t0_len = max(len(get_clean_text(get_cell(table, 0, r))) for r in title_rows)

    if (t0_len > 2 * avg_data or len(col0_data_lens) == 0) and col0_ratio > 0.40:
        return True, title_rows, False

    return False, set(), False


def merge_spanning_cells(table, title_rows, num_cols):
    changed = False
    for r in title_rows:
        cell0 = get_cell(table, 0, r)
        if cell0 is not None and get_clean_text(cell0):
            other_cells = []
            for c in range(1, num_cols):
                other = get_cell(table, c, r)
                if other is not None and not get_clean_text(other):
                    other_cells.append(other)
            if len(other_cells) == num_cols - 1:
                cell0.set("ColumnSpan", str(num_cols))
                for other in other_cells:
                    try:
                        table.remove(other)
                        changed = True
                    except ValueError:
                        pass
    return changed


def compute_balanced_widths(table, num_rows, num_cols, title_rows, is_24, cur_widths, max_table_width=324.0):
    if is_24:
        col_max_words = []
        for c in range(num_cols):
            words = []
            for r in range(num_rows):
                txt = get_clean_text(get_cell(table, c, r))
                if txt:
                    words.extend([len(w) for w in txt.split()])
            col_max_words.append(max(words) if words else 0)

        if num_cols == 3 and col_max_words[0] > 10 and col_max_words[1] <= 4 and col_max_words[2] <= 4:
            return [240.0, 42.0, 42.0]
        if num_cols == 4 and col_max_words[0] > 10 and all(w <= 4 for w in col_max_words[1:]):
            return [240.0, 28.0, 28.0, 28.0]
        w = round(max_table_width / num_cols, 2)
        widths = [w] * num_cols
        diff = round(max_table_width - sum(widths), 2)
        widths[0] = round(widths[0] + diff, 2)
        return widths

    col_max_words = []
    col_max_lens = []
    has_data = []

    for c in range(num_cols):
        words = []
        lens = []
        for r in range(num_rows):
            if r not in title_rows:
                txt = get_clean_text(get_cell(table, c, r))
                if txt:
                    lens.append(len(txt))
                    words.extend([len(w) for w in txt.split()])
        col_max_lens.append(max(lens) if lens else 0)
        col_max_words.append(max(words) if words else 0)
        has_data.append(bool(lens))

    if num_cols >= 3 and not has_data[0] and not has_data[-1] and any(has_data[1:-1]):
        inner_demands = []
        for c in range(1, num_cols - 1):
            mw = col_max_words[c]
            ml = col_max_lens[c]
            inner_demands.append(max(55.0, ml * 5.2 + 18.0, mw * 5.5 + 18.0))
        inner_sum = sum(inner_demands)
        flank_w = round(max(30.0, (max_table_width - inner_sum) / 2.0), 2)
        widths = [flank_w] + [round(x, 2) for x in inner_demands] + [flank_w]
        diff = round(max_table_width - sum(widths), 2)
        widths[0] = round(widths[0] + diff, 2)
        return widths

    if num_cols == 2:
        mw1 = col_max_words[1]
        ml1 = col_max_lens[1]
        w1 = max(65.0, ml1 * 5.2 + 16.0, mw1 * 5.5 + 16.0)
        w0 = max_table_width - w1
        return [round(w0, 2), round(w1, 2)]

    demands = []
    for c in range(num_cols):
        mw = col_max_words[c]
        ml = col_max_lens[c]
        if not has_data[c]:
            demands.append(15.0)
        elif ml <= 3:
            demands.append(max(36.0, mw * 5.5 + 12.0))
        elif ml <= 8:
            demands.append(max(48.0, mw * 5.5 + 12.0))
        elif ml <= 16:
            demands.append(max(60.0, mw * 5.5 + 14.0))
        else:
            demands.append(max(80.0, mw * 5.5 + 16.0))

    if col_max_lens[0] <= 3 and col_max_lens[1] > 15 and num_cols == 3:
        return [36.0, 220.0, 68.0]

    tot_d = sum(demands)
    scale = max_table_width / tot_d
    widths = [round(d * scale, 2) for d in demands]
    diff = round(max_table_width - sum(widths), 2)
    widest = max(range(num_cols), key=lambda i: widths[i])
    widths[widest] = round(widths[widest] + diff, 2)
    return widths


def balance_table(table, max_table_width=324.0):
    cols = [c for c in table if c.tag.endswith("Column")]
    rows = [r for r in table if r.tag.endswith("Row")]
    num_rows, num_cols = len(rows), len(cols)
    if num_rows <= 1 or num_cols <= 1:
        return False

    cur_widths = [float(c.attrib.get("SingleColumnWidth", 0)) for c in cols]
    is_imbal, title_rows, is_24 = detect_imbalance(table, num_rows, num_cols, cur_widths)

    changed = False
    if is_imbal:
        if title_rows:
            changed = merge_spanning_cells(table, title_rows, num_cols) or changed
        new_widths = compute_balanced_widths(table, num_rows, num_cols, title_rows, is_24, cur_widths, max_table_width)
        for col, w in zip(cols, new_widths):
            cur_w = float(col.attrib.get("SingleColumnWidth", 0))
            if abs(cur_w - w) > 0.05:
                col.set("SingleColumnWidth", str(w))
                changed = True
    else:
        tot_w = sum(cur_widths)
        if tot_w > max_table_width + 0.5:
            scale = max_table_width / tot_w
            scaled_widths = [round(w * scale, 2) for w in cur_widths]
            diff = round(max_table_width - sum(scaled_widths), 2)
            scaled_widths[0] = round(scaled_widths[0] + diff, 2)
            for col, w in zip(cols, scaled_widths):
                cur_w = float(col.attrib.get("SingleColumnWidth", 0))
                if abs(cur_w - w) > 0.05:
                    col.set("SingleColumnWidth", str(w))
                    changed = True

    for cell in table.iter():
        if cell.tag.endswith("Cell"):
            if cell.attrib.get("ClipContentToTextCell") != "false":
                cell.set("ClipContentToTextCell", "false")
                changed = True
            for attr in ("TextLeftInset", "LeftInset", "TextRightInset", "RightInset",
                         "TextTopInset", "TopInset", "TextBottomInset", "BottomInset"):
                if cell.attrib.get(attr) != "2":
                    cell.set(attr, "2")
                    changed = True

    for row in rows:
        if row.attrib.get("AutoGrow") != "true":
            row.set("AutoGrow", "true")
            changed = True

    return changed


def process_story_tables(root, max_table_width=324.0):
    changed = False
    for table in root.iter():
        if table.tag.endswith("Table"):
            if balance_table(table, max_table_width):
                changed = True
    return changed


def balance_idml_tables(idml_path, max_table_width=324.0):
    idml_path = str(idml_path)
    tmpd = tempfile.mkdtemp(prefix="idml_tbl_balance_")
    try:
        with zipfile.ZipFile(idml_path, "r") as z:
            names = z.namelist()
            z.extractall(tmpd)

        any_changed = False
        stories_dir = os.path.join(tmpd, "Stories")
        if os.path.isdir(stories_dir):
            for fn in os.listdir(stories_dir):
                if not fn.lower().endswith(".xml"):
                    continue
                fp = os.path.join(stories_dir, fn)
                try:
                    tree = ET.parse(fp)
                except ET.ParseError:
                    continue
                root = tree.getroot()
                if process_story_tables(root, max_table_width):
                    tree.write(fp, xml_declaration=True, encoding="UTF-8")
                    any_changed = True

        if any_changed:
            tmp_zip = os.path.join(tmpd, "repacked.idml")
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zout:
                first = "mimetype"
                if first in names:
                    zout.write(os.path.join(tmpd, first), first, compress_type=zipfile.ZIP_STORED)
                for nm in names:
                    if nm == first:
                        continue
                    fp = os.path.join(tmpd, nm)
                    if os.path.isfile(fp):
                        zout.write(fp, nm, compress_type=zipfile.ZIP_DEFLATED)
            shutil.move(tmp_zip, idml_path)
        return any_changed
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
        if os.path.isfile(target):
            res = balance_idml_tables(target)
            print(f"{target}: tables balanced={res}")
        elif os.path.isdir(target):
            for p in Path(target).glob("*.idml"):
                if not p.name.endswith(".tmp"):
                    res = balance_idml_tables(p)
                    print(f"{p.name}: tables balanced={res}")
    else:
        print("Usage: python table_column_balancer.py <idml_path_or_dir>")
