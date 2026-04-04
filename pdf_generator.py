"""
pdf_generator.py — ProfessorIA
Converte o JSON estruturado do Plano de Aula em um PDF profissional usando ReportLab.

Uso:
    from pdf_generator import gerar_plano_pdf
    pdf_bytes = gerar_plano_pdf(plano_json, display_name="Ana Silva", school_name="E.E. Dom Pedro")
"""

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm as rcm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
)

# ── Paleta de cores (idêntica ao criar_pdf do server.py) ──────────────────────
AZUL        = colors.HexColor('#2b4fc7')
AZUL_ESCURO = colors.HexColor('#1a3399')
AZUL_CLARO  = colors.HexColor('#eef2ff')
VERDE_CLARO = colors.HexColor('#f0fdf4')
AMARELO_BG  = colors.HexColor('#fffbeb')
BRANCO      = colors.white
TEXTO       = colors.HexColor('#1a1a2e')
CINZA       = colors.HexColor('#6b7280')
CINZA_CLARO = colors.HexColor('#f3f4f6')
BORDA       = colors.HexColor('#c0c8e8')


# ── Estilos reutilizáveis ─────────────────────────────────────────────────────

def _estilos():
    return {
        'centro_bold': ParagraphStyle(
            'cb', fontName='Helvetica-Bold', fontSize=10,
            alignment=TA_CENTER, textColor=TEXTO, leading=14
        ),
        'centro': ParagraphStyle(
            'c', fontName='Helvetica', fontSize=9,
            alignment=TA_CENTER, textColor=TEXTO, leading=13
        ),
        'centro_pequeno': ParagraphStyle(
            'cp', fontName='Helvetica', fontSize=8,
            alignment=TA_CENTER, textColor=CINZA, leading=12
        ),
        'titulo_banner': ParagraphStyle(
            'tb', fontName='Helvetica-Bold', fontSize=13,
            alignment=TA_CENTER, textColor=BRANCO, leading=16
        ),
        'secao_header': ParagraphStyle(
            'sh', fontName='Helvetica-Bold', fontSize=9,
            alignment=TA_LEFT, textColor=BRANCO, leading=13
        ),
        'label': ParagraphStyle(
            'lb', fontName='Helvetica-Bold', fontSize=8.5,
            textColor=AZUL, leading=13
        ),
        'valor': ParagraphStyle(
            'vl', fontName='Helvetica', fontSize=8.5,
            textColor=TEXTO, leading=13
        ),
        'corpo': ParagraphStyle(
            'co', fontName='Helvetica', fontSize=8.5,
            textColor=TEXTO, leading=13, alignment=TA_JUSTIFY
        ),
        'bncc_codigo': ParagraphStyle(
            'bc', fontName='Helvetica-Bold', fontSize=8,
            textColor=AZUL, leading=12
        ),
        'bncc_desc': ParagraphStyle(
            'bd', fontName='Helvetica', fontSize=8,
            textColor=TEXTO, leading=12, alignment=TA_JUSTIFY
        ),
        'etapa_titulo': ParagraphStyle(
            'et', fontName='Helvetica-Bold', fontSize=9,
            textColor=AZUL_ESCURO, leading=13
        ),
        'rodape': ParagraphStyle(
            'ro', fontName='Helvetica-Oblique', fontSize=7,
            alignment=TA_CENTER, textColor=CINZA, leading=10
        ),
        'blank_label': ParagraphStyle(
            'bl', fontName='Helvetica', fontSize=8.5,
            textColor=CINZA, leading=13
        ),
    }


def _tabela_banner(texto, largura, cor_bg=None):
    """Cria uma linha colorida de título (estilo banner)."""
    cor = cor_bg or AZUL
    st = ParagraphStyle(
        'bn', fontName='Helvetica-Bold', fontSize=10,
        alignment=TA_LEFT, textColor=BRANCO, leading=14
    )
    t = Table([[Paragraph(texto, st)]], colWidths=[largura])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), cor),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
    ]))
    return t


def _info_par(label, valor, estilos):
    """Parágrafo do tipo 'Label: valor'."""
    return Paragraph(
        f'<font color="#2b4fc7"><b>{label}:</b></font>  {valor or ""}',
        estilos['valor']
    )


