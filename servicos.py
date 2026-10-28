"""Regras de negócio compartilhadas entre os setores."""
from datetime import datetime, timedelta

from flask import abort

from db import get_db, registrar
from util import FORMATO_DATA, agora

HORAS_PARA_INTERNACAO = 24


def obter_paciente(paciente_id):
    paciente = get_db().execute('SELECT * FROM pacientes WHERE id = ?', (paciente_id,)).fetchone()
    if paciente is None:
        abort(404)
    return paciente


def obter_atendimento(atendimento_id):
    atendimento = get_db().execute('SELECT * FROM atendimentos WHERE id = ?', (atendimento_id,)).fetchone()
    if atendimento is None:
        abort(404)
    return atendimento


def atendimento_aberto_do_paciente(paciente_id):
    return get_db().execute(
        "SELECT * FROM atendimentos WHERE paciente_id = ? AND status != 'finalizado'",
        (paciente_id,)).fetchone()


def transferencia_ativa(atendimento_id):
    return get_db().execute(
        "SELECT * FROM transferencias WHERE atendimento_id = ? AND status NOT IN ('concluida', 'cancelada')",
        (atendimento_id,)).fetchone()


def gerar_internacoes_automaticas():
    """Todo atendimento ainda aberto há mais de 24 horas vira internação (com capa pendente de assinatura)."""
    db = get_db()
    limite = (datetime.now() - timedelta(hours=HORAS_PARA_INTERNACAO)).strftime(FORMATO_DATA)
    pendentes = db.execute(
        """SELECT a.* FROM atendimentos a
           WHERE a.status IN ('aberto', 'aguardando_transferencia') AND a.entrada <= ?
             AND NOT EXISTS (SELECT 1 FROM internacoes i WHERE i.atendimento_id = a.id)""",
        (limite,)).fetchall()
    for at in pendentes:
        criar_internacao(at, 'automatica_24h', registrar_auditoria=False)
    if pendentes:
        registrar('internacao_automatica',
                  'Internação gerada (>24h) para atendimento(s) ' + ', '.join(str(a['id']) for a in pendentes))


def criar_internacao(at, origem, registrar_auditoria=True):
    db = get_db()
    db.execute(
        """INSERT INTO internacoes (atendimento_id, criada_em, origem, diagnostico, cid_principal,
                                    descricao_chegada, status)
           VALUES (?, ?, ?, ?, ?, ?, 'pendente_assinatura')""",
        (at['id'], agora(), origem, at['hipotese_diagnostica'], at['cid_principal'], at['motivo_procura']))
    db.execute("UPDATE atendimentos SET status = 'internado' WHERE id = ? AND status = 'aberto'", (at['id'],))
    if registrar_auditoria:
        registrar('internacao_criada', f'Atendimento {at["id"]} ({origem})')


def finalizar_atendimento(at, tipo_saida, resumo, usuario_id):
    """Encerra o atendimento. Se houve internação, encerra-a e envia para o faturamento (AIH)."""
    db = get_db()
    momento = agora()
    db.execute(
        """UPDATE atendimentos SET status = 'finalizado', saida = ?, tipo_saida = ?, resumo_alta = ?, alta_por = ?
           WHERE id = ?""", (momento, tipo_saida, resumo, usuario_id, at['id']))
    db.execute("UPDATE prescricoes SET status = 'suspensa', suspensa_em = ?, suspensa_por = ? "
               "WHERE atendimento_id = ? AND status = 'ativa'", (momento, usuario_id, at['id']))
    internacao = db.execute('SELECT * FROM internacoes WHERE atendimento_id = ?', (at['id'],)).fetchone()
    if internacao is not None:
        db.execute("UPDATE internacoes SET status = 'encerrada', encerrada_em = ? WHERE id = ?",
                   (momento, internacao['id']))
        db.execute("INSERT OR IGNORE INTO aih (atendimento_id, internacao_id, status, criado_em) "
                   "VALUES (?, ?, 'pendente', ?)", (at['id'], internacao['id'], momento))


