# media_manager.py

import os
import re
from aqt.qt import *
from aqt.utils import showInfo, showWarning

try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    QT_MULTIMEDIA_AVAILABLE = True
except ImportError:
    QT_MULTIMEDIA_AVAILABLE = False

class MediaManagerDialog(QDialog):
    def __init__(self, parent, media_files, txt_entrada, mw_instance, translator):
        super().__init__(parent)
        self.media_files = media_files
        self.txt_entrada = txt_entrada
        self.mw = mw_instance
        self._t = translator # Armazena a função de tradução
        self.media_dir = self.mw.col.media.dir()
        self.undo_stack = []
        
        self.player = None
        self.audio_output = None
        
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle(self._t("Gerenciar Mídia (Ctrl+Z para desfazer)"))
        self.resize(600, 450)
        layout = QVBoxLayout()

        self.media_list = QListWidget()
        self.update_media_list()
        self.media_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.media_list)

        btn_layout = QHBoxLayout()
        
        delete_btn = QPushButton(self._t("Excluir"))
        delete_btn.clicked.connect(self.delete_file)
        btn_layout.addWidget(delete_btn)

        rename_btn = QPushButton(self._t("Renomear"))
        rename_btn.clicked.connect(self.rename_file)
        btn_layout.addWidget(rename_btn)

        preview_btn = QPushButton(self._t("Visualizar"))
        preview_btn.clicked.connect(self.preview_media)
        btn_layout.addWidget(preview_btn)

        undo_btn = QPushButton(self._t("Desfazer (Ctrl+Z)"))
        undo_btn.clicked.connect(self.undo_last_action)
        btn_layout.addWidget(undo_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self.undo_last_action)

    def update_media_list(self):
        self.media_list.clear()
        for idx, file_name in enumerate(self.media_files, 1):
            item = QListWidgetItem(f"{idx}-{file_name}")
            self.media_list.addItem(item)

    def delete_file(self):
        selected_row = self.media_list.currentRow()
        if selected_row < 0:
            showWarning(self._t("Selecione um arquivo para excluir!"))
            return

        file_name = self.media_files[selected_row]
        file_path = os.path.join(self.media_dir, file_name)
        
        if os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                file_content = f.read()
            self.undo_stack.append(('delete', file_name, selected_row, file_content))
            
            try:
                os.remove(file_path)
                self.media_files.pop(selected_row)
                self.update_media_list()
                
                current_text = self.txt_entrada.toPlainText()
                updated_text = re.sub(rf'<[^>]*src=["\']{re.escape(file_name)}["\'][^>]*>', '', current_text)
                self.txt_entrada.setPlainText(updated_text)
                
                showInfo(self._t("Arquivo '{}' excluído!").format(file_name))
            except Exception as e:
                showWarning(self._t("Erro ao excluir: {}").format(str(e)))
        else:
            showWarning(self._t("Arquivo '{}' não encontrado!").format(file_name))

    def rename_file(self):
        selected_row = self.media_list.currentRow()
        if selected_row < 0:
            showWarning(self._t("Selecione um arquivo para renomear!"))
            return

        old_name = self.media_files[selected_row]
        new_name, ok = QInputDialog.getText(self, self._t("Renomear"), self._t("Novo nome:"), text=old_name)
        
        if not ok or not new_name or new_name == old_name:
            return

        if new_name in self.media_files:
            showWarning(self._t("O nome '{}' já existe!").format(new_name))
            return

        old_path = os.path.join(self.media_dir, old_name)
        new_path = os.path.join(self.media_dir, new_name)
        
        if os.path.exists(old_path):
            self.undo_stack.append(('rename', old_name, new_name, selected_row))
            
            try:
                os.rename(old_path, new_path)
                self.media_files[selected_row] = new_name
                self.update_media_list()
                
                current_text = self.txt_entrada.toPlainText()
                updated_text = current_text.replace(old_name, new_name)
                self.txt_entrada.setPlainText(updated_text)
                
                showInfo(self._t("Renomeado para '{}'!").format(new_name))
            except Exception as e:
                showWarning(self._t("Erro ao renomear: {}").format(str(e)))
        else:
            showWarning(self._t("Arquivo '{}' não encontrado!").format(old_name))

    def undo_last_action(self):
        if not self.undo_stack:
            showInfo(self._t("Nada para desfazer!"))
            return

        action = self.undo_stack.pop()
        
        if action[0] == 'delete':
            _, file_name, position, file_content = action
            file_path = os.path.join(self.media_dir, file_name)
            
            try:
                with open(file_path, 'wb') as f:
                    f.write(file_content)
                
                self.media_files.insert(position, file_name)
                self.update_media_list()
                self.media_list.setCurrentRow(position)
                
                showInfo(self._t("Arquivo '{}' restaurado!").format(file_name))
            except Exception as e:
                showWarning(self._t("Erro ao desfazer: {}").format(str(e)))
                
        elif action[0] == 'rename':
            _, old_name, new_name, position = action
            old_path = os.path.join(self.media_dir, old_name)
            new_path = os.path.join(self.media_dir, new_name)
            
            try:
                os.rename(new_path, old_path)
                self.media_files[position] = old_name
                self.update_media_list()
                self.media_list.setCurrentRow(position)
                
                current_text = self.txt_entrada.toPlainText()
                updated_text = current_text.replace(new_name, old_name)
                self.txt_entrada.setPlainText(updated_text)
                
                showInfo(self._t("Renomeação revertida!"))
            except Exception as e:
                showWarning(self._t("Erro ao desfazer: {}").format(str(e)))

    def preview_media(self):
        selected_row = self.media_list.currentRow()
        if selected_row < 0:
            showWarning(self._t("Selecione um arquivo para visualizar!"))
            return

        file_name = self.media_files[selected_row]
        file_path = os.path.join(self.media_dir, file_name)
        
        if not os.path.exists(file_path):
            showWarning(self._t("Arquivo '{}' não encontrado!").format(file_name))
            return

        ext = os.path.splitext(file_name)[1].lower()
        
        if ext in ('.png', '.jpg', '.jpeg', '.gif'):
            self.preview_image(file_path, file_name)
        elif ext in ('.mp3', '.wav', '.ogg', '.mp4', '.webm'):
            self.preview_media_player(file_path, file_name)
        else:
            showWarning(self._t("Tipo de arquivo não suportado: {}").format(ext))

    def preview_image(self, file_path, file_name):
        dialog = QDialog(self)
        dialog.setWindowTitle(self._t("Visualizando: {}").format(file_name))
        layout = QVBoxLayout()

        label = QLabel()
        pixmap = QPixmap(file_path)
        
        if pixmap.isNull():
            showWarning(self._t("Não foi possível carregar a imagem!"))
            return

        label.setPixmap(pixmap.scaled(600, 400, Qt.AspectRatioMode.KeepAspectRatio))
        layout.addWidget(label)

        dialog.setLayout(layout)
        dialog.exec()

    def preview_media_player(self, file_path, file_name):
        if not QT_MULTIMEDIA_AVAILABLE:
            showWarning(self._t("Recursos de multimídia (PyQt6.QtMultimedia) não estão instalados."))
            return

        if self.player is None:
            self.player = QMediaPlayer()
            self.audio_output = QAudioOutput()
            self.player.setAudioOutput(self.audio_output)

        dialog = QDialog(self)
        dialog.setWindowTitle(self._t("Visualizando: {}").format(file_name))
        dialog.resize(400, 100)
        layout = QVBoxLayout()

        if os.path.splitext(file_name)[1].lower() in ('.mp4', '.webm'):
            dialog.resize(400, 300)
            video_widget = QVideoWidget()
            self.player.setVideoOutput(video_widget)
            layout.addWidget(video_widget)

        controls = QHBoxLayout()
        play_btn = QPushButton(self._t("Tocar"))
        play_btn.clicked.connect(self.player.play)
        controls.addWidget(play_btn)

        pause_btn = QPushButton(self._t("Pausar"))
        pause_btn.clicked.connect(self.player.pause)
        controls.addWidget(pause_btn)

        layout.addLayout(controls)
        dialog.setLayout(layout)

        self.player.setSource(QUrl.fromLocalFile(file_path))
        
        dialog.finished.connect(self.player.stop)
        
        dialog.exec()

        self.player.setVideoOutput(None)

    def closeEvent(self, event):
        if self.player:
            self.player.stop()
        
        if hasattr(self.parent(), 'media_dialog'):
            self.parent().media_dialog = None
        super().closeEvent(event)