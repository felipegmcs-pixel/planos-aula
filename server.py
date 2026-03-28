import os
import io
import json
import secrets
import smtplib
from email.mime.text import MIMEText
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from flask import (Flask, render_template, request, send_file,
                   jsonify, redirect, url_for, flash, Response, stream_with_context)
from flask_login import (LoginManager, UserMixin, login_user,
                         logout_user, login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from anthropic import Anthropic
from docx import Document
from docx.shared import Pt, RGBColor, Cm, Inches
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

# ── Gemini (Google) — usado se GEMINI_API_KEY estiver configurada ──────────────
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
_gemini_model  = None
if GEMINI_API_KEY:
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        _gemini_model = genai  # referência ao módulo configurado
        print('✓ Gemini configurado com sucesso')
    except Exception as _ge:
        print(f'⚠ Gemini não carregou: {_ge}')
        _gemini_model = None

MP_ACCESS_TOKEN = os.environ.get('MP_ACCESS_TOKEN', '')
MP_PUBLIC_KEY   = os.environ.get('MP_PUBLIC_KEY', '')
mp_sdk = _mp_SDK(MP_ACCESS_TOKEN) if (MP_ACCESS_TOKEN and _mp_SDK) else None

NUPAY_MERCHANT_KEY   = os.environ.get('NUPAY_MERCHANT_KEY', '')
NUPAY_MERCHANT_TOKEN = os.environ.get('NUPAY_MERCHANT_TOKEN', '')
NUPAY_API_URL        = 'https://api.spinpay.com.br'   # produção
# NUPAY_API_URL      = 'https://sandbox-api.spinpay.com.br'  # testes

SITE_URL    = os.environ.get('SITE_URL', 'http://localhost:5001')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', '')

SMTP_HOST  = os.environ.get('SMTP_HOST', '')
SMTP_PORT  = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER  = os.environ.get('SMTP_USER', '')
SMTP_PASS  = os.environ.get('SMTP_PASS', '')
FROM_EMAIL = os.environ.get('FROM_EMAIL', SMTP_USER)

PLANOS = {
    'basic':        {'nome': 'Basic',    'preco': 39.00,  'dias': 30},
    'basic_anual':  {'nome': 'Basic',    'preco': 390.00, 'dias': 365},
    'pro':          {'nome': 'Pro',      'preco': 59.00,  'dias': 30},
    'pro_anual':    {'nome': 'Pro',      'preco': 590.00, 'dias': 365},
}

STRIPE_SECRET_KEY    = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
STRIPE_PRICES = {
    'basic':       os.environ.get('STRIPE_PRICE_BASIC_MENSAL', ''),
    'basic_anual': os.environ.get('STRIPE_PRICE_BASIC_ANUAL', ''),
    'pro':         os.environ.get('STRIPE_PRICE_PRO_MENSAL', ''),
    'pro_anual':   os.environ.get('STRIPE_PRICE_PRO_ANUAL', ''),
}

LIMITE_GRATIS = 5  # gerações gratuitas por mês no plano grátis

SYSTEM_PROMPT = """Você é o ProfessorIA, assistente especializado em ajudar professores brasileiros.

Você cria materiais pedagógicos de alta qualidade, incluindo:
- Planos de aula completos (objetivos, conteúdo, metodologia, avaliação)
- Provas e avaliações (questões abertas e múltipla escolha, com gabarito)
- Caça-palavras (lista de palavras + grade de letras formatada)
- Cruzadinhas (grade com pistas horizontal e vertical, gabarito)
- Mapas mentais (estrutura em árvore com ramos e sub-ramos)
- Atividades e exercícios lúdicos
- Planejamento anual (distribuição por bimestre)
- Resumos de conteúdo para alunos
- Rubricas de avaliação
- Bilhetes para os pais

ADAPTAÇÕES PARA NEE (Necessidades Educacionais Especiais):
Quando o professor pedir material adaptado, aplique as seguintes diretrizes:

- Deficiência Intelectual (DI): linguagem extremamente simples (nível de 6-8 anos), frases curtas (máx 10 palavras), instruções passo a passo numeradas, repetição dos conceitos principais, sem abstração. Avaliação com critérios diferenciados.
- TEA (Transtorno do Espectro Autista): rotina clara e previsível, instruções objetivas sem duplo sentido, evitar linguagem figurada, estrutura visual definida, antecipação das etapas, tópicos específicos e delimitados.
- TDAH: atividades curtas (máx 15 min cada), muita variação de formato, uso de negrito para pontos principais, pausas explícitas, recompensas e gamificação, tarefas com checkboxes.
- Dislexia: abordagem multissensorial (visual + auditivo), fonética explícita, fontes espaçadas, frases curtas, evitar paredes de texto, sugestão de leitura em voz alta.
- Baixa Visão: descrições detalhadas de tudo que seria visual, alto contraste nas instruções, evitar referências como "veja a figura", descrever imagens por extenso.
- CAA (Comunicação Alternativa): usar palavras-chave simples, estrutura de prancha de comunicação, símbolos descritos por texto, frases no formato sujeito+verbo+objeto.

CAÇA-PALAVRAS — geração direta:
Quando pedirem um caça-palavras, gere imediatamente com a seguinte estrutura:

1. Cabeçalho com: Nome: _____________ (use exatamente underscores simples, sem barras invertidas) e Data: ___/___/___
2. Instruções breves
3. Lista das palavras a encontrar em tabela Markdown (mínimo 12 palavras, 3 colunas)
4. Grade de letras 15×15 dentro de um bloco de código (``` ```) para preservar espaçamento
5. As palavras devem aparecer na grade em MAIÚSCULAS
6. Preencha os espaços vazios com letras aleatórias
7. Gabarito em tabela Markdown com posição de cada palavra

IMPORTANTE para campos em branco: use underscores diretos SEM barra invertida. Exemplo correto: Nome: _____________ Data: ___/___/___

Para o formato da grade, SEMPRE use bloco de código com letras separadas por espaço simples, uma letra por célula, prefixando cada linha com a letra da linha:
```
A T R I N C H E I R A M P L K
B W A R M I S T I C I O Q Z B
C K L I B E R D A D E X Y Z A
```
Não inclua linha de números de coluna. Use exatamente este formato: letra da linha + espaço + letras separadas por espaço.

CRUZADINHA — geração direta:
Quando pedirem uma cruzadinha, gere imediatamente com a seguinte estrutura:

1. Cabeçalho: Nome: _____________ Data: ___/___/___ (underscores simples, sem barras)
2. Escolha 8 a 12 palavras do tema (3 a 8 letras cada)
3. Monte um grid onde as palavras se cruzam compartilhando letras
4. Represente o grid dentro de um bloco de código (``` ```):
   - Use █ ou # para células bloqueadas (preto)
   - Numere o quadrado inicial de cada palavra (1, 2, 3...)
   - Use _ para cada célula vazia que o aluno deve preencher
5. Liste as pistas em duas seções: **HORIZONTAL** e **VERTICAL**
6. Gabarito em tabela Markdown ao final

Exemplo de grade (dentro de bloco de código):
```
     1  2  3  4  5
  1  _  _  _  _  _
  2  █  1  _  _  █
  3  _  █  2  █  _
  4  _  _  _  _  _
```

MAPA MENTAL — geração direta:
Quando pedirem um mapa mental, gere imediatamente com a seguinte estrutura:

1. Cabeçalho: Nome: _____________ Data: ___/___/___ (underscores simples)
2. Use estrutura de árvore com caracteres Unicode (├──, └──, │) e emojis
3. Estrutura: TEMA CENTRAL → 5-6 ramos principais → 3-4 sub-ramos cada
4. Palavras-chave curtas e objetivas em cada ramo
5. Ao final: seção "💡 PARA APRENDER MAIS" com sugestões de pesquisa

Exemplo de formato:
```
🧠 TEMA CENTRAL
├── 🔵 RAMO 1
│   ├── subtópico 1.1
│   ├── subtópico 1.2
│   └── subtópico 1.3
├── 🟡 RAMO 2
│   ├── subtópico 2.1
│   └── subtópico 2.2
└── 🟢 RAMO 3
    ├── subtópico 3.1
    └── subtópico 3.2
```

Quando o professor pedir um material:
1. Para caça-palavras, cruzadinhas, mapas mentais, planos de aula simples, atividades e bilhetes: gere DIRETAMENTE sem perguntar mais nada se já tiver tema e série
2. Se faltar informação essencial, pergunte apenas o que falta (1 pergunta objetiva)
3. Gere o material completo, bem estruturado e formatado
4. Use linguagem clara e pedagógica, seguindo a BNCC
5. Para materiais NEE, sempre indique no cabeçalho o perfil para o qual foi adaptado

Responda sempre em português brasileiro. Seja prático, objetivo e direto."""

# ─── Helpers de IA (Gemini first, Claude fallback) ────────────────────────────

def _gemini_disponivel():
    return bool(_gemini_model and GEMINI_API_KEY)

def _to_gemini_parts(content):
    """Converte conteúdo de mensagem (str ou lista multimodal) para partes do Gemini."""
    if isinstance(content, str):
        return [content]
    parts = []
    for item in content:
        if item.get('type') == 'text':
            parts.append(item['text'])
        elif item.get('type') == 'image':
            import base64 as _b64
            parts.append({
                'mime_type': item['source']['media_type'],
                'data': _b64.b64decode(item['source']['data'])
            })
    return parts

def chamar_ia_chat(sistema, messages):
    """Chama Gemini se disponível, senão usa Claude. Suporta mensagens multimodais."""
    if _gemini_disponivel():
        try:
            import google.generativeai as genai
            historico = []
            for m in messages[:-1]:
                role = 'user' if m['role'] == 'user' else 'model'
                historico.append({'role': role, 'parts': _to_gemini_parts(m['content'])})
            gm = genai.GenerativeModel(
                model_name='gemini-1.5-pro',
                system_instruction=sistema
            )
            chat = gm.start_chat(history=historico)
            resp = chat.send_message(_to_gemini_parts(messages[-1]['content']))
            return resp.text
        except Exception as e:
            print(f'Gemini falhou, usando Claude: {e}')

    # Fallback: Claude via HTTP direto (suporta conteúdo multimodal nativamente)
    import requests as req_lib
    api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('Nenhuma API de IA configurada (GEMINI_API_KEY ou ANTHROPIC_API_KEY)')
    r = req_lib.post(
        'https://api.anthropic.com/v1/messages',
        json={'model': 'claude-sonnet-4-6', 'max_tokens': 4000,
              'system': sistema, 'messages': messages},
        headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01',
                 'content-type': 'application/json'},
        timeout=120
    )
    if r.status_code != 200:
        raise RuntimeError(f'Claude API {r.status_code}: {r.text[:300]}')
    return r.json()['content'][0]['text']


