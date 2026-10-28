"""Área clínica: painel, classificação de risco, evoluções, prescrição/medicação,
diagnóstico, internação (capa), alta, pedido de transferência e relatórios."""
import re
from datetime import date, timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from werkzeug.security import check_password_hash

from db import get_db, registrar
from permissoes import SECAO_EVOLUCAO, pode_ver, requer, tem_permissao
from servicos import (criar_internacao, dados_completos, finalizar_atendimento, obter_atendimento,
                      obter_paciente, transferencia_ativa)
from util import (MOTIVOS_TRANSFERENCIA, RISCOS, TIPOS_SAIDA_MEDICO, VIAS, agora, cid_valido, ler_data,
                  normalizar_cid)

bp = Blueprint('clinico', __name__)


def _texto(campo, maximo=4000):
    return request.form.get(campo, '').strip()[:maximo]


def _voltar(atendimento_id, ancora=''):
    return redirect(url_for('clinico.atendimento', atendimento_id=atendimento_id) + (f'#{ancora}' if ancora else ''))


def _atendimento_editavel(atendimento_id, ancora=''):
    """Retorna (atendimento, None) se pode ser alterado, ou (atendimento, resposta de redirecionamento)."""
    at = obter_atendimento(atendimento_id)
    if at['status'] == 'finalizado':
        flash('Atendimento finalizado: o prontuário não pode mais ser alterado.', 'erro')
        return at, _voltar(atendimento_id, ancora)
    return at, None


def _numero(campo, minimo, maximo, rotulo, erros, tipo=int):
    valor = request.form.get(campo, '').strip().replace(',', '.')
    if not valor:
        return None
    try:
        numero = tipo(valor)
    except ValueError:
        erros.append(f'{rotulo}: valor inválido.')
        return None
    if not minimo <= numero <= maximo:
        erros.append(f'{rotulo}: deve estar entre {minimo} e {maximo}.')
        return None
    return numero


def _sinais_vitais(erros):
    pa = request.form.get('pa', '').strip()
    if pa and not re.fullmatch(r'\d{2,3}\s*[/xX]\s*\d{2,3}', pa):
        erros.append('PA: use o formato 120/80.')
        pa = None
    pa = re.sub(r'\s*[/xX]\s*', '/', pa) if pa else None
    return {
        'pa': pa,
        'fc': _numero('fc', 20, 250, 'FC', erros),
        'fr': _numero('fr', 4, 80, 'FR', erros),
        'temperatura': _numero('temperatura', 30, 45, 'Temperatura', erros, float),
        'spo2': _numero('spo2', 40, 100, 'SpO2', erros),
        'glicemia': _numero('glicemia', 10, 1500, 'Glicemia', erros),
    }


# ------------------------------------------------------------------ painel

@bp.route('/painel')
@requer('painel')
def painel():
    filtro = request.args.get('filtro', 'todos')
    sql = """SELECT a.*, p.nome, p.data_nascimento, p.sexo, p.alergias,
                    i.status AS internacao_status, i.leito,
                    (SELECT COUNT(*) FROM prescricoes pr WHERE pr.atendimento_id = a.id AND pr.status = 'ativa')
                        AS prescricoes_ativas
             FROM atendimentos a JOIN pacientes p ON p.id = a.paciente_id
             LEFT JOIN internacoes i ON i.atendimento_id = a.id
             WHERE a.status != 'finalizado'"""
    parametros = []
    if filtro == 'triagem':
        sql += ' AND a.risco IS NULL'
    elif filtro in ('internado', 'aguardando_transferencia', 'aberto'):
        sql += ' AND a.status = ?'
        parametros.append(filtro)
    # Sem classificação primeiro (aguardando triagem), depois do mais grave ao menos grave.
    ordem = ' '.join(f"WHEN '{k}' THEN {v['ordem']}" for k, v in RISCOS.items())
    sql += f' ORDER BY CASE a.risco {ordem} ELSE 0 END, a.entrada'
    atendimentos = get_db().execute(sql, parametros).fetchall()
    return render_template('clinico/painel.html', atendimentos=atendimentos, filtro=filtro)


