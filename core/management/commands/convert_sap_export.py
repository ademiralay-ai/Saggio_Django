import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from django.core.management.base import BaseCommand, CommandError


def _decode_escapes(value):
    return bytes(value, "utf-8").decode("unicode_escape")


def _parse_index_spec(spec):
    """Parse 1-based index spec like '1,3,5-7' into a zero-based set."""
    result = set()
    raw = str(spec or "").strip()
    if not raw:
        return result

    for token in [x.strip() for x in raw.split(",") if x.strip()]:
        if "-" in token:
            parts = [p.strip() for p in token.split("-", 1)]
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                raise ValueError(f"Gecersiz aralik: {token}")
            start = int(parts[0])
            end = int(parts[1])
            if start <= 0 or end <= 0:
                raise ValueError(f"Indeksler 1 veya daha buyuk olmali: {token}")
            if end < start:
                start, end = end, start
            for idx in range(start, end + 1):
                result.add(idx - 1)
            continue

        if not token.isdigit():
            raise ValueError(f"Gecersiz indeks: {token}")
        idx = int(token)
        if idx <= 0:
            raise ValueError(f"Indeks 1 veya daha buyuk olmali: {token}")
        result.add(idx - 1)

    return result


def _read_text_with_fallback(input_path, encodings):
    last_ex = None
    for enc in encodings:
        try:
            return input_path.read_text(encoding=enc), enc
        except Exception as ex:
            last_ex = ex
    raise RuntimeError(f"Dosya hicbir encoding ile okunamadi: {last_ex}")


def _column_letter(col_index):
    # 1 -> A, 27 -> AA
    if col_index <= 0:
        return "A"
    s = ""
    n = col_index
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _looks_like_number(text):
    value = str(text or "").strip()
    if not value:
        return False
    return bool(re.fullmatch(r"[+-]?\d+(?:[\.,]\d+)?", value))


def _as_excel_number(text):
    value = str(text or "").strip().replace(".", "").replace(",", ".")
    return value


def _is_effectively_empty_row(row):
    return not any(str(cell or "").strip() for cell in (row or []))


def _normalize_row_for_compare(row):
    normalized = []
    for cell in (row or []):
        text = re.sub(r"\s+", " ", str(cell or "").strip()).casefold()
        normalized.append(text)
    return tuple(normalized)


def _remove_noise_rows(rows):
    """Drop fully-empty rows and repeated header rows (common in large SAP exports)."""
    cleaned = []
    header_signature = None

    for row in rows or []:
        if _is_effectively_empty_row(row):
            continue

        sig = _normalize_row_for_compare(row)
        if header_signature is None:
            header_signature = sig
            cleaned.append(row)
            continue

        if sig == header_signature:
            # SAP exports can repeat table header blocks in long files (e.g. 60k+ lines).
            continue

        cleaned.append(row)

    return cleaned


def _build_sheet_xml(rows):
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
    lines.append('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">')
    lines.append("<sheetData>")

    for r_idx, row in enumerate(rows, start=1):
        lines.append(f'<row r="{r_idx}">')
        for c_idx, cell in enumerate(row, start=1):
            raw = str(cell or "")
            if raw == "":
                continue
            ref = f"{_column_letter(c_idx)}{r_idx}"
            if _looks_like_number(raw):
                lines.append(f'<c r="{ref}"><v>{escape(_as_excel_number(raw))}</v></c>')
            else:
                lines.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(raw)}</t></is></c>')
        lines.append("</row>")

    lines.append("</sheetData>")
    lines.append("</worksheet>")
    return "".join(lines)


def _build_xlsx_content(rows):
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )

    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '</Relationships>'
    )

    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )

    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )

    sheet_xml = _build_sheet_xml(rows)
    return {
        "[Content_Types].xml": content_types,
        "_rels/.rels": rels,
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": workbook_rels,
        "xl/worksheets/sheet1.xml": sheet_xml,
    }


def _write_xlsx(output_path, rows):
    files = _build_xlsx_content(rows)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)