def _blank(label, estilos):
    """Parágrafo com campo em branco para preenchimento manual."""
    return Paragraph(
        f'<font color="#6b7280">{label}:</font>  '
        '<font color="#9ca3af">__________________________________</font>',
        estilos['blank_label']
    )


# ── Função principal ──────────────────────────────────────────────────────────

def gerar_plano_pdf(plano_json: dict, display_name: str = '', school_name: str = '') -> bytes:
    """
    Converte o JSON estruturado do plano de aula em bytes de um PDF profissional.

    Args:
        plano_json:   Dicionário com a chave 'plano_de_aula' (saída do /api/gerar-plano).
        display_name: Nome do professor (do perfil global). Se vazio, exibe linha em branco.
        school_name:  Nome da escola   (do perfil global). Se vazio, exibe linha em branco.

    Returns:
        bytes do PDF gerado.
    """
    plano = plano_json.get('plano_de_aula', plano_json)  # aceita com ou sem wrapper

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.8 * rcm, rightMargin=1.8 * rcm,
        topMargin=1.5 * rcm, bottomMargin=1.5 * rcm
    )
    w = doc.width
    st = _estilos()
    story = []

    # ── 1. CABEÇALHO INSTITUCIONAL ────────────────────────────────────────────
    story.append(Paragraph("GOVERNO DO ESTADO DE SÃO PAULO", st['centro_bold']))
    story.append(Paragraph("SECRETARIA DE ESTADO DA EDUCAÇÃO", st['centro']))
    story.append(Spacer(1, 3))

    if school_name:
        story.append(Paragraph(school_name.upper(), st['centro_bold']))
    else:
        story.append(_blank("Escola", st))

    story.append(Spacer(1, 4))

    if display_name:
        story.append(Paragraph(f"Prof(a). {display_name}", st['centro']))
    else:
        story.append(_blank("Professor(a)", st))

    story.append(Spacer(1, 8))

    # ── 2. TÍTULO PRINCIPAL ───────────────────────────────────────────────────
    disciplina = plano.get('disciplina', '')
    ano_escolar = plano.get('ano_escolar', '')
    tema = plano.get('tema_central', '')
    titulo_txt = f"PLANO DE AULA  ·  {disciplina.upper()}  |  {ano_escolar}"
    t_titulo = Table(
        [[Paragraph(titulo_txt, st['titulo_banner'])]],
        colWidths=[w]
    )
    t_titulo.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), AZUL),
        ('TOPPADDING',    (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING',   (0, 0), (-1, -1), 12),
    ]))
    story.append(t_titulo)
    story.append(Spacer(1, 8))

    # ── 3. FICHA DE IDENTIFICAÇÃO ─────────────────────────────────────────────
    tempo = plano.get('tempo_estimado', '')
    ficha_rows = [
        [_info_par("Tema Central",    tema,       st), _info_par("Tempo Estimado", tempo, st)],
        [_info_par("Disciplina",      disciplina, st), _info_par("Ano / Série",    ano_escolar, st)],
    ]
    if display_name:
        ficha_rows.append([_info_par("Professor(a)", display_name, st),
                           _info_par("Escola", school_name, st)])

    t_ficha = Table(ficha_rows, colWidths=[w * 0.6, w * 0.4])
    t_ficha.setStyle(TableStyle([
        ('GRID',          (0, 0), (-1, -1), 0.5, BORDA),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [AZUL_CLARO, BRANCO]),
    ]))
    story.append(t_ficha)
    story.append(Spacer(1, 10))

    # ── 4. HABILIDADES BNCC ───────────────────────────────────────────────────
    habilidades = plano.get('habilidades_bncc', [])
    if habilidades:
        story.append(_tabela_banner("  HABILIDADES BNCC", w))
        story.append(Spacer(1, 4))

        bncc_rows = []
        for h in habilidades:
            codigo = h.get('codigo', '')
            descricao = h.get('descricao', '')
            bncc_rows.append([
                Paragraph(codigo, st['bncc_codigo']),
                Paragraph(descricao, st['bncc_desc'])
            ])

        t_bncc = Table(bncc_rows, colWidths=[2.2 * rcm, w - 2.2 * rcm])
        t_bncc.setStyle(TableStyle([
            ('GRID',          (0, 0), (-1, -1), 0.4, BORDA),
            ('TOPPADDING',    (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING',   (0, 0), (-1, -1), 6),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
            ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [AZUL_CLARO, BRANCO]),
        ]))
        story.append(t_bncc)
        story.append(Spacer(1, 10))

    # ── 5. DESENVOLVIMENTO ────────────────────────────────────────────────────
    desenvolvimento = plano.get('desenvolvimento', [])
    if desenvolvimento:
        story.append(_tabela_banner("  DESENVOLVIMENTO DA AULA", w))
        story.append(Spacer(1, 6))

        for idx, etapa in enumerate(desenvolvimento):
            nome_etapa  = etapa.get('etapa', f'Etapa {idx + 1}')
            conteudo    = etapa.get('conteudo', '')
            estrategias = etapa.get('estrategias_didaticas', '')
            recursos    = etapa.get('recursos_pedagogicos', [])

            # Sub-banner de etapa
            cor_etapa = AZUL_ESCURO if idx % 2 == 0 else colors.HexColor('#374151')
            story.append(_tabela_banner(f"  {nome_etapa.upper()}", w, cor_bg=cor_etapa))
            story.append(Spacer(1, 4))

            det_rows = [
                [Paragraph('<b>Conteúdo</b>', st['label']),
                 Paragraph(conteudo, st['corpo'])],
                [Paragraph('<b>Estratégias Didáticas</b>', st['label']),
                 Paragraph(estrategias, st['corpo'])],
                [Paragraph('<b>Recursos Pedagógicos</b>', st['label']),
                 Paragraph(', '.join(recursos) if recursos else '—', st['corpo'])],
            ]
            t_det = Table(det_rows, colWidths=[3.8 * rcm, w - 3.8 * rcm])
            bg = VERDE_CLARO if idx % 2 == 0 else AMARELO_BG
            t_det.setStyle(TableStyle([
                ('GRID',          (0, 0), (-1, -1), 0.4, BORDA),
                ('TOPPADDING',    (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('LEFTPADDING',   (0, 0), (-1, -1), 8),
                ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
                ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
                ('BACKGROUND',    (0, 0), (0, -1), AZUL_CLARO),
                ('BACKGROUND',    (1, 0), (1, -1), bg),
            ]))
            story.append(t_det)
            story.append(Spacer(1, 6))

    # ── 6. AVALIAÇÃO E FECHAMENTO ─────────────────────────────────────────────
    avaliacao = plano.get('avaliacao_e_fechamento', {})
    if avaliacao:
        story.append(_tabela_banner("  AVALIAÇÃO E FECHAMENTO", w, cor_bg=colors.HexColor('#065f46')))
        story.append(Spacer(1, 4))

        metodo   = avaliacao.get('metodo', '')
        criterios = avaliacao.get('criterios', '')
        aval_rows = [
            [Paragraph('<b>Método</b>',    st['label']), Paragraph(metodo,    st['corpo'])],
            [Paragraph('<b>Critérios</b>', st['label']), Paragraph(criterios, st['corpo'])],
        ]
        t_aval = Table(aval_rows, colWidths=[3.0 * rcm, w - 3.0 * rcm])
        t_aval.setStyle(TableStyle([
            ('GRID',          (0, 0), (-1, -1), 0.4, BORDA),
            ('TOPPADDING',    (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING',   (0, 0), (-1, -1), 8),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
            ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND',    (0, 0), (0, -1), AZUL_CLARO),
            ('BACKGROUND',    (1, 0), (1, -1), VERDE_CLARO),
        ]))
        story.append(t_aval)
        story.append(Spacer(1, 12))

    # ── 7. RODAPÉ ─────────────────────────────────────────────────────────────
    story.append(HRFlowable(width='100%', thickness=0.5, color=BORDA))
    story.append(Spacer(1, 4))
    rodape_parts = ['Gerado por ProfessorIA™', datetime.now().strftime('%d/%m/%Y')]
    if school_name:
        rodape_parts.append(school_name)
    story.append(Paragraph('  ·  '.join(rodape_parts), st['rodape']))

    doc.build(story)
    buf.seek(0)
    return buf.read()
