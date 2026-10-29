# Telix Sync (v1.3.0)

O **Telix Sync** é uma ferramenta desktop desenvolvida pela Auro Tecnologia para a injeção e ressincronização de telemetria em massa na plataforma Telix (ThingsBoard). O software processa arquivos brutos originados do concentrador Andrômeda, planilhas exportadas da plataforma Telix, arquivos extraídos diretamente da memória do datalogger Sirius e relatórios de falhas (DLQ), inserindo os dados via HTTP assíncrono de alta performance.

## Funcionalidades Principais

* **Detecção e ETL Automáticos (4 Fontes):** Reconhecimento automático se o arquivo tem origem **Andrômeda**, **Telix**, **Sirius (Datalogger)** ou **Falhas (DLQ)**. Para arquivos do Telix e Sirius, aplica as regras de Extração, Transformação e Carga (ETL) gerando um arquivo `.csv` convertido estruturalmente idêntico ao padrão do concentrador Andrômeda e corrigindo nativamente o fuso horário (`America/Sao_Paulo`) para Epoch (`ts`).
* **Suporte Completo às 3 Redes (WiFi, NB-IoT e LoRa):** Gera automaticamente os tokens e nomes de arquivos convertidos respeitando a arquitetura de transmissão selecionada:
  * **WiFi:** `Sirius` + Nº de Série (ex: `Sirius727`)
  * **NB-IoT:** `00` + Nº de Série (ex: `00727`)
  * **LoRa:** `SiriusLora` + Nº de Série (ex: `SiriusLora727`)
* **Identificação Inteligente de Série:** Extrai automaticamente o número de série do nome do arquivo quando segue o padrão `SiriusXXX`. Para equipamentos que perderam configuração em campo (`default_...`) ou possuem nomenclatura personalizada (ex: `DL-12`), destaca visualmente o campo em amarelo/âmbar para preenchimento obrigatório pelo analista.
* **Reprocessamento Nativo de DLQ (`_FALHAS.csv`):** Telemetrias recusadas pelo servidor por oscilação de rede são salvas em um arquivo `_FALHAS.csv` com o JSON íntegro. Basta adicionar esse arquivo novamente à fila para reenviar apenas os pacotes pendentes.
* **Validador de Conexão e Proteção de Token (Fail-Fast):** Botão dedicado para testar a conectividade com o servidor (Nuvem ou IP Local) antes de iniciar o lote. Caso o servidor recuse o Token do equipamento (`HTTP 401/404`), o sistema aborta o arquivo imediatamente e sinaliza erro na tabela, evitando envios desnecessários.
* **Marcha Adaptativa (Adaptive EPS) e Painel de KPIs:** Motor inteligente que calibra a velocidade (`Requisições por Segundo`) com base na saúde da *Rule Chain* do servidor, exibindo em tempo real cards de indicadores com arquivos concluídos, volume de linhas, velocidade instantânea (`EPS`) e estimativa de tempo restante (`ETA`).
* **Ações em Lote na Fila:** Botões rápidos (**Todos WiFi**, **Todos NB-IoT** e **Todos LoRa**) para alterar o tipo de comunicação de múltiplos arquivos simultaneamente, além de proteção contra arquivos duplicados.
* **Resiliência e Checkpoints:** Acompanha o processamento linha a linha e salva o progresso em `.telix_checkpoints.json`. Se o processo for interrompido ou pausado manualmente, retoma exatamente de onde parou no próximo início.
* **Dry Run (Pré-visualização JSON) e Terminal Semântico:** Validador visual das 3 primeiras linhas do Payload JSON antes do envio e terminal de diagnóstico colorido por criticidade (Sucesso, Aviso, Erro).
* **Proteção contra Bloqueios (Anti-Excel):** Intercepta de forma amigável arquivos que estejam abertos/bloqueados no Microsoft Excel, evitando travamentos.

---

## Como Usar (Guia do Suporte)

O Telix Sync foi projetado para ser executado como uma aplicação *Standalone* (arquivo único `.exe`), sem necessidade de instalação.

### Passo 1: Configuração e Teste de Conexão
1. Abra o aplicativo `TelixSync.exe`.
2. Na barra superior **Servidor Alvo**, selecione o ambiente:
   * **Nuvem (Cliente):** Insira apenas o subdomínio do cliente (ex: para *minasgerais.telix.com.br*, digite `minasgerais`).
   * **Servidor IP:** Insira o endereço IP local (ex: `192.168.0.90`).
3. Clique em **Testar Servidor** para confirmar que o ambiente está online (`✅ Online`).

