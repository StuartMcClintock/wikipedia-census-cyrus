"""
Shared constants for Census API access and citation metadata.
"""

PL_ENDPOINT = "https://api.census.gov/data/2020/dec/pl"
DP_ENDPOINT = "https://api.census.gov/data/2020/dec/dp"
DHC_ENDPOINT = "https://api.census.gov/data/2020/dec/dhc"

PL_FIELDS = (
    "NAME,P1_001N,P1_003N,P1_004N,P1_005N,P1_006N,P1_007N,"
    "P1_008N,P1_009N,P2_001N,P2_002N,H1_001N,H1_002N"
)

DP_FIELDS = (
    "NAME,DP1_0021P,DP1_0024P,DP1_0025C,DP1_0049C,DP1_0045C,"
    "DP1_0069C,DP1_0073C,DP1_0125P,DP1_0126P,DP1_0129P,DP1_0133P,"
    "DP1_0137P,DP1_0138P,DP1_0139P,DP1_0141P,DP1_0142P,DP1_0143P,"
    "DP1_0145P,DP1_0146P,DP1_0147C,DP1_0148C,DP1_0149C,DP1_0156C,"
    "DP1_0157C,DP1_0158C,DP1_0159P,DP1_0160P"
)

DHC_FIELDS = "NAME,P2_002N,P2_003N"

CITATION_SOURCES = {
    # Age
    "age_65_plus_percent": ["dp"],
    "age_median_years": ["dp"],
    "age_under_18_percent": ["dp"],

    # Household / family structure
    "average_family_size": ["dp"],
    "average_household_size": ["dp"],
    "female_householder_no_spouse_percent": ["dp"],
    "male_householder_no_spouse_percent": ["dp"],
    "households_with_children_under_18_percent": ["dp"],
    "living_alone_65_plus_households_percent": ["dp"],
    "married_couple_households_percent": ["dp"],
    "one_person_households_percent": ["dp"],

    # Group quarters
    "group_quarters_percent": ["dp"],
    "institutional_group_quarters_percent": ["dp"],
    "noninstitutional_group_quarters_percent": ["dp"],

    # Tenure & vacancy
    "homeowner_vacancy_rate_percent": ["dp"],
    "rental_vacancy_rate_percent": ["dp"],
    "owner_occupied_percent": ["dp"],
    "renter_occupied_percent": ["dp"],
    "vacant_units_percent": ["dp"],  # PL only has raw counts; percent comes from DP1

    # Race & Hispanic (canonical from PL)
    "race_white_percent": ["pl"],
    "race_black_percent": ["pl"],
    "race_aian_percent": ["pl"],
    "race_asian_percent": ["pl"],
    "race_nhpi_percent": ["pl"],
    "race_some_other_percent": ["pl"],
    "race_two_or_more_percent": ["pl"],
    "hispanic_any_race_percent": ["pl"],

    # Sex ratios (derived from DP1 counts)
    "sex_ratio_males_per_100_females": ["dp"],
    "sex_ratio_18_plus_males_per_100_females": ["dp"],

    # Totals (both datasets have these; prefer PL in your logic if you want)
    "total_families": ["dp"],
    "total_households": ["dp"],
    "total_housing_units": ["dp"],
    "total_population": ["pl", "dp"],
    "urban_population_percent": ["dhc"],
    "rural_population_percent": ["dhc"],
}

CITATION_DETAILS = {
    "dp": {
        "name": "Census2020DP",
        "template": (
            "{{cite web|title=2020 Decennial Census Demographic Profile (DP1)|"
            "url={url}|website=United States Census Bureau|year=2021|access-date="
            "{access_date}|df=mdy}}"
        ),
        "default_url": DP_ENDPOINT,
    },
    "pl": {
        "name": "Census2020PL",
        "template": (
            "{{cite web|title=2020 Decennial Census Redistricting Data (Public Law 94-171)|"
            "url={url}|website=United States Census Bureau|year=2021|access-date="
            "{access_date}|df=mdy}}"
        ),
        "default_url": PL_ENDPOINT,
    },
    "dhc": {
        "name": "Census2020DHC",
        "template": (
            "{{cite web|title=2020 Decennial Census Demographic and Housing Characteristics (DHC)|"
            "url={url}|website=United States Census Bureau|year=2023|access-date="
            "{access_date}|df=mdy}}"
        ),
        "default_url": DHC_ENDPOINT,
    },
}
