import os
import xml.etree.ElementTree as etree

languages = [
    'nl_NL',
    'fr_CA',
    'fr_FR',
    'de_DE',
    'pt_PT',
    'pt_BR',
    'es_ES',
    'es_AR',
    'es_MX',
    'cs_CZ',
    'zh_CN',
    'zh_TW',
    'da_DK',
    'it_IT',
    'no_NO',
    'el_GR',
    'pl_PL',
    # 'sv_SE',
    'hu_HU',
    'ru_RU',
    'uk_UA',
    'lv_LV',
    'sv_SE',
    'lt_LT',
    'ko_KR'
]

tmp_file = r'C:\Users\Kat\Desktop\addon.xml'
PKC_dir = r'C:\Users\Kat\Documents\GitHub\PlexKodiConnect'

addon = {
    'msgctxt "#39703"': 'summary',
    'msgctxt "#39704"': 'description',
    'msgctxt "#39705"': 'disclaimer'
}


def indent(elem, level=0):
    """
    Prettifies xml trees. Pass the etree root in
    """
    i = "\n" + level*"  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indent(elem, level+1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


root = etree.Element('addon')
for lang in languages:
    try:
        with open(os.path.join(PKC_dir,
                               'resources',
                               'language',
                               'resource.language.%s' % lang,
                               'strings.po'), 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip() in addon:
                    msg = ''
                    key = line.strip()
                    # Advance to the line msgstr ""
                    part = ''
                    while not part.startswith('msgstr'):
                        part = next(f)
                    msg += part.replace('msgstr', '').replace('"', '').strip()
                    part = None
                    while part != '':
                        part = next(f).strip()
                        msg += part
                    msg = msg.replace('"', '').replace('\r', '').replace('\n', '')
                    print(msg)
                    etree.SubElement(root,
                                     addon[key],
                                     attrib={'lang': lang}).text = msg
    except IOError:
        print('Missing file %s' % os.path.join(PKC_dir,
                                               'resources',
                                               'language',
                                               'resource.language.%s' % lang,
                                               'strings.po'))
indent(root)
etree.ElementTree(root).write(tmp_file, encoding="UTF-8")
