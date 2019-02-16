import os

path = "C:\\Users\\kat\\AppData\\Local\\Continuum\\anaconda3\\envs\\kodi\\Scripts"
command = os.path.join(path, "tx.exe")
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
    'sv_SE'
]

os.system("cd ..")

for lang in languages:
    os.system(command + " pull -f -l %s" % lang)
