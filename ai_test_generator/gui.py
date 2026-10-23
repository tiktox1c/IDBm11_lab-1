"""Три шага работы: документ и нейросеть, карточки вопросов, результат."""
import copy
import gc
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .config import ROOT, OUTPUT, TYPES, MODEL_LABEL, prepare_temp
from .diagnostics import configure_logging, logger, user_message
from .extraction import extract
from .generation import generate_test, ModelStatus
from .ollama_runtime import OllamaRuntime
from .exporting import export_test, answer_text
from .validation import validate_question
from .gui_text import enable_copy, selected_fragments_text, remarks_text
from .review import question_status, confirm_question, save_correction, return_to_review, fingerprint
from .material_view import MaterialViewer


def put_text(widget, value):
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", value)
    widget.configure(state="disabled")


class QuestionCard(ttk.Frame):
    def __init__(self, parent, app, index, question):
        super().__init__(parent, style="Card.TFrame", padding=18)
        self.app, self.index, self.question = app, index, question
        self.editing = False
        self.option_vars, self.right_vars = [], []
        self.locked = {}
        self.columnconfigure(0, weight=1)
        self.build()

    def label(self, parent, text, **kwargs):
        label = ttk.Label(parent, text=text, style="Card.TLabel", wraplength=700, **kwargs)
        label.pack(anchor="w", fill="x", pady=3)
        self.labels.append(label)
        return label

    def build(self):
        for child in self.winfo_children():
            child.destroy()
        self.labels = []
        q = self.question
        head = ttk.Frame(self, style="Card.TFrame")
        head.pack(fill="x", pady=(0, 8))
        ttk.Label(head, text=f"{self.index + 1:02d}   {TYPES[q['type']]}",
                  style="CardTitle.TLabel").pack(side="left")
        if self.editing:
            ttk.Button(head, text="Сохранить исправление", command=self.app.commit_edits).pack(side="right")
            ttk.Button(head, text="Отменить", command=self.cancel).pack(side="right", padx=6)
        else:
            ttk.Button(head, text="Редактировать", command=self.edit).pack(side="right")
        self.label(self,'Статус: '+question_status(q),foreground='#9b5700' if question_status(q)=='Требует проверки' else '#17653d',font=('Segoe UI',11,'bold'))
        if not self.editing:
            controls=ttk.Frame(self,style='Card.TFrame');controls.pack(fill='x',pady=(0,8))
            ttk.Button(controls,text='Подтвердить',command=self.app.confirm_current).pack(side='left')
            ttk.Button(controls,text='Вернуть на проверку',command=self.app.return_current).pack(side='left',padx=5)
            ttk.Button(controls,text='Прикрепить материал',command=self.app.toggle_material).pack(side='left')
        for reason in q.get('review_reasons',[]):
            if question_status(q)=='Требует проверки':self.label(self,reason,foreground='#9b5700')
        if q.get('attachments'):
            self.label(self,'Вложения: '+', '.join(a['reference'] for a in q['attachments']))
            if not self.editing:ttk.Button(self,text='Убрать вложения',command=self.app.remove_attachments).pack(anchor='w')
        body = ttk.Frame(self, style="Card.TFrame")
        body.pack(fill="x")
        self.option_vars, self.right_vars = [], []
        raw_answer = q["answer"]
        self.answer_var = tk.StringVar(value=", ".join(map(str, raw_answer)) if isinstance(raw_answer, list) else str(raw_answer))
        if self.editing:
            self.label(body, "Формулировка вопроса")
            self.prompt_box = ScrolledText(body, height=3, wrap="word", font=("Segoe UI", 11), relief="solid", bd=1)
            self.prompt_box.pack(fill="x", pady=(0, 8))
            self.prompt_box.insert("1.0", q["prompt"])
            enable_copy(self.prompt_box)
        else:
            self.label(body, q["prompt"], font=("Segoe UI", 12))
        if q["type"] in ("choice", "sequence"):
            values = q["options" if q["type"] == "choice" else "items"]
            for number, value in enumerate(values, 1):
                if self.editing:
                    row = ttk.Frame(body, style="Card.TFrame")
                    row.pack(fill="x", pady=3)
                    ttk.Label(row, text=f"{number}.", width=3, style="Card.TLabel").pack(side="left")
                    variable = tk.StringVar(value=value)
                    ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)
                    self.option_vars.append(variable)
                else:
                    self.label(body, f"{number}. {value}")
        elif q["type"] == "matching":
            pairs = ttk.Frame(body, style="Card.TFrame")
            pairs.pack(fill="x", pady=6)
            pairs.columnconfigure(0, weight=1, uniform="pair")
            pairs.columnconfigure(1, weight=1, uniform="pair")
            for col, title in enumerate(("Левая колонка", "Правая колонка")):
                ttk.Label(pairs, text=title, style="CardTitle.TLabel").grid(row=0, column=col, sticky="w", padx=6, pady=4)
            for number, (left, right) in enumerate(zip(q["left"], q["right"]), 1):
                for col, value in enumerate((left, right)):
                    if self.editing:
                        variable = tk.StringVar(value=value)
                        (self.option_vars if col == 0 else self.right_vars).append(variable)
                        field = ttk.Frame(pairs, style="Card.TFrame")
                        field.grid(row=number, column=col, sticky="ew", padx=6, pady=3)
                        ttk.Label(field, text=f"{number}.", style="Card.TLabel").pack(side="left")
                        ttk.Entry(field, textvariable=variable).pack(side="left", fill="x", expand=True)
                    else:
                        label = ttk.Label(pairs, text=f"{number}. {value}", style="Card.TLabel", wraplength=300)
                        label.grid(row=number, column=col, sticky="nw", padx=6, pady=4)
        elif not self.editing:
            self.label(body, "Краткий ответ: __________________________________")
        self.answer_area = ttk.Frame(self, style="Card.TFrame")
        if self.editing:
            hints = {"choice": "Ответ: номер варианта от 1 до 4",
                     "sequence": "Порядок: номера через запятую, например 2, 3, 1",
                     "matching": "Ответ: номер справа для каждой строки слева, например 2, 3, 1",
                     "short": "Ответ: короткая фраза по источнику"}
            self.label(self.answer_area, hints[q["type"]])
            ttk.Entry(self.answer_area, textvariable=self.answer_var).pack(fill="x", pady=4)
            if q["type"] == "short":
                self.label(self.answer_area, "Допустимые ответы (каждый с новой строки)")
                self.acceptable_box = ScrolledText(self.answer_area, height=3, wrap="word", font=("Segoe UI", 10))
                self.acceptable_box.pack(fill="x", pady=4)
                self.acceptable_box.insert("1.0", "\n".join(q.get("acceptable_answers", [])))
                enable_copy(self.acceptable_box)
        else:
            label = "Предложенный ответ (проверьте): " if q.get("review_required") else "Правильный ответ: "
            self.label(self.answer_area, label + answer_text(q), foreground="#9b5700" if q.get("review_required") else "#17653d")
            if q.get("acceptable_answers"):
                self.label(self.answer_area, "Допустимые варианты: " + "; ".join(q["acceptable_answers"]))
        self.source_area = ttk.Frame(self, style="Card.TFrame")
        self.source_area.pack(fill="x", pady=(10, 0))
        self.label(self.source_area, "Источник: " + q["source_reference"], foreground="#637086")
        self.quote_button = ttk.Button(self.source_area, text="Показать цитату ▾", command=self.toggle_quote)
        self.quote_button.pack(anchor="w", pady=3)
        self.quote_area = ttk.Frame(self, style="Card.TFrame")
        if self.editing:
            self.label(self.quote_area, "Подтверждающая цитата (можно исправить в пределах фрагмента)")
            self.quote_box = ScrolledText(self.quote_area, height=3, wrap="word", font=("Segoe UI", 10))
            self.quote_box.pack(fill="x", pady=4)
            self.quote_box.insert("1.0", q["source_quote"])
            enable_copy(self.quote_box)
        else:
            self.label(self.quote_area, "Цитата")
            quote = ScrolledText(self.quote_area, height=3, wrap="word", font=("Segoe UI", 10))
            quote.pack(fill="x", pady=4)
            put_text(quote, q["source_quote"])
            enable_copy(quote)
        self.label(self.quote_area, "Фрагмент источника — только чтение")
        self.source_excerpt_text = ScrolledText(self.quote_area, height=5, wrap="word", font=("Segoe UI", 10))
        self.source_excerpt_text.pack(fill="x")
        put_text(self.source_excerpt_text, q["source_excerpt"])
        enable_copy(self.source_excerpt_text)
        if self.editing:
            self.draft_changed=False
            self.prompt_box.edit_modified(False);self.quote_box.edit_modified(False)
            self.prompt_box.bind('<<Modified>>',self.draft_modified)
            self.quote_box.bind('<<Modified>>',self.draft_modified)
            for variable in [self.answer_var,*self.option_vars,*self.right_vars]:variable.trace_add('write',self.draft_modified)
            if q['type']=='short':
                self.acceptable_box.edit_modified(False);self.acceptable_box.bind('<<Modified>>',self.draft_modified)
        self.show_answer()
        self.bind("<Configure>", self.resize)

    def resize(self, event):
        for label in self.labels:
            label.configure(wraplength=max(250, event.width - 45))

    def show_answer(self):
        if self.editing or self.app.show_answers.get():
            self.answer_area.pack(fill="x", before=self.source_area, pady=(8, 0))
        else:
            self.answer_area.pack_forget()

    def toggle_quote(self):
        if self.quote_area.winfo_manager():
            self.quote_area.pack_forget()
            self.quote_button.configure(text="Показать цитату ▾")
        else:
            self.quote_area.pack(fill="x", pady=6)
            self.quote_button.configure(text="Скрыть цитату ▴")

    def edit(self):
        if not self.app.busy:
            self.original=copy.deepcopy(self.question)
            self.editing = True
            self.build()

    def cancel(self):
        if hasattr(self,"original"):
            self.question.clear();self.question.update(self.original)
        self.editing = False
        self.build()
        self.app.refresh_preview()

    def draft_modified(self,*args):
        if not self.editing:return
        self.draft_changed=True
        return_to_review(self.question)
        for label in self.labels:
            if str(label.cget('text')).startswith('Статус:'):label.configure(text='Статус: Требует проверки (есть несохранённые изменения)',foreground='#9b5700')
        self.app.question_list.item(str(self.index),text=f'Требует проверки · {self.index+1}. {TYPES[self.question["type"]]}')

    def candidate(self):
        q = copy.deepcopy(self.question)
        if not self.editing:
            return q
        q["prompt"] = self.prompt_box.get("1.0", "end-1c").strip()
        q["source_quote"] = self.quote_box.get("1.0", "end-1c").strip()
        key = {"choice": "options", "sequence": "items", "matching": "left"}.get(q["type"])
        if key:
            q[key] = [v.get().strip() for v in self.option_vars]
        if q["type"] == "matching":
            q["right"] = [v.get().strip() for v in self.right_vars]
        raw = self.answer_var.get().strip()
        try:
            q["answer"] = (int(raw) if q["type"] == "choice" else
                           [int(v.strip()) for v in raw.split(",")] if q["type"] in ("sequence", "matching") else raw)
        except ValueError:
            raise ValueError("Введите номер ответа или номера через запятую согласно подсказке.") from None
        q["edited"] = True
        q['manual_confirmed'] = False
        if q["type"] == "short":
            q["acceptable_answers"] = [line.strip() for line in self.acceptable_box.get("1.0", "end-1c").splitlines() if line.strip()]
        return q

    def set_busy(self, busy):
        def walk(parent):
            for widget in parent.winfo_children():
                if isinstance(widget, (ttk.Button, ttk.Checkbutton, ttk.Entry, tk.Text)):
                    yield widget
                yield from walk(widget)
        if busy:
            for widget in walk(self):
                self.locked[widget] = widget.cget("state")
                widget.configure(state="disabled")
        else:
            for widget, state in self.locked.items():
                if widget.winfo_exists():
                    widget.configure(state=state)
            self.locked.clear()


