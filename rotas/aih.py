"""Faturamento: o agente de AIH confere a internação e autoriza o envio para SISAIH01 ou SIHD2."""
import re

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for

from db import get_db, registrar
from permissoes import requer
from servicos import dados_completos
from util import SISTEMAS_AIH, agora, para_datetime, so_digitos

bp = Blueprint('aih', __name__)


def _obter(aih_id):
    a = get_db().execute('SELECT * FROM aih WHERE id = ?', (aih_id,)).fetchone()
    if a is None:
        abort(404)
    return a


@bp.route('/aih')
@requer('aih')
def lista():
    filtro = request.args.get('status', 'pendente')
    sql = """SELECT x.*, p.nome, p.cns, a.entrada, a.saida, a.tipo_saida, i.cid_principal, u.nome AS revisor
             FROM aih x JOIN atendimentos a ON a.id = x.atendimento_id
             JOIN pacientes p ON p.id = a.paciente_id JOIN internacoes i ON i.id = x.internacao_id
             LEFT JOIN usuarios u ON u.id = x.revisado_por"""
    parametros = []
    if filtro in ('pendente', 'pendencia', 'autorizada', 'exportada'):
        sql += ' WHERE x.status = ?'
        parametros.append(filtro)
    sql += ' ORDER BY a.saida DESC LIMIT 500'
    db = get_db()
    contagem = {r['status']: r['n'] for r in db.execute('SELECT status, COUNT(*) AS n FROM aih GROUP BY status')}
    prontas = {s: db.execute("SELECT COUNT(*) FROM aih WHERE status = 'autorizada' AND sistema_destino = ?",
                             (s,)).fetchone()[0] for s in SISTEMAS_AIH}
    return render_template('aih/lista.html', registros=db.execute(sql, parametros).fetchall(), filtro=filtro,
                           contagem=contagem, prontas=prontas)


@bp.route('/aih/<int:aih_id>')
@requer('aih')
def detalhe(aih_id):
    registro = _obter(aih_id)
    return render_template('aih/detalhe.html', registro=registro, sistemas=SISTEMAS_AIH,
                           **dados_completos(registro['atendimento_id']))


@bp.route('/aih/<int:aih_id>/decidir', methods=['POST'])
@requer('aih', 'editar')
def decidir(aih_id):
    registro = _obter(aih_id)
    if registro['status'] not in ('pendente', 'pendencia'):
        flash('Esta AIH já foi autorizada/exportada.', 'erro')
        return redirect(url_for('aih.detalhe', aih_id=aih_id))
    acao = request.form.get('acao')
    numero = so_digitos(request.form.get('numero_aih'))
    procedimento = so_digitos(request.form.get('procedimento_sigtap'))
    sistema = request.form.get('sistema_destino')
    obs = request.form.get('observacao', '').strip()[:2000]
    db = get_db()

    if acao == 'autorizar':
        erros = []
        if len(numero) != 13:
            erros.append('Número da AIH deve ter 13 dígitos.')
        elif db.execute('SELECT 1 FROM aih WHERE numero_aih = ? AND id != ?', (numero, aih_id)).fetchone():
            erros.append('Este número de AIH já foi usado em outra internação.')
        if len(procedimento) != 10:
            erros.append('Procedimento SIGTAP deve ter 10 dígitos.')
        if sistema not in SISTEMAS_AIH:
            erros.append('Selecione o sistema de destino (SISAIH01 ou SIHD2).')
        internacao = db.execute('SELECT * FROM internacoes WHERE id = ?', (registro['internacao_id'],)).fetchone()
        if internacao['assinada_em'] is None:
            erros.append('A capa de internação não foi assinada pelo médico.')
        if erros:
            for e in erros:
                flash(e, 'erro')
            return redirect(url_for('aih.detalhe', aih_id=aih_id))
        db.execute("""UPDATE aih SET status = 'autorizada', numero_aih = ?, procedimento_sigtap = ?,
                          sistema_destino = ?, observacao = ?, revisado_por = ?, revisado_em = ? WHERE id = ?""",
                   (numero, procedimento, sistema, obs or None, g.usuario['id'], agora(), aih_id))
        registrar('aih_autorizada', f'AIH {aih_id} nº {numero} -> {sistema}')
        flash(f'AIH autorizada para envio ao {sistema}.', 'sucesso')
    elif acao == 'pendencia':
        if len(obs) < 5:
            flash('Descreva a pendência encontrada.', 'erro')
            return redirect(url_for('aih.detalhe', aih_id=aih_id))
        db.execute("UPDATE aih SET status = 'pendencia', observacao = ?, revisado_por = ?, revisado_em = ? "
                   'WHERE id = ?', (obs, g.usuario['id'], agora(), aih_id))
        registrar('aih_pendencia', f'AIH {aih_id}: {obs}')
        flash('Pendência registrada.', 'sucesso')
    else:
        abort(400)
    return redirect(url_for('aih.detalhe', aih_id=aih_id))


