# exporthtml.py

import os
import re
import base64
from aqt import mw
from aqt.utils import showWarning

# --- FUNÇÕES AUXILIARES DO EXEMPLO FORNECIDO ---
# Estas funções foram copiadas e adaptadas do seu código de referência.

def make_ids_unique(html_content, css_content, card_id):
    """Adiciona um sufixo único a todos os IDs no HTML e CSS para evitar conflitos."""
    suffix = f"_{card_id}"
    ids_to_replace = set(re.findall(r'id\s*=\s*["\']([^"\']+)["\']', html_content))
    for original_id in ids_to_replace:
        new_id = f"{original_id}{suffix}"
        html_content = re.sub(f'id\\s*=\\s*(["\']){re.escape(original_id)}\\1', f'id="{new_id}"', html_content)
        html_content = re.sub(f'getElementById\\s*\\(\\s*(["\']){re.escape(original_id)}\\1\\s*\\)', f'getElementById("{new_id}")', html_content)
        css_content = re.sub(f'#{re.escape(original_id)}(?![-_a_zA-Z0-9])', f'#{new_id}', css_content)
    return html_content, css_content

def media_to_data_url(filename):
    """Converte um nome de arquivo de mídia em uma URL de dados Base64."""
    media_dir = mw.col.media.dir()
    if not media_dir or not filename: return None
    if filename.startswith(('data:', 'http')): return filename
    
    filename = filename.strip('\'"')
    file_path = os.path.join(media_dir, filename)
    if not os.path.exists(file_path): return None
    
    ext = os.path.splitext(filename)[1].lower()
    mime_type = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
        '.gif': 'image/gif', '.svg': 'image/svg+xml', '.mp3': 'audio/mpeg',
        '.wav': 'audio/wav', '.ogg': 'audio/ogg', '.mp4': 'video/mp4',
        '.webm': 'video/webm'
    }.get(ext, 'application/octet-stream')
    
    try:
        with open(file_path, 'rb') as f:
            data = base64.b64encode(f.read()).decode('utf-8')
        return f"data:{mime_type};base64,{data}"
    except Exception:
        return None

def embed_media_in_html(html_content, note):
    """Encontra referências de mídia no HTML e as converte para Base64."""
    def img_replacer(match):
        filename = match.group(1)
        data_url = media_to_data_url(filename)
        return f'<img src="{data_url}"' if data_url else match.group(0)
    html_content = re.sub(r'<img src=[\'"]([^"\']+)[\'"]', img_replacer, html_content)
    
    audio_files = []
    for field in note.values():
        audio_files.extend(re.findall(r'\[sound:(.*?)\]', field))
    if not audio_files: return html_content
    
    def audio_replacer(match):
        idx = int(match.group(1))
        if idx < len(audio_files):
            filename = audio_files[idx]
            data_url = media_to_data_url(filename)
            if data_url:
                return f'<audio controls src="{data_url}" style="max-width: 100%; height: 30px;"></audio>'
        return ""
    play_tag_regex = r'\[anki:play:(?:q|a):(\d+)\]'
    html_content = re.sub(play_tag_regex, audio_replacer, html_content)
    return html_content

def process_css_for_embedding(css_text):
    """Encontra referências de URL no CSS e as converte para Base64."""
    if not css_text: return ""
    css_text = re.sub(r'@import url\(.*?\);', '', css_text)
    def url_replacer(match):
        filename = match.group(1).strip().strip('\'"')
        if filename.startswith(('http', 'data:')): return match.group(0)
        data_url = media_to_data_url(filename)
        return f'url("{data_url}")' if data_url else 'url("")'
    return re.sub(r'url\(([^)]+)\)', url_replacer, css_text, flags=re.IGNORECASE)

def get_pure_back_content(card):
    """Extrai apenas o conteúdo do verso do card, de forma inteligente."""
    answer_html = card.render_output(True, False).answer_text
    parts = re.split(r'<hr id=[\'"]?answer[\'"]?>', answer_html, maxsplit=1)
    if len(parts) > 1:
        return parts[1]
    landmarks = ["TRADUÇÃO"] 
    cut_position = -1
    for mark in landmarks:
        match = re.search(mark, answer_html, re.IGNORECASE)
        if match:
            start_pos = answer_html.rfind('<', 0, match.start())
            if start_pos != -1:
                cut_position = start_pos
                break
    if cut_position != -1:
        return answer_html[cut_position:]
    return answer_html

