import os
import io
import json
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from flask import (Flask, render_template, request, send_file,
                   jsonify, redirect, url_for, flash)
from flask_login import (LoginManager, UserMixin, login_user,
                         logout_user, login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from anthropic import Anthropic
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm as rcm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
try:
    import mercadopago as _mp
    _mp_SDK = getattr(_mp, 'SDK', None)
except ImportError:
    _mp_SDK = None

# ─── App ──────────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-troque-em-producao')

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = None

client = Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'), timeout=120.0)

MP_ACCESS_TOKEN = os.environ.get('MP_ACCESS_TOKEN', '')
MP_PUBLIC_KEY   = os.environ.get('MP_PUBLIC_KEY', '')
mp_sdk = _mp_SDK(MP_ACCESS_TOKEN) if (MP_ACCESS_TOKEN and _mp_SDK) else None

NUPAY_MERCHANT_KEY   = os.environ.get('NUPAY_MERCHANT_KEY', '')
NUPAY_MERCHANT_TOKEN = os.environ.get('NUPAY_MERCHANT_TOKEN', '')
NUPAY_API_URL        = 'https://api.spinpay.com.br'   # produção
# NUPAY_API_URL      = 'https://sandbox-api.spinpay.com.br'  # testes

SITE_URL    = os.environ.get('SITE_URL', 'http://localhost:5001')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', '')

PLANOS = {
    'pro':       {'nome': 'Pro',     'preco': 29.00,  'dias': 30},
    'professor': {'nome': 'Premium', 'preco': 49.00,  'dias': 30},
    'escola':    {'nome': 'Escola',  'preco': 199.00, 'dias': 30},
}

LIMITE_GRATIS = 5  # gerações gratuitas por mês no plano grátis

SYSTEM_PROMPT = """Você é o ProfeIA, assistente especializado em ajudar professores brasileiros.

Você cria materiais pedagógicos de alta qualidade, incluindo:
- Planos de aula completos (objetivos, conteúdo, metodologia, avaliação)
- Provas e avaliações (questões abertas e múltipla escolha, com gabarito)
- Caça-palavras (lista de palavras + grade de letras formatada)
- Atividades e exercícios lúdicos
- Planejamento anual (distribuição por bimestre)
- Resumos de conteúdo para alunos
- Rubricas de avaliação
- Bilhetes para os pais

Quando o professor pedir um material:
1. Se faltar informação essencial (disciplina, série, tema), pergunte de forma direta e simples
2. Gere o material completo, bem estruturado e formatado
3. Use linguagem clara e pedagógica, seguindo a BNCC

Responda sempre em português brasileiro. Seja prático, objetivo e útil."""

# ─── Banco de dados ───────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get('DATABASE_URL', '').replace('postgres://', 'postgresql://', 1)

class _DbConn:
    """Wrapper que faz psycopg2 se comportar como sqlite3 no resto do código."""
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        sql = sql.replace('?', '%s')
        params = tuple(
            psycopg2.Binary(p) if isinstance(p, (bytes, bytearray)) else p
            for p in params
        )
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

def get_db():
    if not DATABASE_URL:
        raise RuntimeError('DATABASE_URL não configurada. Adicione a variável de ambiente no Render.')
    conn = psycopg2.connect(DATABASE_URL)
    return _DbConn(conn)

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id         SERIAL PRIMARY KEY,
            nome       TEXT NOT NULL,
            email      TEXT UNIQUE NOT NULL,
            senha      TEXT NOT NULL,
            plano      TEXT DEFAULT '',
            ativo      INTEGER DEFAULT 0,
            valido_ate TEXT DEFAULT '',
            criado_em  TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS historico (
            id           SERIAL PRIMARY KEY,
            usuario_id   INTEGER DEFAULT 0,
            data         TEXT,
            professor    TEXT,
            escola       TEXT,
            disciplina   TEXT,
            turma        TEXT,
            num_aulas    INTEGER,
            periodo      TEXT,
            datas        TEXT,
            temas        TEXT,
            arquivo      BYTEA,
            nome_arquivo TEXT
        )
    ''')
    conn.execute('ALTER TABLE historico ADD COLUMN IF NOT EXISTS usuario_id INTEGER DEFAULT 0')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
            id         SERIAL PRIMARY KEY,
            usuario_id INTEGER,
            role       TEXT,
            content    TEXT,
            criado_em  TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS planejamento_anual (
            id         SERIAL PRIMARY KEY,
            usuario_id INTEGER,
            disciplina TEXT,
            turma      TEXT,
            ano        TEXT,
            conteudo   TEXT,
            criado_em  TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ─── Modelo de usuário ────────────────────────────────────────────────────────

class Usuario(UserMixin):
    def __init__(self, row):
        self.id        = row['id']
        self.nome      = row['nome']
        self.email     = row['email']
        self.plano     = row['plano']
        self.ativo     = row['ativo']
        self.valido_ate= row['valido_ate']

    @property
    def assinatura_ativa(self):
        if not self.ativo or not self.valido_ate:
            return False
        try:
            valido = datetime.strptime(self.valido_ate, '%Y-%m-%d')
            return valido >= datetime.now()
        except Exception:
            return False

    @property
    def is_admin(self):
        return ADMIN_EMAIL and self.email == ADMIN_EMAIL

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM usuarios WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return Usuario(row) if row else None

# ─── Helper: verificar assinatura ─────────────────────────────────────────────

def assinatura_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if not current_user.assinatura_ativa and not current_user.is_admin:
            return redirect(url_for('planos'))
        return f(*args, **kwargs)
    return decorated

# ─── PDF (reportlab) ──────────────────────────────────────────────────────────

AZUL        = colors.HexColor('#2b4fc7')
AZUL_ESCURO = colors.HexColor('#1a3399')
AZUL_CLARO  = colors.HexColor('#eef2ff')
BRANCO      = colors.white
TEXTO       = colors.HexColor('#1a1a2e')
CINZA       = colors.HexColor('#6b7280')

def criar_pdf(dados_form, aulas_ia):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=1.8*rcm, rightMargin=1.8*rcm,
        topMargin=1.5*rcm, bottomMargin=1.5*rcm)

    escola     = dados_form.get('escola', '').strip()
    diretoria  = dados_form.get('diretoria', '').strip()
    endereco   = dados_form.get('endereco', '').strip()
    ano_letivo = dados_form.get('ano_letivo', str(datetime.now().year))

    st_centro_negrito = ParagraphStyle('cn', fontName='Helvetica-Bold', fontSize=10,
                                        alignment=TA_CENTER, textColor=TEXTO, leading=14)
    st_centro         = ParagraphStyle('c',  fontName='Helvetica', fontSize=9,
                                        alignment=TA_CENTER, textColor=TEXTO, leading=13)
    st_centro_pequeno = ParagraphStyle('cp', fontName='Helvetica', fontSize=8,
                                        alignment=TA_CENTER, textColor=CINZA, leading=12)
    st_header_tabela  = ParagraphStyle('ht', fontName='Helvetica-Bold', fontSize=8,
                                        alignment=TA_CENTER, textColor=BRANCO, leading=11)
    st_celula_titulo  = ParagraphStyle('ct', fontName='Helvetica-Bold', fontSize=8.5,
                                        alignment=TA_CENTER, textColor=AZUL, leading=12)
    st_celula         = ParagraphStyle('ce', fontName='Helvetica', fontSize=7.5,
                                        textColor=TEXTO, leading=11)
    st_sub            = ParagraphStyle('s',  fontName='Helvetica-Bold', fontSize=7.5,
                                        textColor=AZUL, leading=11)
    st_rodape         = ParagraphStyle('r',  fontName='Helvetica-Oblique', fontSize=7,
                                        alignment=TA_CENTER, textColor=CINZA, leading=10)

    story = []

    if escola or diretoria:
        story.append(Paragraph("GOVERNO DO ESTADO DE SÃO PAULO", st_centro_negrito))
        story.append(Paragraph("SECRETARIA DE ESTADO DA EDUCAÇÃO", st_centro))
        if diretoria:
            story.append(Paragraph(diretoria.upper(), st_centro))
        if escola:
            story.append(Paragraph(escola.upper(), st_centro_negrito))
        if endereco:
            story.append(Paragraph(endereco, st_centro_pequeno))
        story.append(Spacer(1, 8))

    titulo_data = [[Paragraph(f"PLANEJAMENTO DE AULA  {ano_letivo}", ParagraphStyle(
        'tit', fontName='Helvetica-Bold', fontSize=13,
        alignment=TA_CENTER, textColor=BRANCO, leading=16))]]
    t_titulo = Table(titulo_data, colWidths=[doc.width])
    t_titulo.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), AZUL),
        ('TOPPADDING',    (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(t_titulo)
    story.append(Spacer(1, 10))

    def info(label, valor):
        return Paragraph(f'<font color="#2b4fc7"><b>{label}:</b></font> {valor}',
                         ParagraphStyle('inf', fontName='Helvetica', fontSize=8.5,
                                        textColor=TEXTO, leading=13))

    w = doc.width
    t_info = Table([
        [info("Professor(a)", dados_form.get('professor', ''))],
        [info("Componente Curricular", dados_form.get('disciplina', '')),
         info("Nº de Aulas", str(dados_form.get('num_aulas', '')))],
        [info("Ano/Série/Turma", dados_form.get('turma', '')),
         info("Período", f"{dados_form.get('periodo','')}  |  {dados_form.get('datas','')}")],
    ], colWidths=[w*0.65, w*0.35])
    t_info.setStyle(TableStyle([
        ('SPAN',         (0,0), (1,0)),
        ('GRID',         (0,0), (-1,-1), 0.5, colors.HexColor('#c0c8e8')),
        ('TOPPADDING',    (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ('RIGHTPADDING',  (0,0), (-1,-1), 8),
        ('VALIGN',       (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 10))

    col_w = [2.5*rcm, 5.2*rcm, 4.0*rcm, 2.9*rcm, 3.2*rcm]
    headers = [Paragraph(h, st_header_tabela) for h in
               ['AULA / DATA', 'CONTEÚDO E OBJETIVOS', 'ESTRATÉGIAS DIDÁTICAS', 'RECURSOS', 'AVALIAÇÃO']]
    rows = [headers]

    for i, aula in enumerate(aulas_ia):
        bg = AZUL_CLARO if i % 2 == 0 else BRANCO
        partes = aula['titulo'].split(' - ', 1)
        col0 = [Paragraph(partes[0], st_celula_titulo),
                Paragraph(partes[1] if len(partes) > 1 else '', ParagraphStyle(
                    's0', fontName='Helvetica', fontSize=7.5,
                    alignment=TA_CENTER, textColor=CINZA, leading=11))]
        col1 = [Paragraph("CONTEÚDOS", st_sub)]
        for c in aula.get('conteudos', []):
            col1.append(Paragraph(f"• {c}", st_celula))
        col1.append(Spacer(1, 4))
        col1.append(Paragraph("OBJETIVOS", st_sub))
        for o in aula.get('objetivos', []):
            col1.append(Paragraph(f"• {o}", st_celula))
        rows.append([col0, col1,
                     [Paragraph(aula.get('estrategias', ''), st_celula)],
                     [Paragraph(aula.get('recursos', ''), st_celula)],
                     [Paragraph(aula.get('avaliacao', ''), st_celula)]])

    t_main = Table(rows, colWidths=col_w, repeatRows=1)
    style = [
        ('BACKGROUND',    (0,0), (-1,0), AZUL),
        ('GRID',         (0,0), (-1,-1), 0.5, colors.HexColor('#c0c8e8')),
        ('VALIGN',       (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING',    (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING',   (0,0), (-1,-1), 6),
        ('RIGHTPADDING',  (0,0), (-1,-1), 6),
        ('ALIGN',        (0,1), (0,-1), 'CENTER'),
        ('VALIGN',       (0,1), (0,-1), 'MIDDLE'),
    ]
    for i in range(len(aulas_ia)):
        bg = AZUL_CLARO if i % 2 == 0 else BRANCO
        style.append(('BACKGROUND', (0, i+1), (-1, i+1), bg))
    t_main.setStyle(TableStyle(style))
    story.append(t_main)
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        f"Gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')}  •  Plano de Aula IA",
        st_rodape))
    doc.build(story)
    buf.seek(0)
    return buf

# ─── PDF extrator ──────────────────────────────────────────────────────────────

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
        referencia_pdf = f"\n\nMATERIAL DE REFERÊNCIA:\n{conteudo_pdf}\n\nUse esse material como base."

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
      "estrategias": "Descrição das estratégias didáticas em 2-3 frases.",
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
    return json.loads(texto.strip())

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

        for col_i, key in enumerate(['estrategias', 'recursos', 'avaliacao'], start=2):
            cell = t2.cell(ri, col_i)
            cell.paragraphs[0].clear()
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(3)
            p.paragraph_format.space_after = Pt(3)
            add_run(p, aula[key], size=8)
            set_cell_bg(cell, bg)

        for ci in range(5):
            set_cell_border(t2.cell(ri, ci))

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

# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        conn  = get_db()
        row   = conn.execute('SELECT * FROM usuarios WHERE email = ?', (email,)).fetchone()
        conn.close()
        if row and check_password_hash(row['senha'], senha):
            login_user(Usuario(row))
            return redirect(url_for('index'))
        flash('E-mail ou senha incorretos.')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        nome  = request.form.get('nome', '').strip()
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        if not nome or not email or not senha:
            flash('Preencha todos os campos.')
            return render_template('cadastro.html')
        conn = get_db()
        existe = conn.execute('SELECT id FROM usuarios WHERE email = ?', (email,)).fetchone()
        if existe:
            conn.close()
            flash('Este e-mail já está cadastrado.')
            return render_template('cadastro.html')
        conn.execute(
            'INSERT INTO usuarios (nome, email, senha, criado_em) VALUES (?, ?, ?, ?)',
            (nome, email, generate_password_hash(senha), datetime.now().strftime('%Y-%m-%d'))
        )
        conn.commit()
        row = conn.execute('SELECT * FROM usuarios WHERE email = ?', (email,)).fetchone()
        conn.close()
        login_user(Usuario(row))
        return redirect(url_for('planos'))
    return render_template('cadastro.html')

# ─── Planos e Pagamento ───────────────────────────────────────────────────────

@app.route('/planos')
@login_required
def planos():
    return render_template('planos.html', planos=PLANOS,
                           assinatura_ativa=current_user.assinatura_ativa,
                           valido_ate=current_user.valido_ate,
                           plano_atual=current_user.plano)

@app.route('/pagamento/criar/<plano_id>', methods=['POST'])
@login_required
def pagamento_criar(plano_id):
    if plano_id not in PLANOS:
        return redirect(url_for('planos'))

    if not mp_sdk:
        flash('Pagamento não configurado ainda. Entre em contato com o suporte.')
        return redirect(url_for('planos'))

    plano = PLANOS[plano_id]

    preference_data = {
        "items": [{
            "title": f"Plano {plano['nome']} — Plano de Aula IA",
            "quantity": 1,
            "unit_price": plano['preco'],
            "currency_id": "BRL"
        }],
        "payer": {"email": current_user.email},
        "back_urls": {
            "success": f"{SITE_URL}/pagamento/sucesso",
            "failure": f"{SITE_URL}/pagamento/falha",
            "pending": f"{SITE_URL}/pagamento/pendente"
        },
        "auto_return": "approved",
        "notification_url": f"{SITE_URL}/pagamento/webhook",
        "external_reference": f"{current_user.id}|{plano_id}"
    }

    result = mp_sdk.preference().create(preference_data)
    pref   = result.get("response", {})

    if "init_point" not in pref:
        flash('Erro ao criar pagamento. Tente novamente.')
        return redirect(url_for('planos'))

    return redirect(pref["init_point"])

@app.route('/pagamento/checkout/<plano_id>')
@login_required
def pagamento_checkout(plano_id):
    if plano_id not in PLANOS:
        return redirect(url_for('planos'))
    plano = PLANOS[plano_id]
    return render_template('pagamento_checkout.html',
                           plano_id=plano_id,
                           plano=plano,
                           public_key=MP_PUBLIC_KEY,
                           usuario_email=current_user.email)

@app.route('/pagamento/processar', methods=['POST'])
@login_required
def pagamento_processar():
    import requests as req
    data = request.get_json(silent=True) or {}
    plano_id           = data.get('plano_id')
    token              = data.get('token')
    payment_method_id  = data.get('payment_method_id')
    installments       = int(data.get('installments', 1))
    issuer_id          = data.get('issuer_id')

    if not token or plano_id not in PLANOS:
        return jsonify({'error': 'Dados inválidos'}), 400
    if not MP_ACCESS_TOKEN:
        return jsonify({'error': 'Pagamento não configurado'}), 500

    plano = PLANOS[plano_id]
    payment_data = {
        'id': payment_method_id,
        'type': 'credit_card',
        'token': token,
        'installments': installments,
    }
    if issuer_id:
        payment_data['issuer_id'] = str(issuer_id)

    order_body = {
        'type': 'online',
        'processing_mode': 'automatic',
        'external_reference': f'{current_user.id}|{plano_id}',
        'total_amount': f'{plano["preco"]:.2f}',
        'payer': {'email': current_user.email},
        'transactions': {
            'payments': [{'amount': f'{plano["preco"]:.2f}', 'payment_method': payment_data}]
        }
    }

    headers = {
        'Authorization': f'Bearer {MP_ACCESS_TOKEN}',
        'Content-Type': 'application/json',
        'X-Idempotency-Key': f'{current_user.id}-{plano_id}-{token[:10]}',
    }

    resp   = req.post('https://api.mercadopago.com/v1/orders', json=order_body, headers=headers)
    result = resp.json()

    payments = result.get('transactions', {}).get('payments', [{}])
    pay_status = payments[0].get('status', '') if payments else ''
    order_status = result.get('status', '')

    if order_status in ('processed',) or pay_status in ('processed', 'accredited'):
        dias = plano['dias']
        valido_ate = (datetime.now() + timedelta(days=dias)).strftime('%Y-%m-%d')
        conn = get_db()
        conn.execute('UPDATE usuarios SET ativo = 1, plano = ?, valido_ate = ? WHERE id = ?',
                     (plano_id, valido_ate, current_user.id))
        conn.commit()
        conn.close()
        return jsonify({'status': 'approved'})

    detail = result.get('status_detail') or pay_status or order_status
    return jsonify({'status': 'rejected', 'detail': detail})

@app.route('/pagamento/webhook', methods=['POST'])
def pagamento_webhook():
    if not mp_sdk:
        return jsonify({'ok': False}), 400

    data = request.get_json(silent=True) or {}
    topic = data.get('type') or request.args.get('type', '')
    payment_id = data.get('data', {}).get('id') or request.args.get('id')

    if topic != 'payment' or not payment_id:
        return jsonify({'ok': True})

    result  = mp_sdk.payment().get(payment_id)
    payment = result.get("response", {})

    if payment.get("status") != "approved":
        return jsonify({'ok': True})

    external_ref = payment.get("external_reference", "")
    try:
        usuario_id, plano_id = external_ref.split("|")
        usuario_id = int(usuario_id)
    except Exception:
        return jsonify({'ok': False}), 400

    if plano_id not in PLANOS:
        return jsonify({'ok': False}), 400

    dias = PLANOS[plano_id]['dias']
    valido_ate = (datetime.now() + timedelta(days=dias)).strftime('%Y-%m-%d')

    conn = get_db()
    conn.execute(
        'UPDATE usuarios SET ativo = 1, plano = ?, valido_ate = ? WHERE id = ?',
        (plano_id, valido_ate, usuario_id)
    )
    conn.commit()
    conn.close()

    return jsonify({'ok': True})

@app.route('/pagamento/sucesso')
@login_required
def pagamento_sucesso():
    # Atualiza dados do usuário da sessão
    conn = get_db()
    row  = conn.execute('SELECT * FROM usuarios WHERE id = ?', (current_user.id,)).fetchone()
    conn.close()
    if row:
        login_user(Usuario(row))
    return render_template('pagamento_status.html',
                           status='sucesso',
                           titulo='Pagamento aprovado!',
                           mensagem='Sua conta está ativa. Bom trabalho!')

@app.route('/pagamento/pendente')
@login_required
def pagamento_pendente():
    return render_template('pagamento_status.html',
                           status='pendente',
                           titulo='Pagamento pendente',
                           mensagem='Assim que confirmarmos seu pagamento, sua conta será ativada.')

@app.route('/pagamento/falha')
@login_required
def pagamento_falha():
    return render_template('pagamento_status.html',
                           status='falha',
                           titulo='Pagamento não realizado',
                           mensagem='Ocorreu um problema. Tente novamente ou escolha outro método.')

# ─── NuPay ────────────────────────────────────────────────────────────────────

@app.route('/pagamento/nupay/criar/<plano_id>', methods=['POST'])
@login_required
def nupay_criar(plano_id):
    if plano_id not in PLANOS:
        return redirect(url_for('planos'))

    if not NUPAY_MERCHANT_KEY or not NUPAY_MERCHANT_TOKEN:
        flash('NuPay não configurado ainda. Escolha outro método de pagamento.')
        return redirect(url_for('planos'))

    import requests, uuid
    plano = PLANOS[plano_id]

    payload = {
        "merchantOrderReference": f"order-{current_user.id}-{uuid.uuid4().hex[:8]}",
        "referenceId": f"{current_user.id}|{plano_id}",
        "amount": {
            "value": int(plano['preco'] * 100),
            "currency": "BRL"
        },
        "shopper": {
            "email": current_user.email,
            "fullName": current_user.nome
        },
        "authorizationOptions": {
            "type": "CIBA"
        },
        "callbackUrls": {
            "success": f"{SITE_URL}/pagamento/nupay/sucesso",
            "failure": f"{SITE_URL}/pagamento/falha",
            "pending": f"{SITE_URL}/pagamento/pendente"
        },
        "notificationUrl": f"{SITE_URL}/pagamento/nupay/webhook"
    }

    try:
        resp = requests.post(
            f"{NUPAY_API_URL}/v1/checkouts/payments",
            json=payload,
            headers={
                "X-Merchant-Key":   NUPAY_MERCHANT_KEY,
                "X-Merchant-Token": NUPAY_MERCHANT_TOKEN,
                "Content-Type":     "application/json"
            },
            timeout=15
        )
        data = resp.json()
        payment_url = data.get("paymentUrl")
        if not payment_url:
            raise ValueError("paymentUrl não retornado")
        return redirect(payment_url)
    except Exception as e:
        flash('Erro ao criar pagamento NuPay. Tente Mercado Pago ou tente novamente.')
        return redirect(url_for('planos'))

@app.route('/pagamento/nupay/webhook', methods=['POST'])
def nupay_webhook():
    data = request.get_json(silent=True) or {}

    status        = data.get('status', '')
    reference_id  = data.get('referenceId', '')
    psp_reference = data.get('pspReferenceId', '')

    if status != 'COMPLETED' or not reference_id:
        return jsonify({'ok': True})

    try:
        import requests as req
        resp = req.get(
            f"{NUPAY_API_URL}/v1/checkouts/payments/{psp_reference}/status",
            headers={
                "X-Merchant-Key":   NUPAY_MERCHANT_KEY,
                "X-Merchant-Token": NUPAY_MERCHANT_TOKEN
            },
            timeout=10
        )
        confirmed_status = resp.json().get('status', '')
        if confirmed_status not in ('COMPLETED', 'AUTHORIZED'):
            return jsonify({'ok': True})
    except Exception:
        return jsonify({'ok': False}), 400

    try:
        usuario_id, plano_id = reference_id.split('|')
        usuario_id = int(usuario_id)
    except Exception:
        return jsonify({'ok': False}), 400

    if plano_id not in PLANOS:
        return jsonify({'ok': False}), 400

    dias       = PLANOS[plano_id]['dias']
    valido_ate = (datetime.now() + timedelta(days=dias)).strftime('%Y-%m-%d')

    conn = get_db()
    conn.execute(
        'UPDATE usuarios SET ativo = 1, plano = ?, valido_ate = ? WHERE id = ?',
        (plano_id, valido_ate, usuario_id)
    )
    conn.commit()
    conn.close()

    return jsonify({'ok': True})

@app.route('/pagamento/nupay/sucesso')
@login_required
def nupay_sucesso():
    conn = get_db()
    row  = conn.execute('SELECT * FROM usuarios WHERE id = ?', (current_user.id,)).fetchone()
    conn.close()
    if row:
        login_user(Usuario(row))
    return render_template('pagamento_status.html',
                           status='sucesso',
                           titulo='Pagamento aprovado!',
                           mensagem='Sua conta está ativa. Bom trabalho!')

# ─── Admin ────────────────────────────────────────────────────────────────────

@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        return redirect(url_for('index'))
    conn  = get_db()
    users = conn.execute('SELECT * FROM usuarios ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('admin.html', users=users)

@app.route('/admin/ativar/<int:uid>', methods=['POST'])
@login_required
def admin_ativar(uid):
    if not current_user.is_admin:
        return redirect(url_for('index'))
    dias = int(request.form.get('dias', 30))
    plano = request.form.get('plano', 'professor')
    valido_ate = (datetime.now() + timedelta(days=dias)).strftime('%Y-%m-%d')
    conn = get_db()
    conn.execute('UPDATE usuarios SET ativo = 1, plano = ?, valido_ate = ? WHERE id = ?',
                 (plano, valido_ate, uid))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

@app.route('/admin/desativar/<int:uid>', methods=['POST'])
@login_required
def admin_desativar(uid):
    if not current_user.is_admin:
        return redirect(url_for('index'))
    conn = get_db()
    conn.execute('UPDATE usuarios SET ativo = 0 WHERE id = ?', (uid,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

# ─── Conta / Perfil ───────────────────────────────────────────────────────────

@app.route('/conta')
@login_required
def conta():
    conn = get_db()
    rows = conn.execute(
        'SELECT num_aulas, disciplina FROM historico WHERE usuario_id = ?',
        (current_user.id,)
    ).fetchall()
    conn.close()
    stats = {
        'total':       len(rows),
        'aulas':       sum(int(r['num_aulas'] or 0) for r in rows),
        'disciplinas': len(set(r['disciplina'] for r in rows if r['disciplina']))
    }
    return render_template('conta.html', stats=stats)

@app.route('/conta/senha', methods=['POST'])
@login_required
def conta_senha():
    senha_atual = request.form.get('senha_atual', '')
    senha_nova  = request.form.get('senha_nova', '')
    senha_conf  = request.form.get('senha_conf', '')

    conn = get_db()
    row  = conn.execute('SELECT senha FROM usuarios WHERE id = ?', (current_user.id,)).fetchone()

    if not check_password_hash(row['senha'], senha_atual):
        conn.close()
        flash('Senha atual incorreta.', 'erro')
        return redirect(url_for('conta'))

    if senha_nova != senha_conf:
        conn.close()
        flash('As senhas não coincidem.', 'erro')
        return redirect(url_for('conta'))

    if len(senha_nova) < 6:
        conn.close()
        flash('A nova senha deve ter pelo menos 6 caracteres.', 'erro')
        return redirect(url_for('conta'))

    conn.execute('UPDATE usuarios SET senha = ? WHERE id = ?',
                 (generate_password_hash(senha_nova), current_user.id))
    conn.commit()
    conn.close()
    flash('Senha atualizada com sucesso!', 'ok')
    return redirect(url_for('conta'))

# ─── Rotas principais ─────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    return redirect(url_for('chat'))

@app.route('/historico')
@login_required
@assinatura_required
def historico_page():
    return render_template('historico.html')

@app.route('/api/historico')
@login_required
@assinatura_required
def api_historico():
    conn = get_db()
    rows = conn.execute(
        '''SELECT id, data, professor, escola, disciplina, turma,
                  num_aulas, periodo, datas, temas, nome_arquivo
           FROM historico WHERE usuario_id = ? ORDER BY id DESC LIMIT 100''',
        (current_user.id,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        result.append({
            'id': r['id'], 'data': r['data'], 'professor': r['professor'],
            'escola': r['escola'], 'disciplina': r['disciplina'],
            'turma': r['turma'], 'num_aulas': r['num_aulas'],
            'periodo': r['periodo'], 'datas': r['datas'],
            'temas': json.loads(r['temas']) if r['temas'] else [],
            'nome_arquivo': r['nome_arquivo']
        })
    return jsonify(result)

@app.route('/download/<int:item_id>')
@login_required
@assinatura_required
def download_historico(item_id):
    conn = get_db()
    row  = conn.execute(
        'SELECT arquivo, nome_arquivo FROM historico WHERE id = ? AND usuario_id = ?',
        (item_id, current_user.id)
    ).fetchone()
    conn.close()
    if not row:
        return 'Não encontrado', 404
    buf = io.BytesIO(row['arquivo'])
    return send_file(buf, as_attachment=True, download_name=row['nome_arquivo'],
                     mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')

@app.route('/deletar/<int:item_id>', methods=['DELETE'])
@login_required
@assinatura_required
def deletar_historico(item_id):
    conn = get_db()
    conn.execute('DELETE FROM historico WHERE id = ? AND usuario_id = ?',
                 (item_id, current_user.id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/gerar', methods=['POST'])
@login_required
@assinatura_required
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
    temas    = request.form.getlist('temas[]')
    urls_pdf = [u.strip() for u in request.form.getlist('urls_pdf[]') if u.strip()]
    formato  = request.form.get('formato', 'docx')

    conteudo_pdf = None
    if urls_pdf:
        partes = [f"--- PDF {i+1} ---\n{t}" for i, u in enumerate(urls_pdf)
                  if (t := extrair_pdf(u))]
        if partes:
            conteudo_pdf = "\n\n".join(partes)

    conteudo  = gerar_conteudo_ia(dados['disciplina'], dados['turma'], temas,
                                   dados['periodo'], dados['datas'],
                                   int(dados.get('aula_inicio', 1)), conteudo_pdf)
    base_nome = f"Plano_{dados['disciplina'].replace(' ', '_')}_{dados['turma'].replace(' ', '_')}"

    if formato == 'pdf':
        buf        = criar_pdf(dados, conteudo['aulas'])
        file_bytes = buf.read()
        nome       = base_nome + '.pdf'
        mimetype   = 'application/pdf'
    else:
        buf        = criar_docx(dados, conteudo['aulas'])
        file_bytes = buf.read()
        nome       = base_nome + '.docx'
        mimetype   = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

    conn = get_db()
    conn.execute(
        '''INSERT INTO historico
           (usuario_id, data, professor, escola, disciplina, turma,
            num_aulas, periodo, datas, temas, arquivo, nome_arquivo)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (current_user.id, datetime.now().strftime('%d/%m/%Y %H:%M'),
         dados['professor'], dados['escola'], dados['disciplina'],
         dados['turma'], dados['num_aulas'], dados['periodo'],
         dados['datas'], json.dumps(temas), file_bytes, nome)
    )
    conn.commit()
    conn.close()

    return send_file(io.BytesIO(file_bytes), as_attachment=True,
                     download_name=nome, mimetype=mimetype)