def _data_sus(valor):
    d = para_datetime(valor)
    return d.strftime('%Y%m%d') if d else ''


def _campo(texto):
    return re.sub(r'[;\r\n]', ' ', texto or '').strip()


@bp.route('/aih/exportar', methods=['POST'])
@requer('aih', 'editar')
def exportar():
    """Gera o lote das AIHs autorizadas para o sistema escolhido e marca como exportadas.

    ATENÇÃO: layout simplificado (CSV ';'). Para importação real no SISAIH01/SIHD2 adapte para o
    leiaute oficial publicado pelo DATASUS para a competência vigente.
    """
    sistema = request.form.get('sistema')
    if sistema not in SISTEMAS_AIH:
        abort(400, 'Sistema inválido.')
    db = get_db()
    registros = db.execute(
        """SELECT x.*, p.nome, p.cns, p.cpf, p.data_nascimento, p.sexo, p.nome_mae, p.cep, p.logradouro, p.numero,
                  p.bairro, p.cidade, p.uf, a.entrada, a.saida, a.tipo_saida, i.cid_principal, i.cid_secundario,
                  u.registro_conselho AS crm
           FROM aih x JOIN atendimentos a ON a.id = x.atendimento_id JOIN pacientes p ON p.id = a.paciente_id
           JOIN internacoes i ON i.id = x.internacao_id LEFT JOIN usuarios u ON u.id = i.assinada_por
           WHERE x.status = 'autorizada' AND x.sistema_destino = ? ORDER BY x.id""", (sistema,)).fetchall()
    if not registros:
        flash(f'Nenhuma AIH autorizada aguardando exportação para {sistema}.', 'info')
        return redirect(url_for('aih.lista', status='autorizada'))

    colunas = ['NUM_AIH', 'PROC_SIGTAP', 'CNS', 'CPF', 'NOME', 'NASCIMENTO', 'SEXO', 'NOME_MAE', 'CEP',
               'LOGRADOURO', 'NUMERO', 'BAIRRO', 'MUNICIPIO', 'UF', 'DT_INTERNACAO', 'DT_SAIDA', 'MOTIVO_SAIDA',
               'CID_PRINCIPAL', 'CID_SECUNDARIO', 'CRM_SOLICITANTE']
    linhas = [';'.join(colunas)]
    for r in registros:
        valores = [r['numero_aih'], r['procedimento_sigtap'], r['cns'], r['cpf'], r['nome'],
                   _data_sus(r['data_nascimento']), r['sexo'], r['nome_mae'], r['cep'], r['logradouro'], r['numero'],
                   r['bairro'], r['cidade'], r['uf'], _data_sus(r['entrada']), _data_sus(r['saida']),
                   r['tipo_saida'], (r['cid_principal'] or '').replace('.', ''),
                   (r['cid_secundario'] or '').replace('.', ''), r['crm']]
        linhas.append(';'.join(_campo(str(v) if v is not None else '') for v in valores))

    momento = agora()
    db.executemany("UPDATE aih SET status = 'exportada', exportado_em = ? WHERE id = ?",
                   [(momento, r['id']) for r in registros])
    registrar('aih_exportada', f'{len(registros)} AIH(s) para {sistema}')
    nome = f'lote_{sistema}_{momento[:10].replace("-", "")}_{momento[11:19].replace(":", "")}.csv'
    return Response('\r\n'.join(linhas) + '\r\n', mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename={nome}'})
