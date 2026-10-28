"""Testes automatizados: validações, matriz de permissões e o fluxo completo do paciente.

Executar a partir da pasta SistemaHospitalar:   python -m unittest -v
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash  # noqa: E402

from app import create_app  # noqa: E402
from db import get_db  # noqa: E402
from permissoes import PAPEIS, PERMISSOES, tem_permissao  # noqa: E402
from seed_demo import gerar_cns, gerar_cpf  # noqa: E402
from util import FORMATO_DATA, agora, cid_valido, cns_valido, cpf_valido, senha_forte  # noqa: E402

SENHA = 'Teste@123'


class TestValidacoes(unittest.TestCase):
    def test_cpf(self):
        self.assertTrue(cpf_valido('529.982.247-25'))
        self.assertFalse(cpf_valido('529.982.247-24'))
        self.assertFalse(cpf_valido('111.111.111-11'))
        self.assertFalse(cpf_valido('123'))

    def test_cns(self):
        self.assertTrue(cns_valido(gerar_cns('70000000000001')))
        self.assertFalse(cns_valido('700000000000000'))
        self.assertFalse(cns_valido('12345'))
        self.assertFalse(cns_valido('300000000000000'))

    def test_cid(self):
        for ok in ('J18', 'J18.9', 'j189', 'A09.0'):
            self.assertTrue(cid_valido(ok), ok)
        for ruim in ('18J', 'JJ8', '', 'J1'):
            self.assertFalse(cid_valido(ruim), ruim)

    def test_senha(self):
        self.assertTrue(senha_forte('abc12345'))
        self.assertFalse(senha_forte('abcdefgh'))
        self.assertFalse(senha_forte('a1'))


class TestMatrizPermissoes(unittest.TestCase):
    def test_direcao_nunca_edita(self):
        for secao, regra in PERMISSOES.items():
            self.assertNotIn('direcao', regra['editar'], secao)

    def test_direcao_ve_todos_os_setores(self):
        for secao in PERMISSOES:
            self.assertTrue(tem_permissao(secao, 'ver', 'direcao'), secao)

    def test_hierarquia_enfermagem(self):
        self.assertTrue(tem_permissao('evolucao_tecnico', 'editar', 'enfermeiro'))
        self.assertFalse(tem_permissao('evolucao_enfermagem', 'editar', 'tecnico'))

    def test_medico_ve_mas_nao_edita_enfermagem(self):
        self.assertTrue(tem_permissao('evolucao_enfermagem', 'ver', 'medico'))
        self.assertFalse(tem_permissao('evolucao_enfermagem', 'editar', 'medico'))
        self.assertFalse(tem_permissao('evolucao_tecnico', 'editar', 'medico'))

    def test_recepcao_so_primeiros_passos(self):
        editaveis = {s for s, r in PERMISSOES.items() if 'recepcao' in r['editar']}
        self.assertEqual(editaveis, {'cadastro', 'abertura'})
        self.assertFalse(tem_permissao('atendimento', 'ver', 'recepcao'))


class TestFluxo(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.app = create_app({'DATABASE': os.path.join(self.pasta.name, 'teste.db'), 'TESTING': True})
        with self.app.app_context():
            db = get_db()
            for papel in PAPEIS:
                if papel == 'admin':
                    db.execute("UPDATE usuarios SET senha_hash = ?, trocar_senha = 0 WHERE username = 'admin'",
                               (generate_password_hash(SENHA),))
                    continue
                registro = {'medico': 'CRM-SP 1', 'enfermeiro': 'COREN 2', 'tecnico': 'COREN 3'}.get(papel)
                db.execute('INSERT INTO usuarios (username, nome, senha_hash, papel, registro_conselho, '
                           'trocar_senha, criado_em) VALUES (?, ?, ?, ?, ?, 0, ?)',
                           (papel, f'Usuario {papel}', generate_password_hash(SENHA), papel, registro, agora()))
            db.commit()
        self.clientes = {}

    def tearDown(self):
        self.pasta.cleanup()

    # ----------------------------------------------------------- utilitários

    def cliente(self, papel):
        if papel not in self.clientes:
            c = self.app.test_client()
            r = self.post(c, '/login', {'username': papel, 'senha': SENHA})
            self.assertEqual(r.status_code, 302, f'login {papel}')
            self.clientes[papel] = c
        return self.clientes[papel]

    @staticmethod
    def post(cliente, url, dados):
        with cliente.session_transaction() as s:
            s.setdefault('csrf_token', 'token-teste')
            token = s['csrf_token']
        return cliente.post(url, data=dict(dados, csrf_token=token))

    def como(self, papel, url, dados=None):
        c = self.cliente(papel)
        return self.post(c, url, dados or {}) if dados is not None else c.get(url)

    def consultar(self, sql, *parametros):
        with self.app.app_context():
            return get_db().execute(sql, parametros).fetchone()

    def executar(self, sql, *parametros):
        with self.app.app_context():
            db = get_db()
            db.execute(sql, parametros)
            db.commit()

    def cadastrar_paciente(self, base_cpf='123456789', base_cns='70000000000001'):
        dados = {
            'nome': 'Maria da Silva', 'cpf': gerar_cpf(base_cpf), 'cns': gerar_cns(base_cns),
            'data_nascimento': '1980-05-10', 'sexo': 'F', 'nome_mae': 'Joana da Silva',
            'telefone': '(11) 98765-4321', 'cep': '01310-100', 'logradouro': 'Av Paulista', 'numero': '10',
            'complemento': '', 'bairro': 'Bela Vista', 'cidade': 'Sao Paulo', 'uf': 'SP',
        }
        r = self.como('recepcao', '/pacientes/novo', dados)
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:3000])
        return self.consultar('SELECT id FROM pacientes WHERE cpf = ?', dados['cpf'])['id']

    def abrir_atendimento(self, paciente_id):
        r = self.como('recepcao', f'/pacientes/{paciente_id}/atendimento', {'motivo_procura': 'Dor no peito'})
        self.assertEqual(r.status_code, 302)
        return self.consultar("SELECT id FROM atendimentos WHERE paciente_id = ? AND status != 'finalizado'",
                              paciente_id)['id']

    # ----------------------------------------------------------- testes

    def test_login_obrigatorio_e_csrf(self):
        c = self.app.test_client()
        self.assertEqual(c.get('/painel').status_code, 302)
        self.assertEqual(c.post('/login', data={'username': 'medico', 'senha': SENHA}).status_code, 400)

    def test_bloqueio_apos_tentativas(self):
        c = self.app.test_client()
        for _ in range(5):
            self.post(c, '/login', {'username': 'medico', 'senha': 'errada'})
        r = self.post(c, '/login', {'username': 'medico', 'senha': SENHA})
        self.assertEqual(r.status_code, 429)

    def test_cadastro_rejeita_dados_invalidos(self):
        r = self.como('recepcao', '/pacientes/novo', {'nome': 'Maria', 'cpf': '11111111111', 'cns': '123'})
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn('CPF inválido', html)
        self.assertIn('Cartão do SUS (CNS) inválido', html)
        self.assertIsNone(self.consultar('SELECT id FROM pacientes'))

    def test_cpf_duplicado(self):
        self.cadastrar_paciente()
        r = self.como('recepcao', '/pacientes/novo', {'cpf': gerar_cpf('123456789')})
        self.assertIn('CPF já cadastrado', r.get_data(as_text=True))

    def test_permissoes_nas_rotas(self):
        pid = self.cadastrar_paciente()
        aid = self.abrir_atendimento(pid)
        texto = {'texto': 'Paciente consciente, orientado, aceitou dieta.'}
        # Recepção não acessa o prontuário clínico.
        self.assertEqual(self.como('recepcao', f'/atendimento/{aid}').status_code, 403)
        # Técnico: própria seção sim, enfermagem não.
        self.assertEqual(self.como('tecnico', f'/atendimento/{aid}/evolucao/tecnico', texto).status_code, 302)
        self.assertEqual(self.como('tecnico', f'/atendimento/{aid}/evolucao/enfermagem', texto).status_code, 403)
        # Enfermeiro edita a seção do técnico e a sua.
        self.assertEqual(self.como('enfermeiro', f'/atendimento/{aid}/evolucao/tecnico', texto).status_code, 302)
        self.assertEqual(self.como('enfermeiro', f'/atendimento/{aid}/evolucao/enfermagem', texto).status_code, 302)
        # Médico vê, mas não edita a enfermagem.
        self.assertEqual(self.como('medico', f'/atendimento/{aid}').status_code, 200)
        self.assertEqual(self.como('medico', f'/atendimento/{aid}/evolucao/enfermagem', texto).status_code, 403)
        # Direção vê tudo e não altera nada.
        for url in (f'/atendimento/{aid}', '/painel', '/direcao', '/transferencias', '/aih', '/auditoria',
                    '/usuarios', f'/pacientes/{pid}', '/relatorios/medicacoes'):
            self.assertEqual(self.como('direcao', url).status_code, 200, url)
        for url in (f'/atendimento/{aid}/evolucao/medica', f'/atendimento/{aid}/prescricao',
                    f'/atendimento/{aid}/alta', f'/pacientes/{pid}/atendimento', '/usuarios/novo'):
            self.assertEqual(self.como('direcao', url, texto).status_code, 403, url)
        # Técnico não anula registro do enfermeiro.
        ev = self.consultar("SELECT id FROM evolucoes WHERE tipo = 'enfermagem'")['id']
        self.assertEqual(self.como('tecnico', f'/evolucao/{ev}/anular', {'motivo': 'teste'}).status_code, 403)
        ev_tec = self.consultar("SELECT id FROM evolucoes WHERE tipo = 'tecnico'")['id']
        self.assertEqual(self.como('enfermeiro', f'/evolucao/{ev_tec}/anular', {'motivo': 'erro de digitação'}).status_code, 302)

    def test_fluxo_so_medicacao_gera_relatorio(self):
        pid = self.cadastrar_paciente()
        aid = self.abrir_atendimento(pid)
        self.como('enfermeiro', f'/atendimento/{aid}/triagem',
                  {'risco': 'verde', 'observacao': 'Dor leve', 'pa': '120/80', 'fc': '80'})
        self.como('medico', f'/atendimento/{aid}/prescricao',
                  {'medicamento': 'Dipirona 500mg', 'dose': '2ml', 'via': 'IV (endovenosa)', 'frequencia': 'Dose única'})
        presc = self.consultar('SELECT id FROM prescricoes WHERE atendimento_id = ?', aid)['id']
        self.assertEqual(self.como('tecnico', f'/prescricao/{presc}/administrar', {}).status_code, 302)
        self.assertEqual(self.como('direcao', f'/prescricao/{presc}/administrar', {}).status_code, 403)
        r = self.como('medico', f'/atendimento/{aid}/alta',
                      {'tipo_saida': 'alta_melhorado', 'resumo_alta': 'Melhora da dor, orientado.'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.consultar('SELECT status FROM atendimentos WHERE id = ?', aid)['status'], 'finalizado')
        self.assertIsNone(self.consultar('SELECT id FROM aih'))
        rel = self.como('enfermeiro', f'/atendimento/{aid}/relatorio').get_data(as_text=True)
        self.assertIn('DIPIRONA 500MG', rel)
        self.assertIn('Total de doses administradas:</b> 1', rel)
        med = self.como('direcao', '/relatorios/medicacoes').get_data(as_text=True)
        self.assertIn('DIPIRONA 500MG', med)
        # Prontuário finalizado não aceita mais registros.
        self.como('tecnico', f'/atendimento/{aid}/evolucao/tecnico', {'texto': 'Tentativa após a alta do paciente'})
        self.assertIsNone(self.consultar("SELECT id FROM evolucoes WHERE tipo = 'tecnico'"))

    def test_fluxo_internacao_24h_e_aih(self):
        pid = self.cadastrar_paciente()
        aid = self.abrir_atendimento(pid)
        antes = (datetime.now() - timedelta(hours=25)).strftime(FORMATO_DATA)
        self.executar('UPDATE atendimentos SET entrada = ? WHERE id = ?', antes, aid)
        self.como('medico', '/painel')  # qualquer requisição dispara a regra das 24h
        inter = self.consultar('SELECT * FROM internacoes WHERE atendimento_id = ?', aid)
        self.assertIsNotNone(inter)
        self.assertEqual(self.consultar('SELECT status FROM atendimentos WHERE id = ?', aid)['status'], 'internado')
        # Alta bloqueada sem assinatura da capa.
        self.como('medico', f'/atendimento/{aid}/alta', {'tipo_saida': 'alta_melhorado', 'resumo_alta': 'Resumo da alta.'})
        self.assertEqual(self.consultar('SELECT status FROM atendimentos WHERE id = ?', aid)['status'], 'internado')
        # Senha errada não assina.
        capa = {'diagnostico': 'Pneumonia', 'cid_principal': 'J189', 'descricao_chegada': 'Chegou dispneico',
                'assinar': '1', 'senha': 'errada'}
        self.como('medico', f'/internacao/{inter["id"]}/capa', capa)
        self.assertEqual(self.consultar('SELECT status FROM internacoes WHERE id = ?', inter['id'])['status'],
                         'pendente_assinatura')
        capa['senha'] = SENHA
        self.como('medico', f'/internacao/{inter["id"]}/capa', capa)
        assinada = self.consultar('SELECT * FROM internacoes WHERE id = ?', inter['id'])
        self.assertEqual(assinada['status'], 'assinada')
        self.assertEqual(assinada['cid_principal'], 'J18.9')
        self.assertIn('Pneumonia', self.como('aih', f'/internacao/{inter["id"]}/imprimir').get_data(as_text=True))
        self.como('medico', f'/atendimento/{aid}/alta', {'tipo_saida': 'alta_melhorado', 'resumo_alta': 'Resumo da alta.'})
        aih = self.consultar('SELECT * FROM aih WHERE atendimento_id = ?', aid)
        self.assertEqual(aih['status'], 'pendente')
        # Faturamento autoriza e exporta.
        self.assertEqual(self.como('direcao', f'/aih/{aih["id"]}/decidir', {'acao': 'autorizar'}).status_code, 403)
        self.como('aih', f'/aih/{aih["id"]}/decidir', {'acao': 'autorizar', 'numero_aih': '1234567890123',
                                                        'procedimento_sigtap': '0303140151', 'sistema_destino': 'SISAIH01'})
        self.assertEqual(self.consultar('SELECT status FROM aih WHERE id = ?', aih['id'])['status'], 'autorizada')
        r = self.como('aih', '/aih/exportar', {'sistema': 'SISAIH01'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('1234567890123', r.get_data(as_text=True))
        self.assertEqual(self.consultar('SELECT status FROM aih WHERE id = ?', aih['id'])['status'], 'exportada')

    def test_fluxo_transferencia(self):
        pid = self.cadastrar_paciente()
        aid = self.abrir_atendimento(pid)
        self.assertEqual(self.como('enfermeiro', f'/atendimento/{aid}/transferencia',
                                   {'motivo': 'falta_materiais', 'justificativa': 'x' * 20}).status_code, 403)
        self.como('medico', f'/atendimento/{aid}/transferencia',
                  {'motivo': 'falta_materiais', 'justificativa': 'Sem material para cirurgia ortopédica',
                   'especialidade': 'Ortopedia'})
        t = self.consultar('SELECT * FROM transferencias WHERE atendimento_id = ?', aid)
        self.assertEqual(self.consultar('SELECT status FROM atendimentos WHERE id = ?', aid)['status'],
                         'aguardando_transferencia')
        pagina = self.como('transferencia', f'/transferencias/{t["id"]}').get_data(as_text=True)
        self.assertIn(gerar_cpf('123456789')[:3], pagina)
        self.assertEqual(self.como('transferencia', f'/transferencias/{t["id"]}/ficha').status_code, 200)
        # Concluir exige hospital de destino.
        self.como('transferencia', f'/transferencias/{t["id"]}/atualizar', {'status': 'aceita'})
        self.assertEqual(self.consultar('SELECT status FROM transferencias WHERE id = ?', t['id'])['status'], 'solicitada')
        self.como('transferencia', f'/transferencias/{t["id"]}/atualizar',
                  {'status': 'aceita', 'hospital_destino': 'Hospital Regional'})
        self.como('transferencia', f'/transferencias/{t["id"]}/atualizar',
                  {'status': 'concluida', 'hospital_destino': 'Hospital Regional', 'protocolo_regulacao': '999'})
        at = self.consultar('SELECT * FROM atendimentos WHERE id = ?', aid)
        self.assertEqual((at['status'], at['tipo_saida']), ('finalizado', 'transferencia'))

    def test_todas_as_paginas_renderizam(self):
        pid = self.cadastrar_paciente()
        aid = self.abrir_atendimento(pid)
        paginas = {
            'recepcao': ['/pacientes', '/pacientes?q=maria', f'/pacientes?q={gerar_cpf("123456789")}',
                         '/pacientes/novo', f'/pacientes/{pid}', f'/pacientes/{pid}/editar'],
            'tecnico': ['/painel', f'/atendimento/{aid}', '/relatorios/medicacoes'],
            'enfermeiro': ['/painel?filtro=triagem', f'/atendimento/{aid}'],
            'medico': ['/painel', f'/atendimento/{aid}', f'/atendimento/{aid}/relatorio', '/transferencias'],
            'transferencia': ['/transferencias?filtro=todas'],
            'aih': ['/aih', '/aih?status=todas'],
            'admin': ['/usuarios', '/usuarios/novo', '/usuarios/1/editar', '/auditoria'],
            'direcao': ['/direcao', '/auditoria?data=2026-01-01'],
        }
        for papel, urls in paginas.items():
            for url in urls:
                r = self.como(papel, url)
                self.assertEqual(r.status_code, 200, f'{papel} {url}')
        self.assertEqual(self.como('aih', '/painel').status_code, 403)

    def test_telas_com_prontuario_completo(self):
        pid = self.cadastrar_paciente()
        aid = self.abrir_atendimento(pid)
        self.como('enfermeiro', f'/pacientes/{pid}/alergias', {'alergias': 'Penicilina', 'atendimento_id': aid})
        self.como('enfermeiro', f'/atendimento/{aid}/triagem', {'risco': 'laranja', 'observacao': 'Dor torácica', 'spo2': '93'})
        self.como('tecnico', f'/atendimento/{aid}/evolucao/tecnico', {'texto': 'Paciente dormiu bem, aceitou dieta.', 'temperatura': '37,5'})
        self.como('medico', f'/atendimento/{aid}/evolucao/medica', {'texto': 'Ausculta com crepitações em base direita.'})
        self.como('medico', f'/atendimento/{aid}/diagnostico', {'hipotese_diagnostica': 'Pneumonia', 'cid_principal': 'J18.9'})
        self.como('medico', f'/atendimento/{aid}/prescricao', {'medicamento': 'Ceftriaxona 1g', 'dose': '1g',
                                                               'via': 'IV (endovenosa)', 'frequencia': '12/12h'})
        presc = self.consultar('SELECT id FROM prescricoes')['id']
        self.como('enfermeiro', f'/prescricao/{presc}/administrar', {'observacao': 'sem intercorrências'})
        self.como('medico', f'/atendimento/{aid}/internar', {})
        self.como('medico', f'/atendimento/{aid}/transferencia', {'motivo': 'falta_leito', 'justificativa': 'Necessita UTI adulto'})
        self.assertEqual(self.consultar('SELECT temperatura FROM evolucoes WHERE tipo = ?', 'tecnico')['temperatura'], 37.5)
        inter = self.consultar('SELECT id FROM internacoes')['id']
        t = self.consultar('SELECT id FROM transferencias')['id']
        for papel in ('tecnico', 'enfermeiro', 'medico', 'direcao', 'aih', 'transferencia'):
            r = self.como(papel, f'/atendimento/{aid}')
            self.assertEqual(r.status_code, 200, papel)
            self.assertIn('Penicilina', r.get_data(as_text=True))
        for papel, url in (('medico', f'/internacao/{inter}/imprimir'), ('transferencia', f'/transferencias/{t}'),
                           ('transferencia', f'/transferencias/{t}/ficha'), ('direcao', '/direcao'),
                           ('medico', f'/atendimento/{aid}/relatorio'), ('direcao', f'/pacientes/{pid}'),
                           ('enfermeiro', '/relatorios/medicacoes')):
            self.assertEqual(self.como(papel, url).status_code, 200, url)
        # Cancelar a transferência devolve o paciente para internado.
        self.como('transferencia', f'/transferencias/{t}/atualizar', {'status': 'cancelada', 'observacoes': 'Leito liberado aqui'})
        self.assertEqual(self.consultar('SELECT status FROM atendimentos WHERE id = ?', aid)['status'], 'internado')
        self.como('medico', f'/internacao/{inter}/capa', {'diagnostico': 'Pneumonia', 'cid_principal': 'J18.9',
                                                         'descricao_chegada': 'Chegou com dispneia', 'assinar': '1', 'senha': SENHA})
        self.como('medico', f'/atendimento/{aid}/alta', {'tipo_saida': 'alta_melhorado', 'resumo_alta': 'Alta com antibiótico VO.'})
        aih = self.consultar('SELECT id FROM aih')['id']
        for papel in ('aih', 'direcao'):
            self.assertEqual(self.como(papel, f'/aih/{aih}').status_code, 200)
        self.como('aih', f'/aih/{aih}/decidir', {'acao': 'pendencia', 'observacao': 'Falta laudo'})
        self.assertEqual(self.consultar('SELECT status FROM aih')['status'], 'pendencia')
        self.assertEqual(self.como('aih', '/aih?status=pendencia').status_code, 200)

    def test_admin_cria_usuario_com_troca_de_senha(self):
        r = self.como('admin', '/usuarios/novo', {'nome': 'Novo Medico', 'username': 'novo.med', 'papel': 'medico',
                                                   'registro_conselho': '', 'senha': 'Senha1234'})
        self.assertIn('Obrigatório para este cargo', r.get_data(as_text=True))
        self.como('admin', '/usuarios/novo', {'nome': 'Novo Medico', 'username': 'novo.med', 'papel': 'medico',
                                               'registro_conselho': 'CRM-SP 9', 'senha': 'Senha1234'})
        c = self.app.test_client()
        self.post(c, '/login', {'username': 'novo.med', 'senha': 'Senha1234'})
        r = c.get('/painel')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/trocar-senha', r.headers['Location'])


if __name__ == '__main__':
    unittest.main()
