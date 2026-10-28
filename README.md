# Sistema Hospitalar

Sistema web de gestão de atendimento hospitalar, com **backend em Python (Flask)**, banco **SQLite** e
front-end em **HTML + CSS + JavaScript** (sem frameworks pesados).

## Como rodar no seu computador

```powershell
cd SistemaHospitalar
pip install -r requirements.txt
python seed_demo.py      # (opcional) cria usuários e pacientes de demonstração
python app.py            # abre em http://127.0.0.1:5000
```

O primeiro usuário é criado automaticamente: **admin / Admin@2026** (o sistema obriga a trocar a senha no primeiro acesso).

Usuários de demonstração (`seed_demo.py`, senha **Hospital@123**):

| Login | Cargo |
|---|---|
| recepcao | Recepção |
| tecnico | Técnico(a) de Enfermagem |
| enfermeiro | Enfermeiro(a) |
| medico | Médico(a) |
| transferencia | Central de Transferência |
| faturamento | Faturamento / AIH |
| direcao | Direção |

Testes automatizados: `python -m unittest discover -s tests -v`

## Fluxo do paciente

1. **Recepção** busca o paciente (nome, CPF, cartão SUS ou nº do prontuário). Se for novo, cadastra.
   CPF e CNS são validados pelo dígito verificador; CEP preenche o endereço automaticamente (ViaCEP).
   A recepção vê as passagens anteriores e abre o novo atendimento com o motivo da procura.
2. **Enfermeiro** faz a classificação de risco (Manchester: vermelho → azul) com sinais vitais.
3. **Técnico** e **enfermeiro** registram a evolução (“como o paciente passou”) com sinais vitais.
   Registros não são apagados: são *anulados* com justificativa e ficam no histórico.
4. **Médico** vê todo o quadro (inclusive as evoluções da enfermagem, sem poder editá-las), as passagens
   anteriores, registra evolução médica, diagnóstico/CID e prescreve medicações.
5. **Técnico/enfermeiro** (ou o médico) checam cada dose administrada — fica registrado quem, quando e quantas.
6. Saída:
   - **Só medicação / atendimento curto** → o médico dá alta e o sistema gera o **relatório do atendimento**.
   - **Mais de 24 horas** → o sistema gera **internação automaticamente**, com a **capa** (dados do paciente,
     diagnóstico, CID principal/secundário, descrição da chegada e assinatura do médico — a assinatura exige a senha).
     O médico também pode internar antes das 24h.
   - **Faltam recursos** → o médico envia para a **Central de Transferência**, que vê os dados completos,
     imprime a ficha, registra destino/protocolo de regulação e conclui ou cancela.
7. Internação encerrada → vai para o **Faturamento (AIH)**: o agente confere tudo, informa nº da AIH e
   procedimento SIGTAP, autoriza o envio para **SISAIH01** ou **SIHD2** (ou registra pendência) e gera o lote.
8. **Direção** acompanha tudo (painel geral, todos os setores, prontuários, AIH, transferências, auditoria)
   **sem poder alterar nada**.

## Permissões (resumo)

| Seção | Recepção | Técnico | Enfermeiro | Médico | Transf. | AIH | Direção |
|---|---|---|---|---|---|---|---|
| Cadastro e abertura | **E** | V | V | V | V | V | V |
| Classificação de risco | – | V | **E** | V | V | V | V |
| Evolução do técnico | – | **E** | **E** | V | V | V | V |
| Evolução de enfermagem | – | V | **E** | V | V | V | V |
| Evolução médica / prescrição / diagnóstico / internação / alta | – | V | V | **E** | V | V | V |
| Checar medicação | – | **E** | **E** | **E** | V | V | V |
| Central de transferência | – | – | – | V | **E** | – | V |
| Faturamento AIH | – | – | – | – | – | **E** | V |

E = edita · V = só visualiza. A matriz completa está em `permissoes.py` e na tela *Usuários e permissões*.

## Segurança incluída

- Senhas com hash (Werkzeug), troca obrigatória no 1º acesso, mínimo 8 caracteres com letras e números.
- Bloqueio de 15 min após 5 senhas erradas; sessão expira após 30 min sem uso.
- Proteção CSRF em todos os formulários; cabeçalhos de segurança; páginas não ficam em cache.
- Auditoria de todas as ações (quem, o quê, quando, IP) — visível para direção e administrador.
- Prontuário finalizado não pode mais ser alterado.

## Colocar online

Para produção, use o servidor **Waitress** (já está no `requirements.txt`) e defina as variáveis de ambiente:

| Variável | Para quê |
|---|---|
| `SECRET_KEY` | chave longa e aleatória (obrigatório em produção) |
| `ADMIN_SENHA` | senha inicial do admin (no lugar de `Admin@2026`) |
| `COOKIE_SEGURO=1` | quando estiver com HTTPS |
| `HOSPITAL_DB` | caminho do arquivo do banco (padrão `instance/hospital.db`) |
| `SESSAO_MINUTOS` | tempo de inatividade da sessão (padrão 30) |

Comando de produção: `waitress-serve --port=8000 --call app:create_app`

Opções de hospedagem:
- **PythonAnywhere** (mais simples para SQLite — o arquivo do banco persiste): crie um *Web app Flask*,
  envie a pasta e aponte o WSGI para `from app import create_app; application = create_app()`.
- **Render / Railway**: start command `waitress-serve --port=$PORT --call app:create_app`. Atenção: nesses
  serviços o disco é apagado a cada deploy — é preciso montar um disco persistente para o `HOSPITAL_DB`.
- **Servidor próprio do hospital** (Windows ou Linux) atrás de um proxy com HTTPS (IIS, Nginx ou Caddy).

Sempre use **HTTPS** e faça **backup diário** do arquivo `instance/hospital.db`.

## Observações importantes

- O arquivo de exportação de AIH usa um **layout simplificado (CSV)**. Para importar de fato no SISAIH01/SIHD2
  é preciso adaptar para o leiaute oficial do DATASUS da competência vigente (a função está em `rotas/aih.py`).
- O CID-10 é validado quanto ao formato (ex.: `J18.9`), não contra a tabela oficial.
- Dados de saúde são dados sensíveis pela LGPD: restrinja o acesso, use HTTPS e mantenha backups protegidos.
- <img width="1909" height="912" alt="image" src="https://github.com/user-attachments/assets/60931ec1-9113-4b3c-a2d5-fdef27623514" />

- <img width="1891" height="901" alt="image" src="https://github.com/user-attachments/assets/3dfce19b-2571-4428-965b-f6d364735190" />

<img width="1915" height="922" alt="image" src="https://github.com/user-attachments/assets/3314a441-c8db-4d01-83d3-0da5a154970a" />