def chamar_ia_simples(prompt):
    """Chama Gemini se disponível, senão usa Claude. Para prompts únicos (sem histórico)."""
    if _gemini_disponivel():
        try:
            import google.generativeai as genai
            gm = genai.GenerativeModel('gemini-1.5-pro')
            resp = gm.generate_content(prompt)
            return resp.text
        except Exception as e:
            print(f'Gemini falhou, usando Claude: {e}')

    # Fallback: Claude SDK
    resposta = client.messages.create(
        model='claude-sonnet-4-6',
        max_tokens=4000,
        messages=[{'role': 'user', 'content': prompt}]
    )
    return resposta.content[0].text

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
    conn.execute('''
        CREATE TABLE IF NOT EXISTS reset_tokens (
            id         SERIAL PRIMARY KEY,
            usuario_id INTEGER,
            token      TEXT,
            expira_em  TEXT,
            usado      INTEGER DEFAULT 0
        )
    ''')
    conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS escola_template TEXT DEFAULT ''")
    conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS onboarding_done INTEGER DEFAULT 0")
    conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS escola_nome TEXT DEFAULT ''")
    conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS professor_nome TEXT DEFAULT ''")
    conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS logo_path TEXT DEFAULT ''")
    conn.commit()
    conn.close()

init_db()

# ─── Modelo de usuário ────────────────────────────────────────────────────────

class Usuario(UserMixin):
    def __init__(self, row):
        self.id              = row['id']
        self.nome            = row['nome']
        self.email           = row['email']
        self.plano           = row['plano']
        self.ativo           = row['ativo']
        self.valido_ate      = row['valido_ate']
        self.escola_template = row.get('escola_template', '') or ''
        self.onboarding_done = row.get('onboarding_done', 0) or 0
        self.escola_nome     = row.get('escola_nome', '') or ''
        self.professor_nome  = row.get('professor_nome', '') or ''
        self.logo_path       = row.get('logo_path', '') or ''

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
            return redirect(url_for('chat'))
        return f(*args, **kwargs)
    return decorated

# ─── Email helper ─────────────────────────────────────────────────────────────

