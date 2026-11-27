"""MCP-visible condition types; domain validation remains in policy_groups."""
from typing_extensions import TypedDict
from pydantic import StrictInt, StrictStr


class Condition(TypedDict, total=False):
    name: StrictStr
    label: StrictStr
    age_min: StrictInt
    age_max: StrictInt
    provinces: list[StrictStr]
    occupations: list[StrictStr]
    keywords: list[StrictStr]
    eligibility: list[StrictStr]
    family_type_like: list[StrictStr]
    housing_type_in: list[StrictStr]
    education_in: list[StrictStr]
    sex: StrictStr
    clause_ids: list[StrictStr]


class ConditionGroups(TypedDict):
    groups: list[Condition]


Conditions = Condition | list[Condition] | ConditionGroups | None
