"""Запуск окна с понятной ошибкой даже без консоли (pythonw / Windows EXE)."""
import os
import sys


def main():
    try:
        from ai_test_generator.config import prepare_temp
        prepare_temp()
        from ai_test_generator.diagnostics import configure_logging
        configure_logging()
        from ai_test_generator.gui import App
        app=App()
        app.mainloop()
        return 0
    except Exception:
        try:
            from ai_test_generator.diagnostics import logger
            logger.exception('Не удалось запустить приложение')
        except Exception:
            pass
        message=('Не удалось запустить AI Test Generator. Проверьте, что папка программы доступна для записи '
                 'и приложение полностью распаковано. Для запуска исходников нужен Python с Tkinter. '
                 'Подробности ошибки: logs/app.log рядом с программой.')
        if os.name=='nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,message,'AI Test Generator',0x10)
        elif sys.stderr is not None:
            print(message,file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
