"""Funções utilitárias: datas, formatação, validação e tabelas de rótulos."""
import re
from datetime import date, datetime

FORMATO_DATA = '%Y-%m-%d %H:%M:%S'

# ---------------------------------------------------------------- rótulos

RISCOS = {
    'vermelho': {'nome': 'Vermelho - Emergência', 'ordem': 1},
    'laranja': {'nome': 'Laranja - Muito urgente', 'ordem': 2},
    'amarelo': {'nome': 'Amarelo - Urgente', 'ordem': 3},
    'verde': {'nome': 'Verde - Pouco urgente', 'ordem': 4},
    'azul': {'nome': 'Azul - Não urgente', 'ordem': 5},
}

STATUS_ATENDIMENTO = {
    'aberto': 'Em atendimento',
    'internado': 'Internado',
    'aguardando_transferencia': 'Aguardando transferência',
    'finalizado': 'Finalizado',
}

TIPOS_SAIDA = {
    'alta_melhorado': 'Alta - melhorado',
    'alta_a_pedido': 'Alta a pedido',
    'obito': 'Óbito',
    'evasao': 'Evasão',
    'transferencia': 'Transferência',
}
TIPOS_SAIDA_MEDICO = ['alta_melhorado', 'alta_a_pedido', 'obito', 'evasao']

STATUS_INTERNACAO = {
    'pendente_assinatura': 'Aguardando assinatura médica',
    'assinada': 'Assinada',
    'encerrada': 'Encerrada',
}

MOTIVOS_TRANSFERENCIA = {
    'falta_materiais': 'Falta de materiais / insumos',
    'falta_especialidade': 'Falta de especialidade médica',
    'falta_leito': 'Falta de leito / UTI',
    'falta_exame': 'Exame indisponível na unidade',
    'outro': 'Outro motivo',
}

STATUS_TRANSFERENCIA = {
    'solicitada': 'Solicitada',
    'em_contato': 'Em contato com destino / regulação',
    'aceita': 'Aceita pelo destino',
    'concluida': 'Concluída (paciente transferido)',
    'cancelada': 'Cancelada',
}

STATUS_AIH = {
    'pendente': 'Pendente de análise',
    'pendencia': 'Com pendência',
    'autorizada': 'Autorizada',
    'exportada': 'Exportada',
}

SISTEMAS_AIH = {'SISAIH01': 'SISAIH01', 'SIHD2': 'SIHD2'}

VIAS = ['VO (oral)', 'IV (endovenosa)', 'IM (intramuscular)', 'SC (subcutânea)',
        'SL (sublingual)', 'Inalatória', 'Tópica', 'Retal', 'Outra']

UFS = ['AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS', 'MG', 'PA',
       'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO']

SEXOS = {'F': 'Feminino', 'M': 'Masculino', 'I': 'Intersexo / não informado'}


# ---------------------------------------------------------------- datas

def agora():
    return datetime.now().strftime(FORMATO_DATA)


def para_datetime(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(valor[:19], FORMATO_DATA)
    except ValueError:
        try:
            return datetime.strptime(valor[:10], '%Y-%m-%d')
        except ValueError:
            return None


def formatar_data(valor, com_hora=True):
    d = para_datetime(valor)
    if d is None:
        return '—' if not valor else valor
    if com_hora and len(valor) > 10:
        return d.strftime('%d/%m/%Y %H:%M')
    return d.strftime('%d/%m/%Y')


def horas_desde(valor, ate=None):
    inicio = para_datetime(valor)
    if inicio is None:
        return 0
    fim = para_datetime(ate) if ate else datetime.now()
    return max(0, int((fim - inicio).total_seconds() // 3600))


def idade(data_nascimento):
    d = para_datetime(data_nascimento)
    if d is None:
        return None
    hoje = date.today()
    return hoje.year - d.year - ((hoje.month, hoje.day) < (d.month, d.day))


# ---------------------------------------------------------------- formatação

def so_digitos(texto):
    return re.sub(r'\D', '', texto or '')


def formatar_cpf(cpf):
    c = so_digitos(cpf)
    return f'{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}' if len(c) == 11 else (cpf or '')


def formatar_cns(cns):
    c = so_digitos(cns)
    return f'{c[:3]} {c[3:7]} {c[7:11]} {c[11:]}' if len(c) == 15 else (cns or '')


def formatar_cep(cep):
    c = so_digitos(cep)
    return f'{c[:5]}-{c[5:]}' if len(c) == 8 else (cep or '')


def formatar_telefone(tel):
    c = so_digitos(tel)
    if len(c) == 11:
        return f'({c[:2]}) {c[2:7]}-{c[7:]}'
    if len(c) == 10:
        return f'({c[:2]}) {c[2:6]}-{c[6:]}'
    return tel or ''


# ---------------------------------------------------------------- validação

def cpf_valido(cpf):
    c = so_digitos(cpf)
    if len(c) != 11 or c == c[0] * 11:
        return False
    for i in (9, 10):
        soma = sum(int(c[j]) * (i + 1 - j) for j in range(i))
        if (soma * 10) % 11 % 10 != int(c[i]):
            return False
    return True


def cns_valido(cns):
    """Valida o Cartão Nacional de Saúde (cartão do SUS) pelo algoritmo oficial."""
    c = so_digitos(cns)
    if len(c) != 15:
        return False
    if c[0] in '12':
        pis = c[:11]
        soma = sum(int(pis[i]) * (15 - i) for i in range(11))
        dv = 11 - soma % 11
        if dv == 11:
            dv = 0
        if dv == 10:
            soma += 2
            dv = 11 - soma % 11
            esperado = f'{pis}001{dv}'
        else:
            esperado = f'{pis}000{dv}'
        return esperado == c
    if c[0] in '789':
        return sum(int(c[i]) * (15 - i) for i in range(15)) % 11 == 0
    return False


def cid_valido(cid):
    """Formato CID-10: letra + 2 dígitos, com subcategoria opcional (ex.: J18, J18.9, J189)."""
    return bool(re.fullmatch(r'[A-Z]\d{2}(\.?\d{1,2})?', (cid or '').strip().upper()))


def normalizar_cid(cid):
    c = (cid or '').strip().upper().replace('.', '')
    return f'{c[:3]}.{c[3:]}' if len(c) > 3 else c


def senha_forte(senha):
    """Mínimo de 8 caracteres, com pelo menos uma letra e um número."""
    senha = senha or ''
    return len(senha) >= 8 and bool(re.search(r'[A-Za-z]', senha)) and bool(re.search(r'\d', senha))


def ler_data(texto):
    try:
        return datetime.strptime((texto or '').strip(), '%Y-%m-%d').date()
    except ValueError:
        return None
