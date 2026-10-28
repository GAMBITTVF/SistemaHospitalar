"""Direção: visão geral de todos os setores (somente leitura) e auditoria."""
from flask import Blueprint, render_template, request

from db import get_db
from permissoes import PAPEIS, requer

bp = Blueprint('direcao', __name__)


@bp.route('/direcao')
@requer('direcao')
def painel():
    db = get_db()

    def contar(sql, *parametros):
        return db.execute(sql, parametros).fetchone()[0]

    indicadores = {
        'em_atendimento': contar("SELECT COUNT(*) FROM atendimentos WHERE status = 'aberto'"),
        'internados': contar("SELECT COUNT(*) FROM atendimentos WHERE status = 'internado'"),
        'aguardando_transferencia': contar("SELECT COUNT(*) FROM atendimentos WHERE status = 'aguardando_transferencia'"),
        'sem_triagem': contar("SELECT COUNT(*) FROM atendimentos WHERE status != 'finalizado' AND risco IS NULL"),
        'entradas_hoje': contar("SELECT COUNT(*) FROM atendimentos WHERE date(entrada) = date('now', 'localtime')"),
        'altas_hoje': contar("SELECT COUNT(*) FROM atendimentos WHERE date(saida) = date('now', 'localtime')"),
        'capas_pendentes': contar("SELECT COUNT(*) FROM internacoes WHERE status = 'pendente_assinatura'"),
        'aih_pendentes': contar("SELECT COUNT(*) FROM aih WHERE status IN ('pendente', 'pendencia')"),
        'doses_hoje': contar("SELECT COUNT(*) FROM administracoes WHERE date(administrado_em) = date('now', 'localtime')"),
        'pacientes': contar('SELECT COUNT(*) FROM pacientes'),
    }
    por_risco = {r['risco']: r['n'] for r in db.execute(
        "SELECT risco, COUNT(*) AS n FROM atendimentos WHERE status != 'finalizado' GROUP BY risco")}
    ativos = db.execute(
        """SELECT a.*, p.nome, i.status AS internacao_status FROM atendimentos a
           JOIN pacientes p ON p.id = a.paciente_id LEFT JOIN internacoes i ON i.atendimento_id = a.id
           WHERE a.status != 'finalizado' ORDER BY a.entrada""").fetchall()
    finalizados = db.execute(
        """SELECT a.*, p.nome FROM atendimentos a JOIN pacientes p ON p.id = a.paciente_id
           WHERE a.status = 'finalizado' ORDER BY a.saida DESC LIMIT 30""").fetchall()
    transferencias = db.execute(
        """SELECT t.*, p.nome FROM transferencias t JOIN atendimentos a ON a.id = t.atendimento_id
           JOIN pacientes p ON p.id = a.paciente_id ORDER BY t.solicitada_em DESC LIMIT 15""").fetchall()
    aih = {r['status']: r['n'] for r in db.execute('SELECT status, COUNT(*) AS n FROM aih GROUP BY status')}
    equipe = db.execute('SELECT papel, COUNT(*) AS n FROM usuarios WHERE ativo = 1 GROUP BY papel').fetchall()
    return render_template('direcao/painel.html', ind=indicadores, por_risco=por_risco, ativos=ativos,
                           finalizados=finalizados, transferencias=transferencias, aih=aih, equipe=equipe)


@bp.route('/auditoria')
@requer('auditoria')
def auditoria():
    usuario_id = request.args.get('usuario', type=int)
    data = request.args.get('data', '').strip()
    sql = """SELECT x.*, u.nome, u.papel FROM auditoria x LEFT JOIN usuarios u ON u.id = x.usuario_id WHERE 1 = 1"""
    parametros = []
    if usuario_id:
        sql += ' AND x.usuario_id = ?'
        parametros.append(usuario_id)
    if data:
        sql += ' AND date(x.criado_em) = ?'
        parametros.append(data)
    sql += ' ORDER BY x.id DESC LIMIT 500'
    db = get_db()
    return render_template('direcao/auditoria.html', registros=db.execute(sql, parametros).fetchall(),
                           usuarios=db.execute('SELECT id, nome, papel FROM usuarios ORDER BY nome').fetchall(),
                           usuario_id=usuario_id, data=data, PAPEIS=PAPEIS)
