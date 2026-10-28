"""Central de Transferência: recebe os pacientes enviados pelo médico (ex.: falta de materiais)
com os dados completos para cadastro no hospital de destino / regulação."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from db import get_db, registrar
from permissoes import requer
from servicos import dados_completos, finalizar_atendimento, obter_atendimento
from util import STATUS_TRANSFERENCIA, agora

bp = Blueprint('transferencia', __name__)

# Transições permitidas de status.
FLUXO = {
    'solicitada': {'em_contato', 'aceita', 'cancelada'},
    'em_contato': {'aceita', 'cancelada'},
    'aceita': {'concluida', 'em_contato', 'cancelada'},
}


def _obter(transferencia_id):
    t = get_db().execute('SELECT * FROM transferencias WHERE id = ?', (transferencia_id,)).fetchone()
    if t is None:
        abort(404)
    return t


@bp.route('/transferencias')
@requer('central_transferencia')
def lista():
    filtro = request.args.get('filtro', 'ativas')
    sql = """SELECT t.*, p.nome, p.cpf, p.cns, a.risco, a.entrada, u.nome AS solicitante_nome
             FROM transferencias t JOIN atendimentos a ON a.id = t.atendimento_id
             JOIN pacientes p ON p.id = a.paciente_id JOIN usuarios u ON u.id = t.solicitada_por"""
    if filtro == 'ativas':
        sql += " WHERE t.status NOT IN ('concluida', 'cancelada')"
    sql += ' ORDER BY t.solicitada_em DESC LIMIT 300'
    return render_template('transferencia/lista.html', transferencias=get_db().execute(sql).fetchall(),
                           filtro=filtro)


@bp.route('/transferencias/<int:transferencia_id>')
@requer('central_transferencia')
def detalhe(transferencia_id):
    t = _obter(transferencia_id)
    return render_template('transferencia/detalhe.html', t=t, fluxo=FLUXO.get(t['status'], set()),
                           **dados_completos(t['atendimento_id']))


@bp.route('/transferencias/<int:transferencia_id>/ficha')
@requer('central_transferencia')
def ficha(transferencia_id):
    t = _obter(transferencia_id)
    return render_template('documentos/ficha_transferencia.html', t=t, **dados_completos(t['atendimento_id']))


@bp.route('/transferencias/<int:transferencia_id>/atualizar', methods=['POST'])
@requer('central_transferencia', 'editar')
def atualizar(transferencia_id):
    t = _obter(transferencia_id)
    if t['status'] in ('concluida', 'cancelada'):
        flash('Esta transferência já foi encerrada.', 'erro')
        return redirect(url_for('transferencia.detalhe', transferencia_id=transferencia_id))

    novo = request.form.get('status', t['status'])
    destino = ' '.join(request.form.get('hospital_destino', '').split())[:200]
    contato = request.form.get('contato_destino', '').strip()[:200]
    protocolo = request.form.get('protocolo_regulacao', '').strip()[:60]
    obs = request.form.get('observacoes', '').strip()[:2000]

    if novo != t['status'] and novo not in FLUXO.get(t['status'], set()):
        flash('Mudança de status não permitida.', 'erro')
    elif novo in ('aceita', 'concluida') and not destino:
        flash('Informe o hospital de destino.', 'erro')
    elif novo == 'cancelada' and len(obs) < 5:
        flash('Informe nas observações o motivo do cancelamento.', 'erro')
    else:
        db = get_db()
        momento = agora()
        db.execute("""UPDATE transferencias SET status = ?, hospital_destino = ?, contato_destino = ?,
                          protocolo_regulacao = ?, observacoes = ?, atualizado_por = ?, atualizado_em = ?,
                          concluida_em = CASE WHEN ? = 'concluida' THEN ? ELSE concluida_em END
                      WHERE id = ?""",
                   (novo, destino or None, contato or None, protocolo or None, obs or None, g.usuario['id'],
                    momento, novo, momento, transferencia_id))
        at = obter_atendimento(t['atendimento_id'])
        if novo == 'concluida':
            resumo = f'Transferido para {destino}.' + (f' Protocolo: {protocolo}.' if protocolo else '')
            finalizar_atendimento(at, 'transferencia', resumo, g.usuario['id'])
        elif novo == 'cancelada':
            tem_internacao = db.execute('SELECT 1 FROM internacoes WHERE atendimento_id = ?', (at['id'],)).fetchone()
            db.execute('UPDATE atendimentos SET status = ? WHERE id = ?',
                       ('internado' if tem_internacao else 'aberto', at['id']))
        registrar('transferencia_atualizada', f'Transferência {transferencia_id}: {STATUS_TRANSFERENCIA[novo]}')
        flash('Transferência atualizada.', 'sucesso')
    return redirect(url_for('transferencia.detalhe', transferencia_id=transferencia_id))
