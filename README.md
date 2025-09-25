# E-Paper Calendar Display

Sistema de exibição de calendário e tarefas do Google em display e-paper Waveshare 2.13" para Raspberry Pi.

<img width="250" height="122" alt="out" src="https://github.com/user-attachments/assets/20d3dba2-1164-4416-9584-f250cbf08806" />

## Características

- **Display e-paper**: Waveshare 2.13" V2 (250x122 pixels)
- **Integração Google**: Calendar e Tasks API
- **Layout otimizado**: Eventos à esquerda, calendário e hora à direita
- **🎨 NOVO: Imagens AI**: Pixel art gerada por IA em dias sem eventos
- **Atualizações inteligentes**: Renderização completa inicial, atualizações parciais periódicas
- **Paginação**: Eventos exibidos em grupos de 3, com rotação automática
- **Autenticação flexível**: Suporte para ambiente GUI e headless
- **Configuração**: Arquivo `.env` para fácil customização

## Nova Funcionalidade: Imagens AI

Quando não há eventos para o dia atual, o sistema pode gerar automaticamente uma imagem pixel art usando a API do OpenAI DALL-E. As imagens são:

- **Otimizadas para e-paper**: Preto e branco, baixa resolução (96x110 pixels)
- **Tema diário**: Diferentes temas rotativos (casa, gato, árvore, café, etc.)
- **Cache inteligente**: Uma imagem por dia, armazenada localmente
- **Fallback gracioso**: Se a API falhar, exibe a mensagem tradicional "Dia livre"

## Estrutura do Projeto

```
├── main.py                 # Código principal
├── config.py              # Gerenciamento de configuração
├── google_service.py      # Integração com Google APIs
├── image_renderer.py      # Renderização de imagens
├── display_controller.py  # Controle do display e-paper
├── ai_image_service.py    # 🆕 Geração de imagens AI
├── logger_setup.py        # Configuração de logging
├── .env                   # Arquivo de configuração
├── requirements.txt       # Dependências Python
└── README.md             # Esta documentação
```

## Instalação

### 1. Dependências do Sistema

```bash
# Atualizar sistema
sudo apt update && sudo apt upgrade -y

# Instalar dependências básicas
sudo apt install python3-pip python3-venv git -y

# Habilitar SPI (necessário para e-paper)
sudo raspi-config
# Interfacing Options > SPI > Enable
```

### 2. Biblioteca Waveshare

```bash
# Clonar repositório Waveshare
cd /home/pi
git clone https://github.com/waveshare/e-Paper.git

# Instalar dependências da biblioteca
cd e-Paper/RaspberryPi_JetsonNano/python
sudo pip3 install ./
```

### 3. Projeto

```bash
# Clonar/copiar arquivos do projeto
mkdir -p /home/pi/e-paper-calendar
cd /home/pi/e-paper-calendar

# Criar ambiente virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependências
pip install -r requirements.txt
```

### 4. Configuração Google API

