# Telix Sync (v1.2.0)

O **Telix Sync** é uma ferramenta desktop desenvolvida pela Auro Tecnologia para a injeção e ressincronização de telemetria em massa na plataforma Telix (ThingsBoard)[cite: 1]. O software processa arquivos brutos originados do concentrador Andrômeda, planilhas exportadas da plataforma Telix e relatórios de falhas (DLQ), inserindo os dados via HTTP assíncrono de alta performance[cite: 1].

## Funcionalidades Principais

* **Detecção e ETL Automáticos (3 Fontes):** Reconhecimento automático se o arquivo tem origem **Andrômeda**, **Telix** ou **Falhas (DLQ)**[cite: 1]. Para arquivos do Telix, aplica as regras de Extração, Transformação e Carga (ETL) gerando um arquivo `.csv` convertido estruturalmente idêntico ao padrão do concentrador Andrômeda e corrigindo nativamente o fuso horário (`America/Sao_Paulo`) para Epoch (`ts`)[cite: 1].
* **Identificação Inteligente de Série:** Extrai automaticamente o número de série do nome do arquivo quando segue o padrão `SiriusXXX`. Para equipamentos com nomenclatura personalizada (ex: `DL-12`), destaca visualmente o campo em âmbar para preenchimento seguro pelo analista.
* **Reprocessamento Nativo de DLQ (`_FALHAS.csv`):** Telemetrias recusadas pelo servidor por oscilação de rede são salvas em um arquivo `_FALHAS.csv` com o JSON íntegro[cite: 1]. Basta adicionar esse arquivo novamente à fila para reenviar apenas os pacotes pendentes, sem necessidade de refazer o ETL.
* **Validador de Conexão e Proteção de Token:** Botão dedicado para testar a conectividade com o servidor (Nuvem ou IP Local) antes de iniciar o lote[cite: 1]. Caso o servidor recuse o Token do equipamento (`HTTP 401/404`), o sistema aborta o arquivo imediatamente para evitar envios desnecessários.
* **Marcha Adaptativa (Adaptive EPS) e Painel de KPIs:** Motor inteligente que calibra a velocidade (`Requisições por Segundo`) com base na saúde da *Rule Chain* do servidor[cite: 1], exibindo em tempo real cards de indicadores com arquivos concluídos, volume de linhas, velocidade instantânea (`EPS`) e estimativa de tempo restante (`ETA`).
* **Ações em Lote na Fila:** Botões rápidos (**Todos WiFi** e **Todos NB-IoT**) para alterar o tipo de comunicação de múltiplos arquivos simultaneamente, além de proteção contra arquivos duplicados[cite: 1].
* **Resiliência e Checkpoints:** Acompanha o processamento linha a linha e salva o progresso em `.telix_checkpoints.json`[cite: 1]. Se o processo for interrompido ou pausado manualmente, retoma exatamente de onde parou no próximo início[cite: 1].
* **Dry Run (Pré-visualização JSON) e Terminal Semântico:** Validador visual das 3 primeiras linhas do Payload JSON antes do envio e terminal de diagnóstico colorido por criticidade (Sucesso, Aviso, Erro)[cite: 1].
* **Proteção contra Bloqueios (Anti-Excel):** Intercepta de forma amigável arquivos que estejam abertos/bloqueados no Microsoft Excel, evitando travamentos[cite: 1].

---

## Como Usar (Guia do Suporte)

O Telix Sync foi projetado para ser executado como uma aplicação *Standalone* (arquivo único `.exe`), sem necessidade de instalação[cite: 1].

### Passo 1: Configuração e Teste de Conexão
1. Abra o aplicativo `TelixSync.exe`[cite: 1].
2. Na barra superior **Servidor Alvo**, selecione o ambiente[cite: 1]:
   * **Nuvem (Cliente):** Insira apenas o subdomínio do cliente (ex: para *minasgerais.telix.com.br*, digite `minasgerais`)[cite: 1].
   * **Servidor IP:** Insira o endereço IP local (ex: `192.168.0.90`)[cite: 1].
3. Clique em **Testar Servidor** para confirmar que o ambiente está online (`✅ Online`).

### Passo 2: Preparar a Fila de Processamento
1. Clique em **Adicionar Arquivos** e selecione um ou múltiplos arquivos `.csv` ou `.txt`[cite: 1].
2. **Arquivos Andrômeda:** O sistema extrai o token (ex: `SiriusLora340`) e configura tudo automaticamente[cite: 1].
3. **Arquivos Telix ou Falhas (DLQ):**
   * Defina a **Rede** (`WiFi` para token `SiriusXXX` ou `NB-IoT` para token `00XXX`) individualmente ou use os botões **Todos WiFi** / **Todos NB-IoT** no topo da tabela[cite: 1].
   * Confira o **Nº de Série** preenchido automaticamente (ou digite manualmente nos campos destacados em amarelo para equipamentos com nomes customizados)[cite: 1].
4. *(Opcional)* Clique no ícone de lupa na coluna **JSON** para pré-visualizar os pacotes antes do envio[cite: 1].

### Passo 3: Iniciar Sincronização
1. Clique em **Iniciar Sincronização em Massa**[cite: 1].
2. Acompanhe o andamento pelos **Cards de KPIs** no topo (Velocidade e ETA), pela barra de progresso e pelo **Terminal de Execução**[cite: 1].
3. Caso precise interromper o envio, clique em **Parada Segura (Salvar Checkpoint)**[cite: 1].
4. Ao finalizar, consulte os relatórios detalhados na pasta `/logs` clicando em **Abrir Pasta de Relatórios**[cite: 1].

---

## Como Compilar (Guia para Desenvolvedores)

Se realizar alterações no código-fonte Python (`.py`), você precisará gerar um novo executável[cite: 1]. O projeto utiliza o **Flet** e o **PyInstaller** para empacotamento[cite: 1].

**Pré-requisitos:**
Garanta que seu ambiente virtual (`venv`) está ativo e que as dependências do arquivo `requirements.txt` (`flet`, `pandas`, `aiohttp`, `python-dotenv`) estão instaladas[cite: 1].

**Comando de Build:**
Execute o comando abaixo no terminal, na raiz do projeto, para gerar o executável atualizado na pasta `dist/`[cite: 1]:

```bash
flet pack main.py --name "TelixSync" --icon "assets\logo.png" --add-data "assets;assets"