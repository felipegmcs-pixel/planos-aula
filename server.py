import os
import io
import json
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, send_file, jsonify
from anthropic import Anthropic
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

app = Flask(__name__)
client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# ─── Banco de dados ───────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect('historico.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT,
            professor TEXT,
            escola TEXT,
            disciplina TEXT,
            turma TEXT,
            num_aulas INTEGER,
            periodo TEXT,
            datas TEXT,
            temas TEXT,
            arquivo BLOB,
            nome_arquivo TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ─── PDF ──────────────────────────────────────────────────────────────────────

def extrair_pdf(url):
    try:
        import pdfplumber
        import urllib.request
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
            urllib.request.urlretrieve(url, tmp.name)
            with pdfplumber.open(tmp.name) as pdf:
                texto = ''
                for page in pdf.pages[:10]:
                    t = page.extract_text()
                    if t:
                        texto += t + '\n'
            os.unlink(tmp.name)
        return texto[:3000]
    except Exception:
        return None

# ─── IA ───────────────────────────────────────────────────────────────────────

def gerar_conteudo_ia(disciplina, turma, temas, periodo, datas, aula_inicio=1, conteudo_pdf=None):
    referencia_pdf = ""
    if conteudo_pdf:
        referencia_pdf = f"\n\nMATERIAL DE REFERÊNCIA:\n{conteudo_pdf}\n\nUse esse material como base para os conteúdos e objetivos."

    prompt = f"""Você é um assistente especializado em educação brasileira.
Gere o conteúdo para um plano de aula seguindo EXATAMENTE este formato JSON.

Dados:
- Disciplina: {disciplina}
- Turma: {turma}
- Período: {periodo}
- Datas: {datas}
- Temas das aulas: {temas}
- Numeração começa na aula: {aula_inicio}{referencia_pdf}

Retorne SOMENTE um JSON válido neste formato (sem markdown, sem explicações):
{{
  "aulas": [
    {{
      "numero": {aula_inicio},
      "titulo": "Aula {aula_inicio} - [título baseado no tema]",
      "conteudos": ["conteúdo 1", "conteúdo 2", "conteúdo 3"],
      "objetivos": ["objetivo 1", "objetivo 2", "objetivo 3"],
      "estrategias": "Descrição das estratégias didáticas da aula em 2-3 frases.",
      "recursos": "Kit Multimídia, quadro branco, [outros recursos relevantes]",
      "avaliacao": "Observar participação e desempenho dos alunos. [avaliação específica]"
    }}
  ]
}}

Gere {len(temas)} aulas, uma para cada tema. A primeira aula é número {aula_inicio}. Seja específico e pedagógico."""

    resposta = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    texto = resposta.content[0].text.strip()
    if texto.startswith("```"):
        texto = texto.split("```")[1]
        if texto.startswith("json"):
            texto = texto[4:]
    texto = texto.strip()
    return json.loads(texto)

# ─── DOCX ─────────────────────────────────────────────────────────────────────

def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def set_cell_border(cell, color='c0c8e8'):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement('w:tcBorders')
    for edge in ('top', 'left', 'bottom', 'right'):
        element = OxmlElement(f'w:{edge}')
        element.set(qn('w:val'), 'single')
        element.set(qn('w:sz'), '4')
        element.set(qn('w:color'), color)
        tcBorders.append(element)
    tcPr.append(tcBorders)

def set_cell_bg(cell, color):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), color)
    tcPr.append(shd)

def add_run(paragraph, text, bold=False, size=9, color='1a1a2e', italic=False):
    run = paragraph.add_run(text)
    run.bold = bold
    run.italic = italic
    run.font.size = Pt(size)
    run.font.name = 'Calibri'
    r, g, b = hex_to_rgb(color)
    run.font.color.rgb = RGBColor(r, g, b)
    return run

