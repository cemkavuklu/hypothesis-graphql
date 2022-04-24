import graphql
import pytest
from graphql import GraphQLNamedType
from hypothesis import assume, find, given
from hypothesis import strategies as st

from hypothesis_graphql import strategies as gql_st
from hypothesis_graphql._strategies.selections import value_nodes
from hypothesis_graphql.cache import cached_build_schema


@pytest.fixture(scope="session")
def simple_schema(schema):
    return (
        schema
        + """type Query {
          getBooks: [Book]
          getAuthors: [Author]
        }"""
    )


@pytest.mark.parametrize(
    "query_type",
    (
        """type Query {
      getBooks: [Book]
      getAuthors: [Author]
    }""",
        """type Query {
      getBooksByAuthor(name: String): [Book]
    }""",
    ),
)
@given(data=st.data())
def test_query(data, schema, query_type, validate_operation):
    schema = schema + query_type
    query = data.draw(gql_st.queries(schema))
    validate_operation(schema, query)


@given(data=st.data())
def test_query_subset(data, simple_schema, validate_operation):
    query = data.draw(gql_st.queries(simple_schema, fields=["getBooks"]))
    validate_operation(simple_schema, query)
    assert "getAuthors" not in query


def test_empty_fields(simple_schema):
    with pytest.raises(ValueError, match="If you pass `fields`, it should not be empty"):
        gql_st.queries(simple_schema, fields=[])


def test_wrong_fields(simple_schema):
    with pytest.raises(ValueError, match="Unknown fields: wrong"):
        gql_st.queries(simple_schema, fields=["wrong"])


@given(data=st.data())
def test_query_from_graphql_schema(data, schema, validate_operation):
    query = """type Query {
      getBooksByAuthor(name: String): [Book]
    }"""
    schema = cached_build_schema(schema + query)
    query = data.draw(gql_st.queries(schema))
    validate_operation(schema, query)


@pytest.mark.parametrize("notnull", (True, False))
@pytest.mark.parametrize(
    "arguments, node_names",
    (
        ("int: Int", ("IntValueNode",)),
        ("float: Float", ("FloatValueNode",)),
        ("string: String", ("StringValueNode",)),
        ("id: ID", ("IntValueNode", "StringValueNode")),
        ("boolean: Boolean", ("BooleanValueNode",)),
        ("color: Color", ("EnumValueNode",)),
        ("color: EnumInput", ("EnumValueNode",)),
        ("contain: [Int]", ("ListValueNode", "IntValueNode")),
        ("contain: [Int!]", ("ListValueNode", "IntValueNode")),
        ("contain: [Float]", ("ListValueNode", "FloatValueNode")),
        ("contain: [Float!]", ("ListValueNode", "FloatValueNode")),
        ("contain: [String]", ("ListValueNode", "StringValueNode")),
        ("contain: [String!]", ("ListValueNode", "StringValueNode")),
        ("contain: [Boolean]", ("ListValueNode", "BooleanValueNode")),
        ("contain: [Boolean!]", ("ListValueNode", "BooleanValueNode")),
        ("contain: [Color]", ("ListValueNode", "EnumValueNode")),
        ("contain: [Color!]", ("ListValueNode", "EnumValueNode")),
        ("contain: [[Int]]", ("ListValueNode", "IntValueNode")),
        ("contain: [[Int]!]", ("ListValueNode", "IntValueNode")),
        ("contains: QueryInput", ("ObjectValueNode",)),
        ("contains: RequiredInput", ("ObjectValueNode",)),
        ("contains: NestedQueryInput", ("ObjectValueNode",)),
    ),
)
@given(data=st.data())
def test_arguments(data, schema, arguments, node_names, notnull, validate_operation):
    if notnull:
        arguments += "!"
    query_type = f"""type Query {{
      getModel({arguments}): Model
    }}"""

    schema = schema + query_type
    query = data.draw(gql_st.queries(schema))
    validate_operation(schema, query)
    for node_name in node_names:
        assert node_name not in query
    if notnull:
        assert "getModel(" in query
    parsed = graphql.parse(query)
    selection = parsed.definitions[0].selection_set.selections[0]
    if notnull:
        # there should be one argument if it is not null
        assert len(selection.arguments) == 1
    # at least one Model field is selected
    assert len(selection.selection_set.selections) > 0


