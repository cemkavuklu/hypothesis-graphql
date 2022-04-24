"""Strategies for simple types like scalars or enums."""
from typing import Union

import graphql
from hypothesis import strategies as st

from ..types import ScalarValueNode

MIN_INT = -(2**31)
MAX_INT = 2**31 - 1


def scalar(type_: graphql.GraphQLScalarType, nullable: bool = True) -> st.SearchStrategy[ScalarValueNode]:
    if type_.name == "Int":
        return int_(nullable)
    if type_.name == "Float":
        return float_(nullable)
    if type_.name == "String":
        return string(nullable)
    if type_.name == "ID":
        return id_(nullable)
    if type_.name == "Boolean":
        return boolean(nullable)
    raise TypeError("Custom scalar types are not supported")


def enum(type_: graphql.GraphQLEnumType, nullable: bool = True) -> st.SearchStrategy[graphql.EnumValueNode]:
    value = st.sampled_from(list(type_.values))
    return maybe_null(value.map(lambda v: graphql.EnumValueNode(value=v)), nullable)


def int_(nullable: bool = True) -> st.SearchStrategy[graphql.IntValueNode]:
    value = st.integers(min_value=MIN_INT, max_value=MAX_INT)
    return maybe_null(value.map(lambda v: graphql.IntValueNode(value=str(v))), nullable)


def float_(nullable: bool = True) -> st.SearchStrategy[graphql.FloatValueNode]:
    value = st.floats(allow_infinity=False, allow_nan=False)
    return maybe_null(value.map(lambda v: graphql.FloatValueNode(value=str(v))), nullable)


def string(nullable: bool = True) -> st.SearchStrategy[graphql.StringValueNode]:
    value = st.text(alphabet=st.characters(blacklist_categories=("Cs",), max_codepoint=0xFFFF))
    return maybe_null(value.map(lambda v: graphql.StringValueNode(value=v)), nullable)


def id_(nullable: bool = True) -> st.SearchStrategy[Union[graphql.StringValueNode, graphql.IntValueNode]]:
    return string(nullable) | int_(nullable)


def boolean(nullable: bool = True) -> st.SearchStrategy[graphql.BooleanValueNode]:
    return maybe_null(st.booleans().map(lambda v: graphql.BooleanValueNode(value=v)), nullable)


def maybe_null(strategy: st.SearchStrategy, nullable: bool) -> st.SearchStrategy:
    if nullable:
        strategy |= st.just(graphql.NullValueNode())
    return strategy
