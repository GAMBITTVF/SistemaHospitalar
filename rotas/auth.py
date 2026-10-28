"""Login, logout e troca de senha."""
from datetime import datetime, timedelta

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db, registrar
from permissoes import login_obrigatorio
from util import FORMATO_DATA, para_datetime, senha_forte

bp = Blueprint('auth', __name__)

MAX_TENTATIVAS = 5
MINUTOS_BLOQUEIO = 15


def _destino_seguro(destino):
    if destino and destino.startswith('/') and not destino.startswith('//') and '\\' not in destino:
        return destino
    return url_for('inicio')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if g.usuario is not None:
        return redirect(url_for('inicio'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        senha = request.form.get('senha', '')
        db = get_db()
        usuario = db.execute('SELECT * FROM usuarios WHERE username = ?', (username,)).fetchone()
        erro = 'Usuário ou senha inválidos.'

        if usuario is not None and usuario['bloqueado_ate']:
            bloqueio = para_datetime(usuario['bloqueado_ate'])
            if bloqueio and bloqueio > datetime.now():
                flash(f'Usuário bloqueado por excesso de tentativas. Tente após {bloqueio:%H:%M}.', 'erro')
                return render_template('login.html', username=username), 429

        if usuario is None or not check_password_hash(usuario['senha_hash'], senha):
            if usuario is not None:
                tentativas = usuario['tentativas_falhas'] + 1
                bloqueado = None
                if tentativas >= MAX_TENTATIVAS:
                    bloqueado = (datetime.now() + timedelta(minutes=MINUTOS_BLOQUEIO)).strftime(FORMATO_DATA)
                    tentativas = 0
                db.execute('UPDATE usuarios SET tentativas_falhas = ?, bloqueado_ate = ? WHERE id = ?',
                           (tentativas, bloqueado, usuario['id']))
                registrar('login_falhou', f'Usuário {username}', usuario_id=usuario['id'])
            flash(erro, 'erro')
            return render_template('login.html', username=username), 401

        if not usuario['ativo']:
            flash('Usuário desativado. Procure o administrador do sistema.', 'erro')
            return render_template('login.html', username=username), 403

        db.execute('UPDATE usuarios SET tentativas_falhas = 0, bloqueado_ate = NULL WHERE id = ?', (usuario['id'],))
        session.clear()
        session.permanent = True
        session['uid'] = usuario['id']
        registrar('login', '', usuario_id=usuario['id'])
        return redirect(_destino_seguro(request.args.get('next')))
    return render_template('login.html')


@bp.route('/logout')
def logout():
    if g.usuario is not None:
        registrar('logout')
    session.clear()
    flash('Sessão encerrada.', 'info')
    return redirect(url_for('auth.login'))


@bp.route('/trocar-senha', methods=['GET', 'POST'])
@login_obrigatorio
def trocar_senha():
    if request.method == 'POST':
        atual = request.form.get('senha_atual', '')
        nova = request.form.get('nova_senha', '')
        confirmacao = request.form.get('confirmacao', '')
        if not check_password_hash(g.usuario['senha_hash'], atual):
            flash('Senha atual incorreta.', 'erro')
        elif nova != confirmacao:
            flash('A confirmação não confere com a nova senha.', 'erro')
        elif not senha_forte(nova):
            flash('A nova senha precisa ter no mínimo 8 caracteres, com letras e números.', 'erro')
        elif check_password_hash(g.usuario['senha_hash'], nova):
            flash('A nova senha deve ser diferente da atual.', 'erro')
        else:
            get_db().execute('UPDATE usuarios SET senha_hash = ?, trocar_senha = 0 WHERE id = ?',
                             (generate_password_hash(nova), g.usuario['id']))
            registrar('senha_alterada')
            flash('Senha alterada com sucesso.', 'sucesso')
            return redirect(url_for('inicio'))
    return render_template('trocar_senha.html')
