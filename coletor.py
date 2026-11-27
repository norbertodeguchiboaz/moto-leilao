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

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "MotoLeilaoBot/0.1 (uso pessoal)"}
PAUSA = 3  # segundos entre requisições


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


URL_SUPERBID = (
    "https://www.superbid.net/categorias/carros-motos/motos/motocicletas/"
    "sao-paulo-sp?searchType=opened&pageNumber=1&pageSize=30&orderBy=score:desc"
)


def adaptador_superbid(paginas=3):
    """Superbid Exchange. A listagem é montada por JavaScript (o HTML puro vem
    quase vazio), então usamos um navegador automatizado:
        pip install playwright && playwright install chromium
    Obs.: a categoria "Veículos sinistrados" é separada na Superbid; esta URL
    é a de motocicletas em geral, que mistura outras origens."""
    from playwright.sync_api import sync_playwright

    lotes, vistos = [], set()
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True)
        pg = nav.new_page(user_agent=HEADERS["User-Agent"])
        for n in range(1, paginas + 1):
            abrir(pg, URL_SUPERBID.replace("pageNumber=1", f"pageNumber={n}"),
                  f"superbid_pagina_{n}")
            try:
                pg.wait_for_selector("a[href*='/oferta/']", timeout=20000)
            except Exception:
                break  # acabaram as páginas
            for a in pg.query_selector_all("a[href*='/oferta/']"):
                href = a.get_attribute("href") or ""
                if href in vistos:
                    continue
                vistos.add(href)
                texto = a.inner_text()
                linhas = [x.strip() for x in texto.splitlines() if x.strip()]
                ano = re.search(r"\b(19|20)\d{2}\b", texto)
                data = re.search(r"at[eé]\s+(\d{2}/\d{2})", texto)
                local = re.search(r"([A-Za-zÀ-ú ]+ - [A-Z]{2})", texto)
                lotes.append({
                    "leiloeiro": "Superbid",
                    "lote": href.rstrip("/").split("-")[-1],
                    "titulo": linhas[0] if linhas else "",
                    "ano": int(ano.group(0)) if ano else 0,
                    "km": None,
                    "lance": num(re.findall(r"R\$\s*[\d.]+,\d{2}", texto)[-1]
                                 if "R$" in texto else ""),
                    "fipe": 0,
                    "comitente": "",   # ver TODO abaixo
                    "descricao": " ".join(linhas),
                    "local": local.group(1).strip() if local else "",
                    "data_leilao": data.group(1) if data else "",
                    "url": href if href.startswith("http")
                    else "https://exchange.superbid.net" + href,
                })
            time.sleep(PAUSA)
        nav.close()
    # TODO: abrir a página de cada lote (/oferta/...) e ler km, comitente e a
    # descrição do vendedor. É lá que aparece se é financiamento, sinistro etc.
    # Use só o bloco de descrição do lote: o rodapé do site cita "financiamento"
    # e "sinistro" em textos genéricos e confundiria a classificação.
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
    # adaptador_superbid,  # desativado: a Superbid mostra "Just a moment..." (verificação
    #                      # anti-robô da Cloudflare) e não entrega a lista ao coletor.
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
