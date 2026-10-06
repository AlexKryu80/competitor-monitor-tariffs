"""Настольный клиент «Мониторинг конкурентов» (PyQt6). Работает с backend по HTTP."""
import html
import sys

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

import api_client

STYLE = """
QMainWindow, QWidget { background: #f5f3ee; color: #1d2433; font-size: 14px; }
QTabWidget::pane { border: 1px solid #e3ded3; border-radius: 8px; background: #fffdf9; }
QTabBar::tab { padding: 8px 16px; background: #ebe7dd; border-radius: 6px; margin-right: 4px; }
QTabBar::tab:selected { background: #1f5f8b; color: white; }
QPlainTextEdit, QLineEdit, QTextBrowser, QComboBox { background: #fffdf9; border: 1px solid #e3ded3; border-radius: 6px; padding: 6px; }
QPushButton { background: #1f5f8b; color: white; border: 0; border-radius: 6px; padding: 8px 18px; font-weight: 600; }
QPushButton:disabled { background: #9db6c6; }
QPushButton#ghost { background: transparent; color: #1d2433; border: 1px solid #e3ded3; font-weight: 400; }
"""


class Worker(QObject):
    """Запрос к серверу в отдельном потоке, чтобы окно не зависало на 30–60 секунд парсинга."""
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, func, *args):
        super().__init__()
        self.func, self.args = func, args

    def run(self):
        try:
            self.done.emit(self.func(*self.args))
        except api_client.ApiError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 — любая сбой не должен валить окно
            self.failed.emit(f"Непредвиденная ошибка: {exc}")


def esc(value) -> str:
    return html.escape(str(value)) if value not in (None, "") else "—"


def bullets(title: str, items) -> str:
    body = "".join(f"<li>{esc(i)}</li>" for i in items) if items else "<li><i>нет данных</i></li>"
    return f"<h4>{title}</h4><ul>{body}</ul>"


def render_analysis(a: dict) -> str:
    cov = a.get("service_coverage", {})
    tags = ", ".join(label for key, label in
                     [("financial_support", "финансовое сопровождение"), ("audit", "аудит"), ("tariff_expertise", "тарифы")]
                     if cov.get(key)) or "ничего из ниши не найдено"
    return (f"<p><b>Прозрачность цен:</b> {a.get('pricing_transparency', 0)}/10 &nbsp; "
            f"<b>Глубина по тарифам:</b> {a.get('tariff_expertise_depth', 0)}/10</p>"
            f"<p><b>Направления:</b> {esc(tags)}</p><p>{esc(a.get('summary'))}</p>"
            + bullets("Сильные стороны", a.get("strengths")) + bullets("Слабые стороны", a.get("weaknesses"))
            + bullets("Уникальные предложения", a.get("unique_offers")) + bullets("Рекомендации", a.get("recommendations")))


def render_image(v: dict) -> str:
    return (f"<p><b>Визуальный стиль:</b> {v.get('design_score', 0)}/10 &nbsp; "
            f"<b>Доверие:</b> {v.get('trust_score', 0)}/10</p>"
            f"<p>{esc(v.get('description'))}</p><p>{esc(v.get('design_analysis'))}</p>"
            + bullets("Маркетинговые инсайты", v.get("marketing_insights")) + bullets("Рекомендации", v.get("recommendations")))


def render_page(d: dict) -> str:
    p = d["parsed"]
    head = (f"<h4>Собрано со страницы</h4><ul><li>Адрес: {esc(p.get('url'))}</li><li>Заголовок: {esc(p.get('title'))}</li>"
            f"<li>H1: {esc(p.get('h1'))}</li><li>Первый абзац: {esc(p.get('first_paragraph'))}</li>"
            f"<li>Разделы: {esc('; '.join(p.get('headings') or []))}</li></ul>")
    visual = "<h3>Скриншот первого экрана</h3>" + render_image(d["visual"]) if d.get("visual") else ""
    return head + render_analysis(d["analysis"]) + visual


