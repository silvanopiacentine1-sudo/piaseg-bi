# BI Piaseg — Business Intelligence do Franqueado

Painel único por franqueado (login do Portal do Franqueado), **no ar desde 14/10/2026 em https://piaseg-bi.onrender.com**.

**Na web (franqueados):** serviço no Render (ver seção "Publicação"). **No Mac (teste):** clique duplo em `Abrir BI.command`. Ele encerra qualquer BI antigo na porta 8020, relê as planilhas do Drive, gera `data/bi_data.json` e abre http://localhost:8020.

## Arquivos

| Arquivo | O que faz |
|---|---|
| `build_data.py` | Lê as fontes do Drive e gera `data/bi_data.json` (todas as regras de dados estão aqui) |
| `server.py` | FastAPI local: login, permissões e entrega dos dados de cada unidade |
| `static/index.html` | O painel inteiro (HTML/CSS/JS, gráficos em SVG próprio) |
| `vinculos.json` | Login do portal → franqueado(s), e lista de gestores (`admins`) |

## Fontes (Drive da franqueadora › Piaseg Franchising/TI)

| Tema | Pasta / arquivo | Observações |
|---|---|---|
| Campanha | `Arrancada de Vendas /Comparativo_Campanha_Jan25_vs_Jan26.xlsx` (atenção ao espaço no fim do nome da pasta) | Gerado pelo pipeline da campanha. Ramo vem das abas "Base"; seguradora vem do export de `25/` e `26/` cujos totais batem com a planilha |
| Cotação x Conversão | `Cotação x Conversão/<N> - <Mês>/` (orçamento calculado + análise de produção) | Mesmos filtros do "Indicador de Conversão"; agosto conferido 100% |
| Não renovadas | `Apólices não renovadas/` (XLS mais recente) | Mês = término de vigência |
| Canceladas | `Apólices Canceladas/` (XLS mais recente) | Mês = data de cancelamento; endossos repetidos contam uma vez |
| Comissões | `Comissões/Recebidas/25/` e `/26/` (antes `Comissões recebidas/`), **um arquivo por mês: "Março 26.XLS"** | O relatório não tem data: o mês vem do nome. N=novo, R=renovação, EN/ER=endosso, CN/CR=cancelamento (estorno) |
| Produção geral | **Arquivos DIÁRIOS (desde 16/10/2026): "outubro 16.XLS", "outubro 17.XLS"… = vendas de cada dia, e todos os arquivos com o mesmo mês no nome SOMAM** (arquivo idêntico baixado 2× conta 1×; downloads sem nome de mês só valem se o mês não tiver arquivos nomeados; não misturar arquivo do mês inteiro com diários). A automação da campanha (`piaseg-campanha-automacao`) segue a mesma regra. **Só a corretora "Piaseg Consultoria e Corretora de Seguros Ltda"** (coluna CORRETORA; "Piaseg Corretora de Seguros" e "Piaseg Negócios e Corretora" ficam fora; co-corretagem que inclua a Consultoria conta — regra de 2026-10-15). Exports "Análise de Produção" da pasta da campanha (`25/`, `26/`), **todos os ramos**, sem as exclusões da campanha. Jan–jun/26 vêm da pasta Cotação x Conversão (sem base 2025) | Downloads diários sem nome de mês entram no mês do download, unidos sem duplicar (`_uniao_sem_duplicar`). Crescimento só nos meses que existem nos dois anos |
| Comissões › À receber / Repasses liberados | `Comissões/À Receber/` (RptRepassesPendentes) e `Comissões/Repasses Liberados/` (RptRepassesLiberados): só VALOR e UNIDADE DE NEGÓCIO | Fotografia do momento, sem data: vale o relatório mais recente da pasta, e a data do arquivo é a "posição". Subtemas da aba Comissões, com total, média da rede e "equivale a X meses" da comissão média mensal de 2026 |
| Sinistros | `Sinistros/`, **um arquivo por mês: "Janeiro 26.XLS"** (o usuário passou a nomear "1.Janeiro 26.XLS" … "9.Setembro 26.XLS": o número na frente é só a ordem; o ano é sempre o ÚLTIMO número do nome) | Sem data: mês e ano vêm do nome. Arquivo sem mês no nome é ignorado, com aviso |

**Para atualizar um mês novo:** salve o relatório na pasta certa com o nome do mês (ex.: `Outubro 26.XLS`) e abra o BI.

## Regras de negócio decididas (não rediscutir)