def get_common_css(cards_per_row):
    """Retorna o CSS comum para o layout da grade e controle de altura."""
    return f"""
    <style>
    * {{ box-sizing: border-box; }}
    body {{ background-color: #F0F0F0; font-family: sans-serif; margin: 15px; }}
    h1 {{ margin-bottom: 15px; }}
    .card-container {{ display: grid; grid-template-columns: repeat({cards_per_row}, 1fr); gap: 15px; }}
    .card-item {{ background-color: #FFF; box-shadow: 0 2px 5px rgba(0,0,0,0.1); border-radius: 5px; overflow: hidden; display: flex; flex-direction: column; }}
    .card-content-wrapper {{ 
        padding: 15px; 
        width: 100%; 
        flex-grow: 1; 
        display: flex; 
        flex-direction: column;
        max-height: 70vh; /* CONTROLA A ALTURA MÁXIMA DO CARD */
        overflow-y: auto; /* ADICIONA SCROLL SE O CONTEÚDO FOR MAIOR */
    }}
    .card-content-wrapper img {{ max-width: 100%; height: auto; display: block; margin: auto; }}
    .card {{ flex-grow: 1; display: flex; flex-direction: column; background-size: cover; background-position: center; }}
    .front-title, .back-title {{ text-align: center; font-size: 1.1em; font-weight: bold; margin: 10px 0 5px 0; color: #555; }}
    .separator {{ border-top: 2px solid #EEE; margin: 15px 0; }}
    @media print {{
        @page {{ size: A4; margin: 1cm; }}
        body {{ background-color: #FFF !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; margin: 0; }}
        h1, .front-title, .back-title, .separator {{ display: none; }}
        .card-container {{ grid-template-columns: repeat({cards_per_row}, 1fr); gap: 10px; }}
        .card-item {{ box-shadow: none; border: 1px solid #DDD; page-break-inside: avoid !important; height: auto !important; max-height: none; overflow: visible; }}
        .card-content-wrapper {{ max-height: none; overflow: visible; padding: 5px; }}
        audio {{ display: none !important; }}
        .card {{ display: block; height: auto !important; }}
    }}
    </style>
    """

def get_js_equalizers():
    """Retorna o script JS para igualar a altura dos cards."""
    return """
    <script>
        function equalizeCardHeights() {
            if (window.matchMedia('print').matches) return; // Não executa na impressão
            const cards = document.querySelectorAll('.card-item');
            if (cards.length === 0) return;
            let maxHeight = 0;
            cards.forEach(card => { card.style.height = 'auto'; });
            setTimeout(() => {
                cards.forEach(card => { if (card.offsetHeight > maxHeight) maxHeight = card.offsetHeight; });
                if (maxHeight > 0) { cards.forEach(card => { card.style.height = `${maxHeight}px`; }); }
            }, 200);
        }
        window.addEventListener('load', equalizeCardHeights);
        window.addEventListener('resize', equalizeCardHeights);
    </script>
    """

# --- FUNÇÃO PRINCIPAL DE EXPORTAÇÃO ---

def generate_export_html(self, translator):
    _t = translator

    if not self.lista_notetypes.currentItem():
        showWarning(_t("Por favor, selecione um Tipo de Nota para exportar."))
        return None
    
    cards_text_lines = self.txt_entrada.toPlainText().strip().split('\n')
    if not any(cards_text_lines):
        showWarning(_t("Não há conteúdo para exportar."))
        return None

    model = mw.col.models.by_name(self.lista_notetypes.currentItem().text())
    deck_id = mw.col.decks.current()['id']
    cards_per_row = 3
    
    buf = []
    buf.append(f"<html><head><meta charset='utf-8'>{mw.baseHTML()}{get_common_css(cards_per_row)}</head><body>")
    buf.append(f'<h1>{_t("Cards Exportados")}</h1><div class="card-container">')
    
    mw.progress.start(label=_t("Renderizando e processando cards..."), max=len(cards_text_lines))
    
    for i, line in enumerate(cards_text_lines):
        mw.progress.update(value=i)
        if not line.strip():
            continue

        note = None
        try:
            note = mw.col.new_note(model)
            parts = re.split(r';(?=(?:[^"]*"[^"]*")*[^"]*$)', line)
            for idx, field_content in enumerate(parts):
                if idx < len(note.fields):
                    note.fields[idx] = field_content.strip()
            
            mw.col.add_note(note, deck_id)
            card = note.cards()[0]
            
            raw_front_html = card.render_output(True, False).question_text
            raw_back_html = get_pure_back_content(card)
            raw_css = note.model().get("css", "")
            
            combined_html = (
                f'<div class="front-content"><div class="front-title">{_t("Frente")}</div>{raw_front_html}</div>'
                '<div class="separator"></div>'
                f'<div class="back-content"><div class="back-title">{_t("Verso")}</div>{raw_back_html}</div>'
            )
            
            unique_html, unique_css = make_ids_unique(combined_html, raw_css, card.id)
            processed_css = process_css_for_embedding(unique_css)
            processed_html = embed_media_in_html(unique_html, note)
            
            buf.append(
                f'<div class="card-item">'
                f'<style>{processed_css}</style>'
                f'<div class="card-content-wrapper">'
                f'<div class="card">{processed_html}</div>'
                '</div></div>'
            )
        finally:
            if note and note.id:
                mw.col.remove_notes([note.id])

    mw.progress.finish()
    
    buf.append("</div>")
    buf.append(get_js_equalizers())
    buf.append("</body></html>")
    
    return "".join(buf)