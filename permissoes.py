"""Papéis (cargos) e matriz de permissões do sistema.

Cada seção do sistema define quem pode VER e quem pode EDITAR.
Regras principais:
  - Recepção: apenas cadastro do paciente e abertura do atendimento.
  - Técnico de enfermagem: edita só a própria seção (evolução do técnico) e checa medicações.
  - Enfermeiro: edita a seção do técnico E a da enfermagem (o técnico não edita a do enfermeiro).
  - Médico: vê a enfermagem (sem editar), prescreve, diagnostica, interna, dá alta, pede transferência.
  - Direção: vê tudo, não edita nada.
"""
from functools import wraps

from flask import abort, g, redirect, request, url_for

PAPEIS = {
    'recepcao': 'Recepção',
    'tecnico': 'Técnico(a) de Enfermagem',
    'enfermeiro': 'Enfermeiro(a)',
    'medico': 'Médico(a)',
    'transferencia': 'Central de Transferência',
    'aih': 'Faturamento / AIH',
    'direcao': 'Direção',
    'admin': 'Administrador do Sistema',
}

# Conselho profissional exigido por cargo (registro aparece em assinaturas e documentos).
CONSELHOS = {'tecnico': 'COREN', 'enfermeiro': 'COREN', 'medico': 'CRM'}

_TODOS_SAUDE = {'recepcao', 'tecnico', 'enfermeiro', 'medico', 'direcao', 'aih', 'transferencia'}
_CLINICO = {'tecnico', 'enfermeiro', 'medico', 'direcao', 'aih', 'transferencia'}

PERMISSOES = {
    'cadastro': {'ver': _TODOS_SAUDE, 'editar': {'recepcao'}},
    'abertura': {'ver': _TODOS_SAUDE, 'editar': {'recepcao'}},
    'painel': {'ver': {'tecnico', 'enfermeiro', 'medico', 'direcao'}, 'editar': set()},
    'atendimento': {'ver': _CLINICO, 'editar': set()},
    'triagem': {'ver': _CLINICO, 'editar': {'enfermeiro'}},
    'alergias': {'ver': _TODOS_SAUDE, 'editar': {'enfermeiro', 'medico'}},
    'evolucao_tecnico': {'ver': _CLINICO, 'editar': {'tecnico', 'enfermeiro'}},
    'evolucao_enfermagem': {'ver': _CLINICO, 'editar': {'enfermeiro'}},
    'evolucao_medica': {'ver': _CLINICO, 'editar': {'medico'}},
    'prescricao': {'ver': _CLINICO, 'editar': {'medico'}},
    'administracao': {'ver': _CLINICO, 'editar': {'tecnico', 'enfermeiro', 'medico'}},
    'diagnostico': {'ver': _CLINICO, 'editar': {'medico'}},
    'internacao': {'ver': _CLINICO, 'editar': {'medico'}},
    'alta': {'ver': _CLINICO, 'editar': {'medico'}},
    'solicitar_transferencia': {'ver': _CLINICO, 'editar': {'medico'}},
    'central_transferencia': {'ver': {'transferencia', 'medico', 'direcao'}, 'editar': {'transferencia'}},
    'aih': {'ver': {'aih', 'direcao'}, 'editar': {'aih'}},
    'relatorios': {'ver': {'tecnico', 'enfermeiro', 'medico', 'direcao', 'aih'}, 'editar': set()},
    'direcao': {'ver': {'direcao'}, 'editar': set()},
    'auditoria': {'ver': {'direcao', 'admin'}, 'editar': set()},
    'usuarios': {'ver': {'admin', 'direcao'}, 'editar': {'admin'}},
}

# Mapeia o tipo de evolução para a seção de permissão correspondente.
SECAO_EVOLUCAO = {
    'tecnico': 'evolucao_tecnico',
    'enfermagem': 'evolucao_enfermagem',
    'medica': 'evolucao_medica',
}


def tem_permissao(secao, acao='ver', papel=None):
    if papel is None:
        usuario = g.get('usuario')
        if usuario is None:
            return False
        papel = usuario['papel']
    regra = PERMISSOES.get(secao)
    if regra is None:
        return False
    if acao == 'ver':
        return papel in regra['ver'] or papel in regra['editar']
    return papel in regra['editar']


def pode_ver(secao):
    return tem_permissao(secao, 'ver')


def pode_editar(secao):
    return tem_permissao(secao, 'editar')


def login_obrigatorio(view):
    @wraps(view)
    def envolvida(*args, **kwargs):
        if g.get('usuario') is None:
            return redirect(url_for('auth.login', next=request.full_path))
        return view(*args, **kwargs)
    return envolvida


def requer(secao, acao='ver'):
    """Decorador: exige login e permissão na seção; caso contrário retorna 403."""
    def decorador(view):
        @wraps(view)
        def envolvida(*args, **kwargs):
            if g.get('usuario') is None:
                return redirect(url_for('auth.login', next=request.full_path))
            if not tem_permissao(secao, acao):
                abort(403)
            return view(*args, **kwargs)
        return envolvida
    return decorador