# ─── Helpers de plano ─────────────────────────────────────────────────────────

def get_geracoes_mes(usuario_id):
    mes_atual = datetime.now().strftime('%Y-%m')
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as total FROM chat_messages WHERE usuario_id = ? AND role = 'assistant' AND criado_em LIKE ?",
        (usuario_id, f'{mes_atual}%')
    ).fetchone()
    conn.close()
    return row['total'] if row else 0

# ─── Chat ──────────────────────────────────────────────────────────────────────

@app.route('/chat')
@login_required
def chat():
    geracoes = get_geracoes_mes(current_user.id)
    tem_plano = current_user.assinatura_ativa or current_user.is_admin
    limite_atingido = not tem_plano and geracoes >= LIMITE_GRATIS
    return render_template('chat.html',
                           geracoes=geracoes,
                           limite=LIMITE_GRATIS,
                           limite_atingido=limite_atingido,
                           tem_plano=tem_plano,
                           plano=current_user.plano)


@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    import traceback

    if not current_user.assinatura_ativa and not current_user.is_admin:
        geracoes = get_geracoes_mes(current_user.id)
        if geracoes >= LIMITE_GRATIS:
            return jsonify({'erro': 'limite_atingido', 'geracoes': geracoes}), 403

    data = request.json
    messages = data.get('messages', [])
    if not messages:
        return jsonify({'erro': 'Mensagem vazia'}), 400

    conn = get_db()
    conn.execute(
        "INSERT INTO chat_messages (usuario_id, role, content, criado_em) VALUES (?, ?, ?, ?)",
        (current_user.id, 'user', messages[-1]['content'],
         datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    conn.commit()
    conn.close()

    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return jsonify({'erro': 'ANTHROPIC_API_KEY não configurada no servidor'}), 500

    try:
        c = Anthropic(api_key=api_key, timeout=120.0)
        response = c.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            messages=messages
        )
        resposta = response.content[0].text
    except Exception as e:
        erro_detalhado = f"{type(e).__name__}: {str(e)}"
        print("ERRO API:", traceback.format_exc())
        return jsonify({'erro': erro_detalhado}), 500

    conn2 = get_db()
    conn2.execute(
        "INSERT INTO chat_messages (usuario_id, role, content, criado_em) VALUES (?, ?, ?, ?)",
        (current_user.id, 'assistant', resposta,
         datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    conn2.commit()
    conn2.close()

    return jsonify({'text': resposta})

# ─── Planejamento Anual ────────────────────────────────────────────────────────

@app.route('/planejamento')
@login_required
def planejamento():
    if not current_user.assinatura_ativa and not current_user.is_admin:
        return redirect(url_for('planos'))
    return render_template('planejamento.html')


@app.route('/api/planejamento', methods=['POST'])
@login_required
def api_planejamento():
    if not current_user.assinatura_ativa and not current_user.is_admin:
        return jsonify({'erro': 'Plano necessário'}), 403

    data = request.json
    disciplina    = data.get('disciplina', '')
    turma         = data.get('turma', '')
    ano           = data.get('ano', str(datetime.now().year))
    aulas_semana  = int(data.get('aulas_semana', 2))
    inicio        = data.get('inicio', f'01/02/{ano}')
    fim           = data.get('fim',   f'30/11/{ano}')

    prompt = f"""Crie um planejamento anual completo para professor brasileiro.

Dados:
- Disciplina: {disciplina}
- Turma/Série: {turma}
- Ano letivo: {ano}
- Aulas por semana: {aulas_semana}
- Período: {inicio} até {fim}

Gere um planejamento bimestral detalhado seguindo a BNCC com:
- Divisão por bimestre (4 bimestres)
- Conteúdos de cada bimestre
- Habilidades trabalhadas (códigos BNCC quando aplicável)
- Sugestão de avaliações

Formato: texto estruturado e claro, pronto para entregar à coordenação."""

    resposta = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=6000,
        messages=[{"role": "user", "content": prompt}]
    )
    conteudo = resposta.content[0].text

    conn = get_db()
    conn.execute(
        "INSERT INTO planejamento_anual (usuario_id, disciplina, turma, ano, conteudo, criado_em) VALUES (?, ?, ?, ?, ?, ?)",
        (current_user.id, disciplina, turma, ano, conteudo,
         datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    conn.commit()
    conn.close()

    return jsonify({'conteudo': conteudo})


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=False, host='0.0.0.0', port=port)
