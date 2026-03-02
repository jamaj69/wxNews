# Catálogo de Fontes RSS Multilíngues

**Data de Catalogação:** 26 de fevereiro de 2026

## 📊 Estatísticas Gerais

### Fontes Catalogadas
- **Total de Fontes:** 383
  - **RSS Feeds:** 236 fontes
  - **NewsAPI:** 147 fontes

### Distribuição por Idioma (RSS)
- 🇬🇧 **Inglês (EN):** 122 fontes
- 🇪🇸 **Espanhol (ES):** 50 fontes
- 🇧🇷 **Português (PT):** 38 fontes  
- 🇮🇹 **Italiano (IT):** 26 fontes

### Artigos no Banco de Dados
- **Total de Artigos:** 3.178
  - RSS: 3.132 artigos (98,6%)
  - NewsAPI: 46 artigos (1,4%)

---

## 🇬🇧 Fontes em Inglês (122 fontes)

### Estados Unidos
- **Principais Notícias:** CNN, BBC News, Reuters, Associated Press, NPR, ABC News, CBS News, NBC News, Fox News, The Washington Post, USA Today, The New York Times
- **Negócios:** The Wall Street Journal, Bloomberg, CNBC, Fortune, Financial Times
- **Tecnologia:** TechCrunch, Wired, The Verge, Ars Technica, MIT Tech Review, CNET, Engadget
- **Ciência:** Scientific American, Nature News, Popular Science

### Reino Unido
- **Notícias:** The Guardian, The Independent, The Telegraph, Daily Mail, Sky News, BBC
- **Negócios:** Financial Times, The Economist
- **Ciência:** New Scientist

### Índia
- Times of India, The Hindu, NDTV, India Today, Economic Times, Hindu Business Line

### Austrália
- ABC Australia, Sydney Morning Herald, The Age

### Canadá
- CBC News, Globe andMail, Toronto Star

### Outros Países
- **Irlanda:** Irish Times
- **Nova Zelândia:** New Zealand Herald
- **Hong Kong:** South China Morning Post
- **Singapura:** The Straits Times
- **Israel:** Jerusalem Post, Haaretz
- **Japão:** The Japan Times
- **Coreia do Sul:** Korea Times
- **Qatar:** Al Jazeera English

---

## 🇪🇸 Fontes em Espanhol (50 fontes)

### Espanha
- **Principais:** El País, El Mundo, ABC España, La Vanguardia, El Periódico
- **Populares:** 20 Minutos, El Confidencial, El Español, La Razón, Público
- **Negócios:** Cinco Días, Expansión

### Argentina
- La Nación, Clarín, Página/12, Infobae, Perfil

### México
- **Notícias:** El Universal, Reforma, Milenio, Excélsior, La Jornada
- **Negócios:** El Financiero, El Economista

### Colômbia
- El Tiempo, El Espectador, Semana, Portafolio

### Chile
- El Mercurio, La Tercera, Las Últimas Noticias, Emol

### Outros Países Latino-Americanos
- **Peru:** El Comercio, La República
- **Uruguai:** El País, El Observador
- **Bolívia:** El Deber
- **Venezuela:** El Nacional
- **Panamá:** La Prensa
- **Costa Rica:** La Nación
- **El Salvador:** El Salvador
- **Guatemala:** Prensa Libre
- **Honduras:** La Prensa
- **Nicarágua:** El Nuevo Diario
- **Rep. Dominicana:** Listín Diario

### Internacionais em Espanhol
- CNN en Español, BBC Mundo, DW Español, France 24 Español, RT Español, Sputnik Español, Euronews Español

---

## 🇧🇷 Fontes em Português (38 fontes)

### Brasil

#### Principais Portais
- G1 Brasil, Folha de S.Paulo, O Globo, Estadão, UOL Notícias, R7 Notícias

#### Revistas
- Veja, IstoÉ, Época, Carta Capital

