"""
Shared constants for Census API access and citation metadata.
"""

PL_ENDPOINT = "https://api.census.gov/data/2020/dec/pl"
DP_ENDPOINT = "https://api.census.gov/data/2020/dec/dp"

PL_FIELDS = (
    "NAME,P1_001N,P1_003N,P1_004N,P1_005N,P1_006N,"
    "P1_008N,P1_009N,P2_001N,P2_002N,H1_001N,H1_002N"
)

DP_FIELDS = (
    "NAME,DP1_0021P,DP1_0024P,DP1_0025C,DP1_0049C,DP1_0045C,"
    "DP1_0069C,DP1_0073C,DP1_0125P,DP1_0126P,DP1_0129P,DP1_0138P,"
    "DP1_0139P,DP1_0141P,DP1_0142P,DP1_0143P,DP1_0145P,DP1_0146P,"
    "DP1_0147C,DP1_0148C,DP1_0149C,DP1_0156C,DP1_0157C,DP1_0158C,"
    "DP1_0159P,DP1_0160P"
)

CITATION_SOURCES = {
    "age_65_plus_percent": ["dp"],
    "age_median_years": ["dp"],
    "age_under_18_percent": ["dp"],
    "average_family_size": ["dp"],
    "average_household_size": ["dp"],
    "female_householder_no_spouse_percent": ["dp"],
    "group_quarters_percent": ["dp", "pl"],
    "hispanic_any_race_percent": ["dp", "pl"],
    "homeowner_vacancy_rate_percent": ["dp"],
    "households_with_children_under_18_percent": ["dp"],
    "institutional_group_quarters_percent": ["dp", "pl"],
    "living_alone_65_plus_households_percent": ["dp"],
    "married_couple_households_percent": ["dp"],
    "noninstitutional_group_quarters_percent": ["dp", "pl"],
    "one_person_households_percent": ["dp"],
    "owner_occupied_percent": ["dp"],
    "race_aian_percent": ["dp", "pl"],
    "race_asian_percent": ["dp", "pl"],
    "race_black_percent": ["dp", "pl"],
    "race_some_other_percent": ["dp", "pl"],
    "race_two_or_more_percent": ["dp", "pl"],
    "race_white_percent": ["dp", "pl"],
    "rental_vacancy_rate_percent": ["dp"],
    "renter_occupied_percent": ["dp"],
    "sex_ratio_18_plus_males_per_100_females": ["dp"],
    "sex_ratio_males_per_100_females": ["dp"],
    "total_families": ["dp"],
    "total_households": ["dp", "pl"],
    "total_housing_units": ["dp", "pl"],
    "total_population": ["dp", "pl"],
    "vacant_units_percent": ["dp", "pl"],
}
