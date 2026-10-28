"""Cria usuários de demonstração (um por cargo) e alguns pacientes de exemplo.

Uso:  python seed_demo.py
Senha de todos os usuários de demonstração: Hospital@123
NÃO use em produção.
"""
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from app import create_app
from db import get_db
from util import FORMATO_DATA, agora

SENHA = 'Hospital@123'

USUARIOS = [
    ('recepcao', 'Ana Recepção Silva', 'recepcao', None),
    ('tecnico', 'Bruno Técnico Souza', 'tecnico', 'COREN-SP 111111-TE'),
    ('enfermeiro', 'Carla Enfermeira Lima', 'enfermeiro', 'COREN-SP 222222-ENF'),
    ('medico', 'Daniel Médico Costa', 'medico', 'CRM-SP 333333'),
    ('transferencia', 'Elisa Central Rocha', 'transferencia', None),
    ('faturamento', 'Fábio Faturamento Dias', 'aih', None),
    ('direcao', 'Gabriela Diretora Alves', 'direcao', None),
]


def gerar_cpf(base9):
    d = [int(x) for x in base9]
    for i in (9, 10):
        soma = sum(d[j] * (i + 1 - j) for j in range(i))
        d.append((soma * 10) % 11 % 10)
    return ''.join(map(str, d))


def gerar_cns(inicio):
    """Gera um CNS provisório válido (começando com 7, 8 ou 9)."""
    base = int(inicio)
    while True:
        p = str(base).zfill(14)
        soma = sum(int(p[i]) * (15 - i) for i in range(14))
        dv = (-soma) % 11
        if dv < 10:
            return p + str(dv)
        base += 1


PACIENTES = [
    ('MARIA APARECIDA DOS SANTOS', gerar_cpf('123456789'), gerar_cns('70000000000001'), '1958-03-12', 'F',
     'JOSEFA DOS SANTOS', '11987654321', '01310100', 'Avenida Paulista', '1000', 'Apto 12', 'Bela Vista',
     'SAO PAULO', 'SP'),
    ('JOAO PEDRO OLIVEIRA', gerar_cpf('987654321'), gerar_cns('70000000000500'), '1990-07-25', 'M',
     'MARTA OLIVEIRA', '11912345678', '20040020', 'Rua da Assembleia', '50', None, 'Centro',
     'RIO DE JANEIRO', 'RJ'),
    ('LUCAS FERREIRA LIMA', gerar_cpf('456123789'), gerar_cns('80000000000100'), '2012-11-02', 'M',
     'PATRICIA FERREIRA LIMA', '3134567890', '30130010', 'Avenida Afonso Pena', '300', None, 'Centro',
     'BELO HORIZONTE', 'MG'),
]


def main():
    app = create_app()
    with app.app_context():
        db = get_db()
        for username, nome, papel, registro in USUARIOS:
            if not db.execute('SELECT 1 FROM usuarios WHERE username = ?', (username,)).fetchone():
                db.execute('INSERT INTO usuarios (username, nome, senha_hash, papel, registro_conselho, '
                           'trocar_senha, criado_em) VALUES (?, ?, ?, ?, ?, 0, ?)',
                           (username, nome, generate_password_hash(SENHA), papel, registro, agora()))
        recepcao_id = db.execute("SELECT id FROM usuarios WHERE username = 'recepcao'").fetchone()[0]

        for i, dados in enumerate(PACIENTES):
            if db.execute('SELECT 1 FROM pacientes WHERE cpf = ?', (dados[1],)).fetchone():
                continue
            cur = db.execute(
                """INSERT INTO pacientes (nome, cpf, cns, data_nascimento, sexo, nome_mae, telefone, cep,
                       logradouro, numero, complemento, bairro, cidade, uf, criado_em, criado_por)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", dados + (agora(), recepcao_id))
            # Primeira paciente: chegou há 26 horas (vira internação automaticamente).
            horas = [26, 2, None][i]
            if horas is not None:
                entrada = (datetime.now() - timedelta(hours=horas)).strftime(FORMATO_DATA)
                motivo = ['Falta de ar e febre há 3 dias, tosse produtiva.', 'Dor de cabeça forte desde a manhã.'][i]
                db.execute("INSERT INTO atendimentos (paciente_id, entrada, motivo_procura, status, aberto_por) "
                           "VALUES (?, ?, ?, 'aberto', ?)", (cur.lastrowid, entrada, motivo, recepcao_id))
        db.commit()

    print('Dados de demonstração criados. Usuários (senha: %s):' % SENHA)
    for username, nome, papel, _ in USUARIOS:
        print(f'  {username:<14} {nome}  [{papel}]')


if __name__ == '__main__':
    main()