class MainWindow(QMainWindow):
    _deliver = pyqtSignal(object)  # передача результата из потока запроса в поток окна

    def __init__(self):
        super().__init__()
        self._deliver.connect(self._invoke)
        self.setWindowTitle("Мониторинг конкурентов")
        self.resize(900, 760)
        self._threads: list[QThread] = []

        central = QWidget()
        layout = QVBoxLayout(central)
        self.server_label = QLabel()
        layout.addWidget(self.server_label)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._text_tab(), "Текст")
        self.tabs.addTab(self._image_tab(), "Изображение")
        self.tabs.addTab(self._url_tab(), "Сайт")
        self.tabs.addTab(self._history_tab(), "История")
        self.tabs.currentChanged.connect(self._on_tab)
        layout.addWidget(self.tabs, 2)

        self.status = QLabel("")
        layout.addWidget(self.status)
        self.result = QTextBrowser()
        layout.addWidget(self.result, 3)
        self.setCentralWidget(central)
        self.setStyleSheet(STYLE)
        self._check_server()
        self._load_competitors()

    # --- вкладки ---
    def _text_tab(self):
        tab, box = QWidget(), QVBoxLayout()
        tab.setLayout(box)
        self.text_input = QPlainTextEdit()
        self.text_input.setPlaceholderText("Текст конкурента: страница услуг, предложение, отчёт (от 10 символов)")
        self.go_text = QPushButton("Проанализировать")
        self.go_text.clicked.connect(lambda: self._run(self.go_text, api_client.analyze_text, self.text_input.toPlainText(),
                                                       render=render_analysis, busy="Анализирую текст…"))
        box.addWidget(self.text_input)
        box.addWidget(self.go_text)
        return tab

    def _image_tab(self):
        tab, box = QWidget(), QVBoxLayout()
        tab.setLayout(box)
        row = QHBoxLayout()
        self.image_path = QLineEdit()
        self.image_path.setPlaceholderText("Скриншот лендинга, баннер или страница документа")
        pick = QPushButton("Выбрать…")
        pick.setObjectName("ghost")
        pick.clicked.connect(self._pick_image)
        row.addWidget(self.image_path)
        row.addWidget(pick)
        self.go_image = QPushButton("Проанализировать")
        self.go_image.clicked.connect(lambda: self._run(self.go_image, api_client.analyze_image, self.image_path.text(),
                                                        render=render_image, busy="Анализирую изображение…"))
        box.addLayout(row)
        box.addWidget(self.go_image)
        box.addStretch()
        return tab

    def _url_tab(self):
        tab, box = QWidget(), QVBoxLayout()
        tab.setLayout(box)
        self.competitor_box = QComboBox()
        self.competitor_box.addItem("— выберите —")
        self.competitor_box.currentIndexChanged.connect(self._competitor_chosen)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.com/uslugi")
        self.go_url = QPushButton("Открыть в Chrome и разобрать")
        self.go_url.clicked.connect(lambda: self._run(self.go_url, api_client.parse_url, self.url_input.text(),
                                                      render=render_page, busy="Открываю страницу в Chrome и анализирую (до минуты)…"))
        box.addWidget(QLabel("Конкурент из списка:"))
        box.addWidget(self.competitor_box)
        box.addWidget(self.url_input)
        box.addWidget(self.go_url)
        box.addStretch()
        return tab

    def _history_tab(self):
        tab, box = QWidget(), QVBoxLayout()
        tab.setLayout(box)
        self.history_box = QComboBox()
        self.history_box.currentIndexChanged.connect(self._history_chosen)
        clear = QPushButton("Очистить историю")
        clear.setObjectName("ghost")
        clear.clicked.connect(self._clear_history)
        box.addWidget(self.history_box)
        box.addWidget(clear)
        box.addStretch()
        self._history_items: list[dict] = []
        return tab

    # --- действия ---
    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Изображение", "", "Изображения (*.png *.jpg *.jpeg *.webp *.gif)")
        if path:
            self.image_path.setText(path)

    def _competitor_chosen(self, index):
        if index > 0:
            self.url_input.setText(self.competitor_box.itemData(index))

    def _load_competitors(self):
        if self.competitor_box.count() > 1:
            return  # список уже загружен

        def fill(items):
            if self.competitor_box.count() > 1:
                return
            for c in items:
                self.competitor_box.addItem(f"{c['name']} — {c['focus']}", c["url"])

        self._start(api_client.competitors, (), fill, lambda msg: self.status.setText(f"Список сайтов не загружен: {msg}"))

    def _check_server(self):
        def ok(info):
            key = "ключ задан" if info.get("api_key_set") else "КЛЮЧ НЕ ЗАДАН (файл окружения)"
            self.server_label.setText(f"Сервер подключён · модель {info.get('model')} · {key}")
            self._load_competitors()  # сервер мог подняться позже окна: догружаем список сайтов

        self._start(api_client.health, (), ok, lambda msg: self.server_label.setText(msg))

    def _on_tab(self, index):
        if index == 3:
            self._start(api_client.history, (), self._show_history, lambda msg: self.status.setText(msg))

    def _show_history(self, items):
        self._history_items = items
        self.history_box.blockSignals(True)
        self.history_box.clear()
        names = {"text": "Текст", "image": "Изображение", "parse": "Сайт"}
        self.history_box.addItem("— выберите запись —")
        for item in items:
            self.history_box.addItem(f"{item['timestamp'][:16].replace('T', ' ')} · {names[item['kind']]} · {item['input_preview'][:60]}")
        self.history_box.blockSignals(False)

    def _history_chosen(self, index):
        if index > 0:
            item = self._history_items[index - 1]
            render = {"text": render_analysis, "image": render_image, "parse": render_page}[item["kind"]]
            self.result.setHtml(render(item["result"]))

    def _clear_history(self):
        if QMessageBox.question(self, "История", "Очистить историю запросов?") == QMessageBox.StandardButton.Yes:
            self._start(api_client.clear_history, (), lambda _: (self._show_history([]), self.result.clear()),
                        lambda msg: self.status.setText(msg))

    # --- запуск запросов в потоке ---
    def _run(self, button, func, arg, render, busy):
        button.setEnabled(False)
        self.result.clear()
        self.status.setText(busy)

        def ok(data):
            button.setEnabled(True)
            self.status.setText("")
            self.result.setHtml(render(data))
            self._check_server()  # строка состояния не должна оставаться от старта окна

        def fail(message):
            button.setEnabled(True)
            self.status.setText(f"Ошибка: {message}")
            self._check_server()

        self._start(func, (arg,), ok, fail)

    def _invoke(self, callback):
        callback()

    def _start(self, func, args, on_done, on_fail):
        thread, worker = QThread(self), Worker(func, *args)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        # колбэки трогают виджеты, поэтому выполняем их через сигнал окна, т.е. в потоке окна
        worker.done.connect(lambda data: self._deliver.emit(lambda: on_done(data)))
        worker.failed.connect(lambda message: self._deliver.emit(lambda: on_fail(message)))
        for signal in (worker.done, worker.failed):
            signal.connect(thread.quit)
        thread.finished.connect(lambda: self._threads.remove((thread, worker)))
        self._threads.append((thread, worker))
        thread.start()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
