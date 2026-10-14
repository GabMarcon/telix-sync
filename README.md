# Telix Sync

O **Telix Sync** é uma ferramenta desktop desenvolvida pela Auro Tecnologia para a injeção em massa na plataforma Telix. O software processa arquivos brutos originados do concentrador Andrômeda e Telix e os insere via HTTP assíncrono.

## Funcionalidades Principais

* **Detecção e ETL Automáticos:** Reconhecimento automático se o arquivo CSV tem origem Andrômeda ou Telix, aplicando as regras de Extração, Transformação e Carga (ETL) corretas e corrigindo nativamente o fuso horário (America/Sao_Paulo) para o Epoch (ts).
* **Marcha Adaptativa (Adaptive EPS):** Um motor inteligente de injeção que calibra a velocidade (Requisições por Segundo) com base no congestionamento e tempo de resposta da *Rule Chain* do servidor.
* **Resiliência e Checkpoints:** Acompanha o processamento linha a linha. Se o processo for interrompido, fechado ou cancelado, ele retoma exatamente de onde parou no próximo início.
* **Dead-Letter Queue (DLQ):** Telemetrias corrompidas ou recusadas pelo ThingsBoard (ex: falha de conversão, timeouts excessivos) não travam o lote. Elas são puladas e salvas num arquivo `_FALHAS.csv` para auditoria.
* **Fila de Processamento Acumulativa:** Adicione múltiplos arquivos de diretórios diferentes. O sistema protege contra arquivos duplicados e permite a remoção individual (lixeira) ou limpeza total da fila.
* **Dry Run (Pré-visualização):** Um validador visual do Payload. Permite visualizar como o JSON final será enviado ao servidor antes de iniciar a sincronização.
* **Proteção contra Bloqueios (Anti-Excel):** Intercepta de forma amigável arquivos que estejam abertos/bloqueados por outros processos (como o Microsoft Excel), evitando a quebra (Crash) do sistema.

---

## Como Usar (Guia do Usuário)

O Telix Sync foi projetado para ser executado como uma aplicação *Standalone* (arquivo único `.exe`), sem necessidade de instalação.

### Passo 1: Configuração de Conexão
1. Abra o aplicativo `TelixSync.exe`.
2. Em **Configurações de Conexão**, selecione o tipo de servidor alvo.
   * **Nuvem:** Insira o subdomínio do cliente (ex: para *site_cliente.telix.com.br*, digite apenas `site_cliente`).
   * **Servidor Interno (IP):** Insira o endereço IP local (ex: `192.168.0.90`).

### Passo 2: Preparar a Fila de Arquivos
1. Clique no botão **Adicionar Arquivos** e selecione um ou múltiplos arquivos `.csv`.
2. **Para arquivos Telix:** Selecione o tipo de Rede (WiFi ou NB-IoT) e digite obrigatoriamente o **Série** (número de série do equipamento) no campo indicado na tabela.
3. **Para arquivos Andrômeda:** O sistema resolve tudo de forma automática.
4. *(Opcional)* Clique no ícone de lupa azul (Pré-visualizar) para garantir que a extração de dados está correta.

### Passo 3: Iniciar Sincronização
1. Clique em **Iniciar Sincronização em Massa**.
2. A barra de progresso inferior e o terminal mostrarão o status em tempo real.
3. Se precisar parar, clique em **Cancelar Sincronização**. O sistema fará uma parada segura, salvando o progresso atual.
4. Ao final, um pop-up avisará sobre a conclusão e um botão permitirá abrir diretamente a pasta de relatórios.

---

## Como Compilar (Guia para Desenvolvedores)

Se realizar alterações no código-fonte Python (`.py`), você precisará gerar um novo executável.
O projeto utiliza o Flet e o PyInstaller para empacotamento.

**Pré-requisitos:**
Garanta que seu ambiente virtual (`venv`) está ativo e que as bibliotecas necessárias (Pillow, pandas, aiohttp, flet) estão instaladas.

**Comando de Build:**
Rode o comando abaixo no terminal, na raiz do projeto, para gerar o novo arquivo compilado na pasta `dist/`:

```bash
flet pack main.py --name "TelixSync" --icon "assets\logo.png" --add-data "assets;assets"