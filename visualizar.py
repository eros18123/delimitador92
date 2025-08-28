# visualizar.py

import os
import re
import base64
import html
from aqt import mw
from aqt.qt import *
from aqt.utils import showWarning, showInfo
from aqt.webview import QWebEngineView
from .exporthtml import embed_media_in_html, process_css_for_embedding, get_pure_back_content

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

class VisualizarCards(QDialog):
    def __init__(self, parent, translator):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowMaximizeButtonHint)
        self.parent = parent
        self._t = translator  # Armazena a função de tradução
        self.cards_preview_list = []
        self.cards_visible = True
        self.setup_ui()
        self.view_cards_dialog()

    def setup_ui(self):
        self.setWindowTitle(self._t("Visualizar Todos os Cards"))
        self.resize(800, 600)
        
        main_layout = QVBoxLayout()
        
        top_controls_layout = QHBoxLayout()
        self.toggle_cards_button = QPushButton(self._t("Ocultar Lista"), self)
        self.toggle_cards_button.clicked.connect(self.toggle_cards_visibility)
        top_controls_layout.addWidget(self.toggle_cards_button)
        top_controls_layout.addStretch()
        
        zoom_in_button = ForceLabelButton("+", parent=self)
        zoom_in_button.setFixedSize(30, 30)
        zoom_in_button.setToolTip(self._t("Aumentar Zoom"))
        zoom_in_button.clicked.connect(self.zoom_in)
        top_controls_layout.addWidget(zoom_in_button)
        
        zoom_out_button = ForceLabelButton("-", parent=self)
        zoom_out_button.setFixedSize(30, 30)
        zoom_out_button.setToolTip(self._t("Diminuir Zoom"))
        zoom_out_button.clicked.connect(self.zoom_out)
        top_controls_layout.addWidget(zoom_out_button)
        
        main_layout.addLayout(top_controls_layout)
        
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        self.card_list_widget = QListWidget()
        self.card_list_widget.currentItemChanged.connect(self.update_card_preview)
        self.card_list_widget.setMaximumWidth(200)
        self.card_list_widget.setMinimumWidth(100)
        self.splitter.addWidget(self.card_list_widget)
        
        self.card_preview_webview = QWebEngineView()
        settings = self.card_preview_webview.settings()
        for attr in [QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, 
                     QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, 
                     QWebEngineSettings.WebAttribute.AllowRunningInsecureContent]:
            settings.setAttribute(attr, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        self.card_preview_webview.setMinimumWidth(300)
        self.splitter.addWidget(self.card_preview_webview)
        
        self.splitter.setSizes([200, 600])
        main_layout.addWidget(self.splitter)
        self.setLayout(main_layout)

    def zoom_in(self):
        self.card_preview_webview.setZoomFactor(self.card_preview_webview.zoomFactor() + 0.1)

    def zoom_out(self):
        self.card_preview_webview.setZoomFactor(max(0.1, self.card_preview_webview.zoomFactor() - 0.1))

    def generate_card_previews(self):
        cards_preview_list = []
        
        linhas = self.parent.txt_entrada.toPlainText().strip().split('\n')
        if not self.parent.lista_notetypes.currentItem() or not self.parent.lista_decks.currentItem():
            return []
            
        model = mw.col.models.by_name(self.parent.lista_notetypes.currentItem().text())
        deck_id = mw.col.decks.id_for_name(self.parent.lista_decks.currentItem().text())
        field_mappings = self.parent.field_mappings

        mw.progress.start(label=self._t("Renderizando pré-visualização dos cards..."), max=len(linhas))

        for i, linha in enumerate(linhas):
            mw.progress.update(value=i + 1)
            linha = linha.strip()
            if not linha or ";" not in linha or not any(c.isalpha() for c in linha):
                continue
            
            note = None
            try:
                note = mw.col.new_note(model)
                parts = re.split(r';(?=(?:[^"]*"[^"]*")*[^"]*$)', linha)
                
                if not field_mappings:
                    for idx, field_content in enumerate(parts):
                        if idx < len(note.fields):
                            note.fields[idx] = field_content.strip()
                else:
                    field_names = [f['name'] for f in model['flds']]
                    for part_idx, field_content in enumerate(parts):
                        target_field_name = field_mappings.get(str(part_idx))
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

                final_html = f"""
                <html>
                <head>
                    <meta charset='utf-8'>
                    {mw.baseHTML()}
                    <style>
                        body {{ 
                            background-color: #F0F0F0; 
                            font-family: sans-serif; 
                            margin: 10px;
                            overflow: hidden; 
                        }}
                        .preview-scaler {{
                            transform: scale(0.55); 
                            transform-origin: top left;
                            width: 181.81%;
                            height: 181.81%;
                        }}
                        .card-preview-wrapper {{
                            background-color: #FFF; 
                            box-shadow: 0 2px 5px rgba(0,0,0,0.1); 
                            border-radius: 5px; 
                            padding: 15px; 
                            overflow-x: auto;
                        }}
                        .separator {{ border-top: 2px solid #EEE; margin: 15px 0; }}
                        {processed_css}
                    </style>
                </head>
                <body>
                    <div class="preview-scaler">
                        <div class="card-preview-wrapper card">{processed_front}</div>
                        <div class="separator"></div>
                        <div class="card-preview-wrapper card">{processed_back}</div>
                    </div>
                </body>
                </html>
                """
                cards_preview_list.append(final_html)

            except Exception as e:
                error_html = f"<html><body>{self._t('Erro ao renderizar card {}:<br><pre>{}</pre>').format(i+1, html.escape(str(e)))}</body></html>"
                cards_preview_list.append(error_html)
            
            finally:
                if note and note.id:
                    mw.col.remove_notes([note.id])
        
        mw.progress.finish()
        return cards_preview_list

    def view_cards_dialog(self):
        if not self.parent.txt_entrada.toPlainText().strip():
            showWarning(self._t("Digite conteúdo para visualizar!"))
            self.close()
            return
        if not self.parent.lista_notetypes.currentItem():
            showWarning(self._t("Selecione um tipo de nota para visualizar!"))
            self.close()
            return
            
        self.cards_preview_list = self.generate_card_previews()
        
        if not self.cards_preview_list:
            showWarning(self._t("Nenhum card válido para visualizar!"))
            self.close()
            return
            
        self.card_list_widget.clear()
        self.card_list_widget.addItems([f"Card {i+1}" for i in range(len(self.cards_preview_list))])
        if self.cards_preview_list:
            self.card_list_widget.setCurrentRow(0)

    def update_card_preview(self, current, previous):
        if current:
            index = self.card_list_widget.row(current)
            if 0 <= index < len(self.cards_preview_list):
                self.card_preview_webview.setHtml(self.cards_preview_list[index])
        else:
            self.card_preview_webview.setHtml("")

    def toggle_cards_visibility(self):
        self.cards_visible = not self.cards_visible
        self.toggle_cards_button.setText(self._t("Mostrar Lista") if not self.cards_visible else self._t("Ocultar Lista"))
        self.card_list_widget.setVisible(self.cards_visible)