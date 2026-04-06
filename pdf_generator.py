"""
pdf_generator.py — ProfessorIA
Converte o JSON estruturado do Plano de Aula em um PDF de ELITE usando ReportLab.
Espelha o layout premium do DOCX oficial.
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

# ── Paleta Noites de Alexandria ──────────────────────────────────────────────
TURQUESA_PROFUNDO = colors.HexColor('#0D2327')
TURQUESA_MEDIO    = colors.HexColor('#1E5A63')
DOURADO           = colors.HexColor('#D4AF37')
BRANCO            = colors.white
TEXTO             = colors.HexColor('#1a1a2e')
CINZA_SUAVE       = colors.HexColor('#7A9499')
CINZA_BG          = colors.HexColor('#EEF2FF')
BORDA             = colors.HexColor('#1E5A63')

def _estilos():
    return {
        'header_escola': ParagraphStyle(
            'he', fontName='Helvetica-Bold', fontSize=11,
            alignment=TA_CENTER, textColor=BRANCO, leading=14
        ),
        'header_sec': ParagraphStyle(
            'hs', fontName='Helvetica', fontSize=8,
            alignment=TA_CENTER, textColor=colors.HexColor('#BFDBFE'), leading=10
        ),
        'titulo_banner': ParagraphStyle(
            'tb', fontName='Helvetica-Bold', fontSize=12,
            alignment=TA_CENTER, textColor=BRANCO, leading=16
        ),
        'label_tabela': ParagraphStyle(
            'lt', fontName='Helvetica-Bold', fontSize=9,
            textColor=TURQUESA_PROFUNDO, leading=12
        ),
        'valor_tabela': ParagraphStyle(
            'vt', fontName='Helvetica', fontSize=9,
            textColor=TEXTO, leading=12
        ),
        'secao_header': ParagraphStyle(
            'sh', fontName='Helvetica-Bold', fontSize=10,
            alignment=TA_CENTER, textColor=BRANCO, leading=14
        ),
        'corpo': ParagraphStyle(
            'co', fontName='Helvetica', fontSize=9,
            textColor=TEXTO, leading=13, alignment=TA_JUSTIFY
        ),
        'rodape': ParagraphStyle(
            'ro', fontName='Helvetica-Oblique', fontSize=7,
            alignment=TA_CENTER, textColor=CINZA_SUAVE, leading=10
        )
    }

def _tabela_secao(texto, largura, cor_bg=TURQUESA_MEDIO):
    st = _estilos()['secao_header']
    t = Table([[Paragraph(texto, st)]], colWidths=[largura])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), cor_bg),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    return t

def gerar_plano_pdf(plano_json: dict, display_name: str = '', school_data: dict = None) -> bytes:
    """
    Gera um PDF de elite espelhando o layout do DOCX.
    """
    plano = plano_json.get('plano_de_aula', plano_json)
    
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2.0 * rcm, rightMargin=2.0 * rcm,
        topMargin=1.8 * rcm, bottomMargin=1.8 * rcm
    )
    w = doc.width
    st = _estilos()
    story = []

    # ── 1. CABEÇALHO (BANNER AZUL) ────────────────────────────────────────────
    school_data = school_data or {}
    escola_governo = school_data.get("escola_governo", "GOVERNO DO ESTADO DE SÃO PAULO")
    escola_secretaria = school_data.get("escola_secretaria", "SECRETARIA DE ESTADO DA EDUCAÇÃO")
    escola_diretoria = school_data.get("escola_diretoria", "DIRETORIA DE ENSINO – REGIÃO")
    escola_nome = school_data.get("escola_nome", "ESCOLA ESTADUAL")
    escola_endereco = school_data.get("escola_endereco", "Endereço da Escola")
    escola_fone = school_data.get("escola_fone", "Telefone da Escola")
    escola_email = school_data.get("escola_email", "email@escola.com.br")

    header_content = [
        [Paragraph(escola_governo, st["header_escola"])],
        [Paragraph(escola_secretaria, st["header_sec"])],
        [Paragraph(escola_diretoria, st["header_sec"])],
        [Paragraph(escola_nome, st["header_escola"])],
        [Paragraph(escola_endereco, st["header_sec"])],
        [Paragraph(escola_fone, st["header_sec"])],
        [Paragraph(escola_email, st["header_sec"])]
    ]
    t_header = Table(header_content, colWidths=[w])
    t_header.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), TURQUESA_PROFUNDO),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    story.append(t_header)
    story.append(Spacer(1, 10))

    # ── 2. TÍTULO ─────────────────────────────────────────────────────────────
    t_titulo = _tabela_secao("PLANO DE AULA", w, cor_bg=TURQUESA_PROFUNDO)
    story.append(t_titulo)
    story.append(Spacer(1, 10))

    # ── 3. FICHA DE IDENTIFICAÇÃO ─────────────────────────────────────────────
    info_data = [
        [Paragraph("Tema / Conteúdo", st['label_tabela']), Paragraph(plano.get('tema_central', ''), st['valor_tabela'])],
        [Paragraph("Disciplina", st['label_tabela']), Paragraph(plano.get('disciplina', ''), st['valor_tabela'])],
        [Paragraph("Ano / Série", st['label_tabela']), Paragraph(plano.get('ano_escolar', ''), st['valor_tabela'])],
        [Paragraph("Tempo Estimado", st['label_tabela']), Paragraph(plano.get('tempo_estimado', ''), st['valor_tabela'])],
    ]
    t_info = Table(info_data, colWidths=[4*rcm, w-4*rcm])
    t_info.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, BORDA),
        ('BACKGROUND', (0, 0), (0, -1), CINZA_BG),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 10))

    # ── 4. HABILIDADES BNCC ───────────────────────────────────────────────────
    story.append(_tabela_secao("HABILIDADES BNCC", w))
    habilidades = plano.get('habilidades_bncc', [])
    bncc_txt = "  |  ".join([f"<b>{h['codigo']}</b>: {h['descricao']}" for h in habilidades])
    t_bncc = Table([[Paragraph(bncc_txt, st['corpo'])]], colWidths=[w])
    t_bncc.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, BORDA),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(t_bncc)
    story.append(Spacer(1, 10))

    # ── 5. AULAS ──────────────────────────────────────────────────────────────
    story.append(_tabela_secao("AULAS", w))
    aulas_header = [
        [Paragraph("Data", st["header_escola"]), Paragraph("Conteúdo", st["header_escola"]), 
         Paragraph("Estratégias", st["header_escola"]), Paragraph("Recursos", st["header_escola"]), 
         Paragraph("Avaliação", st["header_escola"]), Paragraph("Verificação", st["header_escola"])]
    ]
    t_aulas_h = Table(aulas_header, colWidths=[w*0.1, w*0.2, w*0.2, w*0.2, w*0.15, w*0.15])
    t_aulas_h.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TURQUESA_MEDIO),
        ("GRID", (0, 0), (-1, -1), 0.5, BRANCO),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(t_aulas_h)

    aulas_rows = []
    for aula in plano.get("aulas", []):
        aulas_rows.append([
            Paragraph(aula.get("data", ""), st["valor_tabela"]),
            Paragraph(aula.get("conteudo", ""), st["valor_tabela"]),
            Paragraph(aula.get("estrategias", ""), st["valor_tabela"]),
            Paragraph(aula.get("recursos", ""), st["valor_tabela"]),
            Paragraph(aula.get("avaliacao", ""), st["valor_tabela"]),
            Paragraph(aula.get("verificacao", ""), st["valor_tabela"])
        ])
    
    t_aulas = Table(aulas_rows, colWidths=[w*0.1, w*0.2, w*0.2, w*0.2, w*0.15, w*0.15])
    t_aulas.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, BORDA),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t_aulas)
    story.append(Spacer(1, 10))

    # ── 6. AVALIAÇÃO ──────────────────────────────────────────────────────────
    story.append(_tabela_secao("AVALIAÇÃO E FECHAMENTO", w))
    av = plano.get('avaliacao_e_fechamento', {})
    av_data = [
        [Paragraph("<b>Método:</b> " + av.get('metodo', ''), st['corpo']),
         Paragraph("<b>Critérios:</b> " + av.get('criterios', ''), st['corpo'])]
    ]
    t_av = Table(av_data, colWidths=[w*0.5, w*0.5])
    t_av.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, BORDA),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(t_av)
    story.append(Spacer(1, 15))

    # ── 7. RODAPÉ ─────────────────────────────────────────────────────────────
    story.append(HRFlowable(width='100%', thickness=0.5, color=TURQUESA_MEDIO))
    story.append(Spacer(1, 5))
    prof = display_name or "ProfessorIA"
    data_txt = datetime.now().strftime('%d/%m/%Y')
    story.append(Paragraph(f"Gerado por ProfessorIA™  ·  Prof(a). {prof}  ·  {data_txt}", st['rodape']))

    doc.build(story)
    buf.seek(0)
    return buf.read()
