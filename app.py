"""Sistema Hospitalar - aplicação Flask.

Execução local:      python app.py
Produção (Windows/Linux):  waitress-serve --port=8000 --call app:create_app
"""
import os
import secrets
from datetime import timedelta

from flask import Flask, abort, g, redirect, render_template, request, session, url_for

import db
import util
from permissoes import CONSELHOS, PAPEIS, pode_editar, pode_ver
from servicos import gerar_internacoes_automaticas

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _chave_secreta(pasta):
    """Usa SECRET_KEY do ambiente ou gera uma chave persistente em instance/secret_key."""
    if os.environ.get('SECRET_KEY'):
        return os.environ['SECRET_KEY']
    caminho = os.path.join(pasta, 'secret_key')
    if not os.path.exists(caminho):
        with open(caminho, 'w', encoding='utf-8') as arq:
            arq.write(secrets.token_hex(32))
    with open(caminho, encoding='utf-8') as arq:
        return arq.read().strip()


def create_app(config=None):
    app = Flask(__name__, instance_path=os.path.join(BASE_DIR, 'instance'))
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.update(
        SECRET_KEY=_chave_secreta(app.instance_path),
        DATABASE=os.environ.get('HOSPITAL_DB', os.path.join(app.instance_path, 'hospital.db')),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SEGURO') == '1',
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=int(os.environ.get('SESSAO_MINUTOS', '30'))),
        MAX_CONTENT_LENGTH=1024 * 1024,
    )
    if config:
        app.config.update(config)

    db.iniciar_banco(app)
    app.teardown_appcontext(db.fechar_db)

    from rotas import admin, aih, auth, clinico, direcao, recepcao, transferencia
    for modulo in (auth, recepcao, clinico, transferencia, aih, direcao, admin):
        app.register_blueprint(modulo.bp)

    # ------------------------------------------------------------ segurança

    def csrf_token():
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)
        return session['csrf_token']

    @app.before_request
    def antes_da_requisicao():
        if request.method == 'POST':
            token = session.get('csrf_token')
            enviado = request.form.get('csrf_token', '')
            if not token or not secrets.compare_digest(token, enviado):
                abort(400, 'Sessão expirada ou formulário inválido. Recarregue a página e tente novamente.')

        g.usuario = None
        uid = session.get('uid')
        if uid is not None:
            usuario = db.get_db().execute('SELECT * FROM usuarios WHERE id = ?', (uid,)).fetchone()
            if usuario is None or not usuario['ativo']:
                session.clear()
            else:
                g.usuario = usuario

        if g.usuario is not None:
            livres = {'auth.trocar_senha', 'auth.logout', 'static'}
            if g.usuario['trocar_senha'] and request.endpoint not in livres:
                return redirect(url_for('auth.trocar_senha'))
            if request.endpoint != 'static':
                gerar_internacoes_automaticas()

    @app.after_request
    def cabecalhos_seguranca(resposta):
        resposta.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        resposta.headers.setdefault('X-Content-Type-Options', 'nosniff')
        resposta.headers.setdefault('Referrer-Policy', 'same-origin')
        if g.get('usuario') is not None:
            resposta.headers.setdefault('Cache-Control', 'no-store')
        return resposta

    # ------------------------------------------------------------ templates

    @app.context_processor
    def contexto_global():
        return {
            'usuario': g.get('usuario'), 'pode_ver': pode_ver, 'pode_editar': pode_editar,
            'csrf_token': csrf_token, 'PAPEIS': PAPEIS, 'CONSELHOS': CONSELHOS,
            'RISCOS': util.RISCOS, 'STATUS_ATENDIMENTO': util.STATUS_ATENDIMENTO,
            'TIPOS_SAIDA': util.TIPOS_SAIDA, 'STATUS_INTERNACAO': util.STATUS_INTERNACAO,
            'STATUS_TRANSFERENCIA': util.STATUS_TRANSFERENCIA, 'STATUS_AIH': util.STATUS_AIH,
            'MOTIVOS_TRANSFERENCIA': util.MOTIVOS_TRANSFERENCIA, 'SEXOS': util.SEXOS,
            'agora': util.agora, 'horas_desde': util.horas_desde, 'idade': util.idade,
        }

    app.jinja_env.filters.update(
        data=util.formatar_data,
        dia=lambda v: util.formatar_data(v, com_hora=False),
        cpf=util.formatar_cpf, cns=util.formatar_cns, cep=util.formatar_cep, telefone=util.formatar_telefone,
    )

    # ------------------------------------------------------------ erros

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    def pagina_erro(erro):
        mensagens = {
            403: 'Você não tem permissão para acessar ou alterar esta área.',
            404: 'Página ou registro não encontrado.',
        }
        texto = mensagens.get(erro.code) or erro.description
        return render_template('erro.html', codigo=erro.code, mensagem=texto), erro.code

    @app.route('/')
    def inicio():
        if g.usuario is None:
            return redirect(url_for('auth.login'))
        destino = {
            'recepcao': 'recepcao.busca', 'tecnico': 'clinico.painel', 'enfermeiro': 'clinico.painel',
            'medico': 'clinico.painel', 'direcao': 'direcao.painel', 'aih': 'aih.lista',
            'transferencia': 'transferencia.lista', 'admin': 'admin.usuarios',
        }.get(g.usuario['papel'], 'auth.logout')
        return redirect(url_for(destino))

    return app


if __name__ == '__main__':
    porta = int(os.environ.get('PORT', '5000'))
    create_app().run(host='127.0.0.1', port=porta, debug=os.environ.get('FLASK_DEBUG') == '1')
