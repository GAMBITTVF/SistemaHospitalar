"""Recepção: cadastro do paciente, consulta de passagens anteriores e abertura de atendimento."""
import re
from datetime import date

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from db import get_db, registrar
from permissoes import requer
from servicos import atendimento_aberto_do_paciente, obter_paciente
from util import SEXOS, UFS, agora, cns_valido, cpf_valido, ler_data, so_digitos

bp = Blueprint('recepcao', __name__)

CAMPOS = ['nome', 'nome_social', 'cpf', 'cns', 'data_nascimento', 'sexo', 'nome_mae', 'telefone',
          'cep', 'logradouro', 'numero', 'complemento', 'bairro', 'cidade', 'uf']


def ler_formulario(paciente_id=None):
    """Lê e valida o formulário de paciente. Retorna (dados, erros)."""
    f = {c: ' '.join(request.form.get(c, '').split()) for c in CAMPOS}
    erros = {}

    f['nome'] = f['nome'].upper()
    f['nome_mae'] = f['nome_mae'].upper()
    f['nome_social'] = f['nome_social'].upper()
    if len(f['nome'].split()) < 2:
        erros['nome'] = 'Informe o nome completo (nome e sobrenome).'
    if len(f['nome_mae'].split()) < 2:
        erros['nome_mae'] = 'Informe o nome completo da mãe.'

    f['cpf'] = so_digitos(f['cpf'])
    if not cpf_valido(f['cpf']):
        erros['cpf'] = 'CPF inválido. Confira os 11 dígitos.'
    f['cns'] = so_digitos(f['cns'])
    if not cns_valido(f['cns']):
        erros['cns'] = 'Cartão do SUS (CNS) inválido. Confira os 15 dígitos.'

    nascimento = ler_data(f['data_nascimento'])
    if nascimento is None:
        erros['data_nascimento'] = 'Data de nascimento inválida.'
    elif nascimento > date.today():
        erros['data_nascimento'] = 'A data de nascimento não pode ser no futuro.'
    elif date.today().year - nascimento.year > 130:
        erros['data_nascimento'] = 'Data de nascimento improvável. Confira o ano.'

    if f['sexo'] not in SEXOS:
        erros['sexo'] = 'Selecione o sexo.'
    f['telefone'] = so_digitos(f['telefone'])
    if len(f['telefone']) not in (10, 11):
        erros['telefone'] = 'Telefone com DDD: 10 ou 11 dígitos.'
    f['cep'] = so_digitos(f['cep'])
    if len(f['cep']) != 8:
        erros['cep'] = 'CEP deve ter 8 dígitos.'
    for campo, rotulo in (('logradouro', 'Logradouro'), ('numero', 'Número'), ('bairro', 'Bairro'),
                          ('cidade', 'Cidade')):
        if not f[campo]:
            erros[campo] = f'{rotulo} é obrigatório.'
    f['cidade'] = f['cidade'].upper()
    f['uf'] = f['uf'].upper()
    if f['uf'] not in UFS:
        erros['uf'] = 'Selecione a UF.'

    db = get_db()
    if 'cpf' not in erros:
        dono = db.execute('SELECT id, nome FROM pacientes WHERE cpf = ? AND id != ?',
                          (f['cpf'], paciente_id or 0)).fetchone()
        if dono:
            erros['cpf'] = f'CPF já cadastrado para {dono["nome"]} (prontuário {dono["id"]}).'
    if 'cns' not in erros:
        dono = db.execute('SELECT id, nome FROM pacientes WHERE cns = ? AND id != ?',
                          (f['cns'], paciente_id or 0)).fetchone()
        if dono:
            erros['cns'] = f'Cartão SUS já cadastrado para {dono["nome"]} (prontuário {dono["id"]}).'
    return f, erros


@bp.route('/pacientes')
@requer('cadastro')
def busca():
    termo = request.args.get('q', '').strip()
    db = get_db()
    pacientes = []
    if termo:
        digitos = re.sub(r'[\s./-]', '', termo)
        if digitos.isdigit():
            pacientes = db.execute(
                'SELECT * FROM pacientes WHERE cpf LIKE ? OR cns LIKE ? OR id = ? ORDER BY nome LIMIT 50',
                (digitos + '%', digitos + '%', int(digitos))).fetchall()
        else:
            pacientes = db.execute('SELECT * FROM pacientes WHERE nome LIKE ? OR nome_social LIKE ? '
                                   'ORDER BY nome LIMIT 50', (f'%{termo.upper()}%', f'%{termo.upper()}%')).fetchall()
    hoje = db.execute(
        """SELECT a.*, p.nome FROM atendimentos a JOIN pacientes p ON p.id = a.paciente_id
           WHERE date(a.entrada) = date('now', 'localtime') ORDER BY a.entrada DESC""").fetchall()
    return render_template('recepcao/busca.html', termo=termo, pacientes=pacientes, hoje=hoje)