- **Nomes de franqueado:** o nome canônico é o da campanha. `canonico()` usa o cruzamento Grupo de Produção→Divisão dos exports da campanha e os `ALIASES` manuais.
- **Matriz fora do BI:** Dourados, Campo Grande, Piaseg Consultoria, Piaseg Corretora, Studio Agronegócios e vendedores Silvano/Wilson/Clessio/Luciano/LP/CHL.
- **Privacidade:** o franqueado vê só a própria posição no ranking. Nenhum dado de outra unidade sai do servidor para ele (testado).
- **Visão TODOS** (opção "TODOS — visão da rede"): só para gestor (`admin`). Mostra o total da rede, a média por franqueado, o comparativo por franqueado em cada tema e o ranking completo da campanha. Franqueado recebe 403.
- **Filtro "Período"** em todas as abas: trimestres (jan–mar, abr–jun, jul–set, out–dez) e meses.
- **Trimestre na campanha:** tem ranking próprio, com a mesma regra do Geral (soma de pontos; desempate pelo maior % de crescimento, sem base 2025 = infinito). Validado: reproduz o Geral da planilha.
- **Comissões "Ano todo" e trimestre:** 2025 é comparado só nos mesmos meses que 2026 já tem.
- **Indicador de crescimento (regra do Silvano, 2026-10-11), em todos os temas:** sem variação = **0%**; tinha no ano anterior e zerou = queda real (**▼ 100%**); não tinha no ano anterior e passou a ter = **só a seta ▲ no quadrinho verde**, sem número (mudado pelo Silvano em 2026-10-11; antes mostrava o valor). NUNCA usar "Novo", "Parou" ou "Estável". Funções `indicador()` (pílula) e `crescTxt()` (texto da tabela mensal da campanha).
- **Não renovadas / Canceladas:** sem link para o antigo painel de apólices (piaseg-apolices), descontinuado pelo Silvano em 2026-10-11. O BI é o único lugar dessas informações.
- **Comissões › À receber / Repasses liberados:** o franqueado NÃO recebe a média da rede (nem no pacote de dados). O 2º cartão é **"Sua média mensal (últimos 12 meses)"** = comissões recebidas (subtema Recebidas) nos 12 meses corridos até o último mês com repasse ÷ 12; "Equivale a" usa a mesma média. À receber = "Total a receber (nos próximos 12 meses)". Na visão TODOS: média mensal da rede.
- **Comissões:** sem a contagem de lançamentos nas tabelas.
- **Valores em R$:** sempre inteiros e completos. Os centavos são cortados, sem arredondar e sem "mil"/"k".
- **TREINAMENTO (exemplo fictício):** unidade com números inventados (`gerar_treinamento`, semente fixa), **só o gestor (admin) vê e abre** (mudado em 2026-10-15; antes era liberada a qualquer login), para ensinar. Fica fora de `franqueados`, então nunca entra em ranking, média, rede ou visão TODOS (testado). Tem a própria "média da rede" fictícia e um selo vermelho de "DADOS FICTÍCIOS".
- **Quadro "Quantidade de negócios"** (Campanha e Produção geral, abaixo de produção por ramo): negócios por ramo no ano anterior x atual, crescimento em número e em %, mais o total. Por isso os quadros de prêmio por ramo e por seguradora dessas abas NÃO mostram mais "X neg." embaixo dos valores (pedido de 2026-10-11, para não duplicar). Negócio = lançamento do relatório (mesma contagem da campanha). Na Produção geral compara só os meses que existem nos dois anos.
- **Pizzas:** Campanha (participação por ramo, ao lado da tabela; seguradora embaixo), Cotação x Conversão (cotações e efetivados por ramo, ao lado da tabela; vendedor e situação embaixo), Produção geral e Comissões. Paleta: navy, dourado, azul, areia, teal, roxo; "Outros" em cinza.
- **Marca "BI":** texto em Playfair Display (fonte mais próxima do monograma "PS" do logotipo), dourado, 22px no cabeçalho; login "BI Piaseg" na mesma fonte. O desenho no traço da Alcubierre foi testado e recusado pelo usuário (2026-10-11).
- **Painel PRIVADO do Clessio (16/10/2026):** fica no BI da nuvem, mas **só o login do Clessio vê; o admin NÃO** (nem no seletor, nem na visão TODOS, nem por URL [403], nem no registro de acessos, nem nos avisos do status). Logins: `clessio@piaseg.com.br` (senha do Portal) e `clessio` (senha própria, PBKDF2), configurados na env **`BI_PRIVADOS_JSON`** do Render (`{"unidades": {"CLESSIO": [logins]}, "usuarios": {"clessio": {nome, sal, hash}}}`). Montado por `build_clessio.py` (cópia do build do BI Clessio local: lê só as subpastas "Clessio" de cada tema, soma os colaboradores, sem filtro de corretora, sem campanha) e guardado em `dados["privados"]["CLESSIO"]`; se falhar, mantém a versão anterior sem derrubar a rede. **Blindagem:** o BI da rede ignora qualquer arquivo em pasta "Clessio" (`PASTAS_PRIVADAS`) e qualquer unidade começando com "CLESSIO" (`UNIDADES_PRIVADAS`). Na tela do Clessio: sem aba Campanha, Resumo com Produção geral, sem "média da rede".
- **Comissões do Clessio (19/10/2026):** os relatórios vêm direto em `Comissões/Clessio/` (um por colaborador: CLESSIO MARTINENGHI e PRODUCAO PIASEG) com COLABORADOR, VALOR e **DATA DO PAGAMENTO**: o ano e o mês saem da data. Sem NEGÓCIO/CÉLULA, a aba Recebidas mostra a **versão simples** (`abaComissoesSimples`: total, média mensal, melhor mês, último mês, gráfico e tabela mês a mês; compara com o ano anterior só se houver dados dele). Quando o relatório trouxer NEGÓCIO e CÉLULA, a aba completa volta sozinha.
- **Visual:** navy `#072a3c`, dourado `#c2a360`, fontes Jost + Cinzel Decorative. Base 2025 em verde claro `#a3d9a5` (Campanha e Comissões). Barras das Canceladas em vermelho sangue `#c1121f`. Cada aba do menu mostra só o seu tema.

