import requests
from pprint import pprint
from credentials import *  # WP_BOT_USER_NAME, WP_BOT_PASSWORD, WP_BOT_USER_AGENT, USER_SANDBOX_ARTICLE
from parser import ParsedWikitext

WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"


class WikipediaClient:
    """
    Thin wrapper around the Wikipedia API that handles login, tokens, and edits.
    """

    def __init__(self, user_agent):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self._csrf_token = None

    def _get(self, params):
        response = self.session.get(WIKIPEDIA_ENDPOINT, params=params)
        response.raise_for_status()
        return response

    def _post(self, data):
        response = self.session.post(WIKIPEDIA_ENDPOINT, data=data)
        response.raise_for_status()
        return response

    def get_login_token(self):
        params = {
            'action': 'query',
            'meta': 'tokens',
            'type': 'login',
            'format': 'json'
        }
        response = self._get(params)
        return response.json()['query']['tokens']['logintoken']

    def login(self, username, password):
        login_token = self.get_login_token()
        payload = {
            'action': 'login',
            'lgname': username,
            'lgpassword': password,
            'lgtoken': login_token,
            'format': 'json'
        }
        response = self._post(payload)
        data = response.json()
        if data['login']['result'] != 'Success':
            raise Exception(f"Login failed: {data['login']['result']}")
        print(f"Successfully logged in as {username}")
        return data

    def get_csrf_token(self):
        if self._csrf_token:
            return self._csrf_token
        params = {
            'action': 'query',
            'meta': 'tokens',
            'type': 'csrf',
            'format': 'json'
        }
        response = self._get(params)
        self._csrf_token = response.json()['query']['tokens']['csrftoken']
        return self._csrf_token

    def fetch_article_wikitext(self, title):
        params = {
            'action': 'query',
            'prop': 'revisions',
            'titles': title,
            'rvprop': 'content',
            'rvslots': 'main',
            'formatversion': '2',
            'format': 'json'
        }
        response = self._get(params)
        data = response.json()
        pages = data.get('query', {}).get('pages', [])
        assert pages and 'revisions' in pages[0], 'revisions field is missing for: ' + title
        return pages[0]['revisions'][0]['slots']['main']['content']

    def edit_article_wikitext(self, title, new_text, summary):
        token = self.get_csrf_token()
        payload = {
            'action': 'edit',
            'title': title,
            'text': new_text,
            'summary': summary,
            'token': token,
            'format': 'json',
            'assert': 'user',
            'maxlag': '5'
        }
        response = self._post(payload)
        return response.json()

    def compare_revision_sizes(self, old_revision_id, new_revision_id):
        """
        Fetch the byte sizes of two revisions and return a delta (new - old).
        """
        params = {
            'action': 'compare',
            'fromrev': old_revision_id,
            'torev': new_revision_id,
            'prop': 'size',
            'format': 'json',
        }
        response = self._get(params)
        data = response.json().get('compare', {})
        old_size = data.get('fromsize')
        new_size = data.get('tosize')
        if old_size is None or new_size is None:
            raise ValueError("Revision size information is unavailable.")
        return new_size - old_size

    def edit_article_with_size_check(
        self,
        title,
        parsed_wikitext,
        summary,
        tolerance=2,
        new_text=None,
    ):
        """
        Edit a page and verify the observed size delta roughly matches expectations.
        """
        new_text = new_text if new_text is not None else parsed_wikitext.to_wikitext()
        expected_delta = len(new_text) - parsed_wikitext.original_length
        response = self.edit_article_wikitext(title, new_text, summary)
        edit_info = response.get('edit', {})
        old_rev = edit_info.get('oldrevid')
        new_rev = edit_info.get('newrevid')
        if old_rev is not None and new_rev is not None:
            actual_delta = self.compare_revision_sizes(old_rev, new_rev)
            if abs(actual_delta - expected_delta) > tolerance:
                raise ValueError(
                    f"Revision size delta {actual_delta} differs from expected {expected_delta} by more than {tolerance}."
                )
        return response


def main():
    client = WikipediaClient(WP_BOT_USER_AGENT)
    client.login(WP_BOT_USER_NAME, WP_BOT_PASSWORD)

    article_title = 'Coolgate,_Oklahoma'
    page_wikitext = client.fetch_article_wikitext(article_title)
    print(page_wikitext)
    # parsed = ParsedWikitext(wikitext=page_wikitext)
    # print(parsed.outline(article_title))
    #
    # old_section = parsed.get_section(['Demographics'])
    # new_line = 'As of the [[2020 United States census|2020 census]], the population of Coalgate was 1,667.\n\n'
    # parsed.overwrite_section(['Demographics'], new_line + old_section)
    #
    # result = client.edit_article_with_size_check(
    #     article_title,
    #     parsed,
    #     'Add 2020 census data'
    # )
    # pprint(result)


if __name__ == '__main__':
    main()
