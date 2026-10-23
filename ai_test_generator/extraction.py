"""Чтение текстового слоя и доступных таблиц; без OCR."""
from dataclasses import dataclass, field
from collections import Counter
from pathlib import Path
import tempfile
import shutil
import re

from .config import TEMP, prepare_temp
from .diagnostics import logger


@dataclass
class Material:
    name: str
    text: str
    warnings: list[str] = field(default_factory=list)
    source_path: str = ""
    elements: list[dict] = field(default_factory=list)

    @property
    def generation_text(self):
        from .elements import generation_text
        return generation_text(self)


def table_text(rows):
    return "\n".join(" | ".join(str(c if c is not None else "").strip().replace("\n", " ")
                                  for c in row) for row in rows)


def _docx_list_labeler(doc):
    """Resolve Word's list labels, which Paragraph.text does not include."""
    from docx.oxml.ns import qn

    try:
        numbering = doc.part.numbering_part.element
    except KeyError:
        return lambda paragraph: ""
    numbers = {node.get(qn("w:numId")): node for node in numbering.findall(qn("w:num"))}
    abstracts = {node.get(qn("w:abstractNumId")): node
                 for node in numbering.findall(qn("w:abstractNum"))}
    counters = {}

    def val(node, tag, default=None):
        child = node.find(qn("w:" + tag)) if node is not None else None
        return child.get(qn("w:val"), default) if child is not None else default

    def label(paragraph):
        properties = [paragraph._p.pPr]
        style = paragraph.style
        while style is not None:
            properties.append(style.element.pPr)
            style = style.base_style
        number_id = level_id = None
        for properties_node in properties:
            num = properties_node.numPr if properties_node is not None else None
            if num is not None:
                if number_id is None:
                    number_id = val(num, "numId")
                if level_id is None:
                    level_id = val(num, "ilvl")
        if number_id not in numbers or number_id == "0":
            return ""
        level_id = int(level_id or 0)
        number = numbers[number_id]
        abstract = abstracts.get(val(number, "abstractNumId"))
        if abstract is None:
            return ""

        def definition(level):
            override = next((n for n in number.findall(qn("w:lvlOverride"))
                             if n.get(qn("w:ilvl")) == str(level)), None)
            item = override.find(qn("w:lvl")) if override is not None else None
            if item is None:
                item = next((n for n in abstract.findall(qn("w:lvl"))
                             if n.get(qn("w:ilvl")) == str(level)), None)
            start = val(override, "startOverride", val(item, "start", "1"))
            return item, int(start)

        item, start = definition(level_id)
        if item is None:
            return ""
        fmt = val(item, "numFmt", "decimal")
        if fmt == "bullet":
            return "• "
        if fmt == "none":
            return ""
        state = counters.setdefault(number_id, {})
        state[level_id] = state.get(level_id, start - 1) + 1
        for deeper in [level for level in state if level > level_id]:
            del state[deeper]
        pattern = val(item, "lvlText", f"%{level_id + 1}.")
        # Normalize ordered labels to decimal while retaining hierarchy/start.
        # This avoids font-dependent symbol encodings in the accessible text.
        return re.sub(r"%([1-9])", lambda match: str(state.get(
            int(match[1]) - 1, definition(int(match[1]) - 1)[1])), pattern) + " "

    return label