def enviar_email(to, subject, body_html):
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASS:
        return False
    try:
        msg = MIMEText(body_html, 'html', 'utf-8')
        msg['Subject'] = subject
        msg['From'] = FROM_EMAIL
        msg['To'] = to
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.ehlo(); s.starttls(); s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(FROM_EMAIL, [to], msg.as_string())
        return True
    except Exception as e:
        print(f'Email error: {e}')
        return False

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

    texto = chamar_ia_simples(prompt).strip()
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
        return redirect(url_for('chat'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        conn  = get_db()
        row   = conn.execute('SELECT * FROM usuarios WHERE email = ?', (email,)).fetchone()
        conn.close()
        if row and check_password_hash(row['senha'], senha):
            login_user(Usuario(row))
            return redirect(url_for('chat'))
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
        return redirect(url_for('chat'))
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
        return redirect(url_for('chat'))
    return render_template('cadastro.html')

# ─── Recuperação de senha ─────────────────────────────────────────────────────

@app.route('/esqueci-senha', methods=['GET', 'POST'])
def esqueci_senha():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        conn = get_db()
        row = conn.execute("SELECT id FROM usuarios WHERE email = ?", (email,)).fetchone()
        if row:
            token = secrets.token_urlsafe(32)
            expira = (datetime.now() + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S')
            conn.execute("INSERT INTO reset_tokens (usuario_id, token, expira_em, usado) VALUES (?, ?, ?, 0)",
                        (row['id'], token, expira))
            conn.commit()
            link = f"{SITE_URL}/redefinir-senha/{token}"
            enviado = enviar_email(email, 'ProfessorIA — Redefinição de senha',
                f'<p>Clique para redefinir sua senha (válido por 2h):</p><p><a href="{link}">{link}</a></p>')
            if enviado:
                flash('Email enviado! Verifique sua caixa de entrada.', 'ok')
            else:
                flash(f'Link de redefinição: {link}', 'ok')
        else:
            flash('Se esse email estiver cadastrado, você receberá as instruções.', 'ok')
        conn.close()
        return redirect(url_for('esqueci_senha'))
    return render_template('esqueci_senha.html')

@app.route('/redefinir-senha/<token>', methods=['GET', 'POST'])
def redefinir_senha(token):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM reset_tokens WHERE token = ? AND usado = 0", (token,)).fetchone()
    if not row:
        conn.close()
        flash('Link inválido ou já utilizado.', 'erro')
        return redirect(url_for('login'))
    if datetime.strptime(row['expira_em'], '%Y-%m-%d %H:%M:%S') < datetime.now():
        conn.close()
        flash('Link expirado. Solicite um novo.', 'erro')
        return redirect(url_for('esqueci_senha'))
    if request.method == 'POST':
        senha = request.form.get('senha', '')
        confirma = request.form.get('confirma', '')
        if len(senha) < 6:
            flash('Senha deve ter pelo menos 6 caracteres.', 'erro')
            conn.close()
            return render_template('redefinir_senha.html', token=token)
        if senha != confirma:
            flash('As senhas não coincidem.', 'erro')
            conn.close()
            return render_template('redefinir_senha.html', token=token)
        conn.execute("UPDATE usuarios SET senha = ? WHERE id = ?",
                    (generate_password_hash(senha), row['usuario_id']))
        conn.execute("UPDATE reset_tokens SET usado = 1 WHERE id = ?", (row['id'],))
        conn.commit()
        conn.close()
        flash('Senha atualizada com sucesso!', 'ok')
        return redirect(url_for('login'))
    conn.close()
    return render_template('redefinir_senha.html', token=token)

# ─── Planos e Pagamento ───────────────────────────────────────────────────────

@app.route('/planos')
@login_required
def planos():
    return render_template('planos.html', planos=PLANOS,
                           assinatura_ativa=current_user.assinatura_ativa,
                           valido_ate=current_user.valido_ate,
                           plano_atual=current_user.plano)

# ─── Stripe ───────────────────────────────────────────────────────────────────

@app.route('/stripe/checkout/<plano_id>')
@login_required
def stripe_checkout(plano_id):
    if plano_id not in PLANOS:
        flash(f'Plano inválido: {plano_id}', 'erro')
        return redirect(url_for('chat'))
    if not STRIPE_SECRET_KEY:
        flash('Chave Stripe não configurada no servidor (STRIPE_SECRET_KEY).', 'erro')
        return redirect(url_for('chat'))
    price_id = STRIPE_PRICES.get(plano_id, '')
    if not price_id:
        flash(f'Price ID não configurado para o plano "{plano_id}" (STRIPE_PRICE_{plano_id.upper()}).', 'erro')
        return redirect(url_for('chat'))
    try:
        import stripe as stripe_lib
        stripe_lib.api_key = STRIPE_SECRET_KEY
        session = stripe_lib.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{'price': price_id, 'quantity': 1}],
            mode='subscription',
            customer_email=current_user.email,
            metadata={'usuario_id': str(current_user.id), 'plano_id': plano_id},
            success_url=f"{SITE_URL}/stripe/sucesso?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{SITE_URL}/planos",
        )
        return redirect(session.url, code=303)
    except Exception as e:
        flash(f'Erro Stripe: {str(e)}', 'erro')
        return redirect(url_for('chat'))


@app.route('/stripe/sucesso')
@login_required
def stripe_sucesso():
    session_id = request.args.get('session_id', '')
    if session_id and STRIPE_SECRET_KEY:
        try:
            import stripe as stripe_lib
            stripe_lib.api_key = STRIPE_SECRET_KEY
            session = stripe_lib.checkout.Session.retrieve(session_id)
            if session.payment_status in ('paid', 'no_payment_required'):
                plano_id = session.metadata.get('plano_id', 'basic')
                plano    = PLANOS.get(plano_id, PLANOS['basic'])
                valido   = (datetime.now() + timedelta(days=plano['dias'])).strftime('%Y-%m-%d')
                conn = get_db()
                conn.execute(
                    "UPDATE usuarios SET plano=?, ativo=1, valido_ate=? WHERE id=?",
                    (plano_id, valido, current_user.id)
                )
                conn.commit()
                # Refresh session user so chat/banner updates immediately
                row = conn.execute('SELECT * FROM usuarios WHERE id=?', (current_user.id,)).fetchone()
                conn.close()
                if row:
                    login_user(Usuario(row))
            else:
                conn = get_db()
                conn.close()
        except Exception:
            pass
    return render_template('pagamento_status.html',
                           status='sucesso',
                           titulo='PAGAMENTO APROVADO',
                           mensagem='Sua assinatura está ativa. Bom trabalho!')


@app.route('/stripe/webhook', methods=['POST'])
def stripe_webhook():
    import stripe as stripe_lib
    stripe_lib.api_key = STRIPE_SECRET_KEY
    payload = request.get_data()
    sig     = request.headers.get('Stripe-Signature', '')
    try:
        event = stripe_lib.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception:
        return '', 400

    if event['type'] == 'checkout.session.completed':
        session  = event['data']['object']
        plano_id = session.get('metadata', {}).get('plano_id', 'basic')
        uid      = session.get('metadata', {}).get('usuario_id')
        if uid and plano_id in PLANOS:
            plano  = PLANOS[plano_id]
            valido = (datetime.now() + timedelta(days=plano['dias'])).strftime('%Y-%m-%d')
            conn   = get_db()
            conn.execute(
                "UPDATE usuarios SET plano=?, ativo=1, valido_ate=? WHERE id=?",
                (plano_id, valido, int(uid))
            )
            conn.commit()
            conn.close()

    elif event['type'] in ('customer.subscription.deleted', 'customer.subscription.paused'):
        sub = event['data']['object']
        # customer_email is not on the subscription object — retrieve customer
        customer_id = sub.get('customer', '')
        email = ''
        if customer_id:
            try:
                customer = stripe_lib.Customer.retrieve(customer_id)
                email = customer.get('email', '') or ''
            except Exception:
                pass
        if email:
            conn = get_db()
            conn.execute("UPDATE usuarios SET plano='', ativo=0, valido_ate='' WHERE email=?", (email,))
            conn.commit()
            conn.close()

    return '', 200


@app.route('/pagamento/criar/<plano_id>', methods=['POST'])
@login_required
def pagamento_criar(plano_id):
    if plano_id not in PLANOS:
        return redirect(url_for('chat'))

    if not mp_sdk:
        flash('Pagamento não configurado ainda. Entre em contato com o suporte.')
        return redirect(url_for('chat'))

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
        return redirect(url_for('chat'))

    return redirect(pref["init_point"])

@app.route('/pagamento/checkout/<plano_id>')
@login_required
def pagamento_checkout(plano_id):
    if plano_id not in PLANOS:
        return redirect(url_for('chat'))
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
        return redirect(url_for('chat'))

    if not NUPAY_MERCHANT_KEY or not NUPAY_MERCHANT_TOKEN:
        flash('NuPay não configurado ainda. Escolha outro método de pagamento.')
        return redirect(url_for('chat'))

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
        return redirect(url_for('chat'))

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
def index():
    return render_template('index.html')

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

@app.route('/api/salvar-template', methods=['POST'])
@login_required
def salvar_template():
    data = request.json or {}
    template = data.get('template', '').strip()
    conn = get_db()
    conn.execute("UPDATE usuarios SET escola_template = ?, onboarding_done = 1 WHERE id = ?",
                (template, current_user.id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

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
                           plano=current_user.plano,
                           onboarding_done=current_user.onboarding_done)


@app.route('/api/processar-arquivo', methods=['POST'])
@login_required
def processar_arquivo():
    """Extrai texto de PDFs, DOCX e TXT enviados pelo professor."""
    if 'arquivo' not in request.files:
        return jsonify({'erro': 'Nenhum arquivo enviado'}), 400

    f    = request.files['arquivo']
    nome = f.filename or 'arquivo'
    mime = f.content_type or ''
    dados = f.read()

    MAX_SIZE = 10 * 1024 * 1024  # 10 MB
    if len(dados) > MAX_SIZE:
        return jsonify({'erro': 'Arquivo muito grande (máximo 10 MB)'}), 400

    nome_lower = nome.lower()

    # PDF
    if mime == 'application/pdf' or nome_lower.endswith('.pdf'):
        try:
            import pdfplumber, io as _io
            texto = ''
            with pdfplumber.open(_io.BytesIO(dados)) as pdf:
                for pg in pdf.pages[:30]:
                    t = pg.extract_text()
                    if t:
                        texto += t + '\n'
            if not texto.strip():
                return jsonify({'erro': 'Não foi possível extrair texto deste PDF.'}), 400
            return jsonify({'tipo': 'documento', 'texto': texto[:20000], 'nome': nome})
        except Exception as e:
            return jsonify({'erro': f'Erro ao ler PDF: {str(e)}'}), 500

    # DOCX
    if (mime == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            or nome_lower.endswith('.docx')):
        try:
            from docx import Document as _Doc
            import io as _io
            doc = _Doc(_io.BytesIO(dados))
            texto = '\n'.join(p.text for p in doc.paragraphs if p.text.strip())
            return jsonify({'tipo': 'documento', 'texto': texto[:20000], 'nome': nome})
        except Exception as e:
            return jsonify({'erro': f'Erro ao ler DOCX: {str(e)}'}), 500

    # TXT / CSV
    if mime.startswith('text/') or nome_lower.endswith(('.txt', '.csv', '.md')):
        try:
            texto = dados.decode('utf-8', errors='ignore')
            return jsonify({'tipo': 'documento', 'texto': texto[:20000], 'nome': nome})
        except Exception as e:
            return jsonify({'erro': f'Erro ao ler arquivo: {str(e)}'}), 500

    return jsonify({'erro': 'Tipo não suportado via upload. Imagens são enviadas diretamente — use JPG, PNG ou WEBP.'}), 400


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
    anexo   = data.get('anexo')   # { tipo, base64, mime, nome } ou { tipo, texto, nome }
    if not messages:
        return jsonify({'erro': 'Mensagem vazia'}), 400

    # Extrai conteúdo de texto da última mensagem para salvar no DB
    last_content = messages[-1].get('content', '')
    if isinstance(last_content, list):
        text_parts = [p['text'] for p in last_content if p.get('type') == 'text']
        db_content = ' '.join(text_parts)
        if anexo:
            db_content += f' [arquivo: {anexo.get("nome", "")}]'
    else:
        db_content = last_content

    conn = get_db()
    conn.execute(
        "INSERT INTO chat_messages (usuario_id, role, content, criado_em) VALUES (?, ?, ?, ?)",
        (current_user.id, 'user', db_content,
         datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    conn.commit()
    conn.close()

    # Prepara sistema e mensagens antes de entrar no generator
    sistema = SYSTEM_PROMPT
    if current_user.escola_template:
        sistema += f"\n\nO professor usa o seguinte esqueleto/modelo padrão de plano de aula da sua escola. SEMPRE que gerar planos de aula, use EXATAMENTE essa estrutura como base:\n\n{current_user.escola_template}"

    if anexo:
        tipo_anexo = anexo.get('tipo')
        if tipo_anexo == 'documento':
            nome_doc = anexo.get('nome', 'documento')
            texto_doc = anexo.get('texto', '')
            sistema += f"\n\n=== DOCUMENTO ENVIADO PELO PROFESSOR: {nome_doc} ===\n{texto_doc}\n=== FIM DO DOCUMENTO ===\n\nUse este documento como referência e base estrutural para criar o material solicitado."
        elif tipo_anexo == 'image':
            b64    = anexo.get('base64', '')
            mime_t = anexo.get('mime', 'image/jpeg')
            texto_msg = messages[-1].get('content', '')
            if not isinstance(texto_msg, list):
                texto_msg = texto_msg or 'Use esta imagem como base para criar o material.'
            messages = messages[:-1] + [{
                'role': 'user',
                'content': [
                    {'type': 'image', 'source': {'type': 'base64', 'media_type': mime_t, 'data': b64}},
                    {'type': 'text',  'text': texto_msg if isinstance(texto_msg, str) else ' '.join(p.get('text','') for p in texto_msg if p.get('type')=='text')}
                ]
            }]

    usuario_id = current_user.id

    @stream_with_context
    def generate():
        chunks = []
        try:
            # Tenta Gemini streaming primeiro
            if _gemini_disponivel():
                try:
                    import google.generativeai as genai
                    historico_g = []
                    for m in messages[:-1]:
                        role = 'user' if m['role'] == 'user' else 'model'
                        historico_g.append({'role': role, 'parts': _to_gemini_parts(m['content'])})
                    gm = genai.GenerativeModel(model_name='gemini-1.5-pro', system_instruction=sistema)
                    chat_g = gm.start_chat(history=historico_g)
                    resp_g = chat_g.send_message(_to_gemini_parts(messages[-1]['content']), stream=True)
                    for chunk in resp_g:
                        text = getattr(chunk, 'text', '') or ''
                        if text:
                            chunks.append(text)
                            yield f"data: {json.dumps({'chunk': text})}\n\n"
                    yield "data: [DONE]\n\n"
                    resposta = ''.join(chunks)
                    conn2 = get_db()
                    conn2.execute(
                        "INSERT INTO chat_messages (usuario_id, role, content, criado_em) VALUES (?, ?, ?, ?)",
                        (usuario_id, 'assistant', resposta, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                    )
                    conn2.commit(); conn2.close()
                    return
                except Exception as e:
                    print(f'Gemini streaming falhou, usando Claude: {e}')
                    chunks = []  # reset

            # Claude streaming
            with client.messages.stream(
                model='claude-sonnet-4-6',
                max_tokens=8000,
                system=sistema,
                messages=messages
            ) as stream:
                for text in stream.text_stream:
                    chunks.append(text)
                    yield f"data: {json.dumps({'chunk': text})}\n\n"

            yield "data: [DONE]\n\n"
            resposta = ''.join(chunks)
            conn2 = get_db()
            conn2.execute(
                "INSERT INTO chat_messages (usuario_id, role, content, criado_em) VALUES (?, ?, ?, ?)",
                (usuario_id, 'assistant', resposta, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )
            conn2.commit(); conn2.close()

        except Exception as e:
            print("ERRO STREAM:", traceback.format_exc())
            yield f"data: {json.dumps({'erro': str(e)})}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )


@app.route('/api/transcribe', methods=['POST'])
@login_required
def api_transcribe():
    """Transcreve áudio do usuário usando OpenAI Whisper."""
    if 'audio' not in request.files:
        return jsonify({'erro': 'Nenhum arquivo de áudio enviado'}), 400

    audio_file = request.files['audio']
    api_key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not api_key:
        return jsonify({'erro': 'OPENAI_API_KEY não configurada no servidor'}), 500

    try:
        import requests as req_lib
        fname = audio_file.filename or 'audio.webm'
        ctype = audio_file.content_type or 'audio/webm'
        files = {'file': (fname, audio_file.read(), ctype)}
        data  = {'model': 'whisper-1', 'language': 'pt'}
        r = req_lib.post(
            'https://api.openai.com/v1/audio/transcriptions',
            headers={'Authorization': f'Bearer {api_key}'},
            files=files, data=data, timeout=30
        )
        if r.status_code != 200:
            return jsonify({'erro': f'Whisper {r.status_code}: {r.text[:200]}'}), 500
        texto = r.json().get('text', '').strip()
        return jsonify({'texto': texto})
    except Exception as e:
        return jsonify({'erro': str(e)}), 500


@app.route('/api/tts', methods=['POST'])
@login_required
def api_tts():
    """Converte texto em áudio usando OpenAI TTS."""
    data = request.json or {}
    texto = data.get('texto', '').strip()[:4000]
    voz   = data.get('voz', 'nova')
    VOZES_VALIDAS = {'alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'}
    if voz not in VOZES_VALIDAS:
        voz = 'nova'
    if not texto:
        return jsonify({'erro': 'Texto vazio'}), 400

    api_key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not api_key:
        return jsonify({'erro': 'OPENAI_API_KEY não configurada no servidor'}), 500

    try:
        import requests as req_lib
        r = req_lib.post(
            'https://api.openai.com/v1/audio/speech',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={'model': 'tts-1', 'input': texto, 'voice': voz},
            timeout=60
        )
        if r.status_code != 200:
            return jsonify({'erro': f'TTS {r.status_code}: {r.text[:200]}'}), 500
        from flask import Response
        return Response(r.content, mimetype='audio/mpeg',
                        headers={'Content-Disposition': 'inline; filename=resposta.mp3'})
    except Exception as e:
        return jsonify({'erro': str(e)}), 500


# ─── Gerador de DOCX com design ProfessorIA ────────────────────────────────────
# Inspirado nas fichas pedagógicas dos exemplos: cabeçalho de marca, campos do
# aluno, seções com caixas, grid monospace, rodapé — tudo black & white p/ impressão.

def _pr(paragraph, text, bold=False, size=10, color='0a0a0a',
        italic=False, font='Arial', underline=False):
    """Adiciona um run estilizado a um parágrafo."""
    run = paragraph.add_run(text)
    run.bold = bold
    run.italic = italic
    run.underline = underline
    run.font.name = font
    run.font.size = Pt(size)
    r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
    run.font.color.rgb = RGBColor(r, g, b)
    return run

def _pr_fmt(paragraph, text, size=10, font='Arial'):
    """Adiciona texto com suporte a **bold**, *italic* e `code` inline."""
    import re
    parts = re.split(r'(\*\*.*?\*\*|\*[^*]+?\*|`[^`]+`)', text)
    for part in parts:
        if part.startswith('**') and part.endswith('**') and len(part) > 4:
            _pr(paragraph, part[2:-2], bold=True, size=size, font=font)
        elif part.startswith('*') and part.endswith('*') and len(part) > 2:
            _pr(paragraph, part[1:-1], italic=True, size=size, font=font)
        elif part.startswith('`') and part.endswith('`') and len(part) > 2:
            _pr(paragraph, part[1:-1], font='Courier New', size=size - 1, color='333333')
        elif part:
            _pr(paragraph, part, size=size, font=font)

def _pia_no_borders(table):
    """Remove todas as bordas de uma tabela."""
    for row in table.rows:
        for cell in row.cells:
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            tcBorders = OxmlElement('w:tcBorders')
            for side in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
                el = OxmlElement(f'w:{side}')
                el.set(qn('w:val'), 'none')
                el.set(qn('w:sz'), '0')
                el.set(qn('w:color'), 'auto')
                tcBorders.append(el)
            tcPr.append(tcBorders)

def _pia_hrule(doc, thick=True, color='0a0a0a'):
    """Linha horizontal fina usando borda inferior de parágrafo."""
    p = doc.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bot = OxmlElement('w:bottom')
    bot.set(qn('w:val'), 'single')
    bot.set(qn('w:sz'), '16' if thick else '6')
    bot.set(qn('w:space'), '1')
    bot.set(qn('w:color'), color)
    pBdr.append(bot)
    pPr.append(pBdr)
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(6)

def _pia_section_box(doc, title):
    """Caixa de seção: fundo preto, texto branco — como nos exemplos."""
    sp = doc.add_paragraph()
    sp.paragraph_format.space_after = Pt(2)
    t = doc.add_table(rows=1, cols=1)
    cell = t.cell(0, 0)
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(5)
    p.paragraph_format.space_after = Pt(5)
    p.paragraph_format.left_indent = Cm(0.25)
    _pr(p, '  ' + title.upper(), bold=True, size=10, color='FFFFFF')
    set_cell_bg(cell, '0a0a0a')
    # bordas pretas
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement('w:tcBorders')
    for side in ('top', 'left', 'bottom', 'right'):
        el = OxmlElement(f'w:{side}')
        el.set(qn('w:val'), 'single')
        el.set(qn('w:sz'), '6')
        el.set(qn('w:color'), '0a0a0a')
        tcBorders.append(el)
    tcPr.append(tcBorders)
    ep = doc.add_paragraph()
    ep.paragraph_format.space_after = Pt(3)

def _is_letter_grid(code):
    """Returns True if code block is a caça-palavras letter grid."""
    import re
    lines = [l for l in code.strip().split('\n') if l.strip()]
    if len(lines) < 5:
        return False
    letter_lines = 0
    for line in lines:
        tokens = line.split()
        if not tokens:
            continue
        if all(re.match(r'^\d+$', t) for t in tokens):
            continue  # skip number header rows
        body = tokens[1:] if (len(tokens) > 1 and len(tokens[0]) == 1 and tokens[0].isalpha()) else tokens
        single = sum(1 for t in body if len(t) == 1 and t.isalpha())
        if single >= 8:
            letter_lines += 1
    return letter_lines >= 5


def _pia_caca_palavras_table(doc, code):
    """Renders a caça-palavras letter grid as a proper bordered Word table."""
    import re
    lines = [l for l in code.strip().split('\n') if l.strip()]

    grid = []
    for line in lines:
        tokens = line.split()
        if not tokens:
            continue
        if all(re.match(r'^\d+$', t) for t in tokens):
            continue  # skip column-number header
        if len(tokens[0]) == 1 and tokens[0].isalpha() and len(tokens) > 8:
            row = [t.upper() for t in tokens[1:] if len(t) == 1 and t.isalpha()]
        else:
            row = [t.upper() for t in tokens if len(t) == 1 and t.isalpha()]
        if len(row) >= 8:
            grid.append(row)

    if not grid:
        _pia_code_block(doc, code)
        return

    n_rows = len(grid)
    n_cols = max(len(r) for r in grid)

    lbl = doc.add_paragraph()
    lbl.paragraph_format.space_before = Pt(6)
    lbl.paragraph_format.space_after  = Pt(3)
    _pr(lbl, 'GRADE DE LETRAS', bold=True, size=8, color='333333')

    tbl = doc.add_table(rows=n_rows, cols=n_cols)
    cell_w = Cm(15.5 / n_cols)

    for ri, row_letters in enumerate(grid):
        for ci in range(n_cols):
            cell = tbl.cell(ri, ci)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after  = Pt(2)
            letter = row_letters[ci] if ci < len(row_letters) else ' '
            _pr(p, letter, bold=True, size=10, color='0a0a0a')
            cell.width = cell_w
            tc    = cell._tc
            tcPr  = tc.get_or_add_tcPr()
            tcBorders = OxmlElement('w:tcBorders')
            for side in ('top', 'left', 'bottom', 'right'):
                el = OxmlElement(f'w:{side}')
                el.set(qn('w:val'), 'single')
                el.set(qn('w:sz'), '4')
                el.set(qn('w:color'), 'bbbbbb')
                tcBorders.append(el)
            tcPr.append(tcBorders)

    ep = doc.add_paragraph()
    ep.paragraph_format.space_after = Pt(8)


def _pia_code_block(doc, code):
    """Bloco monospace para grades de caça-palavras, cruzadinhas, mapas mentais."""
    t = doc.add_table(rows=1, cols=1)
    cell = t.cell(0, 0)
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(4)
    lines = code.split('\n')
    for idx, ln in enumerate(lines):
        if idx > 0:
            p.add_run().add_break()
        _pr(p, ln, font='Courier New', size=8, color='0a0a0a')
    p.paragraph_format.space_after = Pt(4)
    set_cell_bg(cell, 'f5f5f2')
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement('w:tcBorders')
    for side in ('top', 'left', 'bottom', 'right'):
        el = OxmlElement(f'w:{side}')
        el.set(qn('w:val'), 'single')
        el.set(qn('w:sz'), '4')
        el.set(qn('w:color'), 'aaaaaa')
        tcBorders.append(el)
    tcPr.append(tcBorders)
    ep = doc.add_paragraph()
    ep.paragraph_format.space_after = Pt(4)

def _pia_md_table(doc, lines):
    """Renderiza tabela Markdown como tabela Word estilizada."""
    import re
    rows = []
    for line in lines:
        stripped = line.strip()
        if re.match(r'^\|[-\s|:]+\|$', stripped):
            continue  # linha separadora do markdown
        cells = [c.strip() for c in stripped.strip('|').split('|')]
        if any(cells):
            rows.append(cells)
    if not rows:
        return
    max_cols = max(len(r) for r in rows)
    t = doc.add_table(rows=len(rows), cols=max_cols)
    t.style = 'Table Grid'
    for ri, row in enumerate(rows):
        for ci in range(max_cols):
            cell = t.cell(ri, ci)
            cell.paragraphs[0].clear()
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(3)
            p.paragraph_format.space_after = Pt(3)
            text = row[ci] if ci < len(row) else ''
            if ri == 0:
                set_cell_bg(cell, 'e8e8e5')
                _pr(p, text, bold=True, size=8, color='0a0a0a')
            else:
                if ri % 2 == 0:
                    set_cell_bg(cell, 'f8f8f5')
                _pr_fmt(p, text, size=9)
    ep = doc.add_paragraph()
    ep.paragraph_format.space_after = Pt(4)

def gerar_docx_pia(texto, meta=None, logo_path=None):
    """
    Gera DOCX com design ProfessorIA™ inspirado nas fichas pedagógicas dos exemplos.
    Black & white — imprime bem em qualquer impressora.
    meta dict: escola, professor, disciplina, bimestre, serie
    """
    import re
    if meta is None:
        meta = {}

    escola    = meta.get('escola', '').strip()
    professor = meta.get('professor', '').strip()
    disciplina = meta.get('disciplina', '').strip()
    bimestre   = meta.get('bimestre', '').strip()
    serie      = meta.get('serie', '').strip()

    doc = Document()

    # Margens A4
    for section in doc.sections:
        section.page_height = Cm(29.7)
        section.page_width  = Cm(21.0)
        section.top_margin    = Cm(1.5)
        section.bottom_margin = Cm(1.5)
        section.left_margin   = Cm(2.0)
        section.right_margin  = Cm(2.0)

    doc.styles['Normal'].font.name = 'Arial'
    doc.styles['Normal'].font.size = Pt(10)

    # ── CABEÇALHO ESCOLAR ──────────────────────────────────────────────────
    # Tabela: [LOGO | DADOS DA ESCOLA | ProfessorIA™ watermark]
    hdr = doc.add_table(rows=1, cols=3)
    _pia_no_borders(hdr)
    hdr.columns[0].width = Cm(3.2)
    hdr.columns[1].width = Cm(12.0)
    hdr.columns[2].width = Cm(2.6)

    # Coluna esquerda: logo ou placeholder
    logo_cell = hdr.cell(0, 0)
    logo_cell._tc.get_or_add_tcPr()
    lp = logo_cell.paragraphs[0]
    lp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    lp.paragraph_format.space_before = Pt(0)
    lp.paragraph_format.space_after  = Pt(0)
    if logo_path:
        try:
            run = lp.add_run()
            run.add_picture(logo_path, width=Cm(2.8))
        except Exception:
            _pr(lp, '[LOGO]', size=7, color='aaaaaa', italic=True)
    else:
        # Placeholder box para logo
        t2 = logo_cell.add_table(rows=1, cols=1)
        t2_c = t2.cell(0, 0)
        t2_c._tc.get_or_add_tcPr()
        t2_p = t2_c.paragraphs[0]
        t2_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        t2_p.paragraph_format.space_before = Pt(14)
        t2_p.paragraph_format.space_after  = Pt(14)
        _pr(t2_p, 'LOGO', size=7, color='aaaaaa', italic=True)
        tc = t2_c._tc
        tcPr = tc.get_or_add_tcPr()
        tcBorders = OxmlElement('w:tcBorders')
        for side in ('top', 'left', 'bottom', 'right'):
            el = OxmlElement(f'w:{side}')
            el.set(qn('w:val'), 'single')
            el.set(qn('w:sz'), '4')
            el.set(qn('w:color'), 'cccccc')
            tcBorders.append(el)
        tcPr.append(tcBorders)

    # Coluna central: nome da escola, disciplina/bimestre, professor
    mid_cell = hdr.cell(0, 1)
    mp = mid_cell.paragraphs[0]
    mp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    mp.paragraph_format.space_before = Pt(0)
    mp.paragraph_format.space_after  = Pt(2)
    if escola:
        _pr(mp, escola.upper(), bold=True, size=13, color='0a0a0a')
    else:
        _pr(mp, 'ESCOLA / INSTITUIÇÃO DE ENSINO', bold=True, size=11, color='555555')

    # Linha 2: "Avaliação de DISCIPLINA — Xº Bimestre"
    mp2 = mid_cell.add_paragraph()
    mp2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    mp2.paragraph_format.space_before = Pt(1)
    mp2.paragraph_format.space_after  = Pt(1)
    partes = []
    if disciplina:
        partes.append(f'Avaliação de {disciplina}')
    if bimestre:
        partes.append(f'{bimestre}º Bimestre')
    if serie:
        partes.append(serie)
    if partes:
        _pr(mp2, '  ·  '.join(partes), bold=False, size=10, color='222222')
    else:
        _pr(mp2, 'Avaliação', bold=False, size=10, color='555555')

    # Linha 3: professor
    mp3 = mid_cell.add_paragraph()
    mp3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    mp3.paragraph_format.space_before = Pt(1)
    mp3.paragraph_format.space_after  = Pt(0)
    if professor:
        _pr(mp3, f'Prof(a). {professor}', italic=True, size=9, color='444444')
    else:
        _pr(mp3, 'Prof(a). ______________________________', italic=False, size=9, color='888880')

    # Coluna direita: marca ProfessorIA™ (pequena, discreta)
    rc = hdr.cell(0, 2)
    pr_cell = rc.paragraphs[0]
    pr_cell.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    pr_cell.paragraph_format.space_before = Pt(0)
    pr_cell.paragraph_format.space_after  = Pt(0)
    _pr(pr_cell, 'Professor', bold=True, size=7, color='bbbbbb')
    _pr(pr_cell, 'IA', bold=True, size=7, color='bbbbbb')
    ps2 = rc.add_paragraph()
    ps2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    ps2.paragraph_format.space_before = Pt(0)
    ps2.paragraph_format.space_after  = Pt(0)
    _pr(ps2, '™', size=6, color='cccccc')

    # Linha separadora grossa
    _pia_hrule(doc, thick=True)

    # ── CAMPOS DO ALUNO ────────────────────────────────────────────────────
    sf = doc.add_table(rows=2, cols=3)
    _pia_no_borders(sf)

    # Linha 1: Nome (largo), Série/Turma, Data
    c_nome = sf.cell(0, 0)
    p_nome = c_nome.paragraphs[0]
    p_nome.paragraph_format.space_before = Pt(3)
    p_nome.paragraph_format.space_after  = Pt(3)
    _pr(p_nome, 'Nome: ', bold=True, size=9, color='0a0a0a')
    _pr(p_nome, '_' * 44, size=9, color='555550')

    c_serie = sf.cell(0, 1)
    p_serie = c_serie.paragraphs[0]
    p_serie.paragraph_format.space_before = Pt(3)
    p_serie.paragraph_format.space_after  = Pt(3)
    label_serie = f'Série/Turma: {serie}' if serie else 'Série/Turma: ___________'
    _pr(p_serie, label_serie, size=9, color='0a0a0a')

    c_data = sf.cell(0, 2)
    p_data = c_data.paragraphs[0]
    p_data.paragraph_format.space_before = Pt(3)
    p_data.paragraph_format.space_after  = Pt(3)
    _pr(p_data, 'Data: ', bold=True, size=9, color='0a0a0a')
    _pr(p_data, '___/___/______', size=9, color='555550')

    # Linha 2: Número, espaço, Nota
    c_num = sf.cell(1, 0)
    p_num = c_num.paragraphs[0]
    p_num.paragraph_format.space_before = Pt(2)
    p_num.paragraph_format.space_after  = Pt(3)
    _pr(p_num, 'Nº: ', bold=True, size=9, color='0a0a0a')
    _pr(p_num, '______', size=9, color='555550')

    c_blank = sf.cell(1, 1)
    p_blank = c_blank.paragraphs[0]
    p_blank.paragraph_format.space_after = Pt(3)
    if bimestre:
        _pr(p_blank, f'{bimestre}º Bimestre', size=9, color='444444', italic=True)

    c_nota = sf.cell(1, 2)
    p_nota = c_nota.paragraphs[0]
    p_nota.paragraph_format.space_before = Pt(2)
    p_nota.paragraph_format.space_after  = Pt(3)
    _pr(p_nota, 'Nota: ', bold=True, size=9, color='0a0a0a')
    _pr(p_nota, '_________', size=9, color='555550')

    _pia_hrule(doc, thick=False, color='555555')

    # ── CONTEÚDO MARKDOWN ─────────────────────────────────────────────────
    lines = texto.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]

        # Bloco de código (``` ... ```)
        if line.strip().startswith('```'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            code_text = '\n'.join(code_lines)
            if _is_letter_grid(code_text):
                _pia_caca_palavras_table(doc, code_text)
            else:
                _pia_code_block(doc, code_text)
            i += 1
            continue

        # Tabela markdown
        if line.strip().startswith('|'):
            tbl_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                tbl_lines.append(lines[i])
                i += 1
            _pia_md_table(doc, tbl_lines)
            continue

        # H1 → título grande centrado
        if line.startswith('# '):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after  = Pt(10)
            _pr(p, line[2:].strip().upper(), bold=True, size=20, color='0a0a0a')

        # H2 → caixa preta de seção
        elif line.startswith('## '):
            _pia_section_box(doc, line[3:].strip())

        # H3 → sub-seção negrito com linha fina
        elif line.startswith('### '):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after  = Pt(2)
            _pr(p, line[4:].strip().upper(), bold=True, size=10, color='0a0a0a')
            pPr = p._p.get_or_add_pPr()
            pBdr = OxmlElement('w:pBdr')
            bot = OxmlElement('w:bottom')
            bot.set(qn('w:val'), 'single'); bot.set(qn('w:sz'), '4')
            bot.set(qn('w:space'), '1');   bot.set(qn('w:color'), 'aaaaaa')
            pBdr.append(bot); pPr.append(pBdr)

        # Lista com marcador
        elif line.startswith('- ') or line.startswith('* '):
            p = doc.add_paragraph(style='List Bullet')
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after  = Pt(1)
            _pr_fmt(p, line[2:].strip())

        # Lista numerada
        elif re.match(r'^\d+[\.\)\:]\s', line):
            m = re.match(r'^\d+[\.\)\:]\s+(.*)', line)
            p = doc.add_paragraph(style='List Number')
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after  = Pt(1)
            _pr_fmt(p, m.group(1) if m else line)

        # Separador ou linha vazia
        elif line.strip() == '' or re.match(r'^-{3,}$', line.strip()):
            ep = doc.add_paragraph()
            ep.paragraph_format.space_after = Pt(3)

        # Texto normal
        else:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after  = Pt(3)
            _pr_fmt(p, line)

        i += 1

    # ── RODAPÉ ────────────────────────────────────────────────────────────
    doc.add_paragraph()
    _pia_hrule(doc, thick=False, color='aaaaaa')
    pf = doc.add_paragraph()
    pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf.paragraph_format.space_before = Pt(0)
    rodape_parts = ['Gerado por ProfessorIA™', datetime.now().strftime('%d/%m/%Y')]
    if escola:
        rodape_parts.append(escola)
    _pr(pf, '  ·  '.join(rodape_parts), size=7, color='888880')

    return doc


@app.route('/api/chat-download', methods=['POST'])
@login_required
def api_chat_download():
    """Converte o texto de uma mensagem do chat em DOCX com design ProfessorIA."""
    import os
    data = request.json or {}
    texto = data.get('texto', '').strip()
    if not texto:
        return jsonify({'erro': 'Texto vazio'}), 400

    meta = {
        'escola':    data.get('escola', current_user.escola_nome).strip(),
        'professor': data.get('professor', current_user.professor_nome).strip(),
        'disciplina': data.get('disciplina', '').strip(),
        'bimestre':   data.get('bimestre', '').strip(),
        'serie':      data.get('serie', '').strip(),
    }

    logo_abs = None
    if current_user.logo_path:
        candidate = os.path.join(os.path.dirname(__file__), current_user.logo_path)
        if os.path.isfile(candidate):
            logo_abs = candidate

    doc = gerar_docx_pia(texto, meta=meta, logo_path=logo_abs)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return send_file(
        buf, as_attachment=True,
        download_name='material-professorIA.docx',
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )


@app.route('/api/config-escola', methods=['GET', 'POST'])
@login_required
def api_config_escola():
    """Salva ou retorna configurações da escola do professor."""
    if request.method == 'GET':
        return jsonify({
            'escola_nome':    current_user.escola_nome,
            'professor_nome': current_user.professor_nome,
            'logo_path':      current_user.logo_path,
        })
    data = request.json or {}
    escola   = data.get('escola_nome', '').strip()
    prof     = data.get('professor_nome', '').strip()
    conn = get_db()
    conn.execute(
        "UPDATE usuarios SET escola_nome=?, professor_nome=? WHERE id=?",
        (escola, prof, current_user.id)
    )
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/upload-logo', methods=['POST'])
@login_required
def api_upload_logo():
    """Recebe a logo da escola como upload e salva em static/logos/."""
    import os, uuid
    f = request.files.get('logo')
    if not f:
        return jsonify({'erro': 'Nenhum arquivo enviado'}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'):
        return jsonify({'erro': 'Formato não suportado. Use PNG, JPG ou SVG.'}), 400
    fname = f'logo_{current_user.id}_{uuid.uuid4().hex[:8]}{ext}'
    save_dir = os.path.join(os.path.dirname(__file__), 'static', 'logos')
    os.makedirs(save_dir, exist_ok=True)
    fpath = os.path.join(save_dir, fname)
    f.save(fpath)
    rel = f'static/logos/{fname}'
    conn = get_db()
    conn.execute("UPDATE usuarios SET logo_path=? WHERE id=?", (rel, current_user.id))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'logo_path': rel})


def _add_formatted_run(paragraph, text):
    """Legado — mantido para compatibilidade com criar_docx."""
    import re
    parts = re.split(r'(\*\*.*?\*\*|\*.*?\*)', text)
    for part in parts:
        if part.startswith('**') and part.endswith('**'):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        elif part.startswith('*') and part.endswith('*'):
            run = paragraph.add_run(part[1:-1])
            run.italic = True
        else:
            paragraph.add_run(part)


# ─── Planejamento Anual ────────────────────────────────────────────────────────

@app.route('/planejamento')
@login_required
def planejamento():
    if not current_user.assinatura_ativa and not current_user.is_admin:
        return redirect(url_for('chat'))
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


# ─── Termos e Privacidade ─────────────────────────────────────────────────────

@app.route('/termos')
def termos():
    return render_template('termos.html')

@app.route('/privacidade')
def privacidade():
    return render_template('privacidade.html')

# ─── Error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(404)
def nao_encontrado(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def erro_interno(e):
    return render_template('500.html'), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=False, host='0.0.0.0', port=port)
