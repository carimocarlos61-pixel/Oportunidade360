# Oportunidade360

Plataforma inicial em Flask para oportunidades, pesquisas, microtarefas, campanhas empresariais, parceiros e pedidos de levantamento.

## Funcionalidades
- Registo e autenticação de utilizadores.
- Painel de tarefas e submissão de comprovativos.
- Aprovação/rejeição pelo administrador.
- Carteira e histórico de movimentos.
- Pedidos de levantamento M-Pesa/e-Mola (registo e gestão manual; não transfere dinheiro automaticamente).
- Formulário de campanhas para empresas.
- Diretório de parceiros/afiliados.
- Páginas institucionais e espaços preparados para anúncios.

## Executar localmente
1. Instala Python 3.11 ou superior.
2. Cria ambiente virtual: `python -m venv .venv`
3. Ativa o ambiente virtual.
4. Instala dependências: `pip install -r requirements.txt`
5. Define `SECRET_KEY`, `ADMIN_EMAIL` e `ADMIN_PASSWORD` como variáveis de ambiente.
6. Executa: `python app.py`
7. Abre `http://127.0.0.1:5000`.

No PowerShell, por exemplo:
```powershell
$env:SECRET_KEY="uma-chave-longa-e-aleatoria"
$env:ADMIN_EMAIL="admin@exemplo.com"
$env:ADMIN_PASSWORD="UmaSenhaForteAqui123!"
python app.py
```

## Publicar no GitHub e Render
1. Cria um repositório GitHub e envia todos os ficheiros.
2. No Render, cria um Web Service ligado ao repositório.
3. O Render pode ler `render.yaml`.
4. Define `ADMIN_EMAIL` e `ADMIN_PASSWORD` nos Environment Variables do serviço.
5. Mantém `SECRET_KEY` gerada pelo Render.
6. Para manter a base de dados SQLite entre reinícios/deploys, configura um disco persistente e `DATABASE_PATH` para um caminho dentro do disco. O plano gratuito do Render pode não incluir disco persistente; para produção, usa uma base de dados persistente.

## Avisos importantes antes de lançar
- Esta é uma primeira versão funcional (MVP), não uma instituição financeira nem uma garantia de rendimento.
- Não anuncies recompensas sem financiamento real e confirmado. Tarefas de demonstração têm recompensa 0 MT.
- Os pedidos M-Pesa/e-Mola são registados para revisão manual. Não existe integração API nem pagamento automático nesta versão.
- Só marques um levantamento como pago depois de confirmares a transferência fora da plataforma.
- Confirma as condições, licenças, proteção de dados, idade mínima e regras dos operadores antes de aceitar pagamentos ou dados sensíveis.
- Publicidade e afiliados só devem ser ativados após aprovação e acordo com os respetivos fornecedores.
- Para contas publicitárias, contratos e pagamentos que exijam maioridade, um adulto responsável deve gerir a conta legalmente.
- Antes de usar dados reais, acrescenta política de retenção, backups, monitorização, HTTPS (Render fornece HTTPS) e revisão de segurança profissional.

## Segurança
Passwords são armazenadas com hash Werkzeug; formulários POST usam token CSRF; consultas SQL usam parâmetros. Ainda assim, faz revisão de segurança antes de produção e não reutilizes palavras-passe.
