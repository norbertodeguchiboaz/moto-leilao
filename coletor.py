"""
Coletor de lotes de motos de leilão -> gera lotes.json para o painel.

Uso:
    pip install requests beautifulsoup4
    python coletor.py

Cada leiloeiro tem um "adaptador": uma função que devolve uma lista de lotes
no formato abaixo. Os seletores CSS mudam de site para site, então ajuste
cada adaptador depois de inspecionar a página do leiloeiro.

Antes de coletar: leia os termos de uso e o robots.txt de cada site, mantenha
um intervalo entre requisições e prefira APIs/feeds quando existirem.

Formato de cada lote:
    leiloeiro, lote, titulo, ano, km, lance, fipe, comitente,
    descricao, local, data_leilao, url
"""
import json
import re
import time
import unicodedata
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "MotoLeilaoBot/0.1 (uso pessoal)"}
HEADERS_SUPERBID = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}
PAUSA = 3  # segundos entre requisições

URL_SUPERBID_API = "https://offer-query.superbid.net/seo/offers/"
LANCE_MINIMO_SUPERBID = 300.0
BLOQUEIO_SUPERBID_RE = re.compile(
    r"\b(sucata|inserv[ií]vel|pe[cç]a|pe[cç]as|kit\b|quadriciclo|vestu[aá]rio|[oó]rg[aã]o|suporte|carenagem)\b",
    re.IGNORECASE,
)
ESTADOS_BR = (
    "AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|TO"
)
NOMES_ESTADO_PARA_UF = {
    "acre": "AC",
    "alagoas": "AL",
    "amapa": "AP",
    "amazonas": "AM",
    "bahia": "BA",
    "ceara": "CE",
    "distrito federal": "DF",
    "espirito santo": "ES",
    "goias": "GO",
    "maranhao": "MA",
    "mato grosso": "MT",
    "mato grosso do sul": "MS",
    "minas gerais": "MG",
    "para": "PA",
    "paraiba": "PB",
    "parana": "PR",
    "pernambuco": "PE",
    "piaui": "PI",
    "rio de janeiro": "RJ",
    "rio grande do norte": "RN",
    "rio grande do sul": "RS",
    "rondonia": "RO",
    "roraima": "RR",
    "santa catarina": "SC",
    "sao paulo": "SP",
    "tocantins": "TO",
}
CIDADE_SEM_UF_PARA_UF = {
    "macapa": "AP",
    "belo horizonte": "MG",
    "curitiba": "PR",
    "maringa": "PR",
    "sao paulo": "SP",
    "rio de janeiro": "RJ",
    "fortaleza": "CE",
    "recife": "PE",
    "goiania": "GO",
    "campo grande": "MS",
    "florianopolis": "SC",
    "salvador": "BA",
    "manaus": "AM",
    "belem": "PA",
    "porto alegre": "RS",
    "brasilia": "DF",
    "vitoria": "ES",
    "cuiaba": "MT",
    "joao pessoa": "PB",
    "teresina": "PI",
    "natal": "RN",
    "aracaju": "SE",
    "maceio": "AL",
    "sao luis": "MA",
    "porto velho": "RO",
    "boa vista": "RR",
    "palmas": "TO",
    "rio branco": "AC",
}
TERMOS_ENDERECO_RE = re.compile(
    r"\b(bairro|rua|av|avenida|rodovia|estrada|alameda|travessa|lote|ano|placa|chassi|final|centro|visita[cç][aã]o)\b",
    re.IGNORECASE,
)


def num(texto):
    """'R$ 12.500,00' -> 12500.0"""
    if not texto:
        return 0
    limpo = re.sub(r"[^\d,]", "", texto).replace(",", ".")
    return float(limpo) if limpo else 0


