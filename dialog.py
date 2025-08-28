
# dialog.py

import json
import os
import html
import shutil
import re
import urllib.parse
import base64
import logging
from PyQt6.QtCore import QTimer
from aqt import mw
from aqt.qt import *
from aqt.utils import showInfo, showWarning
from aqt.webview import QWebEngineView
from anki.utils import strip_html
from .highlighter import HtmlTagHighlighter
from .media_manager import MediaManagerDialog
from .visualizar import VisualizarCards
from .utils import CONFIG_FILE
from .exporthtml import *
from .english import TRANSLATIONS

import webbrowser

# Configuração de logging
logging.basicConfig(filename="delimitadores.log", level=logging.DEBUG)

# Caminho para a pasta de ícones
addon_path = os.path.dirname(__file__)
icons_path = os.path.join(addon_path, 'icons')

# =============================================================================
# BOTÃO CUSTOMIZADO QUE FORÇA O DESENHO DO TEXTO
# =============================================================================
class ForceLabelButton(QPushButton):
    def __init__(self, text, text_color=Qt.GlobalColor.black, parent=None):
        super().__init__("", parent)
        self.forced_text = text
        self.text_color = text_color

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(self.text_color)
        font = self.font()
        font.setPixelSize(14)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.forced_text)


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.line_numbers = []
        self.setStyleSheet("background-color: #ffffff; color: #555;")

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor("#ffffff"))
        document = self.editor.document()
        font_metrics = self.editor.fontMetrics()
        line_height = font_metrics.height()
        cursor = self.editor.cursorForPosition(QPoint(0, 0))
        first_visible_block = cursor.block()
        first_visible_block_number = first_visible_block.blockNumber()
        rect = self.editor.cursorRect(cursor)
        top = rect.top()
        block = first_visible_block
        block_number = first_visible_block_number
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible():
                if block_number < len(self.line_numbers) and self.line_numbers[block_number]:
                    painter.setPen(QColor("#555"))
                    painter.drawText(
                        0, int(top), self.width() - 5, line_height,
                        Qt.AlignmentFlag.AlignRight, self.line_numbers[block_number]
                    )
            block = block.next()
            cursor.movePosition(QTextCursor.MoveOperation.NextBlock)
            rect = self.editor.cursorRect(cursor)
            top = rect.top()
            block_number += 1


