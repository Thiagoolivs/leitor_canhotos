# Leitor de Canhotos

Sistema web para automatizar a leitura e conciliação de canhotos de notas fiscais escaneados. O que antes exigia 12 a 24 horas de trabalho manual organizando centenas de folhas agora é feito em cerca de 1 hora — com conferência apenas dos casos que o sistema não conseguiu resolver sozinho.

---

## O que o sistema faz

1. **Monitora pastas do scanner** — detecta automaticamente novos arquivos PDF assim que chegam da impressora/scanner.
2. **Lê o número da NF** — usa OCR (Tesseract), leitura de código de barras e, como fallback, inteligência artificial (Groq/Llama) para extrair o número da nota fiscal.
3. **Concilia com as notas cadastradas** — encontra a nota fiscal correspondente e marca o canhoto como recebido.
4. **Separa o que precisa de atenção humana** — canhotos que o sistema não conseguiu identificar vão para a fila de **Revisão**, onde o operador insere o número manualmente e o sistema finaliza a vinculação.

---

## Principais funcionalidades

- Processamento multi-página: PDFs com vários canhotos são divididos e processados individualmente
- Suporte a folhas divisórias (uma folha que cobre várias notas de uma vez)
- Múltiplas pastas de entrada (filiais diferentes)
- Dashboard com alertas de notas aguardando há mais de 1 mês
- Fila de revisão separada por tipo (canhotos individuais vs. divisórias)
- IA como fallback para leituras com baixa confiança
- Reprocessamento manual com um clique

---

## Tecnologias

| Camada | Tecnologia |
|---|---|
| Backend | Django 4.2 + PostgreSQL |
| Filas | Celery + Redis |
| OCR | Tesseract + pdfplumber |
| Barcode | zxing-cpp + pyzbar |
| IA (opcional) | Groq API (Llama 3.3) |
| Frontend | Bootstrap 5 |
| Deploy | Docker + Docker Compose |

---

## Instalação rápida (Docker)

**Pré-requisitos:** Docker Desktop instalado e rodando.

**1. Clone o repositório e crie o arquivo de configuração:**

```bash
git clone https://github.com/Thiagoolivs/leitor_canhotos.git
cd leitor_canhotos
cp .env.example .env
```

**2. Edite o `.env`** e configure pelo menos:

```env
# Pasta onde o scanner salva os canhotos (caminho no seu computador)
SCANNER_HOST_DIR_1=C:\Scans\Canhotos

# Chave secreta Django (troque por qualquer string longa aleatória)
SECRET_KEY=sua-chave-secreta-aqui
```

**3. Suba os serviços:**

```bash
docker-compose up -d
```

**4. Inicialize o banco de dados:**

```bash
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py createsuperuser
```

**5. Acesse:** `http://localhost:8000`

---

## Configuração do `.env`

| Variável | Descrição | Padrão |
|---|---|---|
| `SCANNER_HOST_DIR_1` | Pasta principal do scanner no host | `M:\Nota_Fiscal\NF` |
| `SCANNER_HOST_DIR_2` | Segunda pasta (filial) — opcional | — |
| `SECRET_KEY` | Chave secreta Django | (dev insegura) |
| `DEBUG` | Modo debug | `False` |
| `GROQ_API_KEY` | API key do Groq para IA (opcional) | — |
| `GROQ_API_KEY_2` | Segunda chave Groq (rotação) | — |
| `AI_FALLBACK_HABILITADO` | Liga/desliga a IA | `True` |
| `AUTO_VINCULAR_ALTA_CONFIANCA` | Vincula automaticamente canhotos de alta confiança | `True` |

Para instalação em Windows sem Docker, consulte [`INSTALACAO_WINDOWS_NATIVO.md`](INSTALACAO_WINDOWS_NATIVO.md).

---

## Fluxo de uso diário

```
Scanner salva PDFs na pasta
        ↓
Sistema lê e tenta identificar a NF automaticamente
        ↓
    ┌── Alta/Média confiança → vincula sozinho (SUCESSO)
    ├── Baixa confiança → IA tenta extrair → vincula ou vai para Revisão
    └── Falha total → vai para Erros (reprocessar ou corrigir manualmente)
```

**Na interface web:**

- **Início** — visão geral e alertas de ação prioritária
- **Notas Fiscais** — lista de todas as NFs cadastradas e seus status
- **Canhotos** — todos os canhotos escaneados com filtros
- **Revisar** — canhotos que precisam de atenção manual (insira o número e o sistema vincula)
- **Erros** — falhas de leitura (reprocesse automaticamente ou abra para corrigir)

---

## Comandos úteis

```bash
# Reprocessar uma pasta de canhotos existente
docker-compose exec web python manage.py processar_pasta --tipo canhoto

# Rodar IA em todos os canhotos em Revisão
docker-compose exec web python manage.py revisar_com_ia --limite 50

# Ver o que seria corrigido sem alterar nada
docker-compose exec web python manage.py corrigir_revisao_indevida --dry-run
```

---

## Licença

Uso interno. Todos os direitos reservados.
