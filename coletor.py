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
            pg.goto(URL_SUPERBID.replace("pageNumber=1", f"pageNumber={n}"),
                    wait_until="networkidle")
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


# Copart: filtros fixos (motos, 2016 a 2027, condição FINANCIAMENTO) e uma busca
# por pátio. O número do pátio é o #PhysicalYardNo da URL do site. Parâmetros de
# rastreio (gclid, gbraid, _gl) removidos.
PATIOS_COPART = {
    "EMBÚ DAS ARTES - SP": 2,
    # Neste formato novo da Copart o pátio é filtrado pelo NOME, e o link usado traz
    # "Motor dá partida". ATENÇÃO: este link NÃO tem o filtro de financiamento,
    # então os lotes dele não são necessariamente de financiamento.
    # (o valor pode ser o número do pátio ou a URL completa da busca)
    "ITAQUAQUECETUBA - SP": (
        "https://www.copart.com.br/search/motos/?displayStr=Motos&from=%2FvehicleFinder"
        "&searchCriteria=%7B%22query%22:%5B%22*%22%5D,%22filter%22:%7B%22MISC%22:"
        "%5B%22categoria:Motos%22%5D,%22categoria%22:%5B%22categoria:%5C%22Motos%5C%22%22%5D,"
        "%22condicaofuncionamento%22:%5B%22condicaofuncionamento:%5C%22Motor%20d%C3%A1%20partida%5C%22%22%5D,"
        "%22patioveiculo%22:%5B%22patioveiculo:%5C%22Itaquaquecetuba%20-%20SP%5C%22%22%5D%7D,"
        "%22sort%22:%5B%22auction_date_utc%20asc%22,%22brazil_default_sort%20asc%22%5D,"
        "%22watchListOnly%22:false,%22searchName%22:%22%22,%22freeFormSearch%22:false%7D"
    ),
}


def url_copart(nome, numero):
    from urllib.parse import quote
    return (
        "https://www.copart.com.br/vehicleFinderSearch/?searchStr="
        "%7B%22MISC%22:%5B%22categoria:Motos%22,%22%23LotYear:%5B2016%20TO%202027%5D%22,"
        "%22condicao:%5C%22FINANCIAMENTO%5C%22%22,"
        f"%22%23PhysicalYardNo:{numero}%22%5D,"
        "%22sortByZip%22:false,%22buyerEnteredZip%22:null,%22milesAway%22:null%7D%20"
        "&displayStr=Motos,%5B2016%20TO%202027%5D,FINANCIAMENTO," + quote(nome)
    )


def adaptador_copart():
    """Copart. A página também é montada por JavaScript. Como a URL já filtra
    condicao:FINANCIAMENTO, todo lote retornado é de financiamento (o painel
    reconhece a palavra na descrição).

    PASSO 1 (este): abre a página e grava em copart_debug.json as respostas JSON
    que o site recebe, para mapearmos os campos (modelo, ano, km, lance...).
    PASSO 2: com esse arquivo em mãos, converter cada lote para o formato do
    painel e devolver a lista."""
    from playwright.sync_api import sync_playwright

    respostas = []
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True)
        pg = nav.new_page(user_agent=HEADERS["User-Agent"])

        def captura(r):
            tipo = r.headers.get("content-type") or ""
            if "json" in tipo and "copart" in r.url:
                try:
                    respostas.append({"url": r.url, "dados": r.json()})
                except Exception:
                    pass

        pg.on("response", captura)
        for nome, numero in PATIOS_COPART.items():
            if numero is None:
                print(f"[copart] pátio {nome}: número não definido, pulando")
                continue
            url = numero if isinstance(numero, str) else url_copart(nome, numero)
            pg.goto(url, wait_until="networkidle")
            time.sleep(PAUSA)
        nav.close()
    with open("copart_debug.json", "w", encoding="utf-8") as f:
        json.dump(respostas, f, ensure_ascii=False, indent=2)
    print(f"[copart] {len(respostas)} respostas gravadas em copart_debug.json")
    return []


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
    with open("lotes.json", "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)
    print(f"{len(todos)} lotes salvos em lotes.json")


if __name__ == "__main__":
    main()