class CustomDialog(QDialog):
    def __init__(self, parent=None):
        if not mw:
            showWarning("A janela principal do Anki não está disponível!")
            return
        logging.debug("Inicializando CustomDialog")
        super().__init__(mw, Qt.WindowType.Window | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowMaximizeButtonHint)
        
        self.current_language = 'pt'  # Padrão
        
        self.media_dialog = None
        self.visualizar_dialog = None
        self.last_search_query = ""
        self.last_search_position = 0
        self.zoom_factor = 1.0
        self.cloze_2_count = 1
        self.initial_tags_set = False
        self.initial_numbering_set = False
        self.media_files = []
        self.current_line = 0
        self.previous_text = ""
        self.pre_show_state_file = os.path.join(os.path.dirname(CONFIG_FILE), "pre_show_state.json")
        self.last_edited_line = -1
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self._save_in_real_time)
        self.is_dark_theme = False
        self.field_mappings = {}
        self.field_images = {}
        self.card_notetypes = []
        self.real_text = ""
        self.last_preview_html = ""
        
        self.setup_ui()
        self.load_settings()
        self.retranslate_ui() # Aplica o idioma carregado
        self.setWindowState(Qt.WindowState.WindowMaximized)

    def _t(self, key):
        """Função auxiliar para obter a tradução."""
        if self.current_language == 'en':
            return TRANSLATIONS.get(key, key)
        return key

    def setup_ui(self):
        self.setWindowTitle(self._t("Adicionar Cards com Delimitadores"))
        self.resize(1000, 600)
        main_layout = QVBoxLayout()
        
        # --- SELETOR DE IDIOMA COM BANDEIRAS ---
        top_bar_layout = QHBoxLayout()
        self.lang_label = QLabel(self._t("Idioma:"))
        top_bar_layout.addWidget(self.lang_label)
        self.lang_combo = QComboBox()

        # Carrega ícone do Brasil
        br_icon_path = os.path.join(icons_path, 'br.jpg')
        br_icon = QIcon(br_icon_path) if os.path.exists(br_icon_path) else QIcon()
        self.lang_combo.addItem(br_icon, "Português")

        # Carrega ícone dos EUA
        us_icon_path = os.path.join(icons_path, 'us.jpg')
        us_icon = QIcon(us_icon_path) if os.path.exists(us_icon_path) else QIcon()
        self.lang_combo.addItem(us_icon, "English")

        self.lang_combo.currentIndexChanged.connect(self.switch_language)
        top_bar_layout.addWidget(self.lang_combo)
        top_bar_layout.addStretch()
        main_layout.addLayout(top_bar_layout)
        # --- FIM DO SELETOR ---

        self.vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        
        status_layout = QHBoxLayout()
        self.save_status_label = QLabel(self._t("Pronto"), self)
        self.save_status_label.setStyleSheet("color: gray;")
        status_layout.addWidget(self.save_status_label)
        
        separator_label = QLabel(" / ", self)
        separator_label.setStyleSheet("color: gray;")
        status_layout.addWidget(separator_label)
        
        self.card_count_label = QLabel(self._t("Cards: {}").format(0), self)
        self.card_count_label.setStyleSheet("color: gray;")
        status_layout.addWidget(self.card_count_label)
        status_layout.addStretch()
        top_layout.addLayout(status_layout)
        
        media_layout = QHBoxLayout()
        self.image_button = QPushButton(self._t("Adicionar Imagem, Som ou Vídeo"), self)
        self.image_button.clicked.connect(self.add_image)
        media_layout.addWidget(self.image_button)
        
        self.manage_media_button = QPushButton(self._t("Gerenciar Mídia"), self)
        self.manage_media_button.clicked.connect(self.manage_media)
        media_layout.addWidget(self.manage_media_button)
        
        self.export_html_button = QPushButton(self._t("Exportar para HTML"), self)
        self.export_html_button.clicked.connect(self.export_to_html)
        self.export_html_button.setToolTip(self._t("Exportar cards para arquivo HTML"))
        media_layout.addWidget(self.export_html_button)
        
        self.view_cards_button = QPushButton(self._t("Visualizar Cards"), self)
        self.view_cards_button.clicked.connect(self.view_cards_dialog)
        media_layout.addWidget(self.view_cards_button)
        
        self.show_button = QPushButton(self._t("Mostrar"), self)
        self.show_button.clicked.connect(self.show_all_cards)
        self.show_button.setToolTip(self._t("Mostra todos os cards do deck em 'Digite seus cards'"))
        media_layout.addWidget(self.show_button)
        
        top_layout.addLayout(media_layout)
        
        self.fields_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        self.cards_tags_widget = QWidget()
        cards_tags_layout = QHBoxLayout(self.cards_tags_widget)
        
        self.cards_group = QWidget()
        cards_layout = QVBoxLayout(self.cards_group)
        
        cards_header_layout = QHBoxLayout()
        self.cards_label = QLabel(self._t("Digite seus cards:"))
        cards_header_layout.addWidget(self.cards_label)
        
        self.color_buttons = []
        for color in ["red", "blue", "green", "yellow"]:
            btn = ForceLabelButton("A", text_color=QColor(color))
            btn.setStyleSheet("background-color: black;")
            btn.setFixedSize(30, 30)
            btn.clicked.connect(lambda checked, c=color: self.apply_text_color(c))
            btn.setToolTip(self._t("Aplicar cor ao texto"))
            cards_header_layout.addWidget(btn)
            self.color_buttons.append(btn)
        
        self.bg_color_buttons = []
        for color in ["red", "blue", "green", "yellow"]:
            btn = ForceLabelButton("Af", text_color=Qt.GlobalColor.black)
            btn.setStyleSheet(f"background-color: {color};")
            btn.setFixedSize(30, 30)
            btn.clicked.connect(lambda checked, c=color: self.apply_background_color(c))
            btn.setToolTip(self._t("Aplicar cor de fundo ao texto"))
            cards_header_layout.addWidget(btn)
            self.bg_color_buttons.append(btn)
        
        cards_header_layout.addStretch()
        cards_layout.addLayout(cards_header_layout)
        
        self.stacked_editor = QStackedWidget()

        self.txt_entrada = QTextEdit()
        self.txt_entrada.setUndoRedoEnabled(True)
        self.txt_entrada.setPlaceholderText(self._t("Digite seus cards aqui..."))
        self.txt_entrada.setStyleSheet("QTextEdit { font-family: monospace; padding-top: 3px; padding-left: 5px; line-height: 1.5em; }")
        if self.is_dark_theme:
            self.txt_entrada.setStyleSheet("QTextEdit { font-family: monospace; padding-top: 3px; padding-left: 5px; line-height: 1.5em; background-color: #ffffff; color: #000000; border: 1px solid #555; selection-background-color: #4a90d9; selection-color: #ffffff; }")
        
        self.highlighter = HtmlTagHighlighter(self.txt_entrada.document())
        
        self.txt_entrada.line_number_area = LineNumberArea(self.txt_entrada)
        self.txt_entrada.line_number_area_width = self.line_number_area_width
        self.txt_entrada.textChanged.connect(self.update_line_number_area_width)
        self.txt_entrada.verticalScrollBar().valueChanged.connect(lambda: self.txt_entrada.line_number_area.update())
        self.txt_entrada.cursorPositionChanged.connect(self.highlight_current_line)
        self.txt_entrada.resizeEvent = lambda event: self.custom_resize_event(event)
        self.txt_entrada.textChanged.connect(self.schedule_save)
        self.txt_entrada.textChanged.connect(self.update_tags_lines)
        self.txt_entrada.textChanged.connect(self.update_preview)
        self.txt_entrada.textChanged.connect(self.clean_input_text)
        self.txt_entrada.textChanged.connect(self.update_card_count)
        self.txt_entrada.textChanged.connect(self.update_line_numbers)
        self.txt_entrada.cursorPositionChanged.connect(self.check_line_change)
        self.txt_entrada.installEventFilter(self)
        self.txt_entrada.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.txt_entrada.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.txt_entrada.setAcceptDrops(True)
        self.txt_entrada.dropEvent = self.drop_event
        
        self.stacked_editor.addWidget(self.txt_entrada)

        self.table_widget = QTableWidget()
        self.table_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_widget.customContextMenuRequested.connect(self.show_table_context_menu)
        self.stacked_editor.addWidget(self.table_widget)

        cards_layout.addWidget(self.stacked_editor)
        
        cards_tags_layout.addWidget(self.cards_group, stretch=2)
        
        self.etiquetas_group = QWidget()
        etiquetas_layout = QVBoxLayout(self.etiquetas_group)
        etiquetas_header_layout = QHBoxLayout()
        self.tags_label = QLabel(self._t("Etiquetas:"))
        etiquetas_header_layout.addWidget(self.tags_label)
        etiquetas_header_layout.addStretch()
        etiquetas_layout.addLayout(etiquetas_header_layout)
        self.txt_tags = QTextEdit()
        self.txt_tags.setUndoRedoEnabled(True)
        self.txt_tags.setPlaceholderText(self._t("Digite as etiquetas aqui (uma linha por card)..."))
        self.txt_tags.setMaximumWidth(200)
        self.txt_tags.textChanged.connect(self.schedule_save)
        self.txt_tags.textChanged.connect(self.update_preview)
        self.txt_tags.installEventFilter(self)
        etiquetas_layout.addWidget(self.txt_tags)
        self.etiquetas_group.setVisible(False)
        cards_tags_layout.addWidget(self.etiquetas_group, stretch=1)
        
        self.fields_splitter.addWidget(self.cards_tags_widget)
        
        self.preview_group = QWidget()
        preview_layout = QVBoxLayout(self.preview_group)
        
        preview_header_layout = QHBoxLayout()
        self.preview_label = QLabel(self._t("Preview:"))
        preview_header_layout.addWidget(self.preview_label)
        preview_header_layout.addStretch()
        
        self.zoom_in_preview_button = ForceLabelButton("+", parent=self)
        self.zoom_in_preview_button.clicked.connect(self.zoom_in_preview)
        self.zoom_in_preview_button.setFixedSize(30, 30)
        preview_header_layout.addWidget(self.zoom_in_preview_button)
        
        self.zoom_out_preview_button = ForceLabelButton("-", parent=self)
        self.zoom_out_preview_button.clicked.connect(self.zoom_out_preview)
        self.zoom_out_preview_button.setFixedSize(30, 30)
        preview_header_layout.addWidget(self.zoom_out_preview_button)
        
        preview_layout.addLayout(preview_header_layout)
        
        self.preview_widget = QWebEngineView()
        settings = self.preview_widget.settings()
        for attr in [QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
                     QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
                     QWebEngineSettings.WebAttribute.AllowRunningInsecureContent]:
            settings.setAttribute(attr, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        self.preview_widget.setMinimumWidth(0)
        preview_layout.addWidget(self.preview_widget)
        
        self.fields_splitter.addWidget(self.preview_group)
        self.fields_splitter.setSizes([700, 300])
        self.fields_splitter.setChildrenCollapsible(True)
        self.fields_splitter.setStretchFactor(0, 1)
        self.fields_splitter.setStretchFactor(1, 0)
        
        top_layout.addWidget(self.fields_splitter)
        
        options_layout = QHBoxLayout()
        options_layout.addStretch()
        self.chk_num_tags = QCheckBox(self._t("Numerar Tags"))
        self.chk_repetir_tags = QCheckBox(self._t("Repetir Tags"))
        self.chk_num_tags.stateChanged.connect(self.update_tag_numbers)
        self.chk_num_tags.stateChanged.connect(self.schedule_save)
        self.chk_repetir_tags.stateChanged.connect(self.update_repeated_tags)
        self.chk_repetir_tags.stateChanged.connect(self.schedule_save)
        options_layout.addWidget(self.chk_num_tags)
        options_layout.addWidget(self.chk_repetir_tags)
        
        self.toggle_tags_button = QPushButton(self._t("Mostrar Etiquetas"), self)
        self.toggle_tags_button.clicked.connect(self.toggle_tags)
        options_layout.addWidget(self.toggle_tags_button)
        
        self.theme_button = QPushButton(self._t("Mudar Tema"), self)
        self.theme_button.clicked.connect(self.toggle_theme)
        options_layout.addWidget(self.theme_button)
        
        top_layout.addLayout(options_layout)
        self.vertical_splitter.addWidget(top_widget)
        
        self.main_scroll = QScrollArea()
        self.main_scroll.setWidgetResizable(True)
        self.main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        
        bottom_scroll = QScrollArea()
        bottom_scroll.setWidgetResizable(True)
        bottom_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        
        btn_layout = QHBoxLayout()
        
        self.toggle_view_button = QPushButton(self._t("📝 Editar em Grade"))
        self.toggle_view_button.setToolTip(self._t("Alterna entre a edição de texto livre e uma grade estilo planilha."))
        self.toggle_view_button.clicked.connect(self.toggle_editor_view)
        btn_layout.addWidget(self.toggle_view_button)

        self.botoes_formatacao_defs = [
            ("Juntar Linhas", self.join_lines, "Juntar todas as linhas (sem atalho)"),
            ("Destaque", self.destaque_texto, "Destacar texto (Ctrl+M)"),
            ("B", self.apply_bold, "Negrito (Ctrl+B)"),
            ("I", self.apply_italic, "Itálico (Ctrl+I)"),
            ("U", self.apply_underline, "Sublinhado (Ctrl+U)"),
            ("Concatenar", self.concatenate_text, "Concatenar texto (sem atalho)"),
            ("Limpar Tudo", self.clear_all, "Limpar todos os campos e configurações"),
            ("Desfazer", self.restore_pre_show_state, "Desfazer (Ctrl+Z)"),
            ("Refazer", self.txt_entrada.redo, "Refazer (Ctrl+Y)"),
        ]
        self.botoes_formatacao_widgets = []
        for texto, funcao, tooltip in self.botoes_formatacao_defs:
            btn = QPushButton(self._t(texto))
            btn.clicked.connect(funcao)
            btn.setToolTip(self._t(tooltip))
            if texto == "Destaque":
                btn.setStyleSheet("background-color: yellow; color: black;")
            btn_layout.addWidget(btn)
            self.botoes_formatacao_widgets.append(btn)
        bottom_layout.addLayout(btn_layout)
        
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText(self._t("Pesquisar... Ctrl+P"))
        search_layout.addWidget(self.search_input)
        self.search_button = QPushButton(self._t("Pesquisar"), self)
        self.search_button.clicked.connect(self.search_text)
        search_layout.addWidget(self.search_button)
        self.replace_input = QLineEdit(self)
        self.replace_input.setPlaceholderText(self._t("Substituir tudo por... Ctrl+Shift+R"))
        search_layout.addWidget(self.replace_input)
        self.replace_button = QPushButton(self._t("Substituir Tudo"), self)
        self.replace_button.clicked.connect(self.replace_text)
        search_layout.addWidget(self.replace_button)
        self.zoom_in_button = QPushButton("+", self)
        self.zoom_in_button.clicked.connect(self.zoom_in)
        search_layout.addWidget(self.zoom_in_button)
        self.zoom_out_button = QPushButton("-", self)
        self.zoom_out_button.clicked.connect(self.zoom_out)
        search_layout.addWidget(self.zoom_out_button)
        bottom_layout.addLayout(search_layout)
        
        cloze_layout = QGridLayout()
        self.cloze_buttons_defs = [
            ("Cloze 1 (Ctrl+Shift+D)", self.add_cloze_1, 0, "Adicionar Cloze 1 (Ctrl+Shift+D)"),
            ("Cloze 2 (Ctrl+Shift+F)", self.add_cloze_2, 1, "Adicionar Cloze 2 (Ctrl+Shift+F)"),
            ("Remover Cloze", self.remove_cloze, 2, "Remover Cloze (sem atalho)")
        ]
        self.cloze_buttons_widgets = []
        for text, func, col, tooltip in self.cloze_buttons_defs:
            btn = QPushButton(self._t(text), self)
            btn.clicked.connect(func)
            btn.setToolTip(self._t(tooltip))
            cloze_layout.addWidget(btn, 0, col)
            self.cloze_buttons_widgets.append(btn)
        bottom_layout.addLayout(cloze_layout)
        
        self.group_widget = QWidget()
        group_layout = QVBoxLayout(self.group_widget)
        self.group_splitter = QSplitter(Qt.Orientation.Vertical)
        decks_modelos_widget = QWidget()
        decks_modelos_layout = QVBoxLayout(decks_modelos_widget)
        self.decks_modelos_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.decks_group = QGroupBox(self._t("Decks"))
        decks_layout = QVBoxLayout(self.decks_group)
        self.scroll_decks, self.lista_decks = self.criar_lista_rolavel([d.name for d in mw.col.decks.all_names_and_ids()], 100)
        self.lista_decks.currentItemChanged.connect(self.schedule_save)
        decks_layout.addWidget(self.scroll_decks)
        self.decks_search_input = QLineEdit(self)
        self.decks_search_input.setPlaceholderText(self._t("Pesquisar decks..."))
        self.decks_search_input.textChanged.connect(self.filter_decks)
        decks_layout.addWidget(self.decks_search_input)
        self.deck_name_input = QLineEdit(self)
        self.deck_name_input.setPlaceholderText(self._t("Digite o nome do novo deck..."))
        decks_layout.addWidget(self.deck_name_input)
        self.create_deck_button = QPushButton(self._t("Criar Deck"), self)
        self.create_deck_button.clicked.connect(self.create_deck)
        decks_layout.addWidget(self.create_deck_button)
        self.decks_modelos_splitter.addWidget(self.decks_group)
        self.modelos_group = QGroupBox(self._t("Modelos ou Tipos de Notas"))
        modelos_layout = QVBoxLayout(self.modelos_group)
        self.scroll_notetypes, self.lista_notetypes = self.criar_lista_rolavel(mw.col.models.all_names(), 100)
        self.lista_notetypes.currentItemChanged.connect(self.update_field_mappings)
        self.lista_notetypes.currentItemChanged.connect(self.update_preview)
        self.lista_notetypes.currentItemChanged.connect(self.schedule_save)
        modelos_layout.addWidget(self.scroll_notetypes)
        self.notetypes_search_input = QLineEdit(self)
        self.notetypes_search_input.setPlaceholderText(self._t("Pesquisar tipos de notas..."))
        self.notetypes_search_input.textChanged.connect(self.filter_notetypes)
        modelos_layout.addWidget(self.notetypes_search_input)
        self.decks_modelos_splitter.addWidget(self.modelos_group)
        self.decks_modelos_splitter.setSizes([200, 150])
        decks_modelos_layout.addWidget(self.decks_modelos_splitter)
        self.group_splitter.addWidget(decks_modelos_widget)
        self.fields_group = QGroupBox(self._t("Mapeamento de Campos"))
        fields_layout = QVBoxLayout(self.fields_group)
        self.fields_map_label = QLabel(self._t("Associe cada parte a um campo:"))
        fields_layout.addWidget(self.fields_map_label)
        self.fields_container = QWidget()
        self.fields_container_layout = QVBoxLayout(self.fields_container)
        self.field_combo_boxes = []
        self.field_image_buttons = {}
        fields_layout.addWidget(self.fields_container)
        self.group_splitter.addWidget(self.fields_group)
        delimitadores_widget = QWidget()
        delimitadores_layout = QVBoxLayout(delimitadores_widget)
        self.delimitadores_label = QLabel(self._t("Delimitadores:"))
        delimitadores_layout.addWidget(self.delimitadores_label)
        delimitadores = [("Tab", "\t"), ("Vírgula", ","), ("Ponto e Vírgula", ";"), ("Dois Pontos", ":"),
                         ("Interrogação", "?"), ("Barra", "/"), ("Exclamação", "!"), ("Pipe", "|")]
        grid = QGridLayout()
        self.chk_delimitadores = {}
        for i, (nome, simbolo) in enumerate(delimitadores):
            chk = QCheckBox(self._t(nome))
            chk.simbolo = simbolo
            chk.stateChanged.connect(self.update_preview)
            chk.stateChanged.connect(self.schedule_save)
            grid.addWidget(chk, i // 4, i % 4)
            self.chk_delimitadores[nome] = chk
        delimitadores_layout.addLayout(grid)
        self.group_splitter.addWidget(delimitadores_widget)
        self.group_splitter.setSizes([150, 150, 100])
        group_layout.addWidget(self.group_splitter)
        bottom_layout.addWidget(self.group_widget)
        
        bottom_buttons_layout = QHBoxLayout()
        self.btn_toggle = QPushButton(self._t("Ocultar Decks/Modelos/Delimitadores"))
        self.btn_toggle.clicked.connect(self.toggle_group)
        bottom_buttons_layout.addWidget(self.btn_toggle)
        self.btn_add = QPushButton(self._t("Adicionar Cards (Ctrl+R)"))
        self.btn_add.clicked.connect(self.add_cards)
        self.btn_add.setToolTip(self._t("Adicionar Cards (Ctrl+R)"))
        bottom_buttons_layout.addWidget(self.btn_add)
        bottom_layout.addLayout(bottom_buttons_layout)
        bottom_layout.addStretch()
        
        bottom_scroll.setWidget(bottom_widget)
        scroll_layout.addWidget(bottom_scroll)
        self.main_scroll.setWidget(scroll_content)
        self.vertical_splitter.addWidget(self.main_scroll)
        self.vertical_splitter.setSizes([300, 300])
        self.vertical_splitter.setChildrenCollapsible(False)
        
        main_layout.addWidget(self.vertical_splitter)
        self.setLayout(main_layout)
        
        self.txt_entrada.setMinimumHeight(100)
        self.vertical_splitter.setMinimumSize(800, 600)
        self.fields_splitter.setMinimumSize(400, 200)
        
        self.vertical_splitter.splitterMoved.connect(self.handle_splitter_move)
        self.fields_splitter.splitterMoved.connect(self.handle_splitter_move)
        self.resizeEvent = self.handle_resize
        self.vertical_splitter.splitterMoved.connect(self.schedule_save)
        self.fields_splitter.splitterMoved.connect(self.schedule_save)
        
        for key, func in [
            ("Ctrl+B", "apply_bold"), ("Ctrl+I", "apply_italic"), ("Ctrl+U", "apply_underline"),
            ("Ctrl+M", "destaque_texto"), ("Ctrl+P", "search_text"), ("Ctrl+Shift+R", "replace_text"),
            ("Ctrl+=", "zoom_in"), ("Ctrl+-", "zoom_out"), ("Ctrl+Shift+D", "add_cloze_1"),
            ("Ctrl+Shift+F", "add_cloze_2"), ("Ctrl+R", "add_cards"), ("Ctrl+Z", "restore_pre_show_state"), ("Ctrl+Y", "redo")
        ]:
            QShortcut(QKeySequence(key), self).activated.connect(lambda f=func: self.log_shortcut(f))
        
        self.txt_entrada.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.txt_entrada.customContextMenuRequested.connect(self.show_context_menu)
        self.txt_entrada.setAcceptDrops(True)
        self.txt_entrada.focusInEvent = self.create_focus_handler(self.txt_entrada, "cards")
        self.txt_tags.focusInEvent = self.create_focus_handler(self.txt_tags, "tags")
        self.txt_entrada.textChanged.connect(self.update_line_numbers)
        
        list_style = "QListWidget::item:selected { background-color: #4a90d9; color: #000000; } QListWidget::item { padding: 3px; }"
        self.lista_decks.setStyleSheet(list_style)
        self.lista_notetypes.setStyleSheet(list_style)

    def switch_language(self, index):
        lang_map = {0: 'pt', 1: 'en'}
        new_lang = lang_map.get(index)
        if new_lang and new_lang != self.current_language:
            self.current_language = new_lang
            self.retranslate_ui()
            self.schedule_save()

    def retranslate_ui(self):
        """Atualiza todo o texto da UI para o idioma atual."""
        self.setWindowTitle(self._t("Adicionar Cards com Delimitadores"))
        self.lang_label.setText(self._t("Idioma:"))
        self.save_status_label.setText(self._t("Pronto"))
        self.update_card_count() # Atualiza o contador com o texto correto
        
        self.image_button.setText(self._t("Adicionar Imagem, Som ou Vídeo"))
        self.manage_media_button.setText(self._t("Gerenciar Mídia"))
        self.export_html_button.setText(self._t("Exportar para HTML"))
        self.export_html_button.setToolTip(self._t("Exportar cards para arquivo HTML"))
        self.view_cards_button.setText(self._t("Visualizar Cards"))
        self.show_button.setText(self._t("Mostrar"))
        self.show_button.setToolTip(self._t("Mostra todos os cards do deck em 'Digite seus cards'"))
        
        self.cards_label.setText(self._t("Digite seus cards:"))
        for btn in self.color_buttons:
            btn.setToolTip(self._t("Aplicar cor ao texto"))
        for btn in self.bg_color_buttons:
            btn.setToolTip(self._t("Aplicar cor de fundo ao texto"))
            
        self.txt_entrada.setPlaceholderText(self._t("Digite seus cards aqui..."))
        self.tags_label.setText(self._t("Etiquetas:"))
        self.txt_tags.setPlaceholderText(self._t("Digite as etiquetas aqui (uma linha por card)..."))
        
        self.preview_label.setText(self._t("Preview:"))
        
        self.chk_num_tags.setText(self._t("Numerar Tags"))
        self.chk_repetir_tags.setText(self._t("Repetir Tags"))
        
        is_visible = self.etiquetas_group.isVisible()
        self.toggle_tags_button.setText(self._t("Ocultar Etiquetas") if is_visible else self._t("Mostrar Etiquetas"))
        self.theme_button.setText(self._t("Mudar Tema"))
        
        self.toggle_view_button.setText(self._t("📝 Editar em Grade") if self.stacked_editor.currentIndex() == 0 else self._t("📄 Editar como Texto"))
        self.toggle_view_button.setToolTip(self._t("Alterna entre a edição de texto livre e uma grade estilo planilha."))

        for i, btn in enumerate(self.botoes_formatacao_widgets):
            texto, _, tooltip = self.botoes_formatacao_defs[i]
            btn.setText(self._t(texto))
            btn.setToolTip(self._t(tooltip))

        self.search_input.setPlaceholderText(self._t("Pesquisar... Ctrl+P"))
        self.search_button.setText(self._t("Pesquisar"))
        self.replace_input.setPlaceholderText(self._t("Substituir tudo por... Ctrl+Shift+R"))
        self.replace_button.setText(self._t("Substituir Tudo"))

        for i, btn in enumerate(self.cloze_buttons_widgets):
            text, _, _, tooltip = self.cloze_buttons_defs[i]
            btn.setText(self._t(text))
            btn.setToolTip(self._t(tooltip))

        self.decks_group.setTitle(self._t("Decks"))
        self.decks_search_input.setPlaceholderText(self._t("Pesquisar decks..."))
        self.deck_name_input.setPlaceholderText(self._t("Digite o nome do novo deck..."))
        self.create_deck_button.setText(self._t("Criar Deck"))
        
        self.modelos_group.setTitle(self._t("Modelos ou Tipos de Notas"))
        self.notetypes_search_input.setPlaceholderText(self._t("Pesquisar tipos de notas..."))
        
        self.fields_group.setTitle(self._t("Mapeamento de Campos"))
        self.fields_map_label.setText(self._t("Associe cada parte a um campo:"))
        
        self.delimitadores_label.setText(self._t("Delimitadores:"))
        for nome, chk in self.chk_delimitadores.items():
            chk.setText(self._t(nome))

        is_group_visible = self.group_widget.isVisible()
        self.btn_toggle.setText(self._t("Ocultar Decks/Modelos/Delimitadores") if is_group_visible else self._t("Mostrar Decks/Modelos/Delimitadores"))
        self.btn_add.setText(self._t("Adicionar Cards (Ctrl+R)"))
        self.btn_add.setToolTip(self._t("Adicionar Cards (Ctrl+R)"))

        # Atualiza o preview, pois ele pode conter mensagens de erro/status
        self.update_preview()
        # Atualiza o mapeamento de campos, pois os combos precisam ser recriados com o texto traduzido
        self.update_field_mappings()

    def zoom_in_preview(self):
        current_zoom = self.preview_widget.zoomFactor()
        self.preview_widget.setZoomFactor(current_zoom + 0.1)
    
    def zoom_out_preview(self):
        current_zoom = self.preview_widget.zoomFactor()
        self.preview_widget.setZoomFactor(max(0.1, current_zoom - 0.1))

    def handle_splitter_move(self, pos, index):
        self.txt_entrada.updateGeometry()
        self.txt_entrada.line_number_area.update()

    def handle_resize(self, event):
        QDialog.resizeEvent(self, event)
        self.schedule_save()

    def log_shortcut(self, func_name):
        logging.debug(f"Atalho acionado: {func_name}")
        if func_name in ["undo", "redo"]:
            getattr(self.txt_entrada, func_name)()
        else:
            getattr(self, func_name)()

    def schedule_save(self):
        self.save_status_label.setText(self._t("Salvando..."))
        self.save_status_label.setStyleSheet("color: orange;")
        self.save_timer.start(500)

    def update_card_count(self):
        text = self.txt_entrada.toPlainText()
        lines = text.splitlines()
        
        active_delimiters = [chk.simbolo for chk in self.chk_delimitadores.values() if chk.isChecked()]
        if not active_delimiters:
            active_delimiters = [';']
        
        card_count = 0
        for line in lines:
            line = line.strip()
            if line and any(c.isalpha() for c in line):
                if any(d in line for d in active_delimiters):
                    card_count += 1
        
        self.card_count_label.setText(self._t("Cards: {}").format(card_count))

    def update_line_numbers(self):
        document = self.txt_entrada.document()
        block = document.firstBlock()
        line_numbers = []
        valid_line_count = 0
        
        active_delimiters = [chk.simbolo for chk in self.chk_delimitadores.values() if chk.isChecked()]
        if not active_delimiters:
            active_delimiters = [';']

        while block.isValid():
            text = block.text().strip()
            if text and any(c.isalpha() for c in text) and any(d in text for d in active_delimiters):
                valid_line_count += 1
                line_numbers.append(str(valid_line_count))
            else:
                line_numbers.append("")
            block = block.next()
            
        self.txt_entrada.line_number_area.line_numbers = line_numbers
        self.txt_entrada.line_number_area.update()
        self.update_line_number_area_width()

    def line_number_area_width(self):
        max_num = 0
        for num in self.txt_entrada.line_number_area.line_numbers:
            if num:
                max_num = max(max_num, int(num))
        digits = len(str(max_num)) if max_num > 0 else 1
        space = 3 + self.txt_entrada.fontMetrics().horizontalAdvance('9') * digits
        return space + 10
    
    def update_line_number_area_width(self):
        self.txt_entrada.setViewportMargins(self.line_number_area_width(), 0, 0, 0)
        self.txt_entrada.line_number_area.update()
    
    def custom_resize_event(self, event):
        QTextEdit.resizeEvent(self.txt_entrada, event)
        cr = self.txt_entrada.contentsRect()
        if cr.height() < 100:
            cr.setHeight(100)
        self.txt_entrada.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))
        self.txt_entrada.line_number_area.update()
        self.txt_entrada.updateGeometry()

    def highlight_current_line(self):
        extra_selections = []
        if not self.txt_entrada.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor("#e0e0e0"))
            selection.format.setForeground(QColor("#000000"))
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.txt_entrada.textCursor()
            selection.cursor.clearSelection()
            extra_selections.append(selection)
        self.txt_entrada.setExtraSelections(extra_selections)

    def _save_in_real_time(self):
        try:
            if os.path.exists(CONFIG_FILE):
                shutil.copy2(CONFIG_FILE, CONFIG_FILE + ".bak")
            window_geometry = {'size': (self.width(), self.height()), 'pos': (self.x(), self.y()), 'vertical_splitter': self.vertical_splitter.sizes(), 'fields_splitter': self.fields_splitter.sizes()}
            dados = {
                'conteudo': self.txt_entrada.toPlainText(), 
                'tags': self.txt_tags.toPlainText(), 
                'delimitadores': {nome: chk.isChecked() for nome, chk in self.chk_delimitadores.items()}, 
                'deck_selecionado': self.lista_decks.currentItem().text() if self.lista_decks.currentItem() else '', 
                'modelo_selecionado': self.lista_notetypes.currentItem().text() if self.lista_notetypes.currentItem() else '', 
                'field_mappings': self.field_mappings, 
                'field_images': self.field_images, 
                'window_geometry': window_geometry, 
                'last_preview_html': getattr(self, 'last_preview_html', ''),
                'language': self.current_language
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(dados, f, ensure_ascii=False, indent=2)
            self.save_status_label.setText(self._t("Salvo"))
            self.save_status_label.setStyleSheet("color: green;")
            QTimer.singleShot(2000, lambda: self.save_status_label.setText(self._t("Pronto")) or self.save_status_label.setStyleSheet("color: gray;"))
        except Exception as e:
            logging.error(f"Erro ao salvar em tempo real: {str(e)}")
            self.save_status_label.setText(self._t("Erro ao salvar"))
            self.save_status_label.setStyleSheet("color: red;")

    def toggle_tags(self):
        novo_estado = not self.etiquetas_group.isVisible()
        self.etiquetas_group.setVisible(novo_estado)
        self.toggle_tags_button.setText(self._t("Ocultar Etiquetas") if novo_estado else self._t("Mostrar Etiquetas"))
        if novo_estado:
            self.txt_tags.setFocus()
            cursor = self.txt_tags.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.txt_tags.setTextCursor(cursor)
            self.adjust_scroll_position()
    
    def adjust_scroll_position(self):
        self.txt_tags.verticalScrollBar().setValue(0)

    def showEvent(self, event):
        super().showEvent(event)
        if self.etiquetas_group.isVisible():
            self.txt_tags.setFocus()
            cursor = self.txt_tags.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.txt_tags.setTextCursor(cursor)

    def update_tags_lines(self):
        linhas_cards = self.txt_entrada.toPlainText().strip().split('\n')
        linhas_tags = self.txt_tags.toPlainText().strip().split('\n')
        if len(linhas_tags) < len(linhas_cards):
            self.txt_tags.setPlainText(self.txt_tags.toPlainText() + '\n' * (len(linhas_cards) - len(linhas_tags)))
        elif len(linhas_tags) > len(linhas_cards):
            self.txt_tags.setPlainText('\n'.join(linhas_tags[:len(linhas_cards)]))
        self.update_preview()

    def check_line_change(self):
        cursor = self.txt_entrada.textCursor()
        current_line = cursor.blockNumber()
        if current_line != self.current_line:
            self.process_media_rename()
            self.current_line = current_line
            self.last_edited_line = current_line
        self.update_preview()

    def focus_out_event(self, event):
        self.process_media_rename()
        QTextEdit.focusOutEvent(self.txt_entrada, event)

    def process_media_rename(self):
        current_text = self.txt_entrada.toPlainText()
        if self.previous_text != current_text:
            patterns = [r'<img src="([^"]+)"', r'<source src="([^"]+)"', r'<video src="([^"]+)"']
            previous_media = set()
            current_media = set()
            for pattern in patterns:
                previous_media.update(re.findall(pattern, self.previous_text))
                current_media.update(re.findall(pattern, current_text))
            media_dir = mw.col.media.dir()
            for old_name in previous_media:
                if old_name in self.media_files and old_name not in current_media:
                    for new_name in current_media:
                        if new_name not in previous_media and new_name not in self.media_files:
                            if os.path.exists(os.path.join(media_dir, new_name)):
                                logging.warning(f"O nome '{new_name}' já existe na pasta de mídia!")
                                showWarning(f"O nome '{new_name}' já existe na pasta de mídia!")
                                continue
                            try:
                                src_path = os.path.join(media_dir, old_name)
                                dst_path = os.path.join(media_dir, new_name)
                                if not os.path.exists(src_path):
                                    logging.error(f"Arquivo de origem '{src_path}' não encontrado!")
                                    continue
                                os.rename(src_path, dst_path)
                                self.media_files[self.media_files.index(old_name)] = new_name
                                logging.info(f"Arquivo renomeado de '{old_name}' para '{new_name}' na pasta de mídia.")
                                showInfo(f"Arquivo renomeado de '{old_name}' para '{new_name}' na pasta de mídia.")
                            except Exception as e:
                                logging.error(f"Erro ao renomear o arquivo de '{old_name}' para '{new_name}': {str(e)}")
                                showWarning(f"Erro ao renomear o arquivo: {str(e)}")
                            break
            self.previous_text = current_text

    def update_field_mappings(self):
        while self.fields_container_layout.count():
            child = self.fields_container_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                while child.layout().count():
                    item = child.layout().takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()
                child.layout().deleteLater()

        self.field_combo_boxes.clear()
        self.field_image_buttons.clear()

        if not self.lista_notetypes.currentItem():
            return
        modelo = mw.col.models.by_name(self.lista_notetypes.currentItem().text())
        campos = [fld['name'] for fld in modelo['flds']]
        num_campos = len(campos)
        for i in range(num_campos):
            field_layout = QHBoxLayout()
            combo = QComboBox()
            combo.addItem(self._t("Parte {} -> Ignorar").format(i + 1))
            for campo in campos:
                combo.addItem(self._t("Parte {} -> {}").format(i + 1, campo))
            
            if str(i) in self.field_mappings and self.field_mappings[str(i)] in campos:
                combo.setCurrentText(self._t("Parte {} -> {}").format(i + 1, self.field_mappings[str(i)]))
            else:
                combo.setCurrentIndex(0)
            
            combo.currentIndexChanged.connect(self.update_field_mapping)
            self.field_combo_boxes.append(combo)
            field_layout.addWidget(combo)
            
            btn = QPushButton(self._t("Midia {}").format(campos[i]))
            btn.clicked.connect(lambda checked, idx=i, campo=campos[i]: self.add_media_to_field(idx, campo))
            self.field_image_buttons[campos[i]] = btn
            field_layout.addWidget(btn)
            self.fields_container_layout.addLayout(field_layout)
        self.update_preview()

    def add_media_to_field(self, idx, campo):
        arquivos, _ = QFileDialog.getOpenFileNames(self, self._t("Selecionar Mídia para {}").format(campo), "", "Mídia (*.png *.jpg *.jpeg *.gif *.mp3 *.wav *.ogg *.mp4 *.webm)")
        if not arquivos:
            return
        media_dir = mw.col.media.dir()
        current_line = self.txt_entrada.textCursor().blockNumber()
        linhas = self.txt_entrada.toPlainText().strip().split('\n')
        for caminho in arquivos:
            nome = os.path.basename(caminho)
            destino = os.path.join(media_dir, nome)
            if os.path.exists(destino):
                base, ext = os.path.splitext(nome)
                counter = 1
                while os.path.exists(destino):
                    nome = f"{base}_{counter}{ext}"
                    destino = os.path.join(media_dir, nome)
                    counter += 1
            shutil.copy2(caminho, destino)
            if campo not in self.field_images:
                self.field_images[campo] = []
            while len(self.field_images[campo]) <= current_line:
                self.field_images[campo].append("")
            self.field_images[campo][current_line] = nome
            if current_line < len(linhas):
                partes = self._get_split_parts(linhas[current_line])
                partes = [p.strip() for p in partes]
                if all(str(i) not in self.field_mappings for i in range(len(partes))):
                    if idx < len(partes):
                        partes[idx] += f' <img src="{nome}">' if partes[idx] else f'<img src="{nome}">'
                else:
                    for i, parte in enumerate(partes):
                        if str(i) in self.field_mappings and self.field_mappings[str(i)] == campo:
                            partes[i] += f' <img src="{nome}">' if parte else f'<img src="{nome}">'
                active_delimiter = next((chk.simbolo for chk in self.chk_delimitadores.values() if chk.isChecked()), ';')
                linhas[current_line] = active_delimiter.join(partes)
                self.txt_entrada.setPlainText('\n'.join(linhas))
        self.schedule_save()
        self.update_preview()

    def update_field_mapping(self):
        self.field_mappings = {}
        if not self.lista_notetypes.currentItem(): return

        modelo = mw.col.models.by_name(self.lista_notetypes.currentItem().text())
        campos = [fld['name'] for fld in modelo['flds']]

        for i, combo in enumerate(self.field_combo_boxes):
            text = combo.currentText()
            if " -> " in text:
                parts = text.split(" -> ")
                if len(parts) > 1:
                    campo_display = parts[1]
                    if campo_display != self._t("Ignorar"):
                        # Encontra o nome original do campo, já que ele não é traduzido
                        for original_campo in campos:
                            if self._t(original_campo) == campo_display or original_campo == campo_display:
                                self.field_mappings[str(i)] = original_campo
                                break
        self.schedule_save()
        self.update_preview()

    def clean_input_text(self):
        try:
            current_text = self.txt_entrada.toPlainText()
            if not current_text:
                return

            def clean_attributes(match):
                tag, attrs, content = match.groups()
                attrs_cleaned = re.sub(r'"(.*?);(.*?)"', r'"\1 \2"', attrs)
                return f"<{tag}{attrs_cleaned}>{content}</span>"

            new_text = re.sub(r'<(span)([^>]*)>(.*?)<\/span>', clean_attributes, current_text, flags=re.DOTALL)

            if new_text != current_text:
                cursor = self.txt_entrada.textCursor()
                pos = cursor.position()
                self.txt_entrada.blockSignals(True)
                self.txt_entrada.setPlainText(new_text)
                self.txt_entrada.blockSignals(False)
                cursor.setPosition(pos)
                self.txt_entrada.setTextCursor(cursor)
        except Exception as e:
            logging.error(f"ERRO ao limpar ; em <span>: {str(e)}")

    def clean_non_breaking_spaces(self, text):
        if '\u00A0' in text:
            cleaned_text = text.replace('\u00A0', ' ')
            logging.debug(f"\u00A0 encontrado e substituído: {repr(text)} -> {repr(cleaned_text)}")
            return cleaned_text
        return text

    def _get_split_parts(self, line_text):
        active_delimiters = [
            chk.simbolo for chk in self.chk_delimitadores.values() if chk.isChecked()
        ]

        if active_delimiters:
            delimiter_pattern = "|".join(map(re.escape, active_delimiters))
            regex = f'(?:{delimiter_pattern})(?=(?:[^"]*"[^"]*")*[^"]*$)'
        else:
            regex = r';(?=(?:[^"]*"[^"]*")*[^"]*$)'
        
        return re.split(regex, line_text)

    def update_preview(self):
        cursor = self.txt_entrada.textCursor()
        self.current_line = cursor.blockNumber()
        
        linhas = self.txt_entrada.toPlainText().strip().split('\n')
        if not linhas or self.current_line >= len(linhas):
            preview_html = f"<html><body><p>{self._t('Nenhum conteúdo para exibir.')}</p></body></html>"
            self.preview_widget.setHtml(preview_html)
            self.last_preview_html = preview_html
            return

        linha = linhas[self.current_line].strip()
        if not linha:
            preview_html = f"<html><body><p>{self._t('Linha vazia.')}</p></body></html>"
            self.preview_widget.setHtml(preview_html)
            self.last_preview_html = preview_html
            return

        if not self.lista_notetypes.currentItem() or not self.lista_decks.currentItem():
            preview_html = f"<html><body><p>{self._t('Selecione um deck e um tipo de nota para visualizar.')}</p></body></html>"
            self.preview_widget.setHtml(preview_html)
            self.last_preview_html = preview_html
            return

        note = None
        try:
            model = mw.col.models.by_name(self.lista_notetypes.currentItem().text())
            deck_id = mw.col.decks.id_for_name(self.lista_decks.currentItem().text())
            note = mw.col.new_note(model)
            
            parts = self._get_split_parts(linha)
            
            if not self.field_mappings:
                for idx, field_content in enumerate(parts):
                    if idx < len(note.fields):
                        note.fields[idx] = field_content.strip()
            else:
                field_names = [f['name'] for f in model['flds']]
                for part_idx, field_content in enumerate(parts):
                    target_field_name = self.field_mappings.get(str(part_idx))
                    if target_field_name and target_field_name in field_names:
                        field_idx = field_names.index(target_field_name)
                        note.fields[field_idx] = field_content.strip()

            mw.col.add_note(note, deck_id)
            card = note.cards()[0]

            raw_front_html = card.render_output(True, False).question_text
            raw_back_html = get_pure_back_content(card)
            raw_css = note.model().get("css", "")

            processed_front = embed_media_in_html(raw_front_html, note)
            processed_back = embed_media_in_html(raw_back_html, note)
            processed_css = process_css_for_embedding(raw_css)

            tags_html = ""
            linhas_tags = self.txt_tags.toPlainText().strip().split('\n')
            if self.current_line < len(linhas_tags):
                tags_for_card = [tag.strip() for tag in linhas_tags[self.current_line].split(',') if tag.strip()]
                if tags_for_card:
                    tags_str = ', '.join(f"{tag}{self.current_line + 1}" if self.chk_num_tags.isChecked() else tag for tag in tags_for_card)
                    tags_html = f"<div class='tags-preview'><b>Tags:</b> {tags_str}</div>"

            final_html = f"""
            <html>
            <head>
                <meta charset='utf-8'>
                {mw.baseHTML()}
                <style>
                    body {{ background-color: #F0F0F0; font-family: sans-serif; margin: 10px; }}
                    .card-preview-wrapper {{
                        background-color: #FFF; box-shadow: 0 2px 5px rgba(0,0,0,0.1); 
                        border-radius: 5px; padding: 15px; overflow-x: auto;
                    }}
                    .front-title, .back-title {{
                        text-align: center; font-size: 1.1em; font-weight: bold;
                        margin: 10px 0 5px 0; color: #555;
                    }}
                    .separator {{ border-top: 2px solid #EEE; margin: 15px 0; }}
                    .tags-preview {{ margin-top: 15px; font-size: 0.9em; color: #333; }}
                    {processed_css}
                </style>
            </head>
            <body>
                <div class="front-title">{self._t("Frente")}</div>
                <div class="card-preview-wrapper card">{processed_front}</div>
                <div class="separator"></div>
                <div class="back-title">{self._t("Verso")}</div>
                <div class="card-preview-wrapper card">{processed_back}</div>
                {tags_html}
            </body>
            </html>
            """
            
            self.preview_widget.setHtml(final_html)
            self.last_preview_html = final_html

        except Exception as e:
            logging.error(f"Erro no update_preview: {str(e)}")
            error_html = f"<html><body><p style='color:red;'><b>{self._t('Erro na pré-visualização:')}</b><br>{html.escape(str(e))}</p></body></html>"
            self.preview_widget.setHtml(error_html)
            self.last_preview_html = error_html
        
        finally:
            if note and note.id:
                mw.col.remove_notes([note.id])

    def restore_last_preview(self):
        if hasattr(self, 'last_preview_html') and self.last_preview_html:
            self.preview_widget.setHtml(self.last_preview_html)

    def apply_text_color(self, color):
        cursor = self.txt_entrada.textCursor()
        if cursor.hasSelection():
            texto = cursor.selectedText()
            cursor.insertText(f'<span style="color:{color}">{texto}</span>')
        else:
            cursor.insertText(f'<span style="color:{color}"></span>')
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 7)
            self.txt_entrada.setTextCursor(cursor)
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def apply_background_color(self, color):
        cursor = self.txt_entrada.textCursor()
        if cursor.hasSelection():
            texto = cursor.selectedText()
            cursor.insertText(f'<span style="background-color:{color}">{texto}</span>')
        else:
            cursor.insertText(f'<span style="background-color:{color}"></span>')
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 7)
            self.txt_entrada.setTextCursor(cursor)
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def clear_all(self):
        reply = QMessageBox.question(self, self._t("Confirmação"), self._t("Tem certeza de que deseja limpar tudo? Isso não pode ser desfeito."), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.txt_entrada.clear()
            self.txt_tags.clear()
            self.search_input.clear()
            self.replace_input.clear()
            self.deck_name_input.clear()
            self.decks_search_input.clear()
            self.notetypes_search_input.clear()
            for chk in self.chk_delimitadores.values():
                chk.setChecked(False)
            self.chk_num_tags.setChecked(False)
            self.chk_repetir_tags.setChecked(False)
            self.cloze_2_count = 1
            self.zoom_factor = 1.0
            self.txt_entrada.zoomOut(int((self.zoom_factor - 1.0) * 10))
            self.initial_tags_set = False
            self.initial_numbering_set = False
            self.current_line = 0
            self.previous_text = ""
            self.last_edited_line = -1
            self.last_search_query = ""
            self.last_search_position = 0
            self.field_mappings.clear()
            self.field_images.clear()
            self.media_files.clear()
            self.update_field_mappings()
            self.update_preview()
            self.schedule_save()
            showInfo(self._t("Todos os campos e configurações foram limpos!"))

    def add_cards(self):
        if self.stacked_editor.currentIndex() == 1:
            self.switch_to_text_view()
            self.toggle_view_button.setText(self._t("📝 Editar em Grade"))

        deck_item = self.lista_decks.currentItem()
        notetype_item = self.lista_notetypes.currentItem()
        if not deck_item or not notetype_item:
            showWarning(self._t("Selecione um deck e um modelo!"))
            return
        
        linhas_texto = self.txt_entrada.toPlainText().strip()
        if not linhas_texto:
            showWarning(self._t("Digite algum conteúdo!"))
            return
        
        linhas = linhas_texto.split('\n')
        deck_name = deck_item.text()
        deck_id = mw.col.decks.id_for_name(deck_name)
        model = mw.col.models.by_name(notetype_item.text())
        
        contador = 0
        linhas_tags = self.txt_tags.toPlainText().strip().split('\n')

        mw.progress.start(label="Adicionando cards...", max=len(linhas))

        for i, linha in enumerate(linhas):
            mw.progress.update(value=i + 1)
            linha = linha.strip()
            if not linha:
                continue
            
            active_delimiters = [chk.simbolo for chk in self.chk_delimitadores.values() if chk.isChecked()]
            if not active_delimiters:
                active_delimiters = [';']
            
            if not any(d in linha for d in active_delimiters) and len(linha.split()) < 2:
                continue

            nota = mw.col.new_note(model)
            
            parts = self._get_split_parts(linha)
            
            if not self.field_mappings:
                for idx, field_content in enumerate(parts):
                    if idx < len(nota.fields):
                        nota.fields[idx] = field_content.strip()
            else:
                field_names = [f['name'] for f in model['flds']]
                for part_idx, field_content in enumerate(parts):
                    target_field_name = self.field_mappings.get(str(part_idx))
                    if target_field_name and target_field_name in field_names:
                        field_idx = field_names.index(target_field_name)
                        nota.fields[field_idx] = field_content.strip()
            
            if i < len(linhas_tags):
                tags_for_card = [tag.strip() for tag in linhas_tags[i].split(',') if tag.strip()]
                if tags_for_card:
                    if self.chk_num_tags.isChecked():
                        nota.tags.extend([f"{tag}{i + 1}" for tag in tags_for_card])
                    else:
                        nota.tags.extend(tags_for_card)
            
            try:
                mw.col.add_note(nota, deck_id)
                contador += 1
            except Exception as e:
                logging.error(f"Erro ao adicionar card da linha {i+1}: {str(e)}")

        mw.progress.finish()
        showInfo(self._t("{} cards adicionados com sucesso!").format(contador))
        mw.reset()

    def show_all_cards(self):
        def clean_tags(text):
            text = re.sub(r'(<img[^>]*)alt="[^"]*"([^>]*>)', r'\1\2', text)
            text = re.sub(r'style="([^"]*);([^"]*)"', r'style="\1 \2"', text)
            return text
        if not self.lista_decks.currentItem():
            showWarning(self._t("Selecione um deck primeiro!"))
            return
        deck_name = self.lista_decks.currentItem().text()
        deck_id = mw.col.decks.id_for_name(deck_name)
        if not deck_id:
            showWarning(self._t("Deck '{}' não encontrado!").format(deck_name))
            return
        note_ids = mw.col.find_notes(f"deck:\"{deck_name}\"")
        if not note_ids:
            showWarning(self._t("Nenhum card encontrado no deck '{}'!").format(deck_name))
            return
        current_text = self.txt_entrada.toPlainText()
        try:
            with open(self.pre_show_state_file, 'w', encoding='utf-8') as f:
                json.dump({'pre_show_text': current_text}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Erro ao salvar estado antes de 'Mostrar': {str(e)}")
            showWarning(self._t("Erro ao salvar estado antes de 'Mostrar': {}").format(str(e)))
        card_lines = []
        self.card_notetypes = []
        for nid in note_ids:
            note = mw.col.get_note(nid)
            note_model = mw.col.models.get(note.mid)
            note_type_name = note_model['name']
            self.card_notetypes.append(note_type_name)
            campos = [fld['name'] for fld in note_model['flds']]
            field_values = []
            for campo in campos:
                if campo in note:
                    field_value = html.unescape(note[campo])
                    field_value = re.sub(r'\[sound:([^\]]+)\]', r'<audio controls=""><source src="\1" type="audio/mpeg"></audio>', field_value)
                    field_value = clean_tags(field_value)
                    field_value = field_value.replace('\n', ' ').replace('\u00A0', ' ')
                    field_value = field_value.replace(' ', ' ')
                    field_value = re.sub(r'\s+', ' ', field_value).strip()
                    field_values.append(field_value)
                else:
                    field_values.append("")
            
            active_delimiter = next((chk.simbolo for chk in self.chk_delimitadores.values() if chk.isChecked()), ';')
            card_line = f" {active_delimiter} ".join(field_values)
            if any(c.isalpha() for c in card_line):
                card_lines.append(card_line)
        final_text = "\n".join(card_lines)
        final_text = final_text.replace(' ', ' ').replace('\u00A0', ' ')
        final_text = clean_tags(final_text)
        self.txt_entrada.blockSignals(True)
        self.txt_entrada.setPlainText(final_text)
        self.txt_entrada.blockSignals(False)
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_line_numbers()
        self.update_card_count()
        self.update_preview()
        self._save_in_real_time()

    def restore_pre_show_state(self):
        if os.path.exists(self.pre_show_state_file):
            try:
                with open(self.pre_show_state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    pre_show_text = data.get('pre_show_text', '')
                    self.txt_entrada.blockSignals(True)
                    self.txt_entrada.setPlainText(pre_show_text)
                    self.txt_entrada.blockSignals(False)
                    self.previous_text = pre_show_text
                    self.update_line_numbers()
                    self.update_card_count()
                    self.update_preview()
                    logging.debug("Estado anterior restaurado com sucesso.")
            except Exception as e:
                logging.error(f"Erro ao restaurar estado anterior: {str(e)}")
                showWarning(f"Erro ao restaurar estado anterior: {str(e)}")
        else:
            showWarning(self._t("Nenhum estado anterior salvo encontrado!"))

    def add_image(self):
        if self.stacked_editor.currentIndex() == 1:
            if not self.table_widget.currentItem():
                showWarning(self._t("Por favor, selecione uma célula na grade primeiro."))
                return

        arquivos, _ = QFileDialog.getOpenFileNames(self, self._t("Selecionar Mídia"), "", "Mídia (*.png *.jpg *.jpeg *.gif *.mp3 *.wav *.ogg *.mp4 *.webm)")
        if not arquivos:
            return

        media_dir = mw.col.media.dir()
        html_tags_to_add = []
        for caminho in arquivos:
            nome = os.path.basename(caminho)
            destino = os.path.join(media_dir, nome)
            if os.path.exists(destino):
                base, ext = os.path.splitext(nome)
                counter = 1
                while os.path.exists(destino):
                    nome = f"{base}_{counter}{ext}"
                    destino = os.path.join(media_dir, nome)
                    counter += 1
            shutil.copy2(caminho, destino)
            self.media_files.append(nome)
            
            ext = os.path.splitext(nome)[1].lower()
            if ext in ('.png', '.jpg', '.jpeg', '.gif'):
                html_tags_to_add.append(f'<img src="{nome}">')
            elif ext in ('.mp3', '.wav', '.ogg'):
                html_tags_to_add.append(f'[sound:{nome}]')
            elif ext in ('.mp4', '.webm'):
                html_tags_to_add.append(f'<video src="{nome}" controls></video>')

        if not html_tags_to_add:
            return

        tags_str = " ".join(html_tags_to_add)
        
        if self.stacked_editor.currentIndex() == 0:
            cursor = self.txt_entrada.textCursor()
            cursor.insertText(tags_str)
        else:
            item = self.table_widget.currentItem()
            current_text = item.text()
            new_text = f"{current_text} {tags_str}".strip()
            item.setText(new_text)
            self.switch_to_text_view()
            self.toggle_view_button.setText(self._t("📝 Editar em Grade"))

    def show_table_context_menu(self, pos):
        item = self.table_widget.itemAt(pos)
        if not item:
            return

        menu = QMenu()
        add_image_action = menu.addAction(self._t("🖼️ Adicionar Imagem/Mídia..."))
        add_image_action.triggered.connect(self.add_image)
        
        menu.exec(self.table_widget.mapToGlobal(pos))

    def drag_enter_event(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def drop_event(self, event):
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            file_paths = [url.toLocalFile() for url in mime_data.urls()]
            for file_path in file_paths:
                file_name = os.path.basename(file_path)
                media_dir = mw.col.media.dir()
                dest_path = os.path.join(media_dir, file_name)
                if os.path.exists(dest_path):
                    base, ext = os.path.splitext(file_name)
                    counter = 1
                    while os.path.exists(dest_path):
                        file_name = f"{base}_{counter}{ext}"
                        dest_path = os.path.join(media_dir, file_name)
                        counter += 1
                shutil.copy2(file_path, dest_path)
                self.media_files.append(file_name)
                ext = os.path.splitext(file_name)[1].lower()
                if ext in ('.png', '.jpg', '.jpeg', '.gif'):
                    html_tag = f'<img src="{file_name}">'
                elif ext in ('.mp3', '.wav', '.ogg'):
                    html_tag = f'<audio controls><source src="{file_name}"></audio>'
                elif ext in ('.mp4', '.webm'):
                    html_tag = f'<video src="{file_name}" controls width="320" height="240"></video>'
                else:
                    continue
                cursor = self.txt_entrada.textCursor()
                cursor.insertText(html_tag)
            self.update_line_numbers()
            self.previous_text = self.txt_entrada.toPlainText()
            self.update_preview()
            self.txt_entrada.setFocus()
            QApplication.processEvents()
        event.accept()

    def process_files(self, file_paths):
        media_folder = mw.col.media.dir()
        for file_path in file_paths:
            file_name = os.path.basename(file_path)
            new_path = os.path.join(media_folder, file_name)
            if os.path.exists(new_path):
                base_name, ext = os.path.splitext(file_name)
                counter = 1
                while os.path.exists(new_path):
                    file_name = f"{base_name}{counter}{ext}"
                    new_path = os.path.join(media_folder, file_name)
                    counter += 1
            shutil.copy(file_path, new_path)
            self.media_files.append(file_name)
            ext = file_name.lower()
            if ext.endswith(('.png', '.xpm', '.jpg', '.jpeg', '.bmp', '.gif')):
                self.txt_entrada.insertPlainText(f'<img src="{file_name}">\n')
            elif ext.endswith(('.mp3', '.wav', '.ogg')):
                self.txt_entrada.insertPlainText(f'<audio controls=""><source src="{file_name}" type="audio/mpeg"></audio>\n')
            elif ext.endswith(('.mp4', '.webm', '.avi', '.mkv', '.mov')):
                self.txt_entrada.insertPlainText(f'<video src="{file_name}" controls width="320" height="240"></video>\n')

    def show_context_menu(self, pos):
        menu = self.txt_entrada.createStandardContextMenu()
        paste_action = QAction(self._t("Colar HTML sem Tag e sem Formatação"), self)
        paste_action.triggered.connect(self.paste_html)
        menu.addAction(paste_action)
        paste_raw_action = QAction(self._t("Colar com Tags HTML"), self)
        paste_raw_action.triggered.connect(self.paste_raw_html)
        menu.addAction(paste_raw_action)
        paste_excel_action = QAction(self._t("Colar do Excel com Ponto e Vírgula"), self)
        paste_excel_action.triggered.connect(self.paste_excel)
        menu.addAction(paste_excel_action)
        paste_word_action = QAction(self._t("Colar do Word"), self)
        paste_word_action.triggered.connect(self.paste_word)
        menu.addAction(paste_word_action)
        menu.exec(self.txt_entrada.mapToGlobal(pos))

    def convert_markdown_to_html(self, text):
        lines = text.split('\n')
        table_html = ""
        in_table = False
        headers = []
        rows = []
        table_start_idx = -1
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            if line.startswith('|') and line.endswith('|') and '|' in line[1:-1]:
                cells = [cell.strip() for cell in line[1:-1].split('|')]
                if not in_table and i + 1 < len(lines) and re.match(r'^\|(?:\s*[-:]+(?:\s*\|)?)+$', lines[i + 1]):
                    in_table = True
                    table_start_idx = i
                    headers = cells
                    continue
                elif in_table:
                    rows.append(cells)
            elif in_table:
                if headers and rows:
                    table_html += "<table>\n<thead>\n<tr>"
                    for header in headers:
                        table_html += f"<th>{header}</th>"
                    table_html += "</tr>\n</thead>\n<tbody>\n"
                    for row in rows:
                        while len(row) < len(headers):
                            row.append("")
                        table_html += "<tr>"
                        for cell in row[:len(headers)]:
                            table_html += f"<td>{cell}</td>"
                        table_html += "</tr>\n"
                    table_html += "</tbody>\n</table>"
                in_table = False
                headers = []
                rows = []
        if in_table and headers and rows:
            table_html += "<table>\n<thead>\n<tr>"
            for header in headers:
                table_html += f"<th>{header}</th>"
            table_html += "</tr>\n</thead>\n<tbody>\n"
            for row in rows:
                while len(row) < len(headers):
                    row.append("")
                table_html += "<tr>"
                for cell in row[:len(headers)]:
                    table_html += f"<td>{cell}</td>"
                table_html += "</tr>\n"
            table_html += "</tbody>\n</table>"
        if table_html:
            new_lines = []
            in_table = False
            for i, line in enumerate(lines):
                if i == table_start_idx:
                    in_table = True
                    continue
                elif in_table and (line.strip().startswith('|') and line.strip().endswith('|') and '|' in line.strip()[1:-1] or re.match(r'^\|(?:\s*[-:]+(?:\s*\|)?)+$', line)):
                    continue
                else:
                    in_table = False
                    if line.strip():
                        new_lines.append(line.rstrip())
            remaining_text = '\n'.join(new_lines).rstrip()
            if remaining_text:
                text = remaining_text + '\n' + table_html.rstrip()
            else:
                text = table_html.rstrip()
        else:
            text = '\n'.join(line.rstrip() for line in lines if line.strip()).rstrip()
        return text

    def paste_html(self):
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        if mime_data.hasHtml():
            html_content = mime_data.html()
            cleaned_text = strip_html(html_content)
            cleaned_text = self.convert_markdown_to_html(cleaned_text)
            self.txt_entrada.insertPlainText(cleaned_text)
        elif mime_data.hasImage():
            image = clipboard.image()
            if not image.isNull():
                media_folder = mw.col.media.dir()
                base_name, ext, counter = "img", ".png", 1
                file_name = f"{base_name}{counter}{ext}"
                new_path = os.path.join(media_folder, file_name)
                while os.path.exists(new_path):
                    counter += 1
                    file_name = f"{base_name}{counter}{ext}"
                    new_path = os.path.join(media_folder, file_name)
                image.save(new_path)
                self.media_files.append(file_name)
                self.txt_entrada.insertPlainText(f'<img src="{file_name}">\n')
        elif mime_data.hasText():
            text = clipboard.text()
            text = self.convert_markdown_to_html(text)
            self.txt_entrada.insertPlainText(text)
        else:
            showWarning(self._t("Nenhuma imagem, texto ou HTML encontrado na área de transferência."))
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def paste_excel(self):
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        if mime_data.hasText():
            text = clipboard.text()
            lines = text.strip().split('\n')
            formatted_lines = []
            for line in lines:
                columns = line.split('\t')
                columns = [col.strip() for col in columns]
                formatted_line = ' ; '.join(columns)
                formatted_lines.append(formatted_line)
            formatted_text = '\n'.join(formatted_lines)
            self.txt_entrada.insertPlainText(formatted_text)
            self.previous_text = self.txt_entrada.toPlainText()
            self.update_preview()
        else:
            showWarning(self._t("Nenhum texto encontrado na área de transferência para colar como Excel."))

    def paste_word(self):
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        if mime_data.hasHtml():
            html_content = mime_data.html()
            fragment_match = re.search(r'<!--StartFragment-->(.*?)<!--EndFragment-->', html_content, re.DOTALL)
            if fragment_match:
                html_content = fragment_match.group(1)
            def clean_style_attr(match):
                style_content = match.group(1)
                style_content = re.sub(r'mso-highlight:([\w-]+)', r'background-color:\1', style_content, flags=re.IGNORECASE)
                cleaned_style = re.sub(r'mso-[^;:]*:[^;]*;?', '', style_content)
                cleaned_style = re.sub(r'background:([^;]*)', r'background-color:\1', cleaned_style)
                styles = cleaned_style.split(';')
                style_dict = {}
                for style in styles:
                    if style.strip():
                        key, value = style.split(':')
                        style_dict[key.strip()] = value.strip()
                cleaned_style = ', '.join(f'{key}:{value}' for key, value in style_dict.items() if key in ['color', 'background-color'])
                return f"style='{cleaned_style}'" if cleaned_style else ''
            html_content = re.sub(r"style=['\"]([^'\"]*)['\"]", clean_style_attr, html_content)
            def preserve_colored_spans(match):
                full_span = match.group(0)
                content = match.group(1)
                style = ''
                color_match = re.search(r'color:([#\w]+)', full_span, re.IGNORECASE)
                if color_match and color_match.group(1).lower() != '#000000':
                    style += f'color:{color_match.group(1)}'
                bg_match = re.search(r'background-color:([#\w]+)', full_span, re.IGNORECASE)
                if bg_match and bg_match.group(1).lower() != 'transparent':
                    if style:
                        style += ', '
                    style += f'background-color:{bg_match.group(1)}'
                if style:
                    return f'<span style="{style}">{content}</span>'
                return content
            previous_html = None
            while html_content != previous_html:
                previous_html = html_content
                html_content = re.sub(r'<span[^>]*>(.*?)</span>', preserve_colored_spans, html_content, flags=re.DOTALL)
            html_content = html_content.replace(';', ',')
            html_content = re.sub(r'\s+', ' ', html_content).strip()
            self.txt_entrada.insertPlainText(html_content)
            self.previous_text = self.txt_entrada.toPlainText()
            self.update_preview()
        elif mime_data.hasText():
            text = clipboard.text()
            lines = text.strip().split('\n')
            lines = [line.strip() for line in lines if line.strip()]
            formatted_text = ' '.join(lines)
            self.txt_entrada.insertPlainText(formatted_text)
            self.previous_text = self.txt_entrada.toPlainText()
            self.update_preview()
        else:
            showWarning(self._t("Nenhum texto encontrado na área de transferência para colar como Word."))

    def paste_raw_html(self):
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        if mime_data.hasHtml():
            html_content = mime_data.html()
            tags_to_remove = ['html', 'body', 'head', 'meta', 'link', 'script', 'style', 'title', 'doctype', '!DOCTYPE', 'br', 'hr', 'div', 'p', 'form', 'input', 'button', 'a']
            pattern = r'</?(?:' + '|'.join(tags_to_remove) + r')(?:\s+[^>])?>'
            cleaned_html = re.sub(pattern, '', html_content, flags=re.IGNORECASE)
            cleaned_html = self.convert_markdown_to_html(cleaned_html)
            def protect_structures(match):
                return match.group(0).replace('\n', ' PROTECTED_NEWLINE ')
            cleaned_html = re.sub(r'<ul>.?</ul>|<ol>.?</ol>|<li>.?</li>|<table>.?</table>', protect_structures, cleaned_html, flags=re.DOTALL)
            lines = cleaned_html.split('\n')
            cleaned_lines = [line.strip() for line in lines if line.strip()]
            cleaned_html = '\n'.join(cleaned_lines)
            cleaned_html = cleaned_html.replace(' PROTECTED_NEWLINE ', '\n')
            cleaned_html = re.sub(r'\s+(?![^<]>)', ' ', cleaned_html).strip()
            self.txt_entrada.insertPlainText(cleaned_html)
        elif mime_data.hasText():
            text = clipboard.text()
            text = self.convert_markdown_to_html(text)
            self.txt_entrada.insertPlainText(text)
        else:
            showWarning(self._t("Nenhum texto ou HTML encontrado na área de transferência."))
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def eventFilter(self, obj, event):
        if obj == self.txt_entrada:
            if event.type() == QEvent.Type.KeyPress and event.matches(QKeySequence.StandardKey.Paste):
                self.paste_html()
                return True
            elif event.type() == QEvent.Type.FocusOut:
                self.focus_out_event(event)
                return True
            elif event.type() == QEvent.Type.DragEnter:
                self.drag_enter_event(event)
                return True
            elif event.type() == QEvent.Type.Drop:
                self.drop_event(event)
                return True
        return super().eventFilter(obj, event)

    def criar_lista_rolavel(self, itens, altura_min=100):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(altura_min)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lista = QListWidget()
        lista.addItems(itens)
        scroll.setWidget(lista)
        return scroll, lista

    def toggle_group(self):
        novo_estado = not self.group_widget.isVisible()
        self.group_widget.setVisible(novo_estado)
        self.btn_toggle.setText(self._t("Ocultar Decks/Modelos/Delimitadores") if novo_estado else self._t("Mostrar Decks/Modelos/Delimitadores"))
        if hasattr(self, 'main_scroll') and self.main_scroll:
            QTimer.singleShot(100, lambda: self.main_scroll.ensureVisible(0, self.main_scroll.verticalScrollBar().maximum()))

    def ajustar_tamanho_scroll(self):
        self.scroll_decks.widget().adjustSize()
        self.scroll_notetypes.widget().adjustSize()
        self.scroll_decks.updateGeometry()
        self.scroll_notetypes.updateGeometry()

    def scan_media_files_from_text(self):
        patterns = [r'<img src="([^"]+)"', r'<source src="([^"]+)"', r'<video src="([^"]+)"']
        current_text = self.txt_entrada.toPlainText()
        media_dir = mw.col.media.dir()
        found_media = set()
        for pattern in patterns:
            matches = re.findall(pattern, current_text)
            for file_name in matches:
                file_path = os.path.join(media_dir, file_name)
                if os.path.exists(file_path) and file_name not in self.media_files:
                    found_media.add(file_name)
        self.media_files.extend(found_media)
        self.media_files = list(dict.fromkeys(self.media_files))

    def toggle_theme(self):
        self.is_dark_theme = not self.is_dark_theme
        if self.is_dark_theme:
            self.setStyleSheet("QWidget { background-color: #333; color: #eee; } QListWidget::item:selected { background-color: #4a90d9; color: #000000; } QTextEdit { background-color: #ffffff; color: #000000; border: 1px solid #555; selection-background-color: #4a90d9; selection-color: #ffffff; } QTextEdit:focus { background-color: #ffffff; color: #000000; } QLineEdit, QListWidget { background-color: #444; color: #fff; border: 1px solid #555; } QPushButton { background-color: #E0E0E0; color: #000000; border: 2px solid #B0B0B0; padding: 3px; font-size: 11px; min-height: 20px; min-width: 50px; border-radius: 5px; } QPushButton:hover { background-color: #B0B0B0; } QGroupBox { border: 1px solid #666; margin-top: 10px; padding-top: 15px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }")
            self.txt_entrada.line_number_area.setStyleSheet("background-color: #ffffff; color: #555;")
            self.theme_button.setText(self._t("Tema Claro"))
        else:
            self.setStyleSheet("QWidget { background-color: #ffffff; color: #000000; } QListWidget::item:selected { background-color: #4a90d9; color: #000000; } QListWidget { background-color: #ffffff; color: #000000; } QTextEdit { font-family: monospace; padding-top: 3px; padding-left: 5px; line-height: 1.5em; } QPushButton { background-color: #F5F5F5; color: #000000; border: 2px solid #E0E0E0; padding: 3px; font-size: 11px; min-height: 20px; min-width: 50px; border-radius: 5px; } QPushButton:hover { background-color: #E0E0E0; }")
            list_style = "QListWidget::item:selected { background-color: #4a90d9; color: #000000; } QListWidget::item { padding: 3px; }"
            self.lista_decks.setStyleSheet(list_style)
            self.lista_notetypes.setStyleSheet(list_style)
            self.txt_entrada.line_number_area.setStyleSheet("background-color: #ffffff; color: #555;")
            self.theme_button.setText(self._t("Tema Escuro"))
        button_style = "background-color: {bg_color}; color: #000000; border: 2px solid {border_color}; padding: 3px; font-size: 11px; min-height: 20px; min-width: 50px; border-radius: 5px;"
        button_hover_style = "QPushButton:hover {{ background-color: {hover_color}; }}"
        colors = {'dark': {'bg_color': '#E0E0E0', 'border_color': '#B0B0B0', 'hover_color': '#B0B0B0'}, 'light': {'bg_color': '#F5F5F5', 'border_color': '#E0E0E0', 'hover_color': '#E0E0E0'}}
        theme_colors = colors['dark'] if self.is_dark_theme else colors['light']
        full_button_style = f"QPushButton {{{button_style.format(**theme_colors)}}} {button_hover_style.format(**theme_colors)}"
        highlight_style = "QPushButton {background-color: #FFFF00; color: #000000; border: 2px solid #CCCC00; padding: 3px; font-size: 11px; min-height: 20px; min-width: 50px; border-radius: 5px;} QPushButton:hover {background-color: #CCCC00;}"
        for button in self.findChildren(QPushButton):
            if button.text() == self._t("Destaque"):
                button.setStyleSheet(highlight_style)
            elif isinstance(button, ForceLabelButton):
                if button.forced_text in ["+", "-"]:
                     button.setStyleSheet(full_button_style)
            elif button.text() in ["A", "Af"]:
                 pass
            else:
                button.setStyleSheet(full_button_style)
        self.highlight_current_line()
        self.update_preview()

    def copy_media_files(self, dest_folder):
        media_files = set()
        text = self.txt_entrada.toPlainText()
        for pattern in [r'src="([^"]+)"', r'<source src="([^"]+)"', r'<video src="([^"]+)"']:
            media_files.update(re.findall(pattern, text))
        media_dir = mw.col.media.dir()
        for file_name in media_files:
            src = os.path.join(media_dir, file_name)
            dst = os.path.join(dest_folder, file_name)
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)

    def export_to_html(self):
        try:
            html_content = generate_export_html(self, self._t)
            if not html_content:
                return
            desktop_path = os.path.join(os.path.expanduser("~/Desktop"), "delimit.html")
            with open(desktop_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            webbrowser.open(f"file://{os.path.abspath(desktop_path)}")
        except Exception as e:
            QMessageBox.critical(self, self._t("Erro na Exportação"), self._t("Ocorreu um erro durante a exportação: {}").format(str(e)))

    def update_tag_numbers(self):
        linhas_tags = self.txt_tags.toPlainText().strip().split('\n')
        num_linhas_cards = len(self.txt_entrada.toPlainText().strip().splitlines())
        if not any(linhas_tags) and num_linhas_cards > 0:
            self.txt_tags.setPlainText('\n'.join(f"{i + 1}" for i in range(num_linhas_cards)))
            self.initial_numbering_set = True
            self.update_preview()
            return
        if self.chk_num_tags.isChecked() and not self.initial_numbering_set:
            updated_tags = []
            for i in range(num_linhas_cards):
                if i < len(linhas_tags) and linhas_tags[i].strip():
                    tags_for_card = [tag.rstrip('0123456789') for tag in linhas_tags[i].split(',') if tag.strip()]
                    numbered_tags = [f"{tag}{i + 1}" for tag in tags_for_card]
                    updated_tags.append(", ".join(numbered_tags))
                else:
                    updated_tags.append("")
            self.txt_tags.setPlainText('\n'.join(updated_tags))
            self.initial_numbering_set = True
        elif not self.chk_num_tags.isChecked():
            updated_tags = []
            for i in range(num_linhas_cards):
                if i < len(linhas_tags) and linhas_tags[i].strip():
                    tags_for_card = [tag.rstrip('0123456789') for tag in linhas_tags[i].split(',') if tag.strip()]
                    updated_tags.append(", ".join(tags_for_card))
                else:
                    updated_tags.append("")
            self.txt_tags.setPlainText('\n'.join(updated_tags))
            self.initial_numbering_set = False
        self.update_preview()

    def update_repeated_tags(self):
        if self.chk_repetir_tags.isChecked() and not self.initial_tags_set:
            linhas_tags = self.txt_tags.toPlainText().strip().split('\n')
            num_cards = len(self.txt_entrada.toPlainText().strip().splitlines())
            if not any(linhas_tags):
                self.txt_tags.setPlainText('\n' * (num_cards - 1))
                self.initial_tags_set = True
                self.update_preview()
                return
            first_non_empty = next((tags for tags in linhas_tags if tags.strip()), None)
            if not first_non_empty:
                self.txt_tags.setPlainText('\n' * (num_cards - 1))
                self.initial_tags_set = True
                self.update_preview()
                return
            tags = list(dict.fromkeys([tag.strip() for tag in first_non_empty.split(',') if tag.strip()]))
            if not tags:
                self.txt_tags.setPlainText('\n' * (num_cards - 1))
                self.initial_tags_set = True
                self.update_preview()
                return
            self.txt_tags.setPlainText('\n'.join([", ".join(tags)] * num_cards))
            self.initial_tags_set = True
        elif not self.chk_repetir_tags.isChecked():
            self.initial_tags_set = False
            self.update_tag_numbers()
        self.update_preview()

    def search_text(self):
        search_query = self.search_input.text().strip()
        if not search_query:
            showWarning(self._t("Por favor, insira um texto para pesquisar."))
            return
        search_words = search_query.split()
        if search_query != self.last_search_query:
            self.last_search_query = search_query
            self.last_search_position = 0
        cursor = self.txt_entrada.textCursor()
        cursor.setPosition(self.last_search_position)
        self.txt_entrada.setTextCursor(cursor)
        found = False
        for word in search_words:
            if self.txt_entrada.find(word):
                self.last_search_position = self.txt_entrada.textCursor().position()
                found = True
                break
        if not found:
            self.txt_entrada.moveCursor(QTextCursor.MoveOperation.Start)
            for word in search_words:
                if self.txt_entrada.find(word):
                    self.last_search_position = self.txt_entrada.textCursor().position()
                    found = True
                    break
        if not found:
            showWarning(self._t("Texto '{}' não encontrado.").format(search_query))
        self.update_preview()

    def replace_text(self):
        search_query = self.search_input.text().strip()
        replace_text_str = self.replace_input.text()
        if not search_query:
            showWarning(self._t("Por favor, insira um texto para pesquisar."))
            return
        full_text = self.txt_entrada.toPlainText()
        replaced_text = re.sub(re.escape(search_query), replace_text_str, full_text, flags=re.IGNORECASE)
        self.txt_entrada.setPlainText(replaced_text)
        self.previous_text = replaced_text
        self.update_preview()
        if replace_text_str:
            showInfo(self._t("Todas as ocorrências de '{}' foram substituídas por '{}'.").format(search_query, replace_text_str))
        else:
            showInfo(self._t("Todas as ocorrências de '{}' foram removidas.").format(search_query))

    def zoom_in(self):
        self.txt_entrada.zoomIn(1)
        self.zoom_factor += 0.1

    def create_deck(self):
        deck_name = self.deck_name_input.text().strip()
        if not deck_name:
            showWarning(self._t("Por favor, insira um nome para o deck!"))
            return
        try:
            mw.col.decks.id(deck_name)
            self.lista_decks.clear()
            self.lista_decks.addItems([d.name for d in mw.col.decks.all_names_and_ids()])
            self.deck_name_input.clear()
            self.schedule_save()
        except Exception as e:
            showWarning(self._t("Erro ao criar o deck: {}").format(str(e)))

    def zoom_out(self):
        if self.zoom_factor > 0.2:
            self.txt_entrada.zoomOut(1)
            self.zoom_factor -= 0.1

    def filter_list(self, list_widget, search_input, full_list):
        search_text = search_input.text().strip().lower()
        filtered = [item for item in full_list if search_text in item.lower()]
        list_widget.clear()
        list_widget.addItems(filtered)
        if filtered and search_text:
            list_widget.setCurrentRow(0)

    def filter_decks(self):
        self.filter_list(self.lista_decks, self.decks_search_input, [d.name for d in mw.col.decks.all_names_and_ids()])

    def filter_notetypes(self):
        self.filter_list(self.lista_notetypes, self.notetypes_search_input, mw.col.models.all_names())

    def create_focus_handler(self, widget, field_type):
        def focus_in_event(event):
            self.txt_entrada.setStyleSheet("")
            self.txt_tags.setStyleSheet("")
            widget.setStyleSheet(f"border: 2px solid {'blue' if field_type == 'cards' else 'green'};")
            self.tags_label.setText(self._t("Etiquetas:") if field_type == "cards" else self._t("Etiquetas (Selecionado)"))
            if isinstance(widget, QTextEdit):
                QTextEdit.focusInEvent(widget, event)
        return focus_in_event

    def concatenate_text(self):
        clipboard = QApplication.clipboard()
        copied_text = clipboard.text().strip().split("\n")
        current_widget = self.txt_entrada if self.txt_entrada.styleSheet() else self.txt_tags if self.txt_tags.styleSheet() else self.txt_entrada
        current_text = current_widget.toPlainText().strip().split("\n")
        result_lines = [f"{current_text[i] if i < len(current_text) else ''}{copied_text[i] if i < len(copied_text) else ''}".strip() for i in range(max(len(current_text), len(copied_text)))]
        current_widget.setPlainText("\n".join(result_lines))
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def add_cloze_1(self):
        cursor = self.txt_entrada.textCursor()
        selected_text = cursor.selectedText().strip()
        if not selected_text:
            showWarning(self._t("Por favor, selecione uma palavra para adicionar o cloze."))
            return
        cursor.insertText(f"{{{{c1::{selected_text}}}}}")
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def add_cloze_2(self):
        cursor = self.txt_entrada.textCursor()
        selected_text = cursor.selectedText().strip()
        if not selected_text:
            showWarning(self._t("Por favor, selecione uma palavra para adicionar o cloze."))
            return
        cursor.insertText(f"{{{{c{self.cloze_2_count}::{selected_text}}}}}")
        self.cloze_2_count += 1
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def remove_cloze(self):
        self.txt_entrada.setPlainText(re.sub(r'{{c\d+::(.*?)}}', r'\1', self.txt_entrada.toPlainText()))
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def load_settings(self):
        logging.debug("Carregando configurações do arquivo")
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    dados = json.load(f)
                    self.current_language = dados.get('language', 'pt')
                    self.lang_combo.setCurrentIndex(1 if self.current_language == 'en' else 0)

                    conteudo = dados.get('conteudo', '')
                    logging.debug(f"Conteúdo carregado do CONFIG_FILE: '{conteudo}'")
                    self.real_text = conteudo
                    self.txt_entrada.setPlainText(conteudo)
                    self.previous_text = conteudo
                    self.txt_tags.setPlainText(dados.get('tags', ''))
                    for nome, estado in dados.get('delimitadores', {}).items():
                        if nome in self.chk_delimitadores:
                            self.chk_delimitadores[nome].setChecked(estado)
                    if 'window_geometry' in dados:
                        geo = dados['window_geometry']
                        self.resize(*geo.get('size', (1000, 600)))
                        self.move(*geo.get('pos', (100, 100)))
                        self.vertical_splitter.setSizes(geo.get('vertical_splitter', [300, 300]))
                        self.fields_splitter.setSizes(geo.get('fields_splitter', [700, 300]))
                    for key, lista in [('deck_selecionado', self.lista_decks), ('modelo_selecionado', self.lista_notetypes)]:
                        if dados.get(key):
                            items = lista.findItems(dados[key], Qt.MatchFlag.MatchExactly)
                            if items:
                                lista.setCurrentItem(items[0])
                    self.field_mappings = dados.get('field_mappings', {})
                    self.field_images = dados.get('field_images', {})
                    self.last_preview_html = dados.get('last_preview_html', '')
                    if self.last_preview_html:
                        self.preview_widget.setHtml(self.last_preview_html)
                    self.update_field_mappings()
                    self.update_line_numbers()
                    self.update_card_count()
                    logging.debug(f"Configurações carregadas: {dados}")
            except Exception as e:
                logging.error(f"Erro ao carregar configurações: {str(e)}")
                showWarning(self._t("Erro ao carregar configurações: {}").format(str(e)))
        else:
            logging.debug("Arquivo CONFIG_FILE não encontrado")
            self.real_text = ""
            self.last_preview_html = ""
            self.update_line_numbers()
            self.update_card_count()

    def join_lines(self):
        texto = self.txt_entrada.toPlainText()
        if '\n' not in texto:
            if hasattr(self, 'original_text'):
                self.txt_entrada.setPlainText(self.original_text)
                del self.original_text
        else:
            self.original_text = texto
            self.txt_entrada.setPlainText(texto.replace('\n', ' '))
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def wrap_selected_text(self, tag):
        cursor = self.txt_entrada.textCursor()
        if cursor.hasSelection():
            texto = cursor.selectedText()
            cursor.insertText(f"{tag[0]}{texto}{tag[1]}")
        else:
            cursor.insertText(f"{tag[0]}{tag[1]}")
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, len(tag[1]))
            self.txt_entrada.setTextCursor(cursor)
        self.previous_text = self.txt_entrada.toPlainText()
        self.update_preview()

    def apply_bold(self): self.wrap_selected_text(('<b>', '</b>'))
    def apply_italic(self): self.wrap_selected_text(('<i>', '</i>'))
    def apply_underline(self): self.wrap_selected_text(('<u>', '</u>'))
    def destaque_texto(self): self.wrap_selected_text(('<mark>', '</mark>'))

    def manage_media(self):
        if hasattr(self, 'media_dialog') and self.media_dialog:
            self.media_dialog.showNormal()
            self.media_dialog.raise_()
            self.media_dialog.activateWindow()
            return
        self.scan_media_files_from_text()
        if not self.media_files:
            showWarning(self._t("Nenhum arquivo de mídia foi adicionado ou referenciado no texto!"))
            return
        self.media_dialog = MediaManagerDialog(self, self.media_files, self.txt_entrada, mw, self._t)
        self.media_dialog.show()

    def show_dialog():
        global custom_dialog_instance
        if not hasattr(mw, 'custom_dialog_instance') or not mw.custom_dialog_instance:
            mw.custom_dialog_instance = CustomDialog(mw)
        if mw.custom_dialog_instance.isVisible():
            mw.custom_dialog_instance.raise_()
            mw.custom_dialog_instance.activateWindow()
        else:
            mw.custom_dialog_instance.show()

    def closeEvent(self, event):
        self._save_in_real_time()
        if hasattr(mw, 'delimitadores_dialog'):
            mw.delimitadores_dialog = None
        if hasattr(self, 'media_dialog') and self.media_dialog:
            self.media_dialog.close()
            self.media_dialog = None
        if hasattr(mw, 'custom_dialog_instance'):
            mw.custom_dialog_instance = None
        super().closeEvent(event)

    def view_cards_dialog(self):
        if self.visualizar_dialog is None or not self.visualizar_dialog.isVisible():
            self.visualizar_dialog = VisualizarCards(self, self._t)
            self.visualizar_dialog.show()
        else:
            self.visualizar_dialog.raise_()
            self.visualizar_dialog.activateWindow()

    def toggle_editor_view(self):
        if self.stacked_editor.currentIndex() == 0:
            self.switch_to_grid_view()
            self.toggle_view_button.setText(self._t("📄 Editar como Texto"))
        else:
            self.switch_to_text_view()
            self.toggle_view_button.setText(self._t("📝 Editar em Grade"))

    def switch_to_grid_view(self):
        text = self.txt_entrada.toPlainText()
        lines = text.split('\n')
        
        self.table_widget.setRowCount(0)
        self.table_widget.setColumnCount(0)

        if not text.strip():
            self.stacked_editor.setCurrentIndex(1)
            return

        max_cols = 0
        all_parts = []
        for line in lines:
            parts = self._get_split_parts(line)
            all_parts.append(parts)
            if len(parts) > max_cols:
                max_cols = len(parts)
        
        self.table_widget.setColumnCount(max_cols)
        self.table_widget.setRowCount(len(lines))

        self.table_widget.setHorizontalHeaderLabels([f"Campo {i+1}" for i in range(max_cols)])

        for row, parts in enumerate(all_parts):
            for col, part_text in enumerate(parts):
                item = QTableWidgetItem(part_text.strip())
                self.table_widget.setItem(row, col, item)
        
        self.table_widget.resizeColumnsToContents()
        self.stacked_editor.setCurrentIndex(1)

    def switch_to_text_view(self):
        active_delimiter = next((chk.simbolo for chk in self.chk_delimitadores.values() if chk.isChecked()), ';')
        
        lines = []
        for row in range(self.table_widget.rowCount()):
            row_data = []
            for col in range(self.table_widget.columnCount()):
                item = self.table_widget.item(row, col)
                row_data.append(item.text() if item else "")
            lines.append(active_delimiter.join(row_data))
        
        self.txt_entrada.setPlainText("\n".join(lines))
        self.stacked_editor.setCurrentIndex(0)

    def add_media_to_cell(self, item):
        arquivos, _ = QFileDialog.getOpenFileNames(self, self._t("Selecionar Mídia"), "", "Mídia (*.png *.jpg *.jpeg *.gif *.mp3 *.wav *.ogg *.mp4 *.webm)")
        if not arquivos:
            return

        media_dir = mw.col.media.dir()
        html_to_add = []

        for caminho in arquivos:
            nome = os.path.basename(caminho)
            destino = os.path.join(media_dir, nome)
            if os.path.exists(destino):
                base, ext = os.path.splitext(nome)
                counter = 1
                while os.path.exists(destino):
                    nome = f"{base}_{counter}{ext}"
                    destino = os.path.join(media_dir, nome)
                    counter += 1
            shutil.copy2(caminho, destino)
            
            ext = os.path.splitext(nome)[1].lower()
            if ext in ('.png', '.jpg', '.jpeg', '.gif'):
                html_to_add.append(f'<img src="{nome}">')
            elif ext in ('.mp3', '.wav', '.ogg'):
                html_to_add.append(f'[sound:{nome}]')
            else:
                continue
        
        current_text = item.text()
        new_text = current_text + " " + " ".join(html_to_add)
        item.setText(new_text.strip())
        
        self.switch_to_text_view()
        self.toggle_view_button.setText(self._t("📝 Editar em Grade"))
