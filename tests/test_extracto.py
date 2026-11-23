from core.extracto import LARGO_EXTRACTO, extracto_publico


def test_limpia_html_antes_de_recortar():
    texto = "<br />" * 80 + "<p>Amplio &amp; luminoso.</p><div>Disponible<br/>Ahora</div>"
    assert extracto_publico(texto) == "Amplio & luminoso. Disponible Ahora"


def test_omite_contenido_no_visible_y_limita_el_texto():
    descripcion = "<style>estilos</style><script>código</script><p>" + "a" * 400 + "</p>"
    assert extracto_publico(descripcion) == "a" * LARGO_EXTRACTO
    assert extracto_publico(None) is None