1. Acesse o [Google Cloud Console](https://console.cloud.google.com)
2. Crie um novo projeto ou selecione existente
3. Habilite as APIs:
   - Google Calendar API
   - Google Tasks API
4. Crie credenciais (OAuth 2.0 Client ID) para "Desktop Application"
5. Baixe o arquivo JSON e renomeie para `credentials_raspberry-pi.json`
6. Coloque o arquivo na raiz do projeto

### 5. 🆕 Configuração OpenAI (Opcional)

Para habilitar as imagens AI:

1. Crie uma conta em [OpenAI Platform](https://platform.openai.com)
2. Gere uma API key em [API Keys](https://platform.openai.com/api-keys)
3. Adicione a chave no arquivo `.env`:
   ```bash
   OPENAI_API_KEY=your_openai_api_key_here
   ```

**Custos**: DALL-E 3 custa ~$0.040 por imagem. Com cache diário, são ~$1.20/mês.

## Configuração

### Arquivo `.env`

Copie o arquivo `.env.example` e ajuste conforme necessário:

```bash
cp .env.example .env
nano .env
```

### Principais configurações:

- **Display**: Dimensões, rotação, intervalos de atualização
- **Eventos**: Número máximo, itens por página
- **🆕 AI Images**: Habilitação, cache, dimensões
- **🆕 OpenAI**: Chave da API
- **Fontes**: Caminhos e tamanhos
- **Google API**: Arquivos de credenciais, porta OAuth
- **Logging**: Diretório, retenção, nível

### Configurações de Imagens AI:

```bash
# Habilitar/desabilitar imagens AI
AI_IMAGES_ENABLED=true

# Dias de cache das imagens
AI_IMAGE_CACHE_DAYS=7

# Dimensões das imagens (ajustado para o frame)
AI_IMAGE_WIDTH=96
AI_IMAGE_HEIGHT=110

# Temas personalizáveis (separados por vírgula)
AI_IMAGE_THEMES=um gato pixel art,uma casa pixel art,uma árvore pixel art
```

## Uso

### Teste (geração de PNG)

```bash
# Ativar ambiente virtual
source venv/bin/activate

# Gerar imagem de teste
python3 main.py --dry-run teste.png
```

### Execução normal

```bash
# Ativar ambiente virtual
source venv/bin/activate

# Executar (primeira vez fará autenticação)
python3 main.py
```

### Primeira autenticação

**GUI disponível**: O navegador abrirá automaticamente para autenticação.

**Headless (SSH)**:
1. Execute o comando mostrado no log para criar túnel SSH
2. Acesse `http://localhost:54545` no seu computador
3. Complete a autenticação

## Execução Automática

### Systemd Service

Crie `/etc/systemd/system/e-paper-calendar.service`:

```ini
[Unit]
Description=E-Paper Calendar Display
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/e-paper-calendar
Environment=PATH=/home/pi/e-paper-calendar/venv/bin
ExecStart=/home/pi/e-paper-calendar/venv/bin/python main.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
# Habilitar e iniciar serviço
sudo systemctl enable e-paper-calendar
sudo systemctl start e-paper-calendar

# Verificar status
sudo systemctl status e-paper-calendar

# Ver logs
journalctl -u e-paper-calendar -f
```

## Personalização

### Layout

- Modifique `image_renderer.py` para alterar layout
- Ajuste dimensões dos painéis em `.env`
- Personalize mensagens e emojis

### Imagens AI

- **Temas**: Configure os temas no arquivo `.env` na variável `AI_IMAGE_THEMES`
- **Formato**: Separe os temas por vírgula
- **Exemplo**: `AI_IMAGE_THEMES=um gato pixel art,uma casa pixel art,uma árvore pixel art`
- **Prompts**: Cada tema é automaticamente processado com "8-bit", "muito simples", "minimalista", "fundo branco limpo"
- **Cache**: Configure `AI_IMAGE_CACHE_DAYS` para retenção
- **Fallback**: Sistema automaticamente volta para "Dia livre" se API falhar

### Fontes

- Configure caminhos das fontes em `.env`
- Ajuste tamanhos para diferentes densidades de texto
- Suporte completo a fontes TrueType

### Atualização

- `UPDATE_INTERVAL`: Frequência de atualização (segundos)
- `EVENTS_PER_PAGE`: Número de eventos por página
- `ROTATE_DISPLAY`: Rotação do display se necessário

## Logs

- Localização: `logs/epaper.log`
- Rotação: Diária com compressão
- Retenção: 7 dias (configurável)
- Níveis: INFO, WARNING, ERROR

## Solução de Problemas

### Display não funciona
- Verificar conexão SPI
- Confirmar biblioteca Waveshare instalada
- Checar permissões GPIO

### Erro de autenticação
- Verificar arquivo credentials.json
- Recriar token: `rm token.json`
- Confirmar APIs habilitadas no Google Console

### 🆕 Problemas com imagens AI
- **API Key inválida**: Verificar `OPENAI_API_KEY` no `.env`
- **Quota excedida**: Verificar limites de billing na OpenAI
- **Cache corrompido**: Limpar pasta `image_cache/`
- **Sem internet**: Sistema volta automaticamente para "Dia livre"

### Problemas de fonte
- Verificar caminhos das fontes em `.env`
- Instalar fontes DejaVu se necessário: `sudo apt install fonts-dejavu`

### Erro de importação
- Confirmar ambiente virtual ativo
- Reinstalar dependências: `pip install -r requirements.txt`

## Gerenciamento de Cache

O sistema mantém um cache local das imagens geradas:

```bash
# Limpar cache manualmente
rm -rf image_cache/

# Verificar tamanho do cache
du -sh image_cache/
```

O cache é limpo automaticamente após o número de dias configurado em `AI_IMAGE_CACHE_DAYS`.

## Contribuição

1. Fork do projeto
2. Crie branch para feature (`git checkout -b feature/nova-funcionalidade`)
3. Commit das mudanças (`git commit -am 'Adiciona nova funcionalidade'`)
4. Push para branch (`git push origin feature/nova-funcionalidade`)
5. Abra Pull Request

## Licença

MIT License - veja arquivo LICENSE para detalhes.

## Créditos

- [Waveshare](https://www.waveshare.com/) - Hardware e biblioteca e-paper
- [Google APIs](https://developers.google.com/) - Calendar e Tasks integration
- [OpenAI](https://openai.com/) - DALL-E API para geração de imagens
- Projeto baseado no código original de calendário e-paper