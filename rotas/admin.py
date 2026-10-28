"""Administração de usuários (cadastro, cargo/permissão, ativação, reset de senha)."""
import re
import secrets

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from db import get_db, registrar
from permissoes import CONSELHOS, PAPEIS, PERMISSOES, requer
from util import agora, senha_forte

bp = Blueprint('admin', __name__)


def _obter(usuario_id):
    u = get_db().execute('SELECT * FROM usuarios WHERE id = ?', (usuario_id,)).fetchone()
    if u is None:
        abort(404)
    return u


def _senha_temporaria():
    return 'Tmp' + secrets.token_hex(3) + str(secrets.randbelow(90) + 10)


@bp.route('/usuarios')
@requer('usuarios')
def usuarios():
    lista = get_db().execute('SELECT * FROM usuarios ORDER BY ativo DESC, nome').fetchall()
    return render_template('admin/usuarios.html', usuarios=lista, permissoes=PERMISSOES)


@bp.route('/usuarios/novo', methods=['GET', 'POST'])
@bp.route('/usuarios/<int:usuario_id>/editar', methods=['GET', 'POST'])
@requer('usuarios', 'editar')
def formulario(usuario_id=None):
    existente = _obter(usuario_id) if usuario_id else None
    dados = dict(existente) if existente else {}
    erros = {}
    if request.method == 'POST':
        dados = {
            'username': request.form.get('username', '').strip().lower(),
            'nome': ' '.join(request.form.get('nome', '').split()),
            'papel': request.form.get('papel', ''),
            'registro_conselho': request.form.get('registro_conselho', '').strip().upper(),
        }
        senha = request.form.get('senha', '')
        if not re.fullmatch(r'[a-z0-9._-]{3,30}', dados['username']):
            erros['username'] = 'Use 3 a 30 caracteres: letras minúsculas, números, ponto, hífen ou _.'
        elif get_db().execute('SELECT 1 FROM usuarios WHERE username = ? AND id != ?',
                              (dados['username'], usuario_id or 0)).fetchone():
            erros['username'] = 'Este login já existe.'
        if len(dados['nome'].split()) < 2:
            erros['nome'] = 'Informe nome e sobrenome.'
        if dados['papel'] not in PAPEIS:
            erros['papel'] = 'Selecione o cargo.'
        elif dados['papel'] in CONSELHOS and not dados['registro_conselho']:
            erros['registro_conselho'] = f'Obrigatório para este cargo ({CONSELHOS[dados["papel"]]}).'
        if existente and existente['id'] == g.usuario['id'] and dados['papel'] != 'admin':
            erros['papel'] = 'Você não pode remover o seu próprio acesso de administrador.'
        if not existente and not senha_forte(senha):
            erros['senha'] = 'Senha inicial: mínimo 8 caracteres, com letras e números.'

        if not erros:
            db = get_db()
            if existente:
                db.execute('UPDATE usuarios SET username = ?, nome = ?, papel = ?, registro_conselho = ? WHERE id = ?',
                           (dados['username'], dados['nome'], dados['papel'], dados['registro_conselho'] or None,
                            usuario_id))
                registrar('usuario_editado', f'{dados["username"]} ({dados["papel"]})')
                flash('Usuário atualizado.', 'sucesso')
            else:
                db.execute('INSERT INTO usuarios (username, nome, senha_hash, papel, registro_conselho, trocar_senha, '
                           'criado_em) VALUES (?, ?, ?, ?, ?, 1, ?)',
                           (dados['username'], dados['nome'], generate_password_hash(senha), dados['papel'],
                            dados['registro_conselho'] or None, agora()))
                registrar('usuario_criado', f'{dados["username"]} ({dados["papel"]})')
                flash('Usuário criado. Ele deverá trocar a senha no primeiro acesso.', 'sucesso')
            return redirect(url_for('admin.usuarios'))
        flash('Corrija os campos destacados.', 'erro')
    return render_template('admin/usuario_form.html', dados=dados, erros=erros, existente=existente)


@bp.route('/usuarios/<int:usuario_id>/ativo', methods=['POST'])
@requer('usuarios', 'editar')
def alternar_ativo(usuario_id):
    u = _obter(usuario_id)
    if u['id'] == g.usuario['id']:
        flash('Você não pode desativar o seu próprio usuário.', 'erro')
    else:
        novo = 0 if u['ativo'] else 1
        get_db().execute('UPDATE usuarios SET ativo = ? WHERE id = ?', (novo, usuario_id))
        registrar('usuario_ativado' if novo else 'usuario_desativado', u['username'])
        flash(f'Usuário {"ativado" if novo else "desativado"}.', 'sucesso')
    return redirect(url_for('admin.usuarios'))


@bp.route('/usuarios/<int:usuario_id>/resetar-senha', methods=['POST'])
@requer('usuarios', 'editar')
def resetar_senha(usuario_id):
    u = _obter(usuario_id)
    temporaria = _senha_temporaria()
    get_db().execute('UPDATE usuarios SET senha_hash = ?, trocar_senha = 1, tentativas_falhas = 0, '
                     'bloqueado_ate = NULL WHERE id = ?', (generate_password_hash(temporaria), usuario_id))
    registrar('senha_resetada', u['username'])
    flash(f'Senha temporária de {u["username"]}: {temporaria}  (anote e entregue ao usuário; '
          'ele deverá trocá-la no próximo acesso).', 'aviso')
    return redirect(url_for('admin.usuarios'))