def criar_docx(dados_form, aulas_ia):
    doc = Document()

    for section in doc.sections:
        section.top_margin = Cm(1.5)
        section.bottom_margin = Cm(1.5)
        section.left_margin = Cm(2)
        section.right_margin = Cm(2)

    style = doc.styles['Normal']
    style.font.name = 'Calibri'
    style.font.size = Pt(10)

    escola     = dados_form.get('escola', '').strip()
    diretoria  = dados_form.get('diretoria', '').strip()
    endereco   = dados_form.get('endereco', '').strip()
    ano_letivo = dados_form.get('ano_letivo', str(datetime.now().year))

    def header_line(text, bold=False, size=9):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        add_run(p, text, bold=bold, size=size, color='1a1a2e')

    header_line("GOVERNO DO ESTADO DE SÃO PAULO", bold=True, size=10)
    header_line("SECRETARIA DE ESTADO DA EDUCAÇÃO")
    if diretoria:
        header_line(diretoria.upper())
    if escola:
        header_line(escola.upper(), bold=True, size=10)
    if endereco:
        header_line(endereco, size=8)

    doc.add_paragraph().paragraph_format.space_after = Pt(2)

    # Título azul
    t0 = doc.add_table(rows=1, cols=1)
    t0.style = 'Table Grid'
    cell = t0.cell(0, 0)
    cell.paragraphs[0].clear()
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(5)
    p.paragraph_format.space_after = Pt(5)
    add_run(p, f"PLANEJAMENTO DE AULA  {ano_letivo}", bold=True, size=12, color='FFFFFF')
    set_cell_bg(cell, '2b4fc7')

    doc.add_paragraph().paragraph_format.space_after = Pt(4)

    # Info professor
    t1 = doc.add_table(rows=3, cols=2)
    t1.style = 'Table Grid'

    def info_cell(cell, label, value):
        cell.paragraphs[0].clear()
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(3)
        add_run(p, f"{label}: ", bold=True, size=9, color='2b4fc7')
        add_run(p, value, size=9, color='333333')

    info_cell(t1.cell(0, 0), "Professor(a)", dados_form['professor'])
    t1.cell(0, 0).merge(t1.cell(0, 1))
    info_cell(t1.cell(1, 0), "Componente Curricular", dados_form['disciplina'])
    info_cell(t1.cell(1, 1), "Nº de Aulas", str(dados_form['num_aulas']))
    info_cell(t1.cell(2, 0), "Ano/Série/Turma", dados_form['turma'])
    info_cell(t1.cell(2, 1), "Período", f"{dados_form['periodo']}  |  {dados_form['datas']}")

    for row in t1.rows:
        for c in row.cells:
            set_cell_border(c)

    doc.add_paragraph().paragraph_format.space_after = Pt(4)

    # Tabela principal
    t2 = doc.add_table(rows=1 + len(aulas_ia), cols=5)
    t2.style = 'Table Grid'

    headers = ['AULA / DATA', 'CONTEÚDO E OBJETIVOS', 'ESTRATÉGIAS DIDÁTICAS', 'RECURSOS', 'AVALIAÇÃO']
    widths  = [Cm(2.8), Cm(5.8), Cm(4.5), Cm(3.3), Cm(3.6)]

    for i, (h, w) in enumerate(zip(headers, widths)):
        cell = t2.cell(0, i)
        cell.width = w
        cell.paragraphs[0].clear()
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(4)
        add_run(p, h, bold=True, size=8, color='FFFFFF')
        set_cell_bg(cell, '2b4fc7')
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        set_cell_border(cell, color='1a3399')

    for i, aula in enumerate(aulas_ia):
        ri = i + 1
        bg = 'f0f4ff' if i % 2 == 0 else 'FFFFFF'

        # Aula / número
        cell = t2.cell(ri, 0)
        cell.paragraphs[0].clear()
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(3)
        partes = aula['titulo'].split(' - ', 1)
        add_run(p, partes[0] + '\n', bold=True, size=9, color='2b4fc7')
        if len(partes) > 1:
            add_run(p, partes[1], size=8, color='555555')
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        set_cell_bg(cell, bg)

        # Conteúdo e objetivos
        cell = t2.cell(ri, 1)
        cell.paragraphs[0].clear()
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(3)
        add_run(p, "CONTEÚDOS\n", bold=True, size=8, color='2b4fc7')
        for c in aula['conteudos']:
            add_run(p, f"• {c}\n", size=8)
        add_run(p, "\nOBJETIVOS\n", bold=True, size=8, color='2b4fc7')
        for o in aula['objetivos']:
            add_run(p, f"• {o}\n", size=8)
        set_cell_bg(cell, bg)

        # Estratégias
        cell = t2.cell(ri, 2)
        cell.paragraphs[0].clear()
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(3)
        add_run(p, aula['estrategias'], size=8)
        set_cell_bg(cell, bg)

        # Recursos
        cell = t2.cell(ri, 3)
        cell.paragraphs[0].clear()
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(3)
        add_run(p, aula['recursos'], size=8)
        set_cell_bg(cell, bg)

        # Avaliação
        cell = t2.cell(ri, 4)
        cell.paragraphs[0].clear()
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(3)
        add_run(p, aula['avaliacao'], size=8)
        set_cell_bg(cell, bg)

        for ci in range(5):
            set_cell_border(t2.cell(ri, ci))

    # Rodapé
    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    add_run(p, f"Gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')}  •  Plano de Aula IA",
            size=7, color='aaaaaa', italic=True)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf

