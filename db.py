"""Conexão SQLite, criação do banco e registro de auditoria."""
import os
import sqlite3

from flask import current_app, g, has_request_context, request
from werkzeug.security import generate_password_hash

from util import agora

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    nome TEXT NOT NULL,
    senha_hash TEXT NOT NULL,
    papel TEXT NOT NULL,
    registro_conselho TEXT,
    ativo INTEGER NOT NULL DEFAULT 1,
    trocar_senha INTEGER NOT NULL DEFAULT 1,
    tentativas_falhas INTEGER NOT NULL DEFAULT 0,
    bloqueado_ate TEXT,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pacientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    nome_social TEXT,
    cpf TEXT NOT NULL UNIQUE,
    cns TEXT NOT NULL UNIQUE,
    data_nascimento TEXT NOT NULL,
    sexo TEXT NOT NULL,
    nome_mae TEXT NOT NULL,
    telefone TEXT NOT NULL,
    cep TEXT NOT NULL,
    logradouro TEXT NOT NULL,
    numero TEXT NOT NULL,
    complemento TEXT,
    bairro TEXT NOT NULL,
    cidade TEXT NOT NULL,
    uf TEXT NOT NULL,
    alergias TEXT,
    criado_em TEXT NOT NULL,
    criado_por INTEGER REFERENCES usuarios(id),
    atualizado_em TEXT
);

CREATE TABLE IF NOT EXISTS atendimentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    entrada TEXT NOT NULL,
    motivo_procura TEXT NOT NULL,
    acompanhante TEXT,
    status TEXT NOT NULL DEFAULT 'aberto',
    risco TEXT,
    triagem_em TEXT,
    triagem_por INTEGER REFERENCES usuarios(id),
    hipotese_diagnostica TEXT,
    cid_principal TEXT,
    saida TEXT,
    tipo_saida TEXT,
    resumo_alta TEXT,
    alta_por INTEGER REFERENCES usuarios(id),
    aberto_por INTEGER REFERENCES usuarios(id)
);
CREATE INDEX IF NOT EXISTS ix_atend_paciente ON atendimentos(paciente_id);
CREATE INDEX IF NOT EXISTS ix_atend_status ON atendimentos(status);

CREATE TABLE IF NOT EXISTS evolucoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    atendimento_id INTEGER NOT NULL REFERENCES atendimentos(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('tecnico', 'enfermagem', 'medica')),
    texto TEXT NOT NULL,
    pa TEXT, fc INTEGER, fr INTEGER, temperatura REAL, spo2 INTEGER, glicemia INTEGER,
    autor_id INTEGER NOT NULL REFERENCES usuarios(id),
    criado_em TEXT NOT NULL,
    anulada_por INTEGER REFERENCES usuarios(id),
    anulada_em TEXT,
    anulada_motivo TEXT
);
CREATE INDEX IF NOT EXISTS ix_evol_atend ON evolucoes(atendimento_id);

CREATE TABLE IF NOT EXISTS prescricoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    atendimento_id INTEGER NOT NULL REFERENCES atendimentos(id),
    medicamento TEXT NOT NULL,
    dose TEXT NOT NULL,
    via TEXT NOT NULL,
    frequencia TEXT NOT NULL,
    observacao TEXT,
    status TEXT NOT NULL DEFAULT 'ativa',
    prescrito_por INTEGER NOT NULL REFERENCES usuarios(id),
    prescrito_em TEXT NOT NULL,
    suspensa_por INTEGER REFERENCES usuarios(id),
    suspensa_em TEXT
);
CREATE INDEX IF NOT EXISTS ix_presc_atend ON prescricoes(atendimento_id);

CREATE TABLE IF NOT EXISTS administracoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prescricao_id INTEGER NOT NULL REFERENCES prescricoes(id),
    administrado_por INTEGER NOT NULL REFERENCES usuarios(id),
    administrado_em TEXT NOT NULL,
    observacao TEXT
);
CREATE INDEX IF NOT EXISTS ix_adm_presc ON administracoes(prescricao_id);

CREATE TABLE IF NOT EXISTS internacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    atendimento_id INTEGER NOT NULL UNIQUE REFERENCES atendimentos(id),
    criada_em TEXT NOT NULL,
    origem TEXT NOT NULL,
    leito TEXT,
    diagnostico TEXT,
    cid_principal TEXT,
    cid_secundario TEXT,
    descricao_chegada TEXT,
    status TEXT NOT NULL DEFAULT 'pendente_assinatura',
    assinada_por INTEGER REFERENCES usuarios(id),
    assinada_em TEXT,
    encerrada_em TEXT
);

CREATE TABLE IF NOT EXISTS transferencias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    atendimento_id INTEGER NOT NULL REFERENCES atendimentos(id),
    motivo TEXT NOT NULL,
    justificativa TEXT NOT NULL,
    especialidade TEXT,
    status TEXT NOT NULL DEFAULT 'solicitada',
    solicitada_por INTEGER NOT NULL REFERENCES usuarios(id),
    solicitada_em TEXT NOT NULL,
    hospital_destino TEXT,
    contato_destino TEXT,
    protocolo_regulacao TEXT,
    observacoes TEXT,
    atualizado_por INTEGER REFERENCES usuarios(id),
    atualizado_em TEXT,
    concluida_em TEXT
);

CREATE TABLE IF NOT EXISTS aih (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    atendimento_id INTEGER NOT NULL UNIQUE REFERENCES atendimentos(id),
    internacao_id INTEGER NOT NULL REFERENCES internacoes(id),
    status TEXT NOT NULL DEFAULT 'pendente',
    numero_aih TEXT,
    procedimento_sigtap TEXT,
    sistema_destino TEXT,
    observacao TEXT,
    revisado_por INTEGER REFERENCES usuarios(id),
    revisado_em TEXT,
    exportado_em TEXT,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER REFERENCES usuarios(id),
    acao TEXT NOT NULL,
    detalhe TEXT,
    ip TEXT,
    criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_auditoria_data ON auditoria(criado_em);
"""


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


def fechar_db(_erro=None):
    conexao = g.pop('db', None)
    if conexao is not None:
        conexao.close()


def registrar(acao, detalhe='', usuario_id=None):
    """Grava uma linha de auditoria e confirma (commit) a transação corrente."""
    db = get_db()
    if usuario_id is None and g.get('usuario') is not None:
        usuario_id = g.usuario['id']
    ip = request.remote_addr if has_request_context() else None
    db.execute('INSERT INTO auditoria (usuario_id, acao, detalhe, ip, criado_em) VALUES (?, ?, ?, ?, ?)',
               (usuario_id, acao, detalhe, ip, agora()))
    db.commit()


def iniciar_banco(app):
    """Cria as tabelas e, se não existir nenhum usuário, cria o administrador inicial."""
    os.makedirs(os.path.dirname(os.path.abspath(app.config['DATABASE'])), exist_ok=True)
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA)
        if db.execute('SELECT COUNT(*) FROM usuarios').fetchone()[0] == 0:
            senha = os.environ.get('ADMIN_SENHA', 'Admin@2026')
            db.execute(
                'INSERT INTO usuarios (username, nome, senha_hash, papel, trocar_senha, criado_em) '
                'VALUES (?, ?, ?, ?, 1, ?)',
                ('admin', 'Administrador do Sistema', generate_password_hash(senha), 'admin', agora()))
            db.commit()
            app.logger.warning('Usuário inicial criado: admin / %s (troca obrigatória no 1º acesso)', senha)
        fechar_db()