class Command(BaseCommand):
    help = "SAP'tan inen ham metin/tab dosyasini temizleyip XLSX'e cevirir (satir/sutun silme parametreli)."

    def add_arguments(self, parser):
        parser.add_argument("input", type=str, help="Ham dosya yolu (.xls/.txt/.tab vb.)")
        parser.add_argument("--output", type=str, default="", help="Cikti xlsx yolu (bos ise input ile ayni klasorde .xlsx)")
        parser.add_argument("--delimiter", type=str, default="\\t", help="Kolon ayraci. Varsayilan: tab")
        parser.add_argument(
            "--encodings",
            type=str,
            default="utf-16,utf-16-le,cp1254,latin-1,utf-8",
            help="Okuma encoding onceligi (virgulle)",
        )
        parser.add_argument("--trim-cells", action="store_true", help="Hucre bas/son bosluklarini temizle")
        parser.add_argument("--strip-quotes", action="store_true", help='Hucrelerdeki cift tirnaklari kaldir')
        parser.add_argument("--skip-empty-lines", action="store_true", help="Tamamen bos satirlari atla")

        parser.add_argument("--drop-top-rows", type=int, default=0, help="Bastan N satir sil")
        parser.add_argument("--drop-left-cols", type=int, default=0, help="Soldan N sutun sil")
        parser.add_argument("--drop-rows", type=str, default="", help="Silinecek satirlar (1-based): 1,2,5-7")
        parser.add_argument("--drop-cols", type=str, default="", help="Silinecek sutunlar (1-based): 1,3,8-10")

    def handle(self, *args, **options):
        input_path = Path(options["input"]).expanduser().resolve()
        if not input_path.exists() or not input_path.is_file():
            raise CommandError(f"Input dosya bulunamadi: {input_path}")

        output_raw = str(options.get("output") or "").strip()
        if output_raw:
            output_path = Path(output_raw).expanduser().resolve()
        else:
            output_path = input_path.with_suffix(".xlsx")

        delimiter = _decode_escapes(str(options.get("delimiter") or "\\t"))
        encodings = [x.strip() for x in str(options.get("encodings") or "").split(",") if x.strip()]
        if not encodings:
            raise CommandError("En az bir encoding verilmelidir.")

        trim_cells = bool(options.get("trim_cells"))
        strip_quotes = bool(options.get("strip_quotes"))
        skip_empty_lines = bool(options.get("skip_empty_lines"))

        drop_top_rows = max(0, int(options.get("drop_top_rows") or 0))
        drop_left_cols = max(0, int(options.get("drop_left_cols") or 0))

        try:
            drop_rows = _parse_index_spec(options.get("drop_rows"))
            drop_cols = _parse_index_spec(options.get("drop_cols"))
        except ValueError as ex:
            raise CommandError(str(ex))

        raw_text, used_enc = _read_text_with_fallback(input_path, encodings)
        raw_lines = raw_text.splitlines()

        rows = []
        max_cols = 0
        for line in raw_lines:
            if skip_empty_lines and (not str(line or "").strip()):
                continue
            parts = str(line).split(delimiter)
            if trim_cells:
                parts = [p.strip() for p in parts]
            if strip_quotes:
                parts = [p.replace('"', "") for p in parts]
            rows.append(parts)
            max_cols = max(max_cols, len(parts))

        if not rows:
            raise CommandError("Okunan veri bos. Parametreleri kontrol edin.")

        # Row length normalize
        for row in rows:
            if len(row) < max_cols:
                row.extend([""] * (max_cols - len(row)))

        # Positional drops (top/left)
        if drop_top_rows > 0:
            rows = rows[drop_top_rows:]
        if drop_left_cols > 0:
            rows = [row[drop_left_cols:] if len(row) > drop_left_cols else [] for row in rows]

        # Explicit row/col drops (1-based from current table)
        if drop_rows:
            rows = [row for idx, row in enumerate(rows) if idx not in drop_rows]

        if drop_cols:
            filtered = []
            for row in rows:
                filtered.append([cell for idx, cell in enumerate(row) if idx not in drop_cols])
            rows = filtered

        # Remove noisy rows produced by large SAP exports.
        rows = _remove_noise_rows(rows)

        if not rows:
            raise CommandError("Temizlikten sonra veri kalmadi. Satir/sutun silme parametrelerini kontrol edin.")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        _write_xlsx(output_path, rows)

        self.stdout.write(self.style.SUCCESS("Donusum tamamlandi"))
        self.stdout.write(f"Input   : {input_path}")
        self.stdout.write(f"Output  : {output_path}")
        self.stdout.write(f"Encoding: {used_enc}")
        self.stdout.write(f"Satir   : {len(rows)}")
        self.stdout.write(f"Sutun   : {max((len(r) for r in rows), default=0)}")
