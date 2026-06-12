# Guia de Instalação - Leitor de Canhotos

Este guia explica como instalar e configurar o sistema **Leitor de Canhotos** no Windows usando Docker Desktop.

---

## Pré-requisitos

- Windows 10/11 (64-bit)
- Docker Desktop para Windows instalado e em execução
- A pasta `M:\Nota_Fiscal\NF` deve existir no host Windows
- Git (opcional, para clonar o repositório)

---

## Passo 1 — Instalar Docker Desktop no Windows

1. Acesse: https://docs.docker.com/desktop/install/windows-install/
2. Baixe o instalador "Docker Desktop Installer.exe"
3. Execute o instalador e siga as instruções na tela
4. Reinicie o computador quando solicitado
5. Inicie o Docker Desktop e aguarde o ícone da baleia na bandeja do sistema ficar estável
6. Verifique a instalação: abra o PowerShell e execute:
   ```
   docker --version
   docker compose version
   ```

---

## Passo 2 — Clonar ou copiar o projeto

```powershell
# Opção A: clonar com Git
git clone <url-do-repositorio> leitor_canhotos
cd leitor_canhotos

# Opção B: extrair o ZIP do projeto em uma pasta e entrar nela
cd C:\caminho\para\leitor_canhotos
```

---

## Passo 3 — Configurar variáveis de ambiente

```powershell
# Copie o arquivo de exemplo
copy .env.example .env
```

Abra `.env` em um editor de texto e ajuste os valores conforme necessário.
Para desenvolvimento local, os valores padrão já funcionam.

---

## Passo 4 — Configurar o mapeamento da pasta do scanner

O arquivo `docker-compose.yml` mapeia `M:\Nota_Fiscal\NF` para `/entrada_canhotos` dentro do container.

Verifique as linhas do volume na seção `volumes:` no final do `docker-compose.yml`:

```yaml
entrada_canhotos:
  driver: local
  driver_opts:
    type: none
    o: bind
    device: /mnt/m/Nota_Fiscal/NF   # <- ajuste se necessário
processados:
  driver: local
  driver_opts:
    type: none
    o: bind
    device: /mnt/m/Nota_Fiscal/processados
erro:
  driver: local
  driver_opts:
    type: none
    o: bind
    device: /mnt/m/Nota_Fiscal/erro
```

**Nota para Windows com WSL2**: o caminho `M:\` é acessado pelo Docker via `/mnt/m/` no WSL2.
Certifique-se de que a pasta existe: crie `M:\Nota_Fiscal\NF`, `M:\Nota_Fiscal\processados` e
`M:\Nota_Fiscal\erro` no Windows Explorer antes de continuar.

---

## Passo 5 — Build das imagens Docker

```powershell
docker compose build
```

Este processo pode demorar alguns minutos na primeira vez, pois fará o download da imagem
Python e instalará o Tesseract OCR, Poppler e todas as dependências Python.

---

## Passo 6 — Iniciar banco de dados e Redis primeiro

```powershell
docker compose up -d db redis
```

Aguarde os serviços ficarem saudáveis:

```powershell
docker compose ps
```

O campo `STATUS` deve mostrar `healthy` para `db` e `redis` antes de continuar.
Se necessário, aguarde 15-30 segundos e repita o comando.

---

## Passo 7 — Iniciar todos os serviços

```powershell
docker compose up -d
```

---

## Passo 8 — Criar as tabelas do banco de dados

```powershell
docker compose exec web python manage.py migrate
```

---

## Passo 9 — Coletar arquivos estáticos

```powershell
docker compose exec web python manage.py collectstatic --noinput
```

---

## Passo 10 — Criar superusuário para o Django Admin

```powershell
docker compose exec web python manage.py createsuperuser
```

Siga as instruções interativas para definir nome de usuário, e-mail e senha.

---

## Passo 11 — Acessar o sistema

| URL | Descrição |
|-----|-----------|
| http://localhost:8000 | Interface principal |
| http://localhost:8000/notas/ | Lista de Notas Fiscais |
| http://localhost:8000/canhotos/ | Lista de Canhotos |
| http://localhost:8000/admin/ | Painel administrativo Django |

---

## Comandos úteis do dia a dia

```powershell
# Ver logs em tempo real de todos os serviços
docker compose logs -f

# Ver logs apenas do web (Django)
docker compose logs -f web

# Ver logs do worker Celery
docker compose logs -f celery

# Ver logs do monitor de arquivos
docker compose logs -f monitor

# Reiniciar todos os serviços
docker compose restart

# Reiniciar apenas o web
docker compose restart web

# Abrir shell Django (manage.py shell)
docker compose exec web python manage.py shell

# Ver status de todos os serviços
docker compose ps

# Parar todos os serviços
docker compose down

# Parar e remover volumes (CUIDADO: apaga o banco de dados!)
docker compose down -v
```

---

## Resolução de problemas

### Erro: porta 8000 já está em uso

Algum outro serviço está usando a porta 8000. Altere o mapeamento de portas no `docker-compose.yml`:

```yaml
ports:
  - "8080:8000"  # troque 8000 pelo número desejado
```

### Erro: Cannot connect to database

1. Verifique se o serviço `db` está saudável: `docker compose ps`
2. Aguarde mais alguns segundos e tente novamente
3. Verifique os logs: `docker compose logs db`

### Tesseract: TesseractNotFoundError

O Tesseract é instalado automaticamente na imagem Docker. Se este erro aparecer fora do Docker
(executando localmente), instale o Tesseract manualmente:

- Windows: https://github.com/UB-Mannheim/tesseract/wiki
- Após instalar, adicione o caminho ao `PATH` do sistema ou defina a variável:
  ```python
  pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
  ```

### Pasta M:\ não mapeada corretamente no Docker

No Windows com WSL2, as unidades de rede mapeadas (como `M:\`) nem sempre ficam automaticamente
disponíveis no WSL2. Soluções:

1. **Usar pasta local**: mova os arquivos para `C:\Nota_Fiscal\NF` e ajuste o `device` no `docker-compose.yml` para `/mnt/c/Nota_Fiscal/NF`
2. **Montar a unidade no WSL2**: no terminal WSL2, execute:
   ```bash
   sudo mkdir -p /mnt/m
   sudo mount -t drvfs M: /mnt/m
   ```
3. **Usar volume nomeado**: se não precisar acessar os arquivos diretamente no Windows, remova o driver_opts e use um volume Docker simples.

### Erros de permissão nos volumes

No Linux/Mac, ajuste as permissões das pastas mapeadas:

```bash
chmod -R 755 /mnt/m/Nota_Fiscal/
```

### Imagem não está sendo processada mesmo após cópia na pasta

1. Verifique se o serviço `monitor` está em execução: `docker compose ps monitor`
2. Veja os logs: `docker compose logs -f monitor`
3. Confirme que a extensão do arquivo é suportada: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.tiff`, `.tif`
4. Certifique-se de que o arquivo terminou de ser copiado antes de o monitor detectá-lo (o monitor aguarda 2 segundos automaticamente, mas arquivos muito grandes em redes lentas podem precisar mais tempo)

---

## Estrutura de pastas do scanner

```
M:\Nota_Fiscal\
├── NF\            <- coloque os PDFs escaneados aqui (entrada)
├── processados\   <- arquivos processados com sucesso vão para cá
└── erro\          <- arquivos que falharam no OCR vão para cá
```