def read_docx(path):
    from docx import Document
    from docx.opc.exceptions import PackageNotFoundError
    from zipfile import BadZipFile
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        doc = Document(path)
    except (BadZipFile, PackageNotFoundError, KeyError, ValueError) as exc:
        raise ValueError('Не удалось прочитать DOCX: файл повреждён или имеет неверный формат.') from exc
    parts = []
    list_label = _docx_list_labeler(doc)

    def paragraph_text(paragraph):
        text = paragraph.text.strip()
        return list_label(paragraph) + text if text else ""

    def nested_tables(table, nested=False):
        # python-docx returns the same XML cell at each occupied grid position
        # of a horizontal/vertical merge. Emit its contents once, including its
        # inner paragraphs and tables in their original order.
        seen = set()
        rows = []
        for row in table.rows:
            values = []
            for cell in row.cells:
                if cell._tc in seen:
                    values.append("")
                    continue
                seen.add(cell._tc)
                content = []
                for block in cell.iter_inner_content():
                    if isinstance(block, Paragraph):
                        content.append(paragraph_text(block))
                    elif isinstance(block, Table):
                        content.append(nested_tables(block, nested=True))
                values.append("\n".join(p for p in content if p))
            rows.append(" | ".join(values))
        label = "[Вложенная таблица]" if nested else "[Таблица]"
        return label + "\n" + "\n".join(rows)

    for block in doc.iter_inner_content():
        if isinstance(block, Paragraph):
            parts.append(paragraph_text(block))
        elif isinstance(block, Table):
            parts.append(nested_tables(block))
    from .elements import docx_elements
    elements = docx_elements(doc, path)
    warnings = ["Рисунки сохранены как иллюстрации; пиксели текстовая модель не анализирует. Текстовые поля и колонтитулы могут быть недоступны."]
    warnings.extend(e['reference'] + ': ' + e['note'] for e in elements if e.get('note') and e['type'] in ('table','formula') and not e['reliable'])
    return Material(Path(path).name, "\n\n".join(p for p in parts if p), warnings, elements=elements)


def _inside_cells(char, cells):
    x0, y0, x1, y1 = char["bbox"]
    x, y = (x0 + x1) / 2, (y0 + y1) / 2
    return any(a <= x <= c and b <= y <= d for a, b, c, d in cells)


def _pdf_page_text(page, number, warnings, elements=None, source=""):
    """Replace accepted table cells in the reading stream, never the page bbox."""
    lines = [line for block in page.get_text("rawdict", sort=True)["blocks"]
             if block["type"] == 0 for line in block["lines"]]
    chars = [char for line in lines for span in line["spans"] for char in span["chars"]]
    table_events, occupied = [], []
    try:
        # Filled paragraph/background rectangles in presentation PDFs are not
        # table borders. The default 'lines' strategy invents tables from them.
        tables = page.find_tables(strategy="lines_strict")
        for table in tables.tables:
            value = table_text(table.extract())
            cells = [cell for cell in table.cells if cell is not None]
            if not value.strip(" |\n") or not cells:
                continue
            # A detector can surround text it failed to put into any output
            # cell. Keep that region as ordinary text instead of losing prose.
            captured = Counter(c["c"] for c in chars
                               if not c["c"].isspace() and _inside_cells(c, cells))
            represented = Counter(c for c in value.replace(" | ", "") if not c.isspace())
            if not captured or captured != represented:
                warnings.append(f"Страница {number}: структура таблицы неоднозначна; таблица исключена из генерации.")
                if elements is not None:
                    from .elements import element
                    elements.append(element('table', source, f'{number}-{len(elements)+1}', value,
                        page=number, reference=f'{Path(source).name}, стр. {number}', rows=table.extract(),
                        reliable=False, raw_text=page.get_textbox(table.bbox),
                        note='Ненадёжная структура: автоматические ответы запрещены.'))
                continue
            # Ignore duplicate/overlapping detections rather than re-emit cells.
            if any(_inside_cells(c, occupied) for c in chars if _inside_cells(c, cells)):
                continue
            occupied.extend(cells)
            if elements is not None:
                from .elements import element, describe_table
                rows = [[str(c or '').strip().replace('\n',' ') for c in row] for row in table.extract()]
                headers = [str(c or "") for c in table.header.names] if table.header and table.header.names else (rows[0] if rows else [])
                if table.header and table.header.external and headers:
                    rows.insert(0, [str(c or '') for c in headers])
                elements.append(element('table', source, f'{number}-{len(elements)+1}', describe_table(rows,headers),
                    page=number, reference=f'{Path(source).name}, стр. {number}', rows=rows,headers=headers,
                    reliable=all(c is not None for c in table.cells),raw_grid=value,raw_text=value,bbox=list(table.bbox),
                    note="Объединённые ячейки требуют ручного просмотра" if any(c is None for c in table.cells) else ""))
            table_events.append((table.bbox[1], table.bbox[0],
                                 f"[Таблица, страница {number}]\n{value}"))
    except Exception:
        logger.exception("Не удалось извлечь таблицы PDF, страница %s", number)
        warnings.append(f"Страница {number}: таблицы не удалось прочитать; доступный текст сохранён.")
        table_events, occupied = [], []

    if not table_events:
        # Preserve MuPDF's paragraph spacing and ordering when no real table
        # needs replacing, including a complete fallback on detector failure.
        return page.get_text("text", sort=True).strip()
    events = list(table_events)
    for line in lines:
        text = "".join(char["c"] for span in line["spans"] for char in span["chars"]
                       if not _inside_cells(char, occupied)).strip()
        if text:
            events.append((line["bbox"][1], line["bbox"][0], text))
    events.sort(key=lambda event: (event[0], event[1]))
    return "\n".join(event[2] for event in events)


def read_pdf(path):
    import pymupdf
    parts, warnings, elements = [], [], []
    from .elements import asset_folder, pdf_assets, element
    folder = asset_folder()
    try:
        document = pymupdf.open(path)
    except (pymupdf.FileDataError, pymupdf.EmptyFileError) as exc:
        raise ValueError("Не удалось прочитать PDF: файл повреждён или имеет неверный формат.") from exc
    has_text = False
    with document as doc:
        if doc.needs_pass:
            raise ValueError("PDF защищён паролем. Используйте незашифрованную копию.")
        for number, page in enumerate(doc, 1):
            text = _pdf_page_text(page, number, warnings, elements, path)
            elements.append(element("text",path, f"page-{number}",text,page=number,reference=f"{Path(path).name}, стр. {number}"))
            elements.extend(pdf_assets(page,path,number,folder))
            parts.append(f"[Страница {number}]" + (f"\n{text}" if text else ""))
            if text:
                has_text = True
            else:
                warnings.append(f"Страница {number}: нет текстового слоя; доступны рисунки и фрагмент страницы, генерация по пикселям невозможна.")
    warnings.append("Рисунки сохранены без распознавания. Формулы PDF требуют сверки с изображением; графические формулы и схемы можно прикрепить фрагментом страницы.")
    return Material(Path(path).name, "\n\n".join(parts) if has_text else "", warnings, elements=elements)


def read_doc(path):
    """Отдельный экземпляр Word, только чтение, макросы отключены."""
    import pythoncom
    import win32com.client

    prepare_temp()
    pythoncom.CoInitialize()
    word = document = None
    try:
        with tempfile.TemporaryDirectory(prefix="word-", dir=TEMP) as directory:
            converted = Path(directory) / "converted.docx"
            local_copy = Path(directory) / "input.doc"
            shutil.copyfile(path, local_copy)
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            word.AutomationSecurity = 3
            try:
                document = word.Documents.Open(
                    str(local_copy), ConfirmConversions=False, ReadOnly=True,
                    AddToRecentFiles=False, Visible=False,
                    PasswordDocument="", WritePasswordDocument="")
                document.SaveAs2(str(converted), FileFormat=16, AddToRecentFiles=False)
                document.Close(SaveChanges=0)
                document = None
                material = read_docx(converted)
                material.name = Path(path).name
                for item in material.elements:
                    item["source_path"] = str(Path(path).resolve())
                    item["reference"] = item["reference"].replace("converted.docx", material.name)
                return material
            finally:
                try:
                    if document is not None:
                        document.Close(SaveChanges=0)
                finally:
                    if word is not None:
                        word.Quit(SaveChanges=0)
    except Exception as exc:
        logger.exception("Ошибка чтения DOC через Word")
        raise ValueError("Не удалось прочитать DOC. Нужны Microsoft Word и pywin32; "
                         "проверьте, что документ не защищён и открывается в Word.") from exc
    finally:
        pythoncom.CoUninitialize()


def extract(path):
    path = Path(path).expanduser().resolve()
    readers = {".pdf": read_pdf, ".docx": read_docx, ".doc": read_doc}
    if path.suffix.lower() not in readers:
        raise ValueError("Поддерживаются только PDF, DOCX и DOC.")
    material = readers[path.suffix.lower()](path)
    material.source_path = str(path)
    if not material.text.strip() and not any(e["type"] in ("table","image","formula") for e in material.elements):
        raise ValueError("Доступный текст не найден. Скан без текстового слоя не поддерживается.")
    return material