class App(tk.Tk):
    def __init__(self, runtime=None):
        super().__init__()
        prepare_temp()
        configure_logging()
        self.runtime = runtime or OllamaRuntime()
        self.material = self.test = None
        self.cards = []
        self.selected_question = 0
        self.material_window = None
        self.busy = False
        self.events = queue.Queue()
        self.model_status = ModelStatus("starting")
        self.title("AI Test Generator")
        self.geometry("1080x820")
        self.minsize(800, 740)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 11))
        style.configure("TFrame", background="#f3f5f9")
        style.configure("TLabel", background="#f3f5f9")
        style.configure("TButton", padding=(14, 8))
        style.configure("TButton", background="white", bordercolor="#d4dce9", lightcolor="white", darkcolor="white")
        style.configure("TCheckbutton", background="#f3f5f9")
        style.configure("TLabelframe", background="#f3f5f9", bordercolor="#d4dce9")
        style.configure("TLabelframe.Label", background="#f3f5f9", font=("Segoe UI", 11, "bold"))
        style.configure("TNotebook", background="#f3f5f9", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(20, 12))
        style.map("TNotebook.Tab", background=[("selected", "white"), ("!selected", "#e5ebf5")])
        style.configure("Horizontal.TProgressbar", thickness=6, troughcolor="#e4e9f2", background="#2c58bd", borderwidth=0)
        style.configure("Accent.TButton", background="#2c58bd", foreground="white", padding=(24, 12), font=("Segoe UI", 12, "bold"))
        style.map("Accent.TButton", background=[("disabled", "#c8ced9"), ("active", "#214698")])
        style.configure("Card.TFrame", background="white")
        style.configure("Card.TLabel", background="white")
        style.configure("CardTitle.TLabel", background="white", font=("Segoe UI", 11, "bold"))
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=16, pady=(12, 12))
        self.create_page = ttk.Frame(self.notebook, padding=22)
        self.editor_page = ttk.Frame(self.notebook, padding=16)
        self.result_page = ttk.Frame(self.notebook, padding=20)
        for frame, title in ((self.create_page, "1. Создание теста"), (self.editor_page, "2. Редактор вопросов"), (self.result_page, "3. Результат")):
            self.notebook.add(frame, text=title)
        self.status = tk.StringVar(value="Выберите документ. Подключение к нейросети проверяется автоматически.")
        self.show_answers = tk.BooleanVar(value=False)
        self.make_creation()
        self.make_editor()
        self.make_result()
        self.footer = ttk.Label(self, textvariable=self.status, padding=(24, 0, 24, 12), wraplength=1000)
        self.footer.pack(fill="x")
        self.bind("<Configure>", self.resize)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.notebook.bind("<<NotebookTabChanged>>", self.tab_changed)
        self.bind_all("<MouseWheel>", self.wheel, add="+")
        self.after(50, self.poll)
        self.after(150, self.reconnect)

    def make_creation(self):
        page = self.create_page
        ttk.Label(page, text="Документ для теста", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        document = ttk.Frame(page, padding=(0, 12))
        document.pack(fill="x")
        self.open_button = ttk.Button(document, text="Открыть документ", command=self.open_document)
        self.open_button.pack(side="left", padx=(0, 16))
        self.filename = tk.StringVar(value="Файл не выбран · PDF, DOCX или DOC")
        self.file_label = ttk.Label(document, textvariable=self.filename, wraplength=650)
        self.file_label.pack(side="left", fill="x", expand=True)
        name_row = ttk.Frame(page)
        name_row.pack(fill="x", pady=(0, 12))
        ttk.Label(name_row, text="Название теста").pack(side="left", padx=(0, 12))
        self.test_name = tk.StringVar(value="Учебный тест")
        self.name_box = ttk.Entry(name_row, textvariable=self.test_name)
        self.name_box.pack(side="left", fill="x", expand=True)
        row = ttk.Frame(page)
        row.pack(fill="x", pady=(4, 20))
        ttk.Label(row, text="Количество вопросов").pack(side="left", padx=(0, 12))
        self.count = tk.StringVar(value="8")
        self.count_box = ttk.Spinbox(row, values=(4, 8, 12, 16, 20), textvariable=self.count, width=5, state="readonly")
        self.count_box.pack(side="left", padx=(0, 14))
        ttk.Label(row, text="Поровну заданий четырёх типов", foreground="#637086").pack(side="left")
        model = ttk.LabelFrame(page, text="Локальная нейросеть", padding=18)
        model.pack(fill="x", pady=(0, 18))
        self.model_label = ttk.Label(model, text=self.model_status.label, font=("Segoe UI", 12, "bold"))
        self.model_label.pack(anchor="w")
        self.model_hint = ttk.Label(model, text=self.model_status.message, wraplength=800)
        self.model_hint.pack(fill="x", pady=(8, 12))
        self.reconnect_button = ttk.Button(model, text="Повторить подключение", command=self.reconnect)
        self.reconnect_button.pack(anchor="w")
        self.install_button=ttk.Button(model,text="Открыть сайт установки Ollama",command=self.open_ollama_site)
        self.download_button=ttk.Button(model,text="Загрузить модель",command=self.download_model)
        self.generate_button = ttk.Button(page, text="Создать тест", style="Accent.TButton", command=self.generate, state="disabled")
        self.generate_button.pack(anchor="w", pady=(0, 12))
        self.progress = ttk.Progressbar(page, mode="indeterminate")
        self.material_button = ttk.Button(page, text="Просмотреть извлечённый материал…", command=self.toggle_material, state="disabled")
        self.material_button.pack(anchor="w")

    def make_editor(self):
        toolbar = ttk.Frame(self.editor_page)
        toolbar.pack(fill="x", pady=(0, 12))
        ttk.Checkbutton(toolbar, text="Показать ответы", variable=self.show_answers,
                        command=self.toggle_answers).pack(side="left")
        self.delete_button = ttk.Button(toolbar, text="Удалить вопрос", command=self.delete_question, state="disabled")
        self.delete_button.pack(side="right", padx=8)
        panes = ttk.Panedwindow(self.editor_page, orient="horizontal")
        panes.pack(fill="both", expand=True)
        selector = ttk.Frame(panes, width=230)
        panes.add(selector, weight=0)
        ttk.Label(selector, text="Выберите вопрос", padding=(0, 0, 0, 6)).pack(anchor="w")
        self.question_list = ttk.Treeview(selector, show="tree", selectmode="browse", height=12)
        self.question_list.column("#0", width=220, stretch=True)
        list_scroll = ttk.Scrollbar(selector, orient="vertical", command=self.question_list.yview)
        self.question_list.configure(yscrollcommand=list_scroll.set)
        list_scroll.pack(side="right", fill="y")
        self.question_list.pack(fill="both", expand=True)
        self.question_list.bind("<<TreeviewSelect>>", self.select_question)
        container = ttk.Frame(panes)
        panes.add(container, weight=1)
        self.canvas = tk.Canvas(container, background="#f3f5f9", highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.cards_frame = ttk.Frame(self.canvas)
        self.cards_window = self.canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        self.cards_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.cards_window, width=e.width))
        ttk.Label(self.cards_frame, text="Здесь появятся вопросы после создания теста.", padding=20).pack(anchor="w")

    def make_result(self):
        bar = ttk.Frame(self.result_page)
        bar.pack(fill="x", pady=(0, 12))
        self.docx_button = ttk.Button(bar, text="Сохранить в Word", command=lambda: self.export(".docx"), state="disabled")
        self.docx_button.pack(side="left", padx=(0, 10))
        ttk.Checkbutton(bar,text="Показать ответы",variable=self.show_answers,command=self.toggle_answers).pack(side="left")
        self.summary = ttk.Label(self.result_page, text="Создайте тест, затем проверьте вопросы и сохраните результат.", wraplength=850)
        self.summary.pack(fill="x", pady=(0, 10))
        self.result_panes = tk.PanedWindow(self.result_page, orient="vertical", sashwidth=8, background="#d4dce9", bd=0)
        self.result_panes.pack(fill="both", expand=True)
        preview_frame = ttk.Frame(self.result_panes)
        self.result_panes.add(preview_frame, minsize=100, stretch="always")
        self.preview = ScrolledText(preview_frame, wrap="word", height=10, font=("Segoe UI", 11), state="disabled")
        self.result_canvas=tk.Canvas(preview_frame,background="#f3f5f9",highlightthickness=0)
        result_scroll=ttk.Scrollbar(preview_frame,orient="vertical",command=self.result_canvas.yview)
        result_scroll.pack(side="right",fill="y");self.result_canvas.pack(fill="both",expand=True)
        self.result_canvas.configure(yscrollcommand=result_scroll.set)
        self.result_cards=ttk.Frame(self.result_canvas)
        self.result_window=self.result_canvas.create_window((0,0),window=self.result_cards,anchor="nw")
        self.result_cards.bind("<Configure>",lambda e:self.result_canvas.configure(scrollregion=self.result_canvas.bbox("all")))
        self.result_canvas.bind("<Configure>",lambda e:self.result_canvas.itemconfigure(self.result_window,width=e.width))
        enable_copy(self.preview)
        remarks = ttk.Frame(self.result_panes, height=230)
        self.result_panes.add(remarks, minsize=80, height=140, stretch="never")
        remarks_bar = ttk.Frame(remarks)
        remarks_bar.pack(fill="x", pady=(6, 4))
        ttk.Label(remarks_bar, text="Замечания и попытки генерации", font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(remarks_bar, text="Копировать всё", command=self.copy_warnings).pack(side="right")
        self.warnings = ScrolledText(remarks, height=8, wrap="word", font=("Segoe UI", 10), state="disabled")
        self.warnings.pack(fill="both", expand=True)
        enable_copy(self.warnings)

    def resize(self, event):
        if event.widget is self:
            self.footer.configure(wraplength=max(500, event.width - 50))
            self.file_label.configure(wraplength=max(350, event.width - 290))
            self.model_hint.configure(wraplength=max(450, event.width - 130))

    def wheel(self, event):
        if str(event.widget).startswith(str(self.cards_frame)) and not isinstance(event.widget, tk.Text):
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        elif str(event.widget).startswith(str(self.result_cards)):
            self.result_canvas.yview_scroll(int(-event.delta/120),"units")

    def toggle_material(self):
        if not self.material:return
        if self.material_window is None or not self.material_window.winfo_exists():
            self.material_window=MaterialViewer(self)
            self.material_text=self.material_window.full_text
            self.fragments_text=self.material_window.fragments
        else:self.material_window.refresh()
        self.material_window.deiconify();self.material_window.lift()

    def refresh_material_view(self):
        if self.material_window is not None and self.material_window.winfo_exists():self.material_window.refresh()

    def attach_element(self,item):
        if self.busy or not self.test or not self.test['questions']:
            messagebox.showinfo('Сначала создайте тест','Выберите вопрос в редакторе, затем прикрепите элемент.');return
        if not self.commit_edits():return
        q=self.test['questions'][self.selected_question]
        attachments=q.setdefault('attachments',[])
        if any(a.get('id')==item.get('id') and a.get('bbox')==item.get('bbox') for a in attachments):return
        attachments.append(copy.deepcopy(item));q['edited']=True;return_to_review(q)
        self.render_questions();self.status.set('Вложение добавлено. Проверьте вопрос и нажмите «Подтвердить».')

    def remove_attachments(self):
        if not self.commit_edits():return
        q=self.test['questions'][self.selected_question]
        if q.get('attachments'):
            q['attachments']=[];q['edited']=True;return_to_review(q);self.render_questions()

    def confirm_current(self):
        if not self.test or self.busy or not self.commit_edits():return
        q=self.test['questions'][self.selected_question]
        try:confirm_question(q)
        except ValueError as exc:messagebox.showerror('Вопрос нельзя подтвердить',str(exc));return
        self.render_questions();self.status.set('Вопрос проверен пользователем.')

    def return_current(self):
        if self.test and not self.busy:
            return_to_review(self.test['questions'][self.selected_question]);self.render_questions()

    def copy_warnings(self):
        self.clipboard_clear()
        self.clipboard_append(self.warnings.get("1.0", "end-1c"))

    def set_model_status(self, status):
        self.model_status = status
        self.model_label.configure(text=status.label, foreground={"ready": "#17653d", "starting": "#8a6300"}.get(status.state, "#ad3030"))
        self.model_hint.configure(text=status.message)
        self.install_button.pack_forget();self.download_button.pack_forget()
        if status.state=='not_found':self.install_button.pack(anchor='w',pady=(6,0))
        elif status.state=='missing':self.download_button.pack(anchor='w',pady=(6,0))
        self.update_controls()

    def update_controls(self):
        has_test = bool(self.test and self.test["questions"])
        for button in (self.open_button, self.reconnect_button,self.install_button,self.download_button):
            button.configure(state="disabled" if self.busy else "normal")
        self.generate_button.configure(state="normal" if not self.busy and self.material and self.material.generation_text.strip() and self.model_status.state == "ready" else "disabled")
        self.material_button.configure(state="normal" if self.material else "disabled")
        self.count_box.configure(state="disabled" if self.busy else "readonly")
        self.name_box.configure(state="disabled" if self.busy else "normal")
        self.question_list.configure(selectmode="none" if self.busy else "browse")
        for button in (self.delete_button, self.docx_button):
            button.configure(state="normal" if has_test and not self.busy else "disabled")

    def start_job(self, kind, action, message):
        if self.busy:
            return
        # Уничтоженные карточки могут оставлять циклы с Tk-переменными.
        # Освобождаем их в UI-потоке, до того как выделения памяти worker
        # смогут запустить сборщик и вызвать Variable.__del__ вне Tk.
        gc.collect()
        self.busy = True
        self.status.set(message)
        self.update_controls()
        self.progress.pack(fill="x", before=self.material_button, pady=(0, 10))
        self.progress.start(12)
        for card in self.cards:
            card.set_busy(True)

        def worker():
            try:
                self.events.put(("done", (kind, action())))
            except Exception as exc:
                logger.exception("Ошибка операции %s", kind)
                self.events.put(("error", (kind, user_message(exc))))
        threading.Thread(target=worker, daemon=True).start()

    def finish_job(self):
        self.busy = False
        self.progress.stop()
        self.progress.pack_forget()
        for card in self.cards:
            card.set_busy(False)
        self.update_controls()

    @staticmethod
    def open_ollama_site():
        import webbrowser
        webbrowser.open('https://ollama.com/download/windows')

    def download_model(self):
        if self.busy:return
        message=('Загрузить qwen2.5:1.5b через локальную Ollama? Потребуется интернет и около 1 ГБ на диске.\n\n'
                 'Каталог модели определяет запущенный сервер Ollama. Для другого диска сначала настройте OLLAMA_MODELS и перезапустите Ollama. '
                 'Программа не меняет переменные среды. Инструкция есть в README. Продолжить?')
        if not messagebox.askyesno('Загрузка модели',message):return
        self.start_job('download',lambda:self.runtime.pull_model(lambda m:self.events.put(('progress',m))),'Загрузка модели через Ollama…')

    def reconnect(self):
        if self.busy:
            return
        self.set_model_status(ModelStatus("starting"))
        self.start_job("connection", lambda: self.runtime.ensure_ready(lambda m: self.events.put(("progress", m))), "Подключение к локальной нейросети…")

    def open_document(self):
        if self.test and not messagebox.askyesno("Новый документ", "Текущий тест будет заменён. Продолжить?"):
            return
        path = filedialog.askopenfilename(title="Выберите учебный документ", initialdir=ROOT,
                                          filetypes=[("Учебные документы", "*.pdf *.docx *.doc"), ("PDF", "*.pdf"), ("Word", "*.docx *.doc")])
        if path:
            self.start_job("material", lambda: extract(path), "Читаем текст и доступные таблицы документа…")

    def generate(self):
        if self.busy or self.material is None:
            return
        if self.test and not messagebox.askyesno("Новый тест", "Заменить текущие вопросы? Сначала сохраните нужный результат."):
            return
        count = int(self.count.get())
        self.notebook.select(self.create_page)

        def action():
            connection = self.runtime.ensure_ready(lambda m: self.events.put(("progress", m)))
            self.events.put(("model", connection))
            if connection.state != "ready":
                return None
            return generate_test(self.material, lambda m: self.events.put(("progress", m)), count=count)

        self.start_job("test", action, "Проверяем нейросеть перед созданием теста…")

    def poll(self):
        try:
            while True:
                event, data = self.events.get_nowait()
                if event == "progress":
                    self.status.set(data)
                elif event == "model":
                    self.set_model_status(data)
                elif event == "error":
                    kind, message = data
                    self.finish_job()
                    if kind == "connection":
                        self.set_model_status(ModelStatus("connection_error"))
                    self.status.set(message)
                    messagebox.showerror("Не удалось выполнить операцию", message)
                elif event == "done":
                    kind, result = data
                    if kind == "connection":
                        self.set_model_status(result)
                        self.status.set(result.message)
                    elif kind == "material":
                        self.material, self.test = result, None
                        self.selected_question = 0
                        self.filename.set(result.name)
                        self.refresh_material_view()
                        self.render_questions()
                        self.status.set(f"Документ загружен: {len(result.text):,} символов. Можно создать тест.")
                        put_text(self.warnings, "\n".join(result.warnings))
                    elif kind == "test":
                        if result is not None:
                            self.test = result
                            self.test["title"] = self.test_name.get().strip() or "Учебный тест"
                            self.selected_question = 0
                            self.refresh_material_view()
                            self.render_questions()
                            count = len(result["questions"])
                            self.status.set(f"Создано {count} из {result['requested_count']} вопросов. " +
                                            ("Проверьте и при необходимости исправьте их." if count else "Проверьте замечания и повторите генерацию."))
                            if "connection_state" in result:
                                self.set_model_status(ModelStatus(result["connection_state"]))
                            self.notebook.select(self.editor_page if count else self.result_page)
                        else:
                            self.status.set(self.model_status.message)
                    elif kind == "download":
                        self.set_model_status(result);self.status.set(result.message)
                    elif kind == "export":
                        self.status.set(f"Результат сохранён: {result}")
                    self.finish_job()
        except queue.Empty:
            pass
        self.after(50, self.poll)

    def render_questions(self):
        for widget in self.cards_frame.winfo_children():
            widget.destroy()
        self.cards = []
        self.question_list.delete(*self.question_list.get_children())
        if self.test and self.test["questions"]:
            self.selected_question = min(self.selected_question, len(self.test["questions"]) - 1)
            for i, q in enumerate(self.test["questions"]):
                card = QuestionCard(self.cards_frame, self, i, q)
                if i == self.selected_question:
                    card.pack(fill="x", pady=(0, 12), padx=(0, 8))
                self.cards.append(card)
                marker = question_status(q) + " · "
                self.question_list.insert("", "end", iid=str(i), text=f"{marker}{i + 1}. {TYPES[q['type']]} — {q['prompt']}")
            self.question_list.selection_set(str(self.selected_question))
            self.question_list.see(str(self.selected_question))
        else:
            ttk.Label(self.cards_frame, text="Пока нет вопросов. Создайте тест на первой вкладке.", padding=20).pack(anchor="w")
        self.canvas.yview_moveto(0)
        self.refresh_preview()
        self.update_controls()

    def select_question(self, _event=None):
        selection = self.question_list.selection()
        if not selection:
            return
        index = int(selection[0])
        if index == self.selected_question:
            return
        if self.busy or not self.save_before_navigation():
            self.question_list.selection_set(str(self.selected_question))
            return
        for card in self.cards:
            card.pack_forget()
        self.selected_question = index
        self.cards[index].pack(fill="x", pady=(0, 12), padx=(0, 8))
        self.question_list.selection_set(str(index))
        self.canvas.yview_moveto(0)

    def delete_question(self):
        if self.busy or not self.test or not self.test["questions"] or not self.commit_edits():
            return
        del self.test["questions"][self.selected_question]
        self.render_questions()
        self.status.set("Вопрос удалён. Сохраните изменённый тест.")

    def toggle_answers(self):
        for card in self.cards:
            card.show_answer()
        self.refresh_preview()

    def commit_edits(self):
        if not self.test:
            return True
        self.test["title"] = self.test_name.get().strip() or "Учебный тест"
        if not any(card.editing for card in self.cards):
            return True
        candidates = []
        try:
            for i, card in enumerate(self.cards):
                candidate=card.candidate()
                validate_question(candidate, candidates, grounding=False)
                if card.editing:
                    save_correction(copy_q:=copy.deepcopy(card.question),candidate)
                    candidate=copy_q
                candidates.append(candidate)
        except ValueError as exc:
            self.notebook.select(self.editor_page)
            messagebox.showerror(f"Проверьте вопрос {i+1}",str(exc));return False
        self.test["questions"]=candidates
        self.render_questions()
        self.status.set("Исправления применены. Сохраните тест на вкладке «Результат».")
        return True

    def refresh_preview(self):
        if not self.test:
            put_text(self.preview, "Здесь появится сформированный тест.")
            put_text(self.warnings, "")
            for child in self.result_cards.winfo_children():child.destroy()
            self.summary.configure(text="Создайте тест, затем проверьте вопросы.")
            return
        questions = self.test["questions"]
        requested = self.test.get("requested_count", 8)
        counts={label:sum(question_status(q)==label for q in questions) for label in ('Проверено','Исправлено','Требует проверки')}
        self.summary.configure(text=f"{self.test.get('title','Учебный тест')}\nСоздано {len(questions)} из {requested}. Проверено: {counts['Проверено']} · Исправлено: {counts['Исправлено']} · Требует проверки: {counts['Требует проверки']}")
        lines = [self.test.get("title", self.test_name.get()), ""] if questions else []
        for i, q in enumerate(questions, 1):
            lines.extend([f"{i}. {TYPES[q['type']]}", q["prompt"]])
            lines.append("Статус: "+question_status(q))
            if question_status(q)=="Требует проверки":
                lines.append("⚠ ТРЕБУЕТ ПРОВЕРКИ")
                lines.extend(q.get("review_reasons", []))
            elif q.get('manual_confirmed'):
                lines.append('✓ Проверено вручную')
            if q["type"] in ("choice", "sequence"):
                key = "options" if q["type"] == "choice" else "items"
                lines.extend(f"  {j}. {v}" for j, v in enumerate(q[key], 1))
            elif q["type"] == "matching":
                lines.append("Левая колонка                         Правая колонка")
                lines.extend(f"  {j}. {a}  |  {j}. {b}" for j, (a, b) in enumerate(zip(q["left"], q["right"]), 1))
            else:
                lines.append("Ответ: ______________________________")
            if self.show_answers.get():
                label = "Предложенный ответ (проверьте): " if q.get("review_required") else "Правильный ответ: "
                lines.append(label + answer_text(q))
                if q.get("acceptable_answers"):
                    lines.append("Допустимые варианты: " + "; ".join(q["acceptable_answers"]))
            lines.append("")
        put_text(self.preview, "\n".join(lines) if lines else "Подходящие вопросы пока не получены. Прочитайте замечания и повторите генерацию.")
        put_text(self.warnings, remarks_text(self.test))
        for child in self.result_cards.winfo_children():child.destroy()
        for i,q in enumerate(questions,1):
            frame=ttk.Frame(self.result_cards,style='Card.TFrame',padding=14);frame.pack(fill='x',pady=(0,10),padx=4)
            ttk.Label(frame,text=f"{i}. {TYPES[q['type']]} · Статус: {question_status(q)}",style='CardTitle.TLabel',wraplength=800).pack(anchor='w')
            parts=[q['prompt']]
            if q['type'] in ('choice','sequence'):
                parts.extend(f'{j}. {v}' for j,v in enumerate(q.get('options',q.get('items',[])),1))
            elif q['type']=='matching':
                parts.extend(f'{j}. {a}  |  {j}. {b}' for j,(a,b) in enumerate(zip(q['left'],q['right']),1))
            if self.show_answers.get():parts.append('Ответ: '+answer_text(q))
            if q.get('attachments'):parts.append('Вложения: '+', '.join(a['type'] for a in q['attachments']))
            ttk.Label(frame,text='\n'.join(parts),style='Card.TLabel',wraplength=800,justify='left').pack(fill='x',anchor='w',pady=(6,0))

    def tab_changed(self, _event):
        if self.notebook.select() == str(self.result_page) and not self.busy:
            if self.save_before_navigation():
                self.refresh_preview()
            else:self.notebook.select(self.editor_page)

    def save_before_navigation(self):
        dirty=[c for c in self.cards if c.editing]
        if not dirty:return True
        decision=messagebox.askyesnocancel('Несохранённые исправления','Сохранить исправление перед переходом? «Нет» отменяет текущие изменения.')
        if decision is None:return False
        if decision:return self.commit_edits()
        for card in dirty:card.cancel()
        self.render_questions();return True

    def export(self, extension=".docx"):
        if extension!=".docx":return
        if not self.commit_edits():
            return
        path = filedialog.asksaveasfilename(title="Сохранить тест и ответы", initialdir=OUTPUT,
                                          initialfile="test" + extension, defaultextension=extension,
                                          filetypes=[("Word" if extension == ".docx" else "JSON", "*" + extension)])
        if path:
            snapshot = copy.deepcopy(self.test)
            self.start_job("export", lambda: self.save(snapshot, path), "Сохраняем тест и ответы…")

    @staticmethod
    def save(test, path):
        export_test(test, path)
        return path

    def report_callback_exception(self, exc_type, exc_value, traceback):
        logger.error("Ошибка интерфейса", exc_info=(exc_type, exc_value, traceback))
        messagebox.showerror("Ошибка интерфейса", "Не удалось выполнить действие. Подробности сохранены в logs/app.log.")

    def close(self):
        if self.busy:
            messagebox.showinfo("Операция выполняется", "Дождитесь завершения операции. Подключение и генерация выполняются в фоне.")
            return
        if self.test and not messagebox.askyesno("Выход", "Выйти? Несохранённые вопросы и исправления будут потеряны."):
            return
        # Ollama продолжает работать; чужие и собственные серверы не завершаются.
        self.destroy()