# ------------------------------------------------------------------ prontuário do atendimento

@bp.route('/atendimento/<int:atendimento_id>')
@requer('atendimento')
def atendimento(atendimento_id):
    d = dados_completos(atendimento_id)
    return render_template('clinico/atendimento.html', vias=VIAS, tipos_saida=TIPOS_SAIDA_MEDICO,
                           motivos=MOTIVOS_TRANSFERENCIA, **d)


@bp.route('/atendimento/<int:atendimento_id>/triagem', methods=['POST'])
@requer('triagem', 'editar')
def triagem(atendimento_id):
    at, bloqueio = _atendimento_editavel(atendimento_id, 'triagem')
    if bloqueio:
        return bloqueio
    risco = request.form.get('risco')
    observacao = _texto('observacao')
    erros = []
    if risco not in RISCOS:
        erros.append('Selecione a classificação de risco.')
    if len(observacao) < 5:
        erros.append('Descreva a avaliação da classificação de risco.')
    sinais = _sinais_vitais(erros)
    if erros:
        for e in erros:
            flash(e, 'erro')
        return _voltar(atendimento_id, 'triagem')
    db = get_db()
    momento = agora()
    db.execute('UPDATE atendimentos SET risco = ?, triagem_em = ?, triagem_por = ? WHERE id = ?',
               (risco, momento, g.usuario['id'], atendimento_id))
    texto = f'[CLASSIFICAÇÃO DE RISCO: {RISCOS[risco]["nome"].upper()}] {observacao}'
    db.execute("""INSERT INTO evolucoes (atendimento_id, tipo, texto, pa, fc, fr, temperatura, spo2, glicemia,
                                         autor_id, criado_em) VALUES (?, 'enfermagem', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
               (atendimento_id, texto, sinais['pa'], sinais['fc'], sinais['fr'], sinais['temperatura'],
                sinais['spo2'], sinais['glicemia'], g.usuario['id'], momento))
    registrar('triagem', f'Atendimento {atendimento_id} - risco {risco}')
    flash('Classificação de risco registrada.', 'sucesso')
    return _voltar(atendimento_id)


@bp.route('/pacientes/<int:paciente_id>/alergias', methods=['POST'])
@requer('alergias', 'editar')
def alergias(paciente_id):
    obter_paciente(paciente_id)
    texto = _texto('alergias', 500)
    get_db().execute('UPDATE pacientes SET alergias = ? WHERE id = ?', (texto or None, paciente_id))
    registrar('alergias', f'Paciente {paciente_id}: {texto or "sem alergias conhecidas"}')
    flash('Alergias atualizadas.', 'sucesso')
    atendimento_id = request.form.get('atendimento_id', type=int)
    if atendimento_id:
        return _voltar(atendimento_id)
    return redirect(url_for('recepcao.paciente', paciente_id=paciente_id))


# ------------------------------------------------------------------ evoluções

@bp.route('/atendimento/<int:atendimento_id>/evolucao/<tipo>', methods=['POST'])
def evolucao(atendimento_id, tipo):
    secao = SECAO_EVOLUCAO.get(tipo)
    if secao is None:
        abort(404)
    if g.usuario is None:
        return redirect(url_for('auth.login'))
    if not tem_permissao(secao, 'editar'):
        abort(403)
    at, bloqueio = _atendimento_editavel(atendimento_id, f'evol-{tipo}')
    if bloqueio:
        return bloqueio
    texto = _texto('texto')
    erros = []
    if len(texto) < 10:
        erros.append('A evolução precisa descrever o quadro do paciente (mínimo de 10 caracteres).')
    sinais = _sinais_vitais(erros) if tipo != 'medica' else dict.fromkeys(
        ('pa', 'fc', 'fr', 'temperatura', 'spo2', 'glicemia'))
    if erros:
        for e in erros:
            flash(e, 'erro')
        return _voltar(atendimento_id, f'evol-{tipo}')
    get_db().execute(
        """INSERT INTO evolucoes (atendimento_id, tipo, texto, pa, fc, fr, temperatura, spo2, glicemia,
                                  autor_id, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (atendimento_id, tipo, texto, sinais['pa'], sinais['fc'], sinais['fr'], sinais['temperatura'],
         sinais['spo2'], sinais['glicemia'], g.usuario['id'], agora()))
    registrar('evolucao', f'Atendimento {atendimento_id} - {tipo}')
    flash('Evolução registrada.', 'sucesso')
    return _voltar(atendimento_id, f'evol-{tipo}')


@bp.route('/evolucao/<int:evolucao_id>/anular', methods=['POST'])
def anular_evolucao(evolucao_id):
    """Registros de prontuário não são apagados: são anulados com justificativa (fica no histórico)."""
    if g.usuario is None:
        return redirect(url_for('auth.login'))
    ev = get_db().execute('SELECT * FROM evolucoes WHERE id = ?', (evolucao_id,)).fetchone()
    if ev is None:
        abort(404)
    if not tem_permissao(SECAO_EVOLUCAO[ev['tipo']], 'editar'):
        abort(403)
    at, bloqueio = _atendimento_editavel(ev['atendimento_id'], f'evol-{ev["tipo"]}')
    if bloqueio:
        return bloqueio
    motivo = _texto('motivo', 500)
    if ev['anulada_em']:
        flash('Este registro já foi anulado.', 'erro')
    elif len(motivo) < 5:
        flash('Informe o motivo da anulação.', 'erro')
    else:
        get_db().execute('UPDATE evolucoes SET anulada_por = ?, anulada_em = ?, anulada_motivo = ? WHERE id = ?',
                         (g.usuario['id'], agora(), motivo, evolucao_id))
        registrar('evolucao_anulada', f'Evolução {evolucao_id}: {motivo}')
        flash('Registro anulado (permanece visível no histórico).', 'sucesso')
    return _voltar(ev['atendimento_id'], f'evol-{ev["tipo"]}')


# ------------------------------------------------------------------ prescrição e medicação

@bp.route('/atendimento/<int:atendimento_id>/prescricao', methods=['POST'])
@requer('prescricao', 'editar')
def prescrever(atendimento_id):
    at, bloqueio = _atendimento_editavel(atendimento_id, 'medicacao')
    if bloqueio:
        return bloqueio
    dados = {c: _texto(c, 200) for c in ('medicamento', 'dose', 'via', 'frequencia', 'observacao')}
    faltando = [c for c in ('medicamento', 'dose', 'via', 'frequencia') if not dados[c]]
    if faltando or dados['via'] not in VIAS:
        flash('Preencha medicamento, dose, via e frequência.', 'erro')
        return _voltar(atendimento_id, 'medicacao')
    get_db().execute(
        """INSERT INTO prescricoes (atendimento_id, medicamento, dose, via, frequencia, observacao,
                                    prescrito_por, prescrito_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (atendimento_id, dados['medicamento'].upper(), dados['dose'], dados['via'], dados['frequencia'],
         dados['observacao'] or None, g.usuario['id'], agora()))
    registrar('prescricao', f'Atendimento {atendimento_id}: {dados["medicamento"]} {dados["dose"]}')
    flash('Medicação prescrita.', 'sucesso')
    return _voltar(atendimento_id, 'medicacao')


def _obter_prescricao(prescricao_id):
    p = get_db().execute('SELECT * FROM prescricoes WHERE id = ?', (prescricao_id,)).fetchone()
    if p is None:
        abort(404)
    return p


@bp.route('/prescricao/<int:prescricao_id>/suspender', methods=['POST'])
@requer('prescricao', 'editar')
def suspender(prescricao_id):
    p = _obter_prescricao(prescricao_id)
    at, bloqueio = _atendimento_editavel(p['atendimento_id'], 'medicacao')
    if bloqueio:
        return bloqueio
    if p['status'] == 'ativa':
        get_db().execute("UPDATE prescricoes SET status = 'suspensa', suspensa_por = ?, suspensa_em = ? WHERE id = ?",
                         (g.usuario['id'], agora(), prescricao_id))
        registrar('prescricao_suspensa', f'Prescrição {prescricao_id}')
        flash('Prescrição suspensa.', 'sucesso')
    return _voltar(p['atendimento_id'], 'medicacao')


@bp.route('/prescricao/<int:prescricao_id>/administrar', methods=['POST'])
@requer('administracao', 'editar')
def administrar(prescricao_id):
    p = _obter_prescricao(prescricao_id)
    at, bloqueio = _atendimento_editavel(p['atendimento_id'], 'medicacao')
    if bloqueio:
        return bloqueio
    if p['status'] != 'ativa':
        flash('Prescrição suspensa: não é possível administrar.', 'erro')
        return _voltar(p['atendimento_id'], 'medicacao')
    get_db().execute(
        'INSERT INTO administracoes (prescricao_id, administrado_por, administrado_em, observacao) VALUES (?, ?, ?, ?)',
        (prescricao_id, g.usuario['id'], agora(), _texto('observacao', 300) or None))
    registrar('medicacao_administrada', f'Prescrição {prescricao_id} - {p["medicamento"]}')
    flash(f'Administração de {p["medicamento"]} registrada.', 'sucesso')
    return _voltar(p['atendimento_id'], 'medicacao')


# ------------------------------------------------------------------ diagnóstico, internação, alta

@bp.route('/atendimento/<int:atendimento_id>/diagnostico', methods=['POST'])
@requer('diagnostico', 'editar')
def diagnostico(atendimento_id):
    at, bloqueio = _atendimento_editavel(atendimento_id, 'diagnostico')
    if bloqueio:
        return bloqueio
    hipotese = _texto('hipotese_diagnostica', 1000)
    cid = request.form.get('cid_principal', '').strip().upper()
    if not hipotese:
        flash('Informe a hipótese diagnóstica.', 'erro')
    elif cid and not cid_valido(cid):
        flash('CID-10 em formato inválido (ex.: J18.9).', 'erro')
    else:
        get_db().execute('UPDATE atendimentos SET hipotese_diagnostica = ?, cid_principal = ? WHERE id = ?',
                         (hipotese, normalizar_cid(cid) or None, atendimento_id))
        registrar('diagnostico', f'Atendimento {atendimento_id} - CID {cid or "-"}')
        flash('Diagnóstico atualizado.', 'sucesso')
    return _voltar(atendimento_id, 'diagnostico')


@bp.route('/atendimento/<int:atendimento_id>/internar', methods=['POST'])
@requer('internacao', 'editar')
def internar(atendimento_id):
    at, bloqueio = _atendimento_editavel(atendimento_id, 'internacao')
    if bloqueio:
        return bloqueio
    if get_db().execute('SELECT 1 FROM internacoes WHERE atendimento_id = ?', (atendimento_id,)).fetchone():
        flash('Este atendimento já possui internação.', 'erro')
    else:
        criar_internacao(at, 'medica')
        flash('Internação gerada. Preencha e assine a capa.', 'sucesso')
    return _voltar(atendimento_id, 'internacao')


def _obter_internacao(internacao_id):
    i = get_db().execute('SELECT * FROM internacoes WHERE id = ?', (internacao_id,)).fetchone()
    if i is None:
        abort(404)
    return i


@bp.route('/internacao/<int:internacao_id>/capa', methods=['POST'])
@requer('internacao', 'editar')
def salvar_capa(internacao_id):
    """Salva a capa e, se o médico marcar 'assinar' e confirmar a senha, assina eletronicamente."""
    inter = _obter_internacao(internacao_id)
    at, bloqueio = _atendimento_editavel(inter['atendimento_id'], 'internacao')
    if bloqueio:
        return bloqueio
    if inter['status'] != 'pendente_assinatura':
        flash('A capa já foi assinada e não pode ser alterada.', 'erro')
        return _voltar(inter['atendimento_id'], 'internacao')

    diagnostico_txt = _texto('diagnostico', 1000)
    cid1 = request.form.get('cid_principal', '').strip().upper()
    cid2 = request.form.get('cid_secundario', '').strip().upper()
    chegada = _texto('descricao_chegada', 1000)
    leito = _texto('leito', 30)
    erros = []
    if cid1 and not cid_valido(cid1):
        erros.append('CID principal em formato inválido (ex.: J18.9).')
    if cid2 and not cid_valido(cid2):
        erros.append('CID secundário em formato inválido.')
    assinar = request.form.get('assinar') == '1'
    if assinar:
        if not diagnostico_txt or not cid1 or not chegada:
            erros.append('Para assinar, preencha diagnóstico, CID principal e descrição da chegada.')
        if not check_password_hash(g.usuario['senha_hash'], request.form.get('senha', '')):
            erros.append('Senha de assinatura incorreta.')
        if not g.usuario['registro_conselho']:
            erros.append('Seu usuário não tem CRM cadastrado. Peça ao administrador para incluir.')
    if erros:
        for e in erros:
            flash(e, 'erro')
        return _voltar(inter['atendimento_id'], 'internacao')

    db = get_db()
    db.execute("""UPDATE internacoes SET diagnostico = ?, cid_principal = ?, cid_secundario = ?,
                                         descricao_chegada = ?, leito = ? WHERE id = ?""",
               (diagnostico_txt or None, normalizar_cid(cid1) or None, normalizar_cid(cid2) or None,
                chegada or None, leito or None, internacao_id))
    if assinar:
        db.execute("UPDATE internacoes SET status = 'assinada', assinada_por = ?, assinada_em = ? WHERE id = ?",
                   (g.usuario['id'], agora(), internacao_id))
        if not at['cid_principal']:
            db.execute('UPDATE atendimentos SET cid_principal = ?, hipotese_diagnostica = COALESCE('
                       'hipotese_diagnostica, ?) WHERE id = ?', (normalizar_cid(cid1), diagnostico_txt, at['id']))
        registrar('capa_assinada', f'Internação {internacao_id}')
        flash('Capa de internação assinada.', 'sucesso')
    else:
        registrar('capa_salva', f'Internação {internacao_id}')
        flash('Capa salva (ainda pendente de assinatura).', 'sucesso')
    return _voltar(inter['atendimento_id'], 'internacao')


@bp.route('/internacao/<int:internacao_id>/imprimir')
@requer('internacao')
def imprimir_capa(internacao_id):
    inter = _obter_internacao(internacao_id)
    return render_template('documentos/capa_internacao.html', **dados_completos(inter['atendimento_id']))


@bp.route('/atendimento/<int:atendimento_id>/alta', methods=['POST'])
@requer('alta', 'editar')
def alta(atendimento_id):
    at, bloqueio = _atendimento_editavel(atendimento_id, 'alta')
    if bloqueio:
        return bloqueio
    tipo = request.form.get('tipo_saida')
    resumo = _texto('resumo_alta')
    inter = get_db().execute('SELECT * FROM internacoes WHERE atendimento_id = ?', (atendimento_id,)).fetchone()
    if tipo not in TIPOS_SAIDA_MEDICO:
        flash('Selecione o tipo de saída.', 'erro')
    elif len(resumo) < 10:
        flash('Escreva o resumo da alta / orientações.', 'erro')
    elif transferencia_ativa(atendimento_id):
        flash('Há uma transferência em andamento. Ela precisa ser concluída ou cancelada pela central.', 'erro')
    elif inter is not None and inter['status'] == 'pendente_assinatura':
        flash('Assine a capa de internação antes de dar alta.', 'erro')
    else:
        finalizar_atendimento(at, tipo, resumo, g.usuario['id'])
        registrar('alta', f'Atendimento {atendimento_id} - {tipo}')
        if inter is not None:
            flash('Alta registrada. Internação enviada ao faturamento (AIH).', 'sucesso')
        else:
            flash('Alta registrada. O relatório do atendimento está disponível.', 'sucesso')
    return _voltar(atendimento_id)


@bp.route('/atendimento/<int:atendimento_id>/transferencia', methods=['POST'])
@requer('solicitar_transferencia', 'editar')
def solicitar_transferencia(atendimento_id):
    at, bloqueio = _atendimento_editavel(atendimento_id, 'transferencia')
    if bloqueio:
        return bloqueio
    motivo = request.form.get('motivo')
    justificativa = _texto('justificativa', 2000)
    especialidade = _texto('especialidade', 120)
    if transferencia_ativa(atendimento_id):
        flash('Já existe uma transferência em andamento para este atendimento.', 'erro')
    elif motivo not in MOTIVOS_TRANSFERENCIA:
        flash('Selecione o motivo da transferência.', 'erro')
    elif len(justificativa) < 10:
        flash('Descreva a justificativa clínica (o que falta para atender o paciente).', 'erro')
    else:
        db = get_db()
        db.execute("""INSERT INTO transferencias (atendimento_id, motivo, justificativa, especialidade,
                                                  solicitada_por, solicitada_em) VALUES (?, ?, ?, ?, ?, ?)""",
                   (atendimento_id, motivo, justificativa, especialidade or None, g.usuario['id'], agora()))
        db.execute("UPDATE atendimentos SET status = 'aguardando_transferencia' WHERE id = ?", (atendimento_id,))
        registrar('transferencia_solicitada', f'Atendimento {atendimento_id} - {motivo}')
        flash('Paciente encaminhado para a Central de Transferência.', 'sucesso')
    return _voltar(atendimento_id, 'transferencia')


# ------------------------------------------------------------------ relatórios

@bp.route('/atendimento/<int:atendimento_id>/relatorio')
@requer('relatorios')
def relatorio(atendimento_id):
    return render_template('documentos/relatorio_atendimento.html', **dados_completos(atendimento_id))


@bp.route('/relatorios/medicacoes')
@requer('relatorios')
def relatorio_medicacoes():
    """Quantas medicações foram administradas, quais e para quantos pacientes, no período."""
    inicio = ler_data(request.args.get('inicio'))
    fim = ler_data(request.args.get('fim'))
    if fim is None:
        fim = date.today()
    if inicio is None:
        inicio = fim - timedelta(days=6)
    if inicio > fim:
        inicio, fim = fim, inicio
    parametros = (inicio.isoformat(), fim.isoformat())
    db = get_db()
    resumo = db.execute(
        """SELECT p.medicamento, COUNT(*) AS doses, COUNT(DISTINCT a.paciente_id) AS pacientes,
                  COUNT(DISTINCT a.id) AS atendimentos
           FROM administracoes ad JOIN prescricoes p ON p.id = ad.prescricao_id
           JOIN atendimentos a ON a.id = p.atendimento_id
           WHERE date(ad.administrado_em) BETWEEN ? AND ?
           GROUP BY p.medicamento ORDER BY doses DESC, p.medicamento""", parametros).fetchall()
    detalhes = db.execute(
        """SELECT ad.administrado_em, p.medicamento, p.dose, p.via, pa.nome AS paciente, a.id AS atendimento_id,
                  u.nome AS profissional, u.papel AS profissional_papel,
                  (SELECT COUNT(*) FROM internacoes i WHERE i.atendimento_id = a.id) AS internado
           FROM administracoes ad JOIN prescricoes p ON p.id = ad.prescricao_id
           JOIN atendimentos a ON a.id = p.atendimento_id JOIN pacientes pa ON pa.id = a.paciente_id
           JOIN usuarios u ON u.id = ad.administrado_por
           WHERE date(ad.administrado_em) BETWEEN ? AND ?
           ORDER BY ad.administrado_em DESC LIMIT 500""", parametros).fetchall()
    so_medicacao = db.execute(
        """SELECT COUNT(*) FROM atendimentos a
           WHERE date(a.entrada) BETWEEN ? AND ? AND a.status = 'finalizado'
             AND NOT EXISTS (SELECT 1 FROM internacoes i WHERE i.atendimento_id = a.id)
             AND EXISTS (SELECT 1 FROM prescricoes p JOIN administracoes ad ON ad.prescricao_id = p.id
                         WHERE p.atendimento_id = a.id)""", parametros).fetchone()[0]
    return render_template('clinico/relatorio_medicacoes.html', resumo=resumo, detalhes=detalhes,
                           inicio=inicio, fim=fim, so_medicacao=so_medicacao,
                           total_doses=sum(r['doses'] for r in resumo), pode_abrir=pode_ver('atendimento'))
