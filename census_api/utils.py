import datetime
from urllib.parse import quote, urlencode, urlparse, urlunparse, parse_qsl

from census_api.constants import (
    CITATION_DETAILS,
    DP_FIELDS,
    DP_ENDPOINT,
    DHC_FIELDS,
    DHC_ENDPOINT,
    PL_FIELDS,
    PL_ENDPOINT,
)


def _format_access_date(access_date: str = None) -> str:
    """
    Return access_date or today's date formatted as 'Month D, YYYY'.
    """
    if access_date:
        return access_date
    today = datetime.date.today()
    return today.strftime("%B %-d, %Y") if hasattr(today, "strftime") else f"{today.strftime('%B')} {today.day}, {today.year}"


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


def build_census_api_url(source_key: str, state_fips: str, county_fips: str) -> str:
    """
    Construct a census API URL with query params for the given source and FIPS codes.
    """
    state = state_fips.zfill(2)
    county = county_fips.zfill(3)

    if source_key == "dp":
        endpoint = DP_ENDPOINT
        fields = DP_FIELDS
    elif source_key == "pl":
        endpoint = PL_ENDPOINT
        fields = PL_FIELDS
    elif source_key == "dhc":
        endpoint = DHC_ENDPOINT
        fields = DHC_FIELDS
    else:
        raise ValueError(f"Unsupported source key '{source_key}'")

    fields_q = quote(fields, safe=",_")
    for_part = quote(f"county:{county}")
    in_part = quote(f"state:{state}")
    return f"{endpoint}?get={fields_q}&for={for_part}&in={in_part}"


def strip_census_key(url: str) -> str:
    if not url:
        return url
    parsed = urlparse(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() != "key"
    ]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def get_dp_ref(url: str = None, access_date: str = None, state_fips: str = None, county_fips: str = None) -> str:
    if not url and state_fips and county_fips:
        url = build_census_api_url("dp", state_fips, county_fips)
    return build_census_ref("dp", url=url, access_date=access_date)


def get_pl_ref(url: str = None, access_date: str = None, state_fips: str = None, county_fips: str = None) -> str:
    if not url and state_fips and county_fips:
        url = build_census_api_url("pl", state_fips, county_fips)
    return build_census_ref("pl", url=url, access_date=access_date)


def get_dhc_ref(url: str = None, access_date: str = None, state_fips: str = None, county_fips: str = None) -> str:
    if not url and state_fips and county_fips:
        url = build_census_api_url("dhc", state_fips, county_fips)
    return build_census_ref("dhc", url=url, access_date=access_date)


__all__ = [
    "build_census_ref",
    "get_dp_ref",
    "get_pl_ref",
    "get_dhc_ref",
    "build_census_api_url",
    "strip_census_key",
]