# ─── Rotas ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/historico')
def historico_page():
    return render_template('historico.html')

@app.route('/api/historico')
def api_historico():
    conn = sqlite3.connect('historico.db')
    c = conn.cursor()
    c.execute('''SELECT id, data, professor, escola, disciplina, turma, num_aulas, periodo, datas, temas, nome_arquivo
                 FROM historico ORDER BY id DESC LIMIT 100''')
    rows = c.fetchall()
    conn.close()
    result = []
    for r in rows:
        result.append({
            'id': r[0], 'data': r[1], 'professor': r[2], 'escola': r[3],
            'disciplina': r[4], 'turma': r[5], 'num_aulas': r[6],
            'periodo': r[7], 'datas': r[8],
            'temas': json.loads(r[9]) if r[9] else [],
            'nome_arquivo': r[10]
        })
    return jsonify(result)

@app.route('/download/<int:item_id>')
def download_historico(item_id):
    conn = sqlite3.connect('historico.db')
    c = conn.cursor()
    c.execute('SELECT arquivo, nome_arquivo FROM historico WHERE id = ?', (item_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return 'Não encontrado', 404
    buf = io.BytesIO(row[0])
    return send_file(buf, as_attachment=True, download_name=row[1],
                     mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')

@app.route('/deletar/<int:item_id>', methods=['DELETE'])
def deletar_historico(item_id):
    conn = sqlite3.connect('historico.db')
    c = conn.cursor()
    c.execute('DELETE FROM historico WHERE id = ?', (item_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/gerar', methods=['POST'])
def gerar():
    dados = {
        'professor':  request.form.get('professor', ''),
        'escola':     request.form.get('escola', ''),
        'diretoria':  request.form.get('diretoria', ''),
        'endereco':   request.form.get('endereco', ''),
        'ano_letivo': request.form.get('ano_letivo', str(datetime.now().year)),
        'disciplina': request.form.get('disciplina', ''),
        'turma':      request.form.get('turma', ''),
        'num_aulas':  request.form.get('num_aulas', '1'),
        'aula_inicio':request.form.get('aula_inicio', '1'),
        'periodo':    request.form.get('periodo', 'quinzenal'),
        'datas':      request.form.get('datas', ''),
    }
    temas = request.form.getlist('temas[]')
    urls_pdf = [u.strip() for u in request.form.getlist('urls_pdf[]') if u.strip()]

    conteudo_pdf = None
    if urls_pdf:
        partes = []
        for i, url in enumerate(urls_pdf):
            texto = extrair_pdf(url)
            if texto:
                partes.append(f"--- PDF {i+1} ---\n{texto}")
        if partes:
            conteudo_pdf = "\n\n".join(partes)

    conteudo = gerar_conteudo_ia(
        dados['disciplina'], dados['turma'],
        temas, dados['periodo'], dados['datas'],
        int(dados.get('aula_inicio', 1)),
        conteudo_pdf
    )

    buf = criar_docx(dados, conteudo['aulas'])
    docx_bytes = buf.read()

    nome = f"Plano_{dados['disciplina'].replace(' ', '_')}_{dados['turma'].replace(' ', '_')}.docx"

    conn = sqlite3.connect('historico.db')
    c = conn.cursor()
    c.execute('''INSERT INTO historico
                 (data, professor, escola, disciplina, turma, num_aulas, periodo, datas, temas, arquivo, nome_arquivo)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (datetime.now().strftime('%d/%m/%Y %H:%M'),
               dados['professor'], dados['escola'], dados['disciplina'],
               dados['turma'], dados['num_aulas'], dados['periodo'],
               dados['datas'], json.dumps(temas), docx_bytes, nome))
    conn.commit()
    conn.close()

    return send_file(io.BytesIO(docx_bytes), as_attachment=True, download_name=nome,
                     mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=False, host='0.0.0.0', port=port)
