"""Лёгкие элементы документа. Пиксели не интерпретируются языковой моделью."""
import re
import tempfile
from pathlib import Path
from .config import TEMP, prepare_temp

M='http://schemas.openxmlformats.org/officeDocument/2006/math'
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
A='http://schemas.openxmlformats.org/drawingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'

def asset_folder():
    prepare_temp()
    return Path(tempfile.mkdtemp(prefix='material-',dir=TEMP))

def element(kind,source,index,text='',**extra):
    return {'id':f'{kind}-{index}', 'type':kind,'source_path':str(Path(source).resolve()),
            'reference':f'{Path(source).name}, элемент {index}', 'text':text,
            'reliable':kind=='text', **extra}

def omml_text(node):
    """Разрешённый небольшой набор OMML. Неизвестная конструкция закрывает допуск к LLM."""
    tag=node.tag.split('}')[-1]
    def children():return ''.join(omml_text(c) for c in node)
    def part(name):
        child=node.find(f'{{{M}}}{name}')
        return omml_text(child) if child is not None else ''
    if tag.endswith('Pr'):return ''
    if tag=='t':return node.text or ''
    if tag in ('oMath','oMathPara','r','e','num','den','sup','sub','deg'):
        return children()
    if tag=='f':
        a,b=part('num'),part('den')
        if not a or not b:raise ValueError('Неполная дробь')
        return f'({a})/({b})'
    if tag in ('sSup','sSub','sSubSup'):
        a=part('e')
        if not a:raise ValueError('Нет основания')
        result=a
        for name,mark in [('sub','_'),('sup','^')]:
            if tag=='sSup' and name=='sub' or tag=='sSub' and name=='sup':continue
            v=part(name)
            if not v:raise ValueError('Нет индекса')
            result+=f'{mark}({v})'
        return result
    if tag=='rad':
        v=part('e');degree=part('deg')
        if not v:raise ValueError('Нет подкоренного выражения')
        return f'root({degree}; {v})' if degree else f'√({v})'
    if tag=='d':
        # Custom delimiters require explicit handling; never silently call them parentheses.
        pr=node.find(f'{{{M}}}dPr')
        if pr is not None and len(pr):raise ValueError('Особые разделители')
        return '('+children()+')'
    raise ValueError(f'Неподдерживаемая запись {tag}')

def describe_table(rows,headers=None):
    if not rows:return ''
    if not headers:return '\n'.join(' | '.join(row) for row in rows)
    result=[' | '.join(headers)]
    for row in rows[1:]:
        result.append('; '.join(f'{headers[i] or "Столбец "+str(i+1)}: {value}' for i,value in enumerate(row)))
    return '\n'.join(result)

