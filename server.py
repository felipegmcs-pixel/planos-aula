
import os
import io
import re
import json
import base64
import secrets
import smtplib
import logging
import traceback
from datetime import datetime, timedelta
from email.mime.text import MIMEText

# Carrega .env em desenvolvimento
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─── Logging estruturado ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('professorIA')

def alertar_falha_ia(motor, erro, usuario_id=None, contexto=None):
    msg_erro = f"🚨 FALHA CRÍTICA IA [{motor}]"
    if usuario_id: msg_erro += f" | Usuário: {usuario_id}"
    elif current_user and current_user.is_authenticated: msg_erro += f" | Usuário: {current_user.id}"
    if contexto:   msg_erro += f"\nContexto: {contexto}"
    msg_erro += f"\nErro: {str(erro)[:500]}"
    logger.error(msg_erro)
    admin_email = os.environ.get('ADMIN_EMAIL')
    if admin_email and os.environ.get('SMTP_PASS'):
        try:
            enviar_email_alerta(admin_email, "ALERTA: Falha de IA no ProfessorIA", msg_erro)
        except Exception as e:
            logger.warning("Falha ao enviar e-mail de alerta: %s", e)

def enviar_email_alerta(destinatario, assunto, corpo):
    smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_user = os.environ.get('SMTP_USER')
    smtp_pass = os.environ.get('SMTP_PASS')
    if not all([smtp_user, smtp_pass]): return
    msg = MIMEText(corpo)
    msg['Subject'] = assunto
    msg['From'] = f"ProfessorIA Alertas <{smtp_user}>"
    msg['To'] = destinatario
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)

import psycopg2
import psycopg2.extras
from flask import (Flask, render_template, request, send_file,
                   jsonify, redirect, url_for, flash, Response, stream_with_context)