@pytest.mark.parametrize(
    "query_type",
    (
        "type Query { getModel: Node }",
        "type Query { getModel: Alone }",
    ),
)
@given(data=st.data())
def test_interface(data, schema, query_type, validate_operation):
    schema = schema + query_type
    parsed_schema = cached_build_schema(schema)
    query = data.draw(gql_st.queries(schema))
    validate_operation(parsed_schema, query)


@pytest.mark.parametrize(
    "query, minimum",
    (
        (
            "getAuthors: [Author]",
            "",
        ),
        (
            "getAuthors(value: Int!): [Author]",
            "(value: 0)",
        ),
        (
            "getAuthors(value: Float!): [Author]",
            "(value: 0.0)",
        ),
        (
            "getAuthors(value: String!): [Author]",
            '(value: "")',
        ),
        (
            "getAuthors(value: Color!): [Author]",
            "(value: RED)",
        ),
    ),
)
def test_minimal_queries(query, schema, minimum):
    schema = schema + f"type Query {{ {query} }}"
    strategy = gql_st.queries(schema)
    minimal_query = f"""{{
  getAuthors{minimum} {{
    name
  }}
}}"""
    assert find(strategy, lambda x: True).strip() == minimal_query


def test_missing_query():
    schema = """type Author {
      name: String
    }"""
    with pytest.raises(ValueError, match="Query type is not defined in the schema"):
        gql_st.queries(schema)


def test_unknown_type():
    # If there will be a new input type in `graphql`

    class NewType(GraphQLNamedType):
        pass

    with pytest.raises(TypeError, match="Type NewType is not supported."):
        value_nodes(None, NewType("Test"))


CUSTOM_SCALAR_TEMPLATE = """
scalar Date

type Object {{
  created: Date
}}
type Query {{
  {query}
}}
"""


@given(data=st.data())
def test_custom_scalar_non_argument(data, validate_operation):
    # When a custom scalar type is defined
    # And is used in a non-argument position

    schema = CUSTOM_SCALAR_TEMPLATE.format(query="getObjects: [Object]")
    query = data.draw(gql_st.queries(schema))
    validate_operation(schema, query)
    # Then queries should be generated
    assert "created" in query


def test_custom_scalar_argument_nullable(validate_operation):
    # When a custom scalar type is defined
    # And is used in an argument position
    # And is nullable
    # And there are no other arguments

    num_of_queries = 0

    schema = CUSTOM_SCALAR_TEMPLATE.format(query="getByDate(created: Date): Object")

    @given(query=gql_st.queries(schema))
    def test(query):
        nonlocal num_of_queries

        num_of_queries += 1
        validate_operation(schema, query)
        assert "getByDate {" in query

    test()
    # Then only one query should be generated
    assert num_of_queries == 1


@given(data=st.data())
def test_custom_scalar_argument(data):
    # When a custom scalar type is defined
    # And is used in an argument position
    # And is not nullable

    query = CUSTOM_SCALAR_TEMPLATE.format(query="getByDate(created: Date!): Object")

    with pytest.raises(TypeError, match="Non-nullable custom scalar types are not supported as arguments"):
        data.draw(gql_st.queries(query))


@given(data=st.data())
def test_no_surrogates(data, validate_operation):
    # Unicode surrogates are not supported by GraphQL spec
    schema = """
    type Query {
        hello(user: String!): String
    }
    """
    query = data.draw(gql_st.queries(schema))
    document = validate_operation(schema, query)
    argument_node = document.definitions[0].selection_set.selections[0].arguments[0]
    assume(argument_node.name.value == "user")
    value = argument_node.value.value
    value.encode("utf8")


@pytest.mark.parametrize(
    "schema",
    (
        """interface Conflict {
  id: ID
}

type FloatModel implements Conflict {
  id: ID,
  query: Float!
}

type StringModel implements Conflict {
  id: ID,
  query: String!
}

type Query {
  getData: Conflict
}""",
        """type FloatModel {
  query: Float!
}
type StringModel {
  query: String!
}

union Conflict = FloatModel | StringModel

type Query {
  getData: Conflict
}""",
    ),
    ids=("interface", "union"),
)
@given(data=st.data())
def test_conflicting_field_types(data, validate_operation, schema):
    # See GH-49
    # When Query contain types on the same level that have fields with the same name but with different types
    query = data.draw(gql_st.queries(schema))
    # Then no invalid queries should be generated
    validate_operation(schema, query)