def docx_elements(doc,source):
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from lxml import etree
    from .extraction import _docx_list_labeler
    list_label=_docx_list_labeler(doc)
    folder=None; result=[]; counter=0
    def add(kind,text='',**kw):
        nonlocal counter
        counter+=1;item=element(kind,source,counter,text,**kw);result.append(item);return item
    def paragraph(p):
        nonlocal folder
        if p.text.strip():add('text',list_label(p)+p.text.strip())
        for math in p._p.xpath('.//m:oMath'):
            try:
                value=omml_text(math);reliable=bool(value.strip())
            except ValueError:
                value='Запись формулы требует ручной проверки';reliable=False
            add('formula',value,reliable=reliable,omml=etree.tostring(math,encoding='unicode'))
        for blip in p._p.iter(f'{{{A}}}blip'):
            rid=blip.get(f'{{{R}}}embed')
            if not rid:continue
            part=p.part.related_parts.get(rid)
            if part is None:continue
            if folder is None:folder=asset_folder()
            suffix=Path(str(part.partname)).suffix.lower()
            target=folder/f'image-{counter+1}{suffix}';target.write_bytes(part.blob)
            add('image',p.text.strip(),path=str(target),reliable=False,
                note='Иллюстрация. Модель использует только подпись и соседний текст, не пиксели.')
        # Old VML pictures are common in converted DOC.
        for imagedata in p._p.iter('{urn:schemas-microsoft-com:vml}imagedata'):
            rid=imagedata.get(f'{{{R}}}id');part=p.part.related_parts.get(rid)
            if part is None:continue
            if folder is None:folder=asset_folder()
            target=folder/f'image-{counter+1}{Path(str(part.partname)).suffix}';target.write_bytes(part.blob)
            add('image',p.text.strip(),path=str(target),reliable=False,note='Иллюстрация VML; пиксели модель не анализирует.')
    def table(t):
        rows=[];seen=set();merged=False
        for row in t.rows:
            values=[]
            for cell in row.cells:
                if cell._tc in seen:values.append('');merged=True;continue
                seen.add(cell._tc);values.append(cell.text.strip().replace('\n','; '))
            rows.append(values)
        reliable=bool(rows and all(len(r)==len(rows[0]) for r in rows) and not merged)
        title=result[-1]['text'] if result and result[-1]['type']=='text' and re.match(r'таблица\b',result[-1]['text'],re.I) else ''
        header_row=bool(t.rows and t.rows[0]._tr.xpath('./w:trPr/w:tblHeader'))
        header_words={'компонент','назначение','термин','описание','параметр','значение','этап','действие','тип','part','role'}
        headers=rows[0] if rows and (header_row or any(v.casefold() in header_words for v in rows[0])) else []
        add('table',describe_table(rows,headers),rows=rows,headers=headers,title=title,reliable=reliable,
            raw_text='\n'.join(' | '.join(row) for row in rows),note='' if reliable else 'Объединённые или неоднозначные ячейки: не использовать для автоматических ответов.')
        children_start=len(result)
        asset_cells=set()
        for row in t.rows:
            for cell in row.cells:
                if cell._tc in asset_cells:continue
                asset_cells.add(cell._tc)
                for p in cell.paragraphs:
                    if p._p.xpath('.//m:oMath|.//a:blip'):paragraph(p)
                for nested in cell.tables:table(nested)
        if not reliable:
            for child in result[children_start:]:child['excluded_from_generation']=True
    for block in doc.iter_inner_content():
        if isinstance(block,Paragraph):paragraph(block)
        elif isinstance(block,Table):table(block)
    return result

def pdf_assets(page,source,number,folder):
    result=[]
    def add(kind,text='',**kw):
        item=element(kind,source,f'{number}-{len(result)+1}',text,page=number,
            reference=f'{Path(source).name}, стр. {number}',**kw);result.append(item)
    for index,info in enumerate(page.get_image_info(xrefs=True),1):
        bbox=list(info['bbox']);xref=info.get('xref',0)
        target=folder/f'page-{number}-image-{index}.png'
        try:
            if xref:
                data=page.parent.extract_image(xref)
                if data is None:raise ValueError('Изображение недоступно')
                # Original bytes, no recompression. A soft mask needs rendered composition.
                smask=data.get('smask',0)
                if smask:
                    import pymupdf
                    pix=pymupdf.Pixmap(page.parent,xref);mask=pymupdf.Pixmap(page.parent,smask)
                    pymupdf.Pixmap(pix,mask).save(target)
                else:
                    target=target.with_suffix('.'+data['ext']);target.write_bytes(data['image'])
            else:
                page.get_pixmap(clip=bbox,dpi=150).save(target)
            nearby=page.get_textbox((max(0,bbox[0]-10),max(0,bbox[1]-35),min(page.rect.width,bbox[2]+20),min(page.rect.height,bbox[3]+55))).strip()
            add('image',nearby,path=str(target),bbox=bbox,reliable=False,note='Пиксели не анализируются. Подпись и соседний текст доступны отдельно.')
        except Exception:
            add('image','Не удалось сохранить встроенный рисунок',bbox=bbox,reliable=False,note='Используйте фрагмент исходной страницы.')
    # Accessible mathematical text is kept literally, no normalization or invented repair.
    for block in page.get_text('dict')['blocks']:
        if block['type']!=0:continue
        for line in block['lines']:
            value=''.join(span['text'] for span in line['spans']).strip()
            if re.search(r'[=∑∫√≈≤≥±]',value):
                reliable=bool(not re.search(r'�|\ufffd',value) and '=' in value and all(s.strip() for s in value.split('=')))
                target=folder/f'page-{number}-formula-{len(result)+1}.png'
                page.get_pixmap(clip=line['bbox'],dpi=200).save(target)
                add('formula',value,path=str(target),bbox=list(line['bbox']),reliable=reliable,
                    note='Текст PDF сохраняется буквально; сверяйте индексы с изображением.')
    # Vector diagrams / graphical formulas cannot be identified semantically. This lazy page
    # element permits inspection and attachment of a crop without rendering all pages into RAM.
    if page.get_text().strip() or page.get_images() or page.get_drawings():add('image','Исходная страница: рисунки, схемы и графические формулы',lazy_page=True,reliable=False,
        note='Векторные объекты и формулы доступны как выбранный фрагмент страницы; OCR отсутствует.')
    return result