from flask_login import (LoginManager, UserMixin, login_user,
                         logout_user, login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import stripe as stripe_lib
from anthropic import Anthropic
from openai import OpenAI
from docxtpl import DocxTemplate
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
from pdf_generator import gerar_plano_pdf

# ─── Configuração de Estilo de Imagem (SUPER PROMPT VISUAL DE ELITE) ──────────
IMAGE_STYLE_MODIFIER = (
    "Estilo: Aquarela digital moderna, acadêmica e limpa, fundo 100% branco sólido. "
    "Composição: Ilustração central temática rica em detalhes históricos ou científicos, cercada por ramificações orgânicas "
    "que conectam a ícones icônicos ou banners textuais curtos. "
    "Estética: Sabedoria, acolhimento e design premium (estilo infográfico educacional de alta gama). "
    "OBRIGATÓRIO: No canto inferior direito, insira a assinatura da marca: "
    "Um símbolo geométrico minimalista formado por dois círculos perfeitos entrelaçados horizontalmente, "
    "acompanhado do texto 'ProfessorIA™' em Azul Acadêmico. "
    "PROIBIDO: Inserir textos longos, parágrafos ou frases complexas dentro da imagem. Foque na arte e na assinatura."
)

# ─── App ──────────────────────────────────────────────────────────────────────
app = Flask(__name__)
_secret = os.environ.get('SECRET_KEY', 'dev-secret-troque-em-producao')
app.secret_key = _secret
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

login_manager = LoginManager(app)
login_manager.login_view = 'login'

def _limiter_key():
    if current_user.is_authenticated:
        return f'user:{current_user.id}'
    return get_remote_address()

limiter = Limiter(app=app, key_func=_limiter_key, storage_uri='memory://')

client = Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'), timeout=120.0)
client_openai = OpenAI(api_key=os.environ.get('OPENAI_API_KEY')) if os.environ.get('OPENAI_API_KEY') else None

# ─── Prompts e Schemas ────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Você é o ProfessorIA, Especialista Sênior em Pedagogia Brasileira.
Sua missão é automatizar a criação de materiais pedagógicos de alta qualidade, garantindo 100% de alinhamento à BNCC."""

SYSTEM_PROMPT_PLANO = (
    "Você é um Engenheiro de Planejamento Pedagógico Sênior e Especialista em BNCC. "
    "Sua missão é gerar planos de aula de elite que serão exportados para documentos oficiais (.docx e .pdf). "
    "Ao gerar o plano, identifique 4 a 6 tópicos visuais icônicos que representem o tema para um infográfico de alta qualidade. "
    "Seja extremamente preciso nas habilidades BNCC e na metodologia ativa."
)

SYSTEM_PROMPT_COORDENADOR = (
    "Você é o Coordenador Pedagógico Sênior do ProfessorIA. Sua função é revisar o plano de aula gerado, "
    "garantindo que a linguagem seja acadêmica, os objetivos estejam claros e o alinhamento à BNCC seja impecável. "
    "Corrija qualquer imprecisão didática ou erro de formatação no JSON."
)

_OAI_PLANO_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "plano_de_aula": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "tema_central":   {"type": "string"},
                "disciplina":     {"type": "string"},
                "ano_escolar":    {"type": "string"},
                "tempo_estimado": {"type": "string"},
                "habilidades_bncc": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "codigo":    {"type": "string"},
                            "descricao": {"type": "string"}
                        },
                        "required": ["codigo", "descricao"]
                    }
                },
                "desenvolvimento": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "etapa":                 {"type": "string"},
                            "conteudo":              {"type": "string"},
                            "estrategias_didaticas": {"type": "string"},
                            "recursos_pedagogicos":  {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["etapa", "conteudo", "estrategias_didaticas", "recursos_pedagogicos"]
                    }
                },
                "avaliacao_e_fechamento": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "metodo":    {"type": "string"},
                        "criterios": {"type": "string"}
                    },
                    "required": ["metodo", "criterios"]
                },
                "infografico_sugestao": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "titulo": {"type": "string"},
                        "topicos": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["titulo", "topicos"]
                }
            },
            "required": [
                "tema_central", "disciplina", "ano_escolar", "tempo_estimado",
                "habilidades_bncc", "desenvolvimento", "avaliacao_e_fechamento", "infografico_sugestao"
            ]
        }
    },
    "required": ["plano_de_aula"]
}

# ─── Banco de Dados ───────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get('DATABASE_URL', '').replace('postgres://', 'postgresql://', 1)

class _DbConn:
    def __init__(self, conn): self._conn = conn
    def execute(self, sql, params=()):
        sql = sql.replace('?', '%s')
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return cur
    def commit(self): self._conn.commit()
    def close(self): self._conn.close()

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return _DbConn(conn)

def _migrar_banco():
    """Cria tabelas se não existirem e adiciona colunas novas."""
    schema = [
        """CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_premium BOOLEAN DEFAULT FALSE,
            stripe_customer_id TEXT,
            escola_governo TEXT DEFAULT '',
            escola_secretaria TEXT DEFAULT '',
            escola_diretoria TEXT DEFAULT '',
            escola_nome TEXT DEFAULT '',
            escola_endereco TEXT DEFAULT '',
            escola_fone TEXT DEFAULT '',
            escola_email TEXT DEFAULT '',
            data_criacao TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS planos_aula (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            titulo TEXT,
            disciplina TEXT,
            ano_serie TEXT,
            plano_json TEXT,
            data_criacao TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS lista_vip (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            email TEXT NOT NULL,
            whatsapp TEXT,
            criado_em TIMESTAMP DEFAULT NOW()
        )""",
    ]
    colunas = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS escola_governo TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS escola_secretaria TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS escola_diretoria TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS escola_nome TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS escola_endereco TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS escola_fone TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS escola_email TEXT DEFAULT ''",
    ]
    db = get_db()
    try:
        for sql in schema:
            try:
                db.execute(sql)
                db.commit()
            except Exception as e:
                logger.warning('Schema pulado: %s — %s', sql[:60], e)
        for sql in colunas:
            try:
                db.execute(sql)
                db.commit()
            except Exception as e:
                logger.warning('Migração pulada: %s — %s', sql[:60], e)
    finally:
        db.close()

try:
    _migrar_banco()
    logger.info('Migrações de banco aplicadas com sucesso.')
except Exception as e:
    logger.critical('_migrar_banco falhou: %s', e)

# ─── Rotas e Lógica ───────────────────────────────────────────────────────────

@app.route('/api/generate/image', methods=['POST'])
@login_required
def api_generate_image():
    data = request.get_json(force=True) or {}
    prompt = str(data.get('prompt', '')).strip()[:4000]
    if not prompt: return jsonify({'erro': 'Prompt obrigatório'}), 400
    
    prompt_final = f"{prompt}. {IMAGE_STYLE_MODIFIER}"
    try:
        resp = client_openai.images.generate(
            model='dall-e-3', prompt=prompt_final, size='1024x1024', quality='standard', n=1
        )
        return jsonify({'url': resp.data[0].url})
    except Exception as e:
        alertar_falha_ia("DALL-E 3", e, getattr(current_user, 'id', None), prompt)
        return jsonify({'erro': str(e)}), 500

@app.route('/api/gerar-plano', methods=['POST'])
@login_required
def api_gerar_plano():
    data = request.get_json(force=True) or {}
    tema, ano, disciplina = data.get('tema'), data.get('ano'), data.get('disciplina')
    estado = data.get('estado', 'Nacional (BNCC)')
    
    try:
        user_prompt = f"Gere um plano de aula de elite para {tema}, {ano}, {disciplina}. Contexto Regional: {estado}."
        # 1. Geração Inicial (Criador)
        resp = client_openai.chat.completions.create(
            model='gemini-2.5-flash',
            messages=[{'role': 'system', 'content': SYSTEM_PROMPT_PLANO}, {'role': 'user', 'content': user_prompt}],
            response_format={'type': 'json_object', 'json_schema': _OAI_PLANO_SCHEMA}
        )
        plano_bruto = resp.choices[0].message.content
        
        # 2. Refinamento (Coordenador Invisível)
        resp_ref = client_openai.chat.completions.create(
            model='gemini-2.5-flash',
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT_COORDENADOR},
                {'role': 'user', 'content': f"Refine este plano de aula: {plano_bruto}"}
            ],
            response_format={'type': 'json_object', 'json_schema': _OAI_PLANO_SCHEMA}
        )
        plano_json = json.loads(resp_ref.choices[0].message.content)
        return jsonify(plano_json)
    except Exception as e:
        alertar_falha_ia("OpenAI Plano", e, getattr(current_user, 'id', None), tema)
        return jsonify({'erro': str(e)}), 500

@app.route("/api/plano-aula/pdf", methods=["POST"])
@login_required
def api_plano_aula_pdf():
    data = request.get_json(force=True) or {}
    plano = data.get("plano_de_aula")
    school_data = data.get("school_data")
    display_name = data.get("display_name", "ProfessorIA")

    if not plano: return jsonify({"erro": "Plano ausente"}), 400

    try:
        pdf_bytes = gerar_plano_pdf(plano, display_name, school_data)
        response = Response(pdf_bytes, mimetype="application/pdf")
        response.headers["Content-Disposition"] = "attachment; filename=plano_de_aula.pdf"
        return response
    except Exception as e:
        alertar_falha_ia("ReportLab PDF", e, getattr(current_user, "id", None), "Geração de PDF")
        return jsonify({"erro": str(e)}), 500


@app.route("/api/plano-aula/docx", methods=["POST"])
@login_required
def api_plano_aula_docx():
    data = request.get_json(force=True) or {}
    plano = data.get('plano_de_aula')
    if not plano: return jsonify({'erro': 'Plano ausente'}), 400
    
    # Mapeamento para o template oficial (plano_de_aula.docx com jinja2)
    # Estruturar aulas a partir do desenvolvimento
    aulas = []
    for idx, dev in enumerate(plano.get('desenvolvimento', []), 1):
        aulas.append({
            'data': f"Aula {idx}",
            'conteudo': dev.get('conteudo', ''),
            'estrategias': dev.get('estrategias_didaticas', ''),
            'recursos': ", ".join(dev.get('recursos_pedagogicos', [])),
            'avaliacao': plano.get('avaliacao_e_fechamento', {}).get('metodo', '') # Assumindo que a avaliação é a mesma para todas as aulas
        })

    # Nome do professor: prioridade request > perfil logado
    professor_nome = data.get('display_name')
    if not professor_nome and hasattr(current_user, 'nome') and current_user.is_authenticated:
        professor_nome = current_user.nome
    if not professor_nome:
        professor_nome = 'ProfessorIA'

    context = {
        'professor': professor_nome,
        'tema_central': plano.get('tema_central', ''),
        'disciplina': plano.get('disciplina', ''),
        'ano_escolar': plano.get('ano_escolar', ''),
        'tempo_estimado': plano.get('tempo_estimado', ''),
        'habilidades_bncc': "\n".join([
            f"{h['codigo']}: {h['descricao']}" 
            for h in (plano.get('habilidades_bncc', []) if isinstance(plano.get('habilidades_bncc', []), list) else [{'descricao': plano.get('habilidades_bncc', '')}])
            if isinstance(h, dict) and 'descricao' in h
        ]),
        'aulas': aulas,
        'avaliacao_metodo': plano.get('avaliacao_e_fechamento', {}).get('metodo', ''),
        'avaliacao_criterios': plano.get('avaliacao_e_fechamento', {}).get('criterios', ''),
        'infografico_titulo': plano.get('infografico_sugestao', {}).get('titulo', ''),
        'infografico_topicos': "\n".join(plano.get('infografico_sugestao', {}).get('topicos', [])),
    }

    # Adicionar dados da escola ao contexto
    # Prioridade: 1) dados do request, 2) perfil do professor logado
    school_data = data.get('school_data')
    if school_data:
        context.update(school_data)
    elif hasattr(current_user, 'school_data') and current_user.is_authenticated:
        context.update(current_user.school_data)

    _template_path = os.path.join(os.path.dirname(__file__), 'static', 'templates', 'plano_de_aula.docx')
    doc = DocxTemplate(_template_path)
    doc.render(context)
    
    # Salvar em buffer e enviar
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    
    return send_file(
        buffer, as_attachment=True, download_name=f"plano_{plano.get('tema_central', 'aula').replace(' ', '_').lower()}.docx"
    )

@app.route('/api/meus-planos', methods=['GET'])
@login_required
def api_meus_planos():
    db = get_db()
    try:
        planos = db.execute(
            "SELECT id, titulo, disciplina, ano_serie, data_criacao FROM planos_aula WHERE user_id = ? ORDER BY data_criacao DESC",
            (current_user.id,)
        ).fetchall()
        return jsonify(planos)
    finally:
        db.close()

@app.route('/api/salvar-plano', methods=['POST'])
@login_required
def api_salvar_plano():
    data = request.get_json(force=True) or {}
    titulo = data.get('titulo')
    plano_json = data.get('plano_de_aula')
    
    if not all([titulo, plano_json]):
        return jsonify({'erro': 'Título e plano de aula são obrigatórios'}), 400
    
    db = get_db()
    try:
        db.execute(
            "INSERT INTO planos_aula (user_id, titulo, disciplina, ano_serie, plano_json) VALUES (?, ?, ?, ?, ?)",
            (current_user.id, titulo, plano_json.get('disciplina'), plano_json.get('ano_escolar'), json.dumps(plano_json))
        )
        db.commit()
        return jsonify({'mensagem': 'Plano salvo com sucesso!'})
    except Exception as e:
        logger.error("Erro ao salvar plano: %s", e)
        return jsonify({'erro': str(e)}), 500
    finally:
        db.close()

# ─── Autenticação e Usuários ──────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, id, email, nome, is_premium=False, stripe_customer_id=None,
                 escola_governo=None, escola_secretaria=None, escola_diretoria=None,
                 escola_nome=None, escola_endereco=None, escola_fone=None, escola_email=None, **kwargs):
        self.id = id
        self.email = email
        self.nome = nome
        self.is_premium = is_premium
        self.stripe_customer_id = stripe_customer_id
        self.escola_governo = escola_governo or ''
        self.escola_secretaria = escola_secretaria or ''
        self.escola_diretoria = escola_diretoria or ''
        self.escola_nome = escola_nome or ''
        self.escola_endereco = escola_endereco or ''
        self.escola_fone = escola_fone or ''
        self.escola_email = escola_email or ''

    @property
    def school_data(self):
        """Retorna os dados da escola como dicionário para uso no template DOCX."""
        return {
            'escola_governo': self.escola_governo,
            'escola_secretaria': self.escola_secretaria,
            'escola_diretoria': self.escola_diretoria,
            'escola_nome': self.escola_nome,
            'escola_endereco': self.escola_endereco,
            'escola_fone': self.escola_fone,
            'escola_email': self.escola_email,
        }

    @property
    def escola_preenchida(self):
        """Verifica se o professor já preencheu os dados da escola."""
        return bool(self.escola_nome)

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    try:
        # Tenta carregar com campos de escola; se não existirem, carrega sem eles
        try:
            user_data = db.execute(
                "SELECT id, email, nome, is_premium, stripe_customer_id, "
                "escola_governo, escola_secretaria, escola_diretoria, "
                "escola_nome, escola_endereco, escola_fone, escola_email "
                "FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        except Exception:
            user_data = db.execute(
                "SELECT id, email, nome, is_premium, stripe_customer_id "
                "FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        if user_data:
            return User(**user_data)
    finally:
        db.close()
    return None

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('painel'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        db = get_db()
        try:
            user_data = db.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
            if user_data and check_password_hash(user_data['password_hash'], password):
                user = load_user(user_data['id'])
                login_user(user)
                return redirect(url_for('painel'))
            flash('Email ou senha inválidos', 'danger')
        finally:
            db.close()
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/cadastro', methods=['GET', 'POST'])
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('painel'))
    if request.method == 'POST':
        nome = request.form.get('nome')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not all([nome, email, password]):
            flash('Preencha todos os campos', 'danger')
            return redirect(url_for('register'))
        
        db = get_db()
        try:
            user_exists = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if user_exists:
                flash('Este email já está cadastrado', 'warning')
                return redirect(url_for('register'))
            
            hashed_password = generate_password_hash(password)
            db.execute("INSERT INTO users (nome, email, password_hash) VALUES (?, ?, ?)", (nome, email, hashed_password))
            db.commit()
            flash('Cadastro realizado com sucesso! Faça login para continuar.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            logger.error("Erro no registro: %s", e)
            flash('Ocorreu um erro ao cadastrar. Tente novamente.', 'danger')
        finally:
            db.close()
    return render_template('register.html')

# ─── Admin ────────────────────────────────────────────────────────────────────

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin: # Supondo um campo `is_admin` no modelo User
        return redirect(url_for('painel'))
    
    db = get_db()
    try:
        total_users = db.execute("SELECT COUNT(*) as count FROM users").fetchone()['count']
        total_planos = db.execute("SELECT COUNT(*) as count FROM planos_aula").fetchone()['count']
        recent_users = db.execute("SELECT nome, email, data_criacao FROM users ORDER BY data_criacao DESC LIMIT 5").fetchall()
    finally:
        db.close()
        
    return render_template(
        'admin.html',
        total_users=total_users,
        total_planos=total_planos,
        recent_users=recent_users
    )

# ─── Páginas Web ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/painel')
@login_required
def painel():
    return render_template('painel.html')

@app.route('/gerador')
@login_required
def gerador():
    return render_template('gerador.html')

@app.route('/planos-salvos')
@login_required
def planos_salvos():
    return render_template('planos_salvos.html')

@app.route('/assinatura')
@login_required
def assinatura():
    return render_template('assinatura.html')

@app.route('/conta')
@login_required
def conta():
    return render_template('conta.html')

@app.route('/conta/escola', methods=['POST'])
@login_required
def conta_escola():
    escola_governo = request.form.get('escola_governo', '').strip()
    escola_secretaria = request.form.get('escola_secretaria', '').strip()
    escola_diretoria = request.form.get('escola_diretoria', '').strip()
    escola_nome = request.form.get('escola_nome', '').strip()
    escola_endereco = request.form.get('escola_endereco', '').strip()
    escola_fone = request.form.get('escola_fone', '').strip()
    escola_email = request.form.get('escola_email', '').strip()

    if not escola_nome:
        flash('O nome da escola é obrigatório.', 'danger')
        return redirect(url_for('conta'))

    db = get_db()
    try:
        db.execute(
            "UPDATE users SET escola_governo = ?, escola_secretaria = ?, escola_diretoria = ?, "
            "escola_nome = ?, escola_endereco = ?, escola_fone = ?, escola_email = ? WHERE id = ?",
            (escola_governo, escola_secretaria, escola_diretoria, escola_nome,
             escola_endereco, escola_fone, escola_email, current_user.id)
        )
        db.commit()
        # Recarregar o usuário para atualizar os dados em memória
        updated_user = load_user(current_user.id)
        if updated_user:
            login_user(updated_user)
        flash('Dados da escola atualizados com sucesso!', 'ok')
    except Exception as e:
        logger.error("Erro ao atualizar escola: %s", e)
        flash('Erro ao salvar os dados da escola. Tente novamente.', 'danger')
    finally:
        db.close()
    return redirect(url_for('conta'))

@app.route('/conta/senha', methods=['POST'])
@login_required
def conta_senha():
    senha_atual = request.form.get('senha_atual')
    senha_nova = request.form.get('senha_nova')
    senha_conf = request.form.get('senha_conf')

    if not all([senha_atual, senha_nova, senha_conf]):
        flash('Preencha todos os campos de senha.', 'danger')
        return redirect(url_for('conta'))

    if senha_nova != senha_conf:
        flash('A nova senha e a confirmação não coincidem.', 'danger')
        return redirect(url_for('conta'))

    if len(senha_nova) < 6:
        flash('A nova senha deve ter pelo menos 6 caracteres.', 'danger')
        return redirect(url_for('conta'))

    db = get_db()
    try:
        user_data = db.execute("SELECT password_hash FROM users WHERE id = ?", (current_user.id,)).fetchone()
        if not user_data or not check_password_hash(user_data['password_hash'], senha_atual):
            flash('Senha atual incorreta.', 'danger')
            return redirect(url_for('conta'))

        db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                   (generate_password_hash(senha_nova), current_user.id))
        db.commit()
        flash('Senha atualizada com sucesso!', 'ok')
    except Exception as e:
        logger.error("Erro ao atualizar senha: %s", e)
        flash('Erro ao atualizar a senha. Tente novamente.', 'danger')
    finally:
        db.close()
    return redirect(url_for('conta'))

# ─── Pagamentos (Stripe) ──────────────────────────────────────────────────────

stripe_lib.api_key = os.environ.get('STRIPE_SECRET_KEY')

@app.route('/create-checkout-session', methods=['POST'])
@login_required
def create_checkout_session():
    try:
        checkout_session = stripe_lib.checkout.Session.create(
            customer=current_user.stripe_customer_id,
            payment_method_types=['card'],
            line_items=[
                {
                    "price": os.environ.get('STRIPE_PREMIUM_PRICE_ID'),
                    "quantity": 1,
                },
            ],
            mode='subscription',
            success_url=url_for('success', _external=True),
            cancel_url=url_for('cancel', _external=True),
        )
        return jsonify({'checkout_url': checkout_session.url})
    except Exception as e:
        return jsonify(error=str(e)), 403

@app.route('/success')
@login_required
def success():
    flash('Sua assinatura foi ativada com sucesso!', 'success')
    return redirect(url_for('painel'))

@app.route('/cancel')
@login_required
def cancel():
    flash('Sua assinatura não foi ativada.', 'info')
    return redirect(url_for('painel'))

@app.route('/create-portal-session', methods=['POST'])
@login_required
def create_portal_session():
    portal_session = stripe_lib.billing_portal.Session.create(
        customer=current_user.stripe_customer_id,
        return_url=url_for('painel', _external=True)
    )
    return redirect(portal_session.url, code=303)

@app.route('/stripe-webhook', methods=['POST'])
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('stripe-signature')
    endpoint_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')

    try:
        event = stripe_lib.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError as e:
        # Invalid payload
        return "Invalid payload", 400
    except stripe_lib.error.SignatureVerificationError as e:
        # Invalid signature
        return "Invalid signature", 400

    # Handle the checkout.session.completed event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        customer_id = session.get('customer')
        user_id = session.get('client_reference_id') # Assumindo que você passa o user_id aqui
        
        if user_id:
            db = get_db()
            try:
                db.execute("UPDATE users SET is_premium = TRUE, stripe_customer_id = ? WHERE id = ?", (customer_id, user_id))
                db.commit()
            finally:
                db.close()

    return "Success", 200

# ─── Inicialização ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
