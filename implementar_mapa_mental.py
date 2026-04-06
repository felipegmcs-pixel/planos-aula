import os
import re

def aplicar_alteracoes():
    path = '/home/ubuntu/planos-aula/server.py'
    with open(path, 'r') as f:
        content = f.read()

    # 1. Definir o Schema e o Prompt do Cérebro Textual
    schema_mapa = """
_OAI_MAPA_MENTAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "titulo_central": {"type": "string"},
        "subtopicos": {
            "type": "array",
            "items": {"type": "string"}
        }
    },
    "required": ["titulo_central", "subtopicos"]
}
"""
    
    # Inserir o schema após o schema de prova
    if '_OAI_PROVA_SCHEMA = {' in content:
        content = content.replace('# ─── Gerador de Prova Estruturada ───', '# ─── Gerador de Prova Estruturada ───\n' + schema_mapa)
    else:
        # Fallback se não achar o comentário exato
        content = content.replace('SYSTEM_PROMPT_PROVA = (', schema_mapa + '\nSYSTEM_PROMPT_PROVA = (')

    # 2. Criar a rota /api/generate/mapa-mental
    nova_rota = """
@app.route('/api/generate/mapa-mental', methods=['POST'])
@login_required
@limiter.limit('3 per minute')
def api_generate_mapa_mental():
    \"\"\"Pipeline Duplo: Texto (OpenAI Strict) -> Imagem (DALL-E 3).\"\"\"
    if not current_user.assinatura_ativa and not current_user.is_admin:
        return jsonify({'erro': 'Assinatura necessária'}), 403

    data = request.get_json(force=True) or {}
    tema = str(data.get('tema', '')).strip()[:200]
    if not tema:
        return jsonify({'erro': 'Tema obrigatório'}), 400

    # --- ETAPA 1: O Cérebro Textual (OpenAI Strict) ---
    try:
        oai_client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))
        resp_t = oai_client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {'role': 'system', 'content': 'Você é um especialista em síntese educacional. Gere um mapa mental ultra-conciso. Título e subtópicos devem ter no máximo 3 palavras cada.'},
                {'role': 'user', 'content': f'Gere a estrutura de um mapa mental sobre: {tema}'}
            ],
            response_format={
                'type': 'json_schema',
                'json_schema': {
                    'name': 'mapa_mental_textual',
                    'strict': True,
                    'schema': _OAI_MAPA_MENTAL_SCHEMA
                }
            }
        )
        mapa_json = json.loads(resp_t.choices[0].message.content)
    except Exception as e:
        logger.error(f'Erro Etapa 1 Mapa Mental: {e}')
        return jsonify({'erro': 'Falha na síntese textual do mapa'}), 500

    # --- ETAPA 2: O Artista Visual (DALL-E 3) ---
    titulo = mapa_json['titulo_central']
    subtopicos = ", ".join(mapa_json['subtopicos'])
    
    super_prompt = (
        f"Ilustração educacional em aquarela digital moderna sobre '{titulo}', fundo 100% branco sólido. "
        f"O centro contém o título '{titulo}'. Ramificações puxam para banners textuais com os temas: {subtopicos}. "
        f"Estética que remeta à sabedoria e acolhimento. "
        f"OBRIGATÓRIO: No canto inferior direito, insira a assinatura da marca: um símbolo geométrico minimalista "
        f"formado por dois círculos perfeitos entrelaçados horizontalmente, acompanhado do texto ProfessorIA™ em Azul Acadêmico."
    )

    try:
        resp_v = oai_client.images.generate(
            model='dall-e-3',
            prompt=super_prompt,
            size='1024x1024',
            quality='standard',
            n=1
        )
        url_imagem = resp_v.data[0].url
        return jsonify({
            'ok': True,
            'url': url_imagem,
            'titulo': titulo,
            'subtopicos': mapa_json['subtopicos']
        })
    except Exception as e:
        logger.error(f'Erro Etapa 2 Mapa Mental: {e}')
        return jsonify({'erro': 'Falha na geração visual do mapa'}), 500
"""
    
    # Inserir a nova rota antes do bloco __main__
    content = content.replace("if __name__ == '__main__':", nova_rota + "\n\nif __name__ == '__main__':")

    with open(path, 'w') as f:
        f.write(content)
    print("Alterações aplicadas no server.py")

if __name__ == "__main__":
    aplicar_alteracoes()
