"""Small self-contained page with deliberately different naming situations."""

from urllib.parse import quote


def page():
    picture = "data:image/svg+xml," + quote('<svg xmlns="http://www.w3.org/2000/svg" width="240" height="150"><rect width="240" height="150" rx="12" fill="#dbeafe"/><path d="M30 120L95 35L155 115L195 60L225 120Z" fill="#1d4ed8"/><circle cx="190" cy="35" r="17" fill="#f59e0b"/></svg>')
    image = lambda attributes: f'<img width="240" height="150" src="{picture}" {attributes}>'
    return f'''<!doctype html><html lang="en"><title>AltReview demonstration</title>
    <style>body{{font:18px system-ui;max-width:1000px;margin:40px auto}}section{{display:inline-block;width:280px;vertical-align:top;margin:16px}}figure{{margin:0}}h2{{font-size:20px}}img{{max-width:100%}}</style>
    <h1>Image naming demonstration</h1><p>These examples test naming structure. Their visual meaning is a separate review.</p>
    <section><h2>Named photograph</h2>{image('id="named" alt="Blue mountain silhouettes beneath a yellow sun."')}</section>
    <section><h2>Missing alternative</h2>{image('id="missing"')}</section>
    <section><h2>Empty alt</h2>{image('id="decorative" alt=""')}<p>Empty alt alone is not an automatic failure.</p></section>
    <section><h2>Unnamed image link</h2><figure><a href="#gallery">{image('id="unnamed-link" alt=""')}</a><figcaption>Photo gallery</figcaption></figure></section>
    <section><h2>Text inside the link</h2><a href="#gallery">{image('id="named-link" alt=""')}Open the photo gallery</a></section>
    <section><h2>Filename alternative</h2>{image('id="filename" alt="IMG_0421.jpg"')}<p>A name can be present while its quality needs review.</p></section>
    <section><h2>Title alternative</h2>{image('id="title-name" title="Mountain illustration"')}</section>
    <section><h2>ARIA label</h2><div role="img" aria-label="Mountain illustration" style="width:240px;height:150px;background:#dbeafe"></div></section>
    <section><h2>Hidden copy</h2><div style="display:none">{image('id="hidden"')}</div><p>Hidden content is inventoried separately.</p></section>
    <div id="gallery">Gallery destination</div></html>'''