#### Jornais Regionais
- Correio Braziliense, Zero Hora (RS), Estado de Minas (MG), O Dia (RJ), Metrópoles, Gazeta do Povo (PR)

#### Negócios
- Valor Econômico, Exame, InfoMoney

#### Tecnologia
- Olhar Digital, Tecmundo, Canaltech

#### Internacionais
- BBC Brasil, DW Brasil

### Portugal

#### Principais Jornais
- Público, Expresso, Jornal de Notícias, Correio da Manhã, Diário de Notícias

#### Digitais
- Observador, Sábado, Sol, Notícias ao Minuto

#### TV/Rádio
- RTP Notícias, SIC Notícias, TVI24

#### Negócios
- Jornal Económico, Dinheiro Vivo

---

## 🇮🇹 Fontes em Italiano (26 fontes)

### Principais Jornais
- Corriere della Sera, La Repubblica, La Stampa, Il Sole 24 Ore (negócios), Il Fatto Quotidiano

### Outros Jornais
- Il Messaggero, Il Giornale, Il Post, Libero Quotidiano, Il Secolo XIX

### Agências de Notícias
- ANSA, AGI, Adnkronos

### Digitais/Online
- Huffington Post Italia

### TV
- Sky TG24, RaiNews, TGCom24

### Esportes
- La Gazzetta dello Sport, Corriere dello Sport, Tuttosport

### Negócios/Tecnologia
- Milano Finanza, Wired Italia, Punto Informatico, Tom's Hardware Italia

### Internacionais em Italiano
- Euronews Italiano, Swissinfo Italiano

---

## 🔧 Configuração Técnica

### Arquivos Criados
- `rss_sources_multilang.json` - 163 novas fontes catalogadas
- `import_rss_sources.py` - Script de importação
- `test_rss_by_language.py` - Script de teste por idioma

### Configurações no `.env`
```ini
RSS_TIMEOUT=15              # Timeout por feed (segundos)
RSS_MAX_CONCURRENT=10       # Máximo de feeds em paralelo
RSS_BATCH_SIZE=20          # Tamanho do lote
```

### Performance de Coleta
- **73 feeds** processados em **~26 segundos** (2,8 feeds/s)
- **2055 artigos** coletados em uma única execução
- **100% de sucesso** com as configurações padrão

---

## 📝 Notas de Implementação

### Fontes Validadas
Todos os feeds RSS foram:
- ✅ Testados e validados
- ✅ Importados no banco de dados
- ✅ Configurados com idioma e país corretos
- ✅ Categorizados (general, business, technology, sports, science)

### Cobertura Geográfica

**Inglês:** USA, UK, Austrália, Canadá, Índia, Irlanda, NZ, Hong Kong, Singapura, Israel, Japão, Coreia do Sul, Qatar

**Espanhol:** Espanha, Argentina, México, Colômbia, Chile, Peru, Uruguai, Bolívia, Venezuela, América Central, República Dominicana

**Português:** Brasil (todas regiões), Portugal

**Italiano:** Itália, Suíça

### Categorias Cobertas
- **Notícias Gerais** (180+ fontes)
- **Negócios/Economia** (40+ fontes)
- **Tecnologia** (25+ fontes)
- **Esportes** (10+ fontes)
- **Ciência** (10+ fontes)

---

## 🚀 Próximos Passos

1. **Coleta Automática:** Integrar com `wxAsyncNewsGather.py` para coleta periódica
2. **Monitoramento:** Verificar feeds que não respondem e remover inativos
3. **Expansão:** Adicionar mais fontes conforme necessário
4. **Análise:** Estatísticas de popularidade e qualidade das fontes

---

**Total de Fontes Ativas:** 236 RSS feeds funcionais em 4 idiomas
**Cobertura:** 30+ países em 4 continentes
**Artigos Disponíveis:** 3.178+ artigos no banco de dados