def baixar(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    time.sleep(PAUSA)
    return BeautifulSoup(r.text, "html.parser")


# ---------------------------------------------------------------- adaptadores
DIAG = []              # diagnóstico de cada página aberta (vai para copart_debug.json)
RESPOSTAS_COPART = []  # respostas JSON recebidas pela página da Copart


def abrir(pg, url, nome):
    """Abre a página sem esperar a rede 'parar' (sites com anúncios e rastreadores
    nunca param, e isso causava o erro de timeout) e registra o que apareceu,
    para sabermos se a página carregou ou se o site bloqueou o robô."""
    info = {"nome": nome, "url": url}
    DIAG.append(info)
    try:
        pg.goto(url, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(8000)
        info["titulo"] = pg.title()
        info["texto"] = pg.inner_text("body")[:800]
    except Exception as erro:
        info["erro"] = str(erro)[:300]
        raise


def adaptador_exemplo():
    """Modelo a copiar para cada leiloeiro. Troque a URL e os seletores."""
    url = "https://www.exemplo-leiloeiro.com.br/motos"  # <- URL real da listagem
    soup = baixar(url)
    lotes = []
    for card in soup.select(".lote-card"):  # <- seletor do card de cada lote
        lotes.append({
            "leiloeiro": "Exemplo",
            "lote": card.select_one(".numero").get_text(strip=True),
            "titulo": card.select_one(".titulo").get_text(strip=True),
            "ano": int(card.select_one(".ano").get_text(strip=True)[:4]),
            "km": int(num(card.select_one(".km").get_text())),
            "lance": num(card.select_one(".lance").get_text()),
            "fipe": 0,  # preenchido em enriquecer_fipe()
            "comitente": card.select_one(".comitente").get_text(strip=True),
            "descricao": card.select_one(".descricao").get_text(" ", strip=True),
            "local": card.select_one(".local").get_text(strip=True),
            "data_leilao": card.select_one(".data").get_text(strip=True),
            "url": card.select_one("a")["href"],
        })
    return lotes


def _normalizar_sem_acento(texto):
    normalizado = unicodedata.normalize("NFKD", texto or "")
    sem_acentos = "".join(ch for ch in normalizado if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", sem_acentos).strip().lower()


def _limpar_html_superbid(html_texto):
    sem_tags = re.sub(r"<[^>]+>", " ", html_texto or "")
    return re.sub(r"\s+", " ", sem_tags).strip()


def _slug_superbid(titulo):
    slug = re.sub(r"[^a-z0-9]+", "-", _normalizar_sem_acento(titulo)).strip("-")
    return slug or "lote"


def _ano_superbid(titulo, desc_limpa):
    for fonte in (titulo, desc_limpa):
        m4 = re.search(r"\b(19\d{2}|20[0-2]\d)\b", fonte or "")
        if m4:
            return int(m4.group(1))
        m2 = re.search(r"\b(\d{2})/\d{2}\b", fonte or "")
        if m2:
            yy = int(m2.group(1))
            return 1900 + yy if yy >= 70 else 2000 + yy
    return 0


def _uf_de_valor(valor):
    if not valor:
        return ""
    s = str(valor).strip()
    up = s.upper()
    if re.fullmatch(rf"(?:{ESTADOS_BR})", up):
        return up
    chave = _normalizar_sem_acento(s)
    if chave in NOMES_ESTADO_PARA_UF:
        return NOMES_ESTADO_PARA_UF[chave]
    m_uf = re.search(rf"\b({ESTADOS_BR})\b", up)
    return m_uf.group(1) if m_uf else ""


def _local_superbid(offer, texto_analise):
    texto = re.sub(r"\s+", " ", texto_analise or "").strip()
    seller = offer.get("seller") or {}
    location = offer.get("location") or {}
    auction = offer.get("auction") or {}

    cidade = (
        location.get("city")
        or seller.get("city")
        or auction.get("city")
        or ""
    ).strip()

    # 1. Busca UF nos campos estruturados da oferta
    uf = ""
    for fonte in (location, seller, auction):
        for campo in ("state", "uf", "stateCode", "region"):
            uf = _uf_de_valor(fonte.get(campo))
            if uf:
                break
        if uf:
            break

    # 2. Tenta extrair "Cidade/UF" ou "Cidade - UF" limpo no texto (sem endereço/bairro)
    for m_cid_uf in re.finditer(
        rf"\b([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\']{{2,32}}?)\s*(?:/|-|–)\s*({ESTADOS_BR})(?=$|[\s,.;:)\]])",
        texto,
        re.IGNORECASE,
    ):
        cid = re.sub(r"\s+", " ", m_cid_uf.group(1)).strip(" ,;-")
        uf_texto = m_cid_uf.group(2).upper()
        if (
            len(cid) >= 3
            and not TERMOS_ENDERECO_RE.search(cid)
            and not re.search(rf"\b(?:{ESTADOS_BR}|BH)\b", cid, re.IGNORECASE)
        ):
            return f"{cid.title()} - {uf_texto}"

    # 3. Se temos a cidade da API, resolve UF pelo mapa direto
    if not uf and cidade:
        uf = CIDADE_SEM_UF_PARA_UF.get(_normalizar_sem_acento(cidade), "")

    # 4. Caso específico de "- BH - MG" ou sigla/nome de estado no texto
    if not uf and re.search(r"\bBH\s*-\s*MG\b", texto, re.IGNORECASE):
        return "Belo Horizonte - MG"

    if not uf:
        m_uf = re.search(
            rf"\(({ESTADOS_BR})\)|\bUF[:\s]*({ESTADOS_BR})\b|(?:^|[\s/–-])({ESTADOS_BR})(?=$|[\s,.;:)\]])",
            texto,
            re.IGNORECASE,
        )
        if m_uf:
            uf = ((m_uf.group(1) or m_uf.group(2) or m_uf.group(3)) or "").upper()

    if cidade and uf:
        return f"{cidade.title()} - {uf}"
    return uf or (cidade.title() if cidade else "Brasil")


def adaptador_superbid(max_paginas=15, page_size=30):
    """Superbid Exchange via API JSON de ofertas de motocicletas."""
    lotes, vistos = [], set()
    for pagina in range(1, max_paginas + 1):
        params = {
            "filter": "",
            "locale": "pt_BR",
            "orderBy": "score:desc",
            "pageNumber": pagina,
            "pageSize": page_size,
            "portalId": "[2,15]",
            "preOrderBy": "orderByFirstOpenedOffersAndSecondHasPhoto",
            "requestOrigin": "marketplace",
            "searchType": "opened",
            "timeZoneId": "America/Sao_Paulo",
            "urlSeo": "https://www.superbid.net/categorias/carros-motos/motos/motocicletas",
        }
        url_api = f"{URL_SUPERBID_API}?{urlencode(params)}"
        resp = requests.get(url_api, headers=HEADERS_SUPERBID, timeout=30)
        resp.raise_for_status()
        payload = resp.json()

        ofertas = payload.get("offers") or []
        if not ofertas:
            break

        for o in ofertas:
            offer_id = str(o.get("id") or "")
            if not offer_id or offer_id in vistos:
                continue

            titulo = ((o.get("product") or {}).get("shortDesc") or "").strip()
            desc_raw = ((o.get("offerDescription") or {}).get("offerDescription") or "")
            desc_limpa = _limpar_html_superbid(desc_raw)
            texto_analise = f"{titulo} {desc_limpa}"

            lance = float(o.get("price") or 0)
            if BLOQUEIO_SUPERBID_RE.search(texto_analise) or lance < LANCE_MINIMO_SUPERBID:
                continue

            vistos.add(offer_id)
            end_date = str(o.get("endDate") or "")
            auction_desc = ((o.get("auction") or {}).get("desc") or "Superbid").strip()
            seller_name = ((o.get("seller") or {}).get("name") or auction_desc).strip()
            detalhe_resumo = f"Encerra: {end_date} • Leilão: {auction_desc}"
            descricao_final = f"{detalhe_resumo} — {desc_limpa[:260]}".strip(" —")

            lotes.append({
                "leiloeiro": "Superbid",
                "lote": str(o.get("lotNumber") or ""),
                "titulo": titulo,
                "ano": _ano_superbid(titulo, desc_limpa),
                "km": None,
                "lance": lance,
                "fipe": 0,
                "comitente": seller_name,
                "descricao": descricao_final,
                "local": _local_superbid(o, texto_analise),
                "data_leilao": end_date[:10],
                "url": f"https://www.superbid.net/oferta/{_slug_superbid(titulo)}-{offer_id}",
            })

        total = int(payload.get("total") or 0)
        if total > 0 and pagina * page_size >= total:
            break
        time.sleep(PAUSA)

    print(f"[superbid] {len(lotes)} lotes coletados")
    return lotes


# Copart: motos de 2016 a 2027 com condição FINANCIAMENTO. Uma busca por pátio
# (o número do pátio é o #PhysicalYardNo da URL do site) e uma busca em todos
# os pátios do Brasil (número None). Parâmetros de rastreio removidos.
PATIOS_COPART = {
    "EMBÚ DAS ARTES - SP": 2,
    "ITAQUAQUECETUBA - SP": 46,
    "TODOS OS PÁTIOS": None,
}

# Condições da Copart que indicam sinistro (o painel descarta esses lotes).
SINISTRO = ("COLISÃO", "ROUBO/FURTO", "ENCHENTE", "QUEIMADO", "SINISTRADO")

JS_BUSCA = """async ([url, corpo]) => {
  const r = await fetch(url, {method: 'POST',
    headers: {'Content-Type': 'application/json'}, body: corpo});
  return await r.json();
}"""


def url_copart(nome, numero):
    from urllib.parse import quote
    patio = f",%22%23PhysicalYardNo:{numero}%22" if numero is not None else ""
    return (
        "https://www.copart.com.br/vehicleFinderSearch/?searchStr="
        "%7B%22MISC%22:%5B%22categoria:Motos%22,%22%23LotYear:%5B2016%20TO%202027%5D%22,"
        "%22condicao:%5C%22FINANCIAMENTO%5C%22%22"
        + patio +
        "%5D,%22sortByZip%22:false,%22buyerEnteredZip%22:null,%22milesAway%22:null%7D%20"
        "&displayStr=Motos,%5B2016%20TO%202027%5D,FINANCIAMENTO," + quote(nome)
    )


def converter_lote_copart(c):
    """Converte um lote da Copart para o formato do painel.
    Campos da Copart: mkn=marca, lm=modelo, lcy=ano, hb=maior lance,
    la=valor de referência, lossType=condição, sellerName=vendedor, yn=pátio,
    ad=data do leilão. (hb e la: confira com o site na primeira vez.)"""
    perda = (c.get("lossType") or "").upper()
    dica = " (sinistro)" if perda in SINISTRO else ""
    ano = str(c.get("lcy") or "")
    num = str(c.get("lotNumberStr") or "")
    return {
        "leiloeiro": "Copart",
        "lote": num,
        "titulo": f'{c.get("mkn", "")} {c.get("lm", "")}'.strip(),
        "ano": int(ano) if ano.isdigit() else 0,
        "km": None,
        "lance": float(c.get("hb") or 0),
        "fipe": float(c.get("la") or 0),
        "comitente": c.get("sellerName") or "",
        "descricao": (f'Condição: {perda}{dica}. Documento: {c.get("td", "")}. '
                      f'Dano: {c.get("damageClassification", "")}. '
                      f'Funcionamento: {c.get("drivabilityRating", "")}.'),
        "local": c.get("yn") or c.get("syn") or "",
        "data_leilao": (c.get("ad") or "")[:10],
        "url": "https://www.copart.com.br/lot/" + num,  # confira se o link abre
    }


def adaptador_copart(max_paginas=5):
    """Copart. A página é montada por JavaScript e os lotes chegam por uma busca
    interna (/public/lots/search). Abrimos a página, lemos essa resposta e, se
    houver mais lotes do que cabem numa página, pedimos as próximas."""
    from playwright.sync_api import sync_playwright

    def eh_busca(url):
        return "/public/lots/search" in url or "/public/vehicleFinder/search" in url

    respostas, pedidos, lotes, vistos = [], [], [], set()
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True)
        pg = nav.new_page(user_agent=HEADERS["User-Agent"])

        def ao_pedir(r):
            if eh_busca(r.url) and r.post_data:
                pedidos.append((r.url, r.post_data))

        def ao_responder(r):
            if eh_busca(r.url):
                try:
                    respostas.append(r.json())
                except Exception:
                    pass

        pg.on("request", ao_pedir)
        pg.on("response", ao_responder)

        for nome, numero in PATIOS_COPART.items():
            respostas.clear()
            pedidos.clear()
            try:
                abrir(pg, url_copart(nome, numero),
                      "copart_" + re.sub(r"\W+", "_", nome))
            except Exception as erro:
                print(f"[copart] {nome}: {erro}")
                continue
            if not respostas:
                print(f"[copart] {nome}: nenhuma resposta de busca recebida")
                continue
            dados = respostas[-1].get("data", {})
            resultado = dados.get("results", {})
            conteudo = list(resultado.get("content", []))
            total = resultado.get("totalElements", 0)
            DIAG[-1]["total_copart"] = total
            RESPOSTAS_COPART.append({"patio": nome, "total": total,
                                     "query": dados.get("query")})
            if pedidos and total > len(conteudo):
                url_busca, corpo = pedidos[-1]
                try:
                    corpo = json.loads(corpo)
                    tam = corpo.get("size") or 20
                    for pagina in range(1, min(max_paginas, -(-total // tam))):
                        corpo["page"] = pagina
                        corpo["start"] = pagina * tam
                        r = pg.evaluate(JS_BUSCA, [url_busca, json.dumps(corpo)])
                        conteudo += r["data"]["results"]["content"]
                        time.sleep(PAUSA)
                except Exception as erro:
                    print(f"[copart] {nome}: só a primeira página ({erro})")
            for c in conteudo:
                chave = c.get("lotNumberStr")
                if chave in vistos:
                    continue
                vistos.add(chave)
                lotes.append(converter_lote_copart(c))
            print(f"[copart] {nome}: {len(conteudo)} lotes lidos de {total}")
        nav.close()
    return lotes


ADAPTADORES = [
    adaptador_superbid,
    adaptador_copart,
    # adaptador_exemplo,   # modelo para os demais leiloeiros
]


# ------------------------------------------------------------------ enriquecer
def enriquecer_fipe(lotes):
    """Preencha l['fipe'] consultando uma API de tabela FIPE
    (por exemplo, a API pública parallelum: https://deividfortuna.github.io/fipe/).
    Mapeie marca/modelo/ano do título para os códigos da FIPE."""
    return lotes


def main():
    todos = []
    for adaptador in ADAPTADORES:
        try:
            todos += adaptador()
        except Exception as erro:  # um site fora do ar não derruba os demais
            print(f"[aviso] {adaptador.__name__}: {erro}")
    todos = enriquecer_fipe(todos)
    with open("copart_debug.json", "w", encoding="utf-8") as f:
        json.dump({"diagnostico": DIAG, "respostas_copart": RESPOSTAS_COPART},
                  f, ensure_ascii=False, indent=2)
    with open("lotes.json", "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)
    print(f"{len(todos)} lotes salvos em lotes.json")


if __name__ == "__main__":
    main()