def dados_completos(atendimento_id):
    """Reúne tudo de um atendimento (usado na tela clínica, relatórios, AIH e transferência)."""
    db = get_db()
    at = obter_atendimento(atendimento_id)
    paciente = obter_paciente(at['paciente_id'])

    evolucoes = db.execute(
        """SELECT e.*, u.nome AS autor_nome, u.papel AS autor_papel, u.registro_conselho AS autor_registro,
                  ua.nome AS anulada_por_nome
           FROM evolucoes e JOIN usuarios u ON u.id = e.autor_id
           LEFT JOIN usuarios ua ON ua.id = e.anulada_por
           WHERE e.atendimento_id = ? ORDER BY e.criado_em DESC, e.id DESC""", (atendimento_id,)).fetchall()
    por_tipo = {'tecnico': [], 'enfermagem': [], 'medica': []}
    for e in evolucoes:
        por_tipo[e['tipo']].append(e)

    prescricoes = db.execute(
        """SELECT p.*, u.nome AS medico_nome, u.registro_conselho AS medico_registro,
                  (SELECT COUNT(*) FROM administracoes ad WHERE ad.prescricao_id = p.id) AS total_administrado,
                  (SELECT MAX(ad.administrado_em) FROM administracoes ad WHERE ad.prescricao_id = p.id) AS ultima_dose
           FROM prescricoes p JOIN usuarios u ON u.id = p.prescrito_por
           WHERE p.atendimento_id = ? ORDER BY p.prescrito_em DESC, p.id DESC""", (atendimento_id,)).fetchall()

    administracoes = db.execute(
        """SELECT ad.*, p.medicamento, p.dose, p.via, u.nome AS profissional, u.papel AS profissional_papel
           FROM administracoes ad JOIN prescricoes p ON p.id = ad.prescricao_id
           JOIN usuarios u ON u.id = ad.administrado_por
           WHERE p.atendimento_id = ? ORDER BY ad.administrado_em DESC, ad.id DESC""", (atendimento_id,)).fetchall()

    internacao = db.execute(
        """SELECT i.*, u.nome AS medico_nome, u.registro_conselho AS medico_registro
           FROM internacoes i LEFT JOIN usuarios u ON u.id = i.assinada_por
           WHERE i.atendimento_id = ?""", (atendimento_id,)).fetchone()

    transferencias = db.execute(
        """SELECT t.*, u.nome AS solicitante_nome, u.registro_conselho AS solicitante_registro
           FROM transferencias t JOIN usuarios u ON u.id = t.solicitada_por
           WHERE t.atendimento_id = ? ORDER BY t.solicitada_em DESC""", (atendimento_id,)).fetchall()

    passagens = db.execute(
        """SELECT a.*, (SELECT COUNT(*) FROM internacoes i WHERE i.atendimento_id = a.id) AS teve_internacao
           FROM atendimentos a WHERE a.paciente_id = ? AND a.id != ? ORDER BY a.entrada DESC""",
        (paciente['id'], atendimento_id)).fetchall()

    nomes = {}
    for chave in ('triagem_por', 'alta_por', 'aberto_por'):
        if at[chave]:
            u = db.execute('SELECT nome, registro_conselho FROM usuarios WHERE id = ?', (at[chave],)).fetchone()
            nomes[chave] = u
    aih = db.execute('SELECT * FROM aih WHERE atendimento_id = ?', (atendimento_id,)).fetchone()

    return {
        'at': at, 'paciente': paciente, 'evolucoes': por_tipo, 'prescricoes': prescricoes,
        'administracoes': administracoes, 'internacao': internacao, 'transferencias': transferencias,
        'transferencia_ativa': next((t for t in transferencias if t['status'] not in ('concluida', 'cancelada')), None),
        'passagens': passagens, 'nomes': nomes, 'aih': aih,
    }
