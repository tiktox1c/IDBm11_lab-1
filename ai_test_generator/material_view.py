"""Просмотр одного элемента за раз; оригинальные изображения остаются на диске."""
import copy
import tkinter as tk
from tkinter import ttk,messagebox
from tkinter.scrolledtext import ScrolledText
from .elements import image_path
from .gui_text import enable_copy

NAMES={'text':'Текст','table':'Таблица','image':'Рисунок / страница','formula':'Формула'}

class MaterialViewer(tk.Toplevel):
    def __init__(self,app):
        super().__init__(app);self.app=app;self.photo=None;self.selected=None;self.crop=None
        self.title('Извлечённый материал');self.geometry('1000x720');self.minsize(650,450)
        bar=ttk.Frame(self,padding=8);bar.pack(fill='x')
        ttk.Label(bar,text='Модель читает доступный текст. Пиксели рисунков и формул она не распознаёт.',wraplength=900).pack(anchor='w')
        self.attach_button=ttk.Button(bar,text='Прикрепить к текущему вопросу',command=self.attach);self.attach_button.pack(anchor='w',pady=5)
        self.tabs=ttk.Notebook(self);self.tabs.pack(fill='both',expand=True,padx=8,pady=8)
        frame=ttk.Frame(self.tabs);self.tabs.add(frame,text='Элементы документа')
        pane=ttk.Panedwindow(frame,orient='horizontal');pane.pack(fill='both',expand=True)
        left=ttk.Frame(pane);right=ttk.Frame(pane);pane.add(left,weight=1);pane.add(right,weight=3)
        self.list=ttk.Treeview(left,show='tree');self.list.pack(fill='both',expand=True)
        scroll=ttk.Scrollbar(left,orient='vertical',command=self.list.yview);self.list.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y')
        self.list.bind('<<TreeviewSelect>>',self.select)
        self.description=ScrolledText(right,height=8,wrap='word');self.description.pack(fill='x');enable_copy(self.description)
        self.image_canvas=tk.Canvas(right,background='white',height=350,highlightthickness=0);self.image_canvas.pack(fill='both',expand=True)
        self.image_canvas.bind('<ButtonPress-1>',self.crop_start);self.image_canvas.bind('<B1-Motion>',self.crop_move)
        self.note=ttk.Label(right,text='Для фрагмента страницы выделите нужную область мышью.',wraplength=650);self.note.pack(fill='x')
        self.full_text=ScrolledText(self.tabs,wrap='word');self.tabs.add(self.full_text,text='Полный извлечённый текст');enable_copy(self.full_text)
        self.fragments=ScrolledText(self.tabs,wrap='word');self.tabs.add(self.fragments,text='Фрагменты генерации');enable_copy(self.fragments)
        self.refresh()
    @staticmethod
    def put(widget,value):
        widget.configure(state='normal');widget.delete('1.0','end');widget.insert('1.0',value);widget.configure(state='disabled')
    def refresh(self):
        material=self.app.material
        self.list.delete(*self.list.get_children());self.items=material.elements if material else []
        for i,item in enumerate(self.items):
            state='текст для генерации' if item.get('reliable') else 'ручной просмотр'
            self.list.insert('', 'end',iid=str(i),text=f'{NAMES[item["type"]]} · {item["reference"]} · {state}')
        self.put(self.full_text,material.text if material else '')
        from .gui_text import selected_fragments_text
        self.put(self.fragments,selected_fragments_text(self.app.test))
        if self.items:self.list.selection_set('0')
    def select(self,event=None):
        selection=self.list.selection()
        if not selection:return
        self.selected=self.items[int(selection[0])];item=self.selected;self.crop=None
        self.image_canvas.delete('all');self.photo=None
        content=[item['reference'],NAMES[item['type']],item.get('text',''),item.get('note','')]
        if item['type']=='table':content.append('\n'.join(' | '.join(str(c or '') for c in row) for row in item['rows']))
        self.put(self.description,'\n\n'.join(v for v in content if v))
        try:
            path=image_path(item)
            if path:
                import pymupdf
                pix=pymupdf.Pixmap(str(path))
                if pix.colorspace is None:raise ValueError('Недоступный формат изображения')
                if pix.colorspace.n not in (1,3):pix=pymupdf.Pixmap(pymupdf.csRGB,pix)
                original=(pix.width,pix.height)
                while pix.width>760 or pix.height>460:pix.shrink(1)
                self.photo=tk.PhotoImage(data=pix.tobytes('png'))
                self.image_canvas.create_image(0,0,image=self.photo,anchor='nw')
                self.display_size=(pix.width,pix.height)
                self.note.configure(text='Иллюстрация сохранена без распознавания. Для страницы можно выделить фрагмент мышью.')
        except Exception as exc:self.note.configure(text='Предпросмотр недоступен: '+str(exc))
    def crop_start(self,event):
        if self.selected and self.selected.get('lazy_page') and self.photo:
            self.origin=(event.x,event.y);self.image_canvas.delete('crop')
    def crop_move(self,event):
        if not self.selected or not self.selected.get('lazy_page') or not hasattr(self,'origin'):return
        x,y=self.origin;self.crop=(x,y,event.x,event.y);self.image_canvas.delete('crop')
        self.image_canvas.create_rectangle(*self.crop,outline='#2458bd',width=2,tags='crop')
    def attach(self):
        if not self.selected:return
        item=copy.deepcopy(self.selected)
        if item['type']=='text':messagebox.showinfo('Вложение','Обычный текст уже используется для генерации. Выберите таблицу, рисунок или формулу.',parent=self);return
        if item['type']=='table' and not item.get('reliable'):
            messagebox.showinfo('Структура не подтверждена','Таблица неоднозначна. Прикрепите изображение исходной страницы вместо восстановленной структуры.',parent=self);return
        try:
            if item.get('lazy_page') and self.crop:
                w,h=self.display_size;a,b,c,d=self.crop
                x0,y0,x1,y1=item['bbox'];sx=(x1-x0)/w;sy=(y1-y0)/h
                rect=[x0+min(a,c)*sx,y0+min(b,d)*sy,x0+max(a,c)*sx,y0+max(b,d)*sy]
                item.pop('path',None);image_path(item,rect)
            elif item['type']=='image':image_path(item)
            self.app.attach_element(item)
        except (ValueError,OSError) as exc:messagebox.showerror('Не удалось прикрепить',str(exc),parent=self)