## Pendências em aberto

1. Conversão acima de 100%: as cotações excluem "Renovação Própria Corretora", mas os efetivados incluem renovações (mesma regra do Indicador original). Falta decidir.
2. Logins sem vínculo: Ricardo Macedo Portela, Ernani, Frutuoso, Mano Motors, Vale Representações etc. Para vincular, editar a variável **BI_VINCULOS_JSON no Render** (e o `vinculos.json` local, usado só no Mac).
3. Pipeline da campanha (outro projeto): Outubro/26 do ranking da campanha está subestimado (só um dos exports diários é usado). Aguardando autorização para corrigir. A Produção geral do BI já junta todos os downloads.
4. Subpastas novas que eventualmente surgirem no Drive só entram no BI se forem pedidas (ex.: novas pastas dentro de Comissões).

Resolvido: publicação online feita em 14/10/2026 (Render, ver abaixo).

## Publicação (web)

- **Endereço: https://piaseg-bi.onrender.com** · GitHub (público, só código): github.com/silvanopiacentine1-sudo/piaseg-bi, branch `main` com deploy automático a cada push.
- Render, serviço web `piaseg-bi` (`srv-db7mbio473hc73dt95rg`, região virginia) (time Piaseg), plano starter, **disco persistente em `/var/data`** (dados + espelho do Drive). Inicia com `python3 server.py`.
- Variáveis de ambiente: `DATA_DIR=/var/data`, `SECRET_KEY` (assina as sessões), `GOOGLE_SERVICE_ACCOUNT_JSON` (conta `campanha-automacao@…`, a mesma da automação da campanha), `BI_VINCULOS_JSON` (login → franqueado e gestores; o vinculos.json NÃO vai para o GitHub), `PYTHON_VERSION=3.11.9`.
- A conta de serviço precisa ter acesso de **Leitor** às pastas: Arrancada de Vendas, Cotação x Conversão, Apólices não renovadas, Apólices Canceladas, Comissões recebidas e Sinistros.
- **Atualização automática** (`atualizador.py`, roda dentro do próprio serviço, fuso de MS):
  - todo dia às **10h**: TODAS as pastas, todos os temas (desde 14/10/2026; antes os temas mensais eram só no dia 05). Se a planilha da campanha ainda não foi regerada pela automação da campanha (que roda por volta das 10h), ou se alguma pasta não pôde ser lida, tenta de novo a cada 15 min até as 12h;
  - o build roda em processo separado; se der erro ou o resultado for suspeito (muito menos franqueados que antes), **a versão anterior continua no ar**. A última versão boa também fica em `bi_data.anterior.json`.
- **Registro de acessos** (botão "Acessos", só gestor): SQLite em `/var/data/acessos.db`. Uma visita começa no 1º sinal da página depois do login (ou depois de 30 min sem sinal); a página manda sinal a cada 2 min enquanto está visível; a saída é o clique em "Sair" ou o último sinal. Filtros por unidade e período (7/30/90/365 dias), resumo por unidade com "nunca acessou". Registros com mais de 400 dias são apagados.
- O gestor (`admin`) tem o botão **"⟳ Atualizar dados"**: mostra o status, os avisos e permite forçar uma atualização completa.
- Segurança: sessão assinada de 12 h, bloqueio de 15 min após 8 senhas erradas (por IP e por usuário), cabeçalhos de segurança, sem páginas de documentação da API.
- O Campanha depende da planilha `Comparativo_Campanha_Jan25_vs_Jan26.xlsx`, gerada pela automação da campanha (Render `piaseg-campanha-cron`). Se essa automação for desligada, o tema Campanha para de atualizar.

### Histórico do git
O histórico antigo (que continha o vinculos.json com e-mails) ficou só no Mac, na branch `historico-local`. O GitHub recebeu um histórico novo e limpo. Trabalhar sempre na branch `main`.
