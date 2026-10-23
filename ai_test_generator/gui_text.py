"""Readable source and audit text shared by the Tk views."""
import tkinter as tk

from .config import TYPES


def enable_copy(widget):
    """Keep even disabled Text widgets selectable and explicitly copyable."""
    def select_all(_event=None):
        widget.tag_add("sel", "1.0", "end-1c")
        widget.mark_set("insert", "1.0")
        widget.focus_set()
        return "break"

    def copy_selection(_event=None):
        try:
            value = widget.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"
        widget.clipboard_clear()
        widget.clipboard_append(value)
        return "break"

    menu = tk.Menu(widget, tearoff=False)
    menu.add_command(label="Копировать", command=copy_selection)
    menu.add_command(label="Выделить всё", command=select_all)

    def popup(event):
        widget.focus_set()
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    for sequence in ("<Control-a>", "<Control-A>"):
        widget.bind(sequence, select_all)
    for sequence in ("<Control-c>", "<Control-C>", "<<Copy>>"):
        widget.bind(sequence, copy_selection)
    def control_key(event):
        # Windows reports Cyrillic keysyms when a Russian keyboard is active.
        # Physical A/C shortcuts must still work without changing the layout.
        if event.keycode == 65 or event.keysym.lower() in ("a", "cyrillic_ef"):
            return select_all()
        if event.keycode == 67 or event.keysym.lower() in ("c", "cyrillic_es"):
            return copy_selection()
    widget.bind("<Control-KeyPress>", control_key)
    widget.bind("<Button-3>", popup)


def selected_fragments_text(test):
    if not test:
        return "Фрагменты ещё не выбраны. Они появятся после запуска генерации."
    fragments = test.get("fragments")
    if fragments is None:
        # Older saved tests did not retain the selected fragment list.
        seen, fragments = set(), []
        for question in test.get("questions", []):
            excerpt = question.get("source_excerpt", "")
            if excerpt and excerpt not in seen:
                seen.add(excerpt)
                fragments.append({"id": question.get("fragment_id", len(fragments) + 1),
                                  "text": excerpt, "pages": question.get("source_pages", [])})
    if not fragments:
        return "Выбранных фрагментов нет. Генерация ещё не выбрала пригодный текст."
    parts = []
    for fragment in fragments:
        pages = ", ".join(map(str, fragment.get("pages", [])))
        heading = f"Фрагмент {fragment['id']}" + (f" · страницы {pages}" if pages else "")
        parts.append(heading + "\n" + fragment["text"])
    return "\n\n".join(parts)


def remarks_text(test):
    parts = list(dict.fromkeys(test.get("warnings", [])))
    statuses = {"accepted": "принят", "review": "требует проверки", "rejected": "отклонён",
                "refused": "отказ модели", "unavailable": "модель недоступна"}
    attempts = test.get("attempts", [])
    if attempts:
        parts.append("История попыток генерации. Текущий статус проверки указан в карточке вопроса.")
    for attempt in attempts:
        kind = TYPES.get(attempt.get("type"), attempt.get("type", "Вопрос"))
        parts.append(f"{kind} · задание {attempt.get('slot', '?')} · попытка {attempt.get('attempt', '?')} · "
                     f"фрагмент {attempt.get('fragment_id', '?')}\n"
                     f"Статус: {statuses.get(attempt.get('status'), attempt.get('status', ''))}\n"
                     f"Причина: {attempt.get('reason') or '—'}\n"
                     f"Действие: {attempt.get('action') or '—'}")
    for index, question in enumerate(test.get("questions", []), 1):
        if question.get("review_required"):
            reasons = "\n".join(question.get("review_reasons", [])) or "Проверьте вопрос и ответ по источнику."
            parts.append(f"Вопрос {index}: ТРЕБУЕТ ПРОВЕРКИ\n{reasons}")
    return "\n\n".join(parts)
