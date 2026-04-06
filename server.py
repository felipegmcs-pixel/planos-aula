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
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('professorIA')

def alertar_falha_ia(motor, erro, usuario_id=None, contexto=None):
    msg_erro = f"🚨 FALHA CRÍTICA IA [{motor}]"
    if usuario_id: msg_erro += f" | Usuário: {usuario_id}"
    if contexto:   msg_erro += f" | Contexto: {contexto}"
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
        alertar_falha_ia("DALL-E 3", e, current_user.id, prompt)
        return jsonify({'erro': str(e)}), 500

@app.route('/api/gerar-plano', methods=['POST'])
@login_required
def api_gerar_plano():
    data = request.get_json(force=True) or {}
    tema, ano, disciplina = data.get('tema'), data.get('ano'), data.get('disciplina')
    estado = data.get('estado', 'Nacional (BNCC)')
    
    user_prompt = f"Gere um plano de aula de elite para {tema}, {ano}, {disciplina}. Contexto Regional: {estado}."
    try:
        # 1. Geração Inicial (Criador)
        resp = client_openai.chat.completions.create(
            model='gpt-4o-mini',
            messages=[{'role': 'system', 'content': SYSTEM_PROMPT_PLANO}, {'role': 'user', 'content': user_prompt}],
            response_format={'type': 'json_schema', 'json_schema': {'name': 'plano', 'strict': True, 'schema': _OAI_PLANO_SCHEMA}}
        )
        plano_bruto = resp.choices[0].message.content
        
        # 2. Refinamento (Coordenador Invisível)
        resp_ref = client_openai.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT_COORDENADOR},
                {'role': 'user', 'content': f"Refine este plano de aula: {plano_bruto}"}
            ],
            response_format={'type': 'json_schema', 'json_schema': {'name': 'plano_refinado', 'strict': True, 'schema': _OAI_PLANO_SCHEMA}}
        )
        plano_json = json.loads(resp_ref.choices[0].message.content)
        return jsonify(plano_json)
    except Exception as e:
        alertar_falha_ia("OpenAI Plano", e, current_user.id, tema)
        return jsonify({'erro': str(e)}), 500

@app.route('/api/plano-aula/docx', methods=['POST'])
@login_required
def api_plano_aula_docx():
    data = request.get_json(force=True) or {}
    plano = data.get('plano_de_aula')
    if not plano: return jsonify({'erro': 'Plano ausente'}), 400
    
    # Mapeamento para o template oficial (gerar_template_plano.py)
    context = {
        'escola': data.get('escola') or current_user.escola_nome or 'ESCOLA ESTADUAL',
        'tema_central': plano['tema_central'],
        'disciplina': plano['disciplina'],
        'ano_escolar': plano['ano_escolar'],
        'tempo_estimado': plano['tempo_estimado'],
        'habilidades_bncc': plano['habilidades_bncc'],
        'desenvolvimento': plano['desenvolvimento'],
        'avaliacao_e_fechamento': plano['avaliacao_e_fechamento'],
        'professor': data.get('professor') or current_user.professor_nome or 'ProfessorIA',
        'data_geracao': datetime.now().strftime('%d/%m/%Y')
    }
    
    try:
        from docxtpl import DocxTemplate
        template_path = os.path.join(app.root_path, 'static/templates/plano_de_aula.docx')
        doc = DocxTemplate(template_path)
        doc.render(context)
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=f"Plano_{plano['tema_central'].replace(' ', '_')}.docx")
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5001)