### Passo 2: Preparar a Fila de Processamento
1. Clique em **Adicionar Arquivos** e selecione um ou múltiplos arquivos `.csv` ou `.txt`.
2. **Arquivos Andrômeda:** O sistema extrai o token (ex: `SiriusLora340`) e configura tudo automaticamente.
3. **Arquivos Telix, Sirius (Datalogger) ou Falhas (DLQ):**
   * Defina a **Rede** (`WiFi`, `NB-IoT` ou `LoRa`) individualmente ou use os botões **Todos WiFi** / **Todos NB-IoT** / **Todos LoRa** no topo da tabela.
   * Confira o **Nº de Série** preenchido automaticamente (ou digite manualmente nos campos destacados em amarelo para arquivos `default_...` ou nomes customizados).
4. *(Opcional)* Clique no ícone de lupa na coluna **JSON** para pré-visualizar os pacotes antes do envio.

### Passo 3: Iniciar Sincronização
1. Clique em **Iniciar Sincronização em Massa**.
2. Acompanhe o andamento pelos **Cards de KPIs** no topo (Velocidade e ETA), pela barra de progresso e pelo **Terminal de Execução**.
3. Caso precise interromper o envio, clique em **Parada Segura (Salvar Checkpoint)**.
4. Ao finalizar, consulte os relatórios detalhados na pasta `/logs` clicando em **Abrir Pasta de Relatórios**.

---

## Como Compilar (Guia para Desenvolvedores)

Se realizar alterações no código-fonte Python (`.py`), você precisará gerar um novo executável. O projeto utiliza o **Flet** e o **PyInstaller** para empacotamento.

**Pré-requisitos:**
Garanta que seu ambiente virtual (`venv`) está ativo e que as dependências do arquivo `requirements.txt` (`flet`, `pandas`, `aiohttp`, `python-dotenv`) estão instaladas.

**Comando de Build:**
Execute o comando abaixo no terminal, na raiz do projeto, para gerar o executável atualizado na pasta `dist/`:

```bash
flet pack main.py --name "TelixSync" --icon "assets\logo.png" --add-data "assets;assets"
```

---

## Changelog (Histórico de Versões)

### [v1.3.0] - 2026-10-29
#### Adicionado
* **Suporte a arquivos nativos do Datalogger (`Sirius`):** Nova regra de ETL para arquivos extraídos diretamente da memória do equipamento (`n;ID;Datetime;Battery [V];Low Bat;Sens1 Data1...`), convertendo anos de 2 dígitos (`%y`) para 4 dígitos (`%Y`) e gerando CSV padronizado no formato Andrômeda.
* **Opção de Rede `LoRa`:** Permite gerar tokens e arquivos convertidos com o prefixo `SiriusLora` (ex: `SiriusLora727`), incluindo botão rápido **"Todos LoRa"** para alteração em lote.
* **Filtro para arquivos `default_`:** Detecção automática de arquivos sem número de série no nome (como `default_...`), acionando alerta visual obrigatório no campo de série.

#### Corrigido
* **Tratamento de erro crítico de Token (`HTTP 401/404`):** O motor de injeção agora levanta exceção visual na tabela (status vermelho de erro) quando o servidor recusa o token, preservando checkpoints anteriores e evitando a criação desnecessária de arquivos `_FALHAS.csv` por erro de configuração.
* **Leitura de CSV com delimitador extra:** Adicionado `index_col=False` no Pandas para evitar deslocamento de colunas em arquivos do datalogger Sirius que possuem `;` no final de cada linha.

---

### [v1.2.0] - 2026-10-28
#### Adicionado
* **Dashboard Enterprise UI:** Novo layout com barra superior compacta de conexão, 4 cards de KPIs em tempo real (Arquivos, Volume de Linhas, Velocidade EPS e Tempo Estimado ETA), tabela expansível com efeito Zebra e terminal colorido por semântica.
* **Reprocessador Nativo de Falhas (`DLQ`):** Suporte direto para leitura e reenvio de arquivos `_FALHAS.csv`.
* **Teste de Conexão e Ações em Lote:** Botão para testar disponibilidade do servidor antes do envio, auto-preenchimento inteligente de Nº de Série via Regex e botões para troca de rede em massa (**Todos WiFi** / **Todos NB-IoT**).

#### Corrigido
* **Cabeçalho do CSV Convertido:** Remoção da coluna interna `ts` ao salvar o arquivo `.csv` convertido, garantindo 100% de compatibilidade estrutural com o padrão Andrômeda.
* **Performance e Estabilidade no ETL:** Substituição de `iterrows()` por `to_dict('records')` (ganho de até 15x em velocidade), execução do ETL em thread separada para não congelar a interface, proteção contra datas inválidas (`NaT`) e preservação de valores vazios de bateria sem forçar `0.000`.

---

### [v1.0.0] - Versão Inicial
* Lançamento inicial do Telix Sync com suporte a arquivos Andrômeda e Telix, motor de envio assíncrono com controle adaptativo de velocidade (Adaptive EPS), sistema de checkpoints e geração de relatórios em `/logs`.