def image_path(item,clip=None):
    if item.get('path'):return Path(item['path'])
    if not item.get('lazy_page'):return None
    import pymupdf
    with pymupdf.open(item['source_path']) as doc:
        page=doc[item['page']-1]
        rectangle=pymupdf.Rect(clip) if clip is not None else page.rect
        rectangle &= page.rect
        if rectangle.is_empty:raise ValueError('Пустой фрагмент страницы')
        folder=asset_folder();target=folder/'page.png'
        page.get_pixmap(clip=rectangle,dpi=150,alpha=False).save(target)
    item['path']=str(target);item['bbox']=list(rectangle)
    return target

def generation_text(material):
    value=material.text
    bad_pages={e['page'] for e in material.elements if e['type']=='table' and not e.get('reliable') and e.get('page')}
    # A detector can disagree with MuPDF's reading order. Plain string replacement is
    # insufficient in that case; conservatively exclude the entire affected PDF page.
    for page in bad_pages:
        pattern=rf'(?ms)^\[Страница {page}\].*?(?=^\[Страница \d+\]|\Z)'
        value=re.sub(pattern,f'[Страница {page}: структура таблицы требует ручной проверки]\n\n',value)
    if any(e['type']=='table' and not e.get('reliable') and not e.get('page') for e in material.elements):
        return '\n\n'.join(e['text'] for e in material.elements
            if e.get('reliable') and e['type'] in ('text','table','formula') and not e.get('excluded_from_generation'))
    for item in material.elements:
        if item.get('page') in bad_pages or item.get('excluded_from_generation'):continue
        if item['type']=='formula' and item.get('reliable') and item['text'] not in value:
            value+='\n\n'+item['text']
        if item['type']=='table':
            if item.get('reliable'):
                # Table's plain grid already occurs once in material.text. Add no duplicate.
                old=item.get('raw_grid') or '\n'.join(' | '.join(row) for row in item['rows'])
                if old in value:value=value.replace(old,item['text'],1)
            elif item.get('raw_text'):
                value=value.replace(item['raw_text'],'\n[Структура таблицы требует ручной проверки]\n')
        if item['type']=='formula' and not item.get('reliable') and item['text'] in value:
            value=value.replace(item['text'],'')
    return value

def attach_source_elements(material,q):
    from .validation import normalized
    excerpt=normalized(q['source_excerpt']);attachments=[]
    for item in material.elements:
        if item['type'] not in ('table','formula') or not item.get('reliable'):continue
        if item.get('page') and item['page'] not in q.get('source_pages',[]):continue
        values=[c for row in item.get('rows',[]) for c in row if len(c.strip())>2] if item['type']=='table' else [item['text']]
        if values and sum(normalized(v) in excerpt for v in values)>=min(2,len(values)):
            attachments.append(dict(item))
    q['attachments']=attachments
