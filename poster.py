import requests
from pprint import pprint
from credentials import *  # WP_BOT_USER_NAME, WP_BOT_PASSWORD, WP_BOT_USER_AGENT, USER_SANDBOX_ARTICLE
from parser import ParsedWikitext

WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"

S = requests.Session()
S.headers.update({"User-Agent": WP_BOT_USER_AGENT})


def getLoginToken():
    params = {
        'action': 'query',
        'meta': 'tokens',
        'type': 'login',
        'format': 'json'
    }
    res = S.get(WIKIPEDIA_ENDPOINT, params=params)
    res.raise_for_status()
    return res.json()['query']['tokens']['logintoken']

def login():
    loginToken = getLoginToken()
    postData = {
        'action': 'login',
        'lgname': WP_BOT_USER_NAME,
        'lgpassword': WP_BOT_PASSWORD,
        'lgtoken': loginToken,
        'format': 'json'
    }
    res = S.post(WIKIPEDIA_ENDPOINT, data=postData)
    res.raise_for_status()
    data = res.json()
    if data['login']['result'] != 'Success':
        raise Exception(f"Login failed: {data['login']['result']}")
    print(f"Successfully logged in as {WP_BOT_USER_NAME}")
    return data

def getCsrfToken():
    params = {
        'action': 'query',
        'meta': 'tokens',
        'type': 'csrf',
        'format': 'json'
    }
    res = S.get(WIKIPEDIA_ENDPOINT, params=params)
    res.raise_for_status()
    return res.json()['query']['tokens']['csrftoken']

def fetchArticleWikitext(title):
    params = {
        'action': 'query',
        'prop': 'revisions',
        'titles': title,
        'rvprop': 'content',
        'rvslots': 'main',
        'formatversion': '2',
        'format': 'json'
    }
    res = S.get(WIKIPEDIA_ENDPOINT, params=params)
    res.raise_for_status()
    data = res.json()
    pages = data.get('query', {}).get('pages', [])
    assert pages and 'revisions' in pages[0], 'revisions field is missing for: '+title
    return pages[0]['revisions'][0]['slots']['main']['content']

def editArticleWikitext(csrfToken, articleTitle, newText):
    postData = {
        'action': 'edit',
        'title': articleTitle,
        'text': newText,
        'summary': 'Add 2020 census data',
        'token': csrfToken,
        'format': 'json',
        'assert': 'user',
        'maxlag': '5'
    }
    res = S.post(WIKIPEDIA_ENDPOINT, data=postData)
    pprint(res.json())

if __name__ == '__main__':
    login()
    article_title = 'Coalgate,_Oklahoma'
    pageWikitext = fetchArticleWikitext(article_title)
    parsed = ParsedWikitext.from_wikitext(pageWikitext)
    print(parsed.outline(article_title))

    oldSection = parsed.get_section(['Demographics'])
    newLine = 'As of the [[2020 United States census|2020 census]], the population of Coalgate was 1,667.\n\n'
    parsed.overwrite_section(['Demographics'], newLine + oldSection)
    newWikitext = parsed.to_wikitext()

    csrfToken = getCsrfToken()
    editArticleWikitext(csrfToken, article_title, newWikitext)