@bp.route('/pacientes/novo', methods=['GET', 'POST'])
@requer('cadastro', 'editar')
def novo():
    dados, erros = {}, {}
    if request.method == 'POST':
        dados, erros = ler_formulario()
        if not erros:
            db = get_db()
            cursor = db.execute(
                """INSERT INTO pacientes (nome, nome_social, cpf, cns, data_nascimento, sexo, nome_mae, telefone,
                       cep, logradouro, numero, complemento, bairro, cidade, uf, criado_em, criado_por)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                tuple(dados[c] or None for c in CAMPOS) + (agora(), g.usuario['id']))
            registrar('paciente_cadastrado', f'Paciente {cursor.lastrowid} - {dados["nome"]}')
            flash('Paciente cadastrado com sucesso. Agora abra o atendimento.', 'sucesso')
            return redirect(url_for('recepcao.paciente', paciente_id=cursor.lastrowid))
        flash('Corrija os campos destacados.', 'erro')
    elif request.args.get('q'):
        termo = request.args['q']
        digitos = so_digitos(termo)
        dados = {'cpf': digitos} if len(digitos) == 11 else {'cns': digitos} if len(digitos) == 15 else {'nome': termo}
    return render_template('recepcao/paciente_form.html', dados=dados, erros=erros, ufs=UFS, novo=True)


@bp.route('/pacientes/<int:paciente_id>/editar', methods=['GET', 'POST'])
@requer('cadastro', 'editar')
def editar(paciente_id):
    paciente = obter_paciente(paciente_id)
    dados, erros = dict(paciente), {}
    if request.method == 'POST':
        dados, erros = ler_formulario(paciente_id)
        if not erros:
            get_db().execute(
                f"UPDATE pacientes SET {', '.join(c + ' = ?' for c in CAMPOS)}, atualizado_em = ? WHERE id = ?",
                tuple(dados[c] or None for c in CAMPOS) + (agora(), paciente_id))
            registrar('paciente_editado', f'Paciente {paciente_id}')
            flash('Cadastro atualizado.', 'sucesso')
            return redirect(url_for('recepcao.paciente', paciente_id=paciente_id))
        flash('Corrija os campos destacados.', 'erro')
    return render_template('recepcao/paciente_form.html', dados=dados, erros=erros, ufs=UFS, novo=False,
                           paciente=paciente)


@bp.route('/pacientes/<int:paciente_id>')
@requer('cadastro')
def paciente(paciente_id):
    p = obter_paciente(paciente_id)
    passagens = get_db().execute(
        """SELECT a.*, (SELECT COUNT(*) FROM internacoes i WHERE i.atendimento_id = a.id) AS teve_internacao
           FROM atendimentos a WHERE a.paciente_id = ? ORDER BY a.entrada DESC""", (paciente_id,)).fetchall()
    aberto = next((a for a in passagens if a['status'] != 'finalizado'), None)
    return render_template('recepcao/paciente.html', p=p, passagens=passagens, aberto=aberto)


@bp.route('/pacientes/<int:paciente_id>/atendimento', methods=['POST'])
@requer('abertura', 'editar')
def abrir_atendimento(paciente_id):
    p = obter_paciente(paciente_id)
    if atendimento_aberto_do_paciente(paciente_id):
        flash('Este paciente já possui um atendimento em andamento.', 'erro')
        return redirect(url_for('recepcao.paciente', paciente_id=paciente_id))
    motivo = request.form.get('motivo_procura', '').strip()
    acompanhante = ' '.join(request.form.get('acompanhante', '').split()).upper()
    if len(motivo) < 3:
        flash('Descreva o motivo da procura (queixa principal relatada pelo paciente).', 'erro')
        return redirect(url_for('recepcao.paciente', paciente_id=paciente_id))
    db = get_db()
    cursor = db.execute(
        'INSERT INTO atendimentos (paciente_id, entrada, motivo_procura, acompanhante, status, aberto_por) '
        "VALUES (?, ?, ?, ?, 'aberto', ?)", (paciente_id, agora(), motivo, acompanhante or None, g.usuario['id']))
    registrar('atendimento_aberto', f'Atendimento {cursor.lastrowid} - paciente {p["id"]}')
    flash(f'Atendimento nº {cursor.lastrowid} aberto. Paciente encaminhado para classificação de risco.', 'sucesso')
    return redirect(url_for('recepcao.paciente', paciente_id=paciente_id))
