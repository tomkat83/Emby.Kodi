import os

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
]

os.system("cd ..")

for lang in languages:
    os.system("tx pull -f -l %s" % lang)
