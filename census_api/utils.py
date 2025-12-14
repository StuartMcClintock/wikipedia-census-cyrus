import datetime

from census_api.constants import CITATION_DETAILS


def _format_access_date(access_date: str = None) -> str:
    """
    Return access_date or today's date formatted as 'D Month YYYY'.
    """
    if access_date:
        return access_date
    today = datetime.date.today()
    return f"{today.day} {today.strftime('%B')} {today.year}"


def _ensure_template_closed(template: str) -> str:
    """
    Wrap a cite template with exactly '{{' and '}}'.
    """
    trimmed = template.strip()
    while trimmed.startswith("{"):
        trimmed = trimmed[1:]
    while trimmed.endswith("}"):
        trimmed = trimmed[:-1]
    return "{{" + trimmed.strip() + "}}"


def build_census_ref(source_key: str, url: str = None, access_date: str = None) -> str:
    """
    Build a full <ref>...</ref> citation for the given census source key (dp, pl, dhc).
    """
    detail = CITATION_DETAILS[source_key]
    resolved_url = url or detail["default_url"]
    template = detail["template"].format(url=resolved_url, access_date=_format_access_date(access_date))
    return f'<ref name="{detail["name"]}">{_ensure_template_closed(template)}</ref>'


def get_dp_ref(url: str = None, access_date: str = None) -> str:
    return build_census_ref("dp", url=url, access_date=access_date)


def get_pl_ref(url: str = None, access_date: str = None) -> str:
    return build_census_ref("pl", url=url, access_date=access_date)


def get_dhc_ref(url: str = None, access_date: str = None) -> str:
    return build_census_ref("dhc", url=url, access_date=access_date)


__all__ = ["build_census_ref", "get_dp_ref", "get_pl_ref", "get_dhc_ref"]
