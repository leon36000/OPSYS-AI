import json
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

_XML_MAX_BYTES = 2_000_000  # garde-fou DoS (~2 Mo) ; ajustable selon les fixtures


class SEOParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = None
        self.meta_description = None
        self.h1_list = []
        self.scripts_ld = []
        self.links = []
        self._in_title = False
        self._current_h1 = None
        self._in_script_ld = False
        self._script_ld_buffer = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == 'title':
            self._in_title = True
        elif tag == 'meta':
            if attrs_dict.get('name', '').lower() == 'description':
                self.meta_description = attrs_dict.get('content')
        elif tag == 'h1':
            self._current_h1 = []
        elif tag == 'script':
            if attrs_dict.get('type') == 'application/ld+json':
                self._in_script_ld = True
                self._script_ld_buffer = []
        elif tag == 'a':
            href = attrs_dict.get('href')
            if href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False
        elif tag == 'h1':
            if self._current_h1 is not None:
                content = ''.join(self._current_h1).strip()
                self.h1_list.append(content)
                self._current_h1 = None
        elif tag == 'script' and self._in_script_ld:
            self.scripts_ld.append(''.join(self._script_ld_buffer).strip())
            self._in_script_ld = False

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or '') + data
        if self._current_h1 is not None:
            self._current_h1.append(data)
        if self._in_script_ld:
            self._script_ld_buffer.append(data)


def extract_domain(url: str) -> str:
    domain_part = url.split('://', 1)[1] if '://' in url else url
    domain = domain_part.split('/')[0]
    return domain.lower().strip()


def analyze_page(html_str: str, url: str) -> dict:
    parser = SEOParser()
    parser.feed(html_str)
    title = (parser.title or '').strip()

    if title and len(title) <= 60:
        c01 = "conforme"
    elif title:
        c01 = "non_conforme"
    else:
        c01 = "non_conforme"

    desc = parser.meta_description or ''
    if desc and len(desc) <= 160:
        c02 = "conforme"
    elif desc:
        c02 = "non_conforme"
    else:
        c02 = "non_conforme"

    h1_texts = [h for h in parser.h1_list if h]
    if len(h1_texts) == 1:
        c03 = "conforme"
    elif len(h1_texts) > 1:
        c03 = "non_conforme"
    else:
        c03 = "non_conforme"

    schema_verdict = _check_schema(parser.scripts_ld)
    c04 = schema_verdict

    domain = extract_domain(url)
    internal_links = set()
    for link in parser.links:
        if link.startswith('/'):
            internal_links.add(link)
        else:
            if extract_domain(link) == domain:
                internal_links.add(link)
    c05 = "conforme" if len(internal_links) >= 3 else "non_conforme"

    return {
        "C-01": c01,
        "C-02": c02,
        "C-03": c03,
        "C-04": c04,
        "C-05": c05,
    }


def _check_schema(scripts):
    if not scripts:
        return "non_conforme"
    for s in scripts:
        try:
            data = json.loads(s)
            if isinstance(data, dict) and data.get("@context") == "https://schema.org":
                return "conforme"
        except json.JSONDecodeError:
            continue
    return "candidat_a_verifier"


def analyze_robots(robots_str: str) -> dict:
    if not robots_str.strip():
        return {"C-06": "KO", "detail_C-06": "Fichier robots.txt absent"}

    target_bots = {'gptbot', 'perplexitybot', 'claudebot', 'google-extended', 'ccbot'}
    user_agent = None
    bots_blocked = set()

    for raw_line in robots_str.splitlines():
        line = raw_line.split('#', 1)[0].strip()
        if not line:
            continue
        if line.lower().startswith('user-agent:'):
            user_agent = line.split(':', 1)[1].strip().lower()
        elif line.lower().startswith('disallow:') and user_agent is not None:
            path = line.split(':', 1)[1].strip()
            if user_agent in target_bots and path == '/':
                bots_blocked.add(user_agent)

    if bots_blocked:
        return {"C-06": "non_conforme", "detail_C-06": f"Bots IA bloqués: {', '.join(sorted(bots_blocked))}"}
    else:
        return {"C-06": "conforme", "detail_C-06": "Aucun blocage de bots IA détecté"}


def analyze_sitemap(xml_str: str) -> dict:
    if not xml_str.strip():
        return {"C-07": "KO", "detail_C-07": "Fichier sitemap.xml absent"}
    if len(xml_str.encode("utf-8")) > _XML_MAX_BYTES:
        return {"C-07": "KO", "detail_C-07": "sitemap.xml dépasse la taille maximale autorisée"}
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        return {"C-07": "KO", "detail_C-07": f"Erreur de parsing XML: {e}. parse_error"}
    # Vérifier la présence d'au moins un <url> contenant un <loc> non vide
    has_url_loc = False
    for url_elem in root.iter():
        if url_elem.tag.split('}')[-1] == 'url':
            for child in url_elem:
                if child.tag.split('}')[-1] == 'loc' and child.text and child.text.strip():
                    has_url_loc = True
                    break
            if has_url_loc:
                break
    if has_url_loc:
        return {"C-07": "conforme", "detail_C-07": "Sitemap valide avec des URLs"}
    else:
        return {"C-07": "non_conforme", "detail_C-07": "Sitemap valide mais aucune URL trouvée"}
