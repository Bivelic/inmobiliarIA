"""Convierte una descripción de portal en un extracto de texto plano."""

from html.parser import HTMLParser

LARGO_EXTRACTO = 280
_SEPARADORES = {
    "br",
    "p",
    "div",
    "li",
    "ul",
    "ol",
    "hr",
    "section",
    "td",
    "tr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}
_OCULTOS = {"script", "style", "template"}


class _TextoVisible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fragmentos: list[str] = []
        self.ocultos: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _OCULTOS:
            self.ocultos.append(tag)
        elif not self.ocultos and tag in _SEPARADORES:
            self.fragmentos.append(" ")

    def handle_endtag(self, tag):
        if self.ocultos:
            if tag == self.ocultos[-1]:
                self.ocultos.pop()
                if not self.ocultos:
                    self.fragmentos.append(" ")
        elif tag in _SEPARADORES:
            self.fragmentos.append(" ")

    def handle_data(self, data):
        if not self.ocultos:
            self.fragmentos.append(data)


def extracto_publico(descripcion: str | None) -> str | None:
    """Limpia el HTML antes de recortar, incluso en avisos ya guardados."""
    if not descripcion:
        return descripcion
    if "<" not in descripcion and "&" not in descripcion:
        return descripcion[:LARGO_EXTRACTO]
    parser = _TextoVisible()
    parser.feed(descripcion)
    parser.close()
    texto = " ".join("".join(parser.fragmentos).split())
    return texto[:LARGO_EXTRACTO]
