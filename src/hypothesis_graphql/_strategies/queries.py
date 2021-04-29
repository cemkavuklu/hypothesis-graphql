"""Strategies for GraphQL queries."""
from functools import partial
from typing import Callable, Iterable, List, Optional, Tuple, Union

import graphql
from hypothesis import strategies as st

from ..types import Field, InputTypeNode
from . import primitives


def query(schema: Union[str, graphql.GraphQLSchema], fields: Optional[Iterable[str]] = None) -> st.SearchStrategy[str]:
    """A strategy for generating valid queries for the given GraphQL schema.

    The output query will contain a subset of fields defined in the `Query` type.

    :param schema: GraphQL schema as a string or `graphql.GraphQLSchema`.
    :param fields: Restrict generated fields to ones in this list.
    """
    if isinstance(schema, str):
        parsed_schema = graphql.build_schema(schema)
    else:
        parsed_schema = schema
    if parsed_schema.query_type is None:
        raise ValueError("Query type is not defined in the schema")
    if fields is not None:
        fields = tuple(fields)
        if not fields:
            raise ValueError("If you pass `fields`, it should not be empty")
        invalid_fields = tuple(field for field in fields if field not in parsed_schema.query_type.fields)
        if invalid_fields:
            raise ValueError(f"Unknown fields: {', '.join(invalid_fields)}")
    return _fields(parsed_schema.query_type, fields=fields).map(make_query).map(graphql.print_ast)


def _fields(
    object_type: graphql.GraphQLObjectType, fields: Optional[Tuple[str, ...]] = None
) -> st.SearchStrategy[List[graphql.FieldNode]]:
    """Generate a subset of fields defined on the given type."""
    if fields:
        subset = {name: value for name, value in object_type.fields.items() if name in fields}
    else:
        subset = object_type.fields
    # minimum 1 field, an empty query is not valid
    return subset_of_fields(**subset).flatmap(lists_of_field_nodes)


make_selection_set_node = partial(graphql.SelectionSetNode, kind="selection_set")


def make_query(selections: List[graphql.FieldNode]) -> graphql.DocumentNode:
    """Create top-level node for a query AST."""
    return graphql.DocumentNode(
        kind="document",
        definitions=[
            graphql.OperationDefinitionNode(
                kind="operation_definition",
                operation=graphql.OperationType.QUERY,
                selection_set=make_selection_set_node(selections=selections),
            )
        ],
    )


def field_nodes(name: str, field: graphql.GraphQLField) -> st.SearchStrategy[graphql.FieldNode]:
    """Generate a single field node with optional children."""
    return st.builds(
        partial(graphql.FieldNode, name=graphql.NameNode(value=name)),
        arguments=list_of_arguments(**field.args),
        selection_set=st.builds(make_selection_set_node, selections=fields_for_type(field)),
    )


def fields_for_type(
    field: graphql.GraphQLField,
) -> st.SearchStrategy[Union[List[graphql.FieldNode], List[graphql.InlineFragmentNode], None]]:
    """Extract proper type from the field and generate field nodes for this type."""
    type_ = field.type
    while isinstance(type_, graphql.GraphQLWrappingType):
        type_ = type_.of_type
    if isinstance(type_, graphql.GraphQLObjectType):
        return _fields(type_)
    if isinstance(type_, graphql.GraphQLUnionType):
        # A union is a set of object types
        return st.lists(st.sampled_from(type_.types), min_size=1, unique_by=lambda m: m.name).flatmap(inline_fragments)
    # Only object has field, others don't
    return st.none()


def inline_fragments(items: List[graphql.GraphQLObjectType]) -> st.SearchStrategy[List[graphql.InlineFragmentNode]]:
    """Create inline fragment nodes for each given item."""
    return st.tuples(*(inline_fragment(type_) for type_ in items)).map(list)


def inline_fragment(type_: graphql.GraphQLObjectType) -> st.SearchStrategy[graphql.InlineFragmentNode]:
    return st.builds(
        partial(
            graphql.InlineFragmentNode, type_condition=graphql.NamedTypeNode(name=graphql.NameNode(value=type_.name))
        ),
        selection_set=st.builds(make_selection_set_node, selections=_fields(type_)),
    )


def list_of_arguments(**kwargs: graphql.GraphQLArgument) -> st.SearchStrategy[List[graphql.ArgumentNode]]:
    """Generate a list `graphql.ArgumentNode` for a field."""
    args = []
    for name, argument in kwargs.items():
        try:
            argument_strategy = argument_values(argument)
        except TypeError as exc:
            if not isinstance(argument.type, graphql.GraphQLNonNull):
                continue
            raise TypeError("Non-nullable custom scalar types are not supported as arguments") from exc
        args.append(
            st.builds(partial(graphql.ArgumentNode, name=graphql.NameNode(value=name)), value=argument_strategy)
        )
    return st.tuples(*args).map(list)


def argument_values(argument: graphql.GraphQLArgument) -> st.SearchStrategy[InputTypeNode]:
    """Value of `graphql.ArgumentNode`."""
    return value_nodes(argument.type)


def value_nodes(type_: graphql.GraphQLInputType) -> st.SearchStrategy[InputTypeNode]:
    """Generate value nodes of a type, that corresponds to the input type.

    They correspond to all `GraphQLInputType` variants:
        - GraphQLScalarType -> ScalarValueNode
        - GraphQLEnumType -> EnumValueNode
        - GraphQLInputObjectType -> ObjectValueNode

    GraphQLWrappingType[T] is unwrapped:
        - GraphQLList -> ListValueNode[T]
        - GraphQLNonNull -> T (processed with nullable=False)
    """
    type_, nullable = check_nullable(type_)
    # Types without children
    if isinstance(type_, graphql.GraphQLScalarType):
        return primitives.scalar(type_, nullable)
    if isinstance(type_, graphql.GraphQLEnumType):
        return primitives.enum(type_, nullable)
    # Types with children
    if isinstance(type_, graphql.GraphQLList):
        return lists(type_, nullable)
    if isinstance(type_, graphql.GraphQLInputObjectType):
        return objects(type_, nullable)
    raise TypeError(f"Type {type_.__class__.__name__} is not supported.")


def check_nullable(type_: graphql.GraphQLInputType) -> Tuple[graphql.GraphQLInputType, bool]:
    """Get the wrapped type and detect if it is nullable."""
    nullable = True
    if isinstance(type_, graphql.GraphQLNonNull):
        type_ = type_.of_type
        nullable = False
    return type_, nullable


def lists(type_: graphql.GraphQLList, nullable: bool = True) -> st.SearchStrategy[graphql.ListValueNode]:
    """Generate a `graphql.ListValueNode`."""
    type_ = type_.of_type
    list_value = st.lists(value_nodes(type_))
    if nullable:
        list_value |= st.none()
    return st.builds(graphql.ListValueNode, values=list_value)


def objects(type_: graphql.GraphQLInputObjectType, nullable: bool = True) -> st.SearchStrategy[graphql.ObjectValueNode]:
    """Generate a `graphql.ObjectValueNode`."""
    fields_value = subset_of_fields(**type_.fields).flatmap(list_of_object_field_nodes)
    if nullable:
        fields_value |= st.none()
    return st.builds(graphql.ObjectValueNode, fields=fields_value)


def subset_of_fields(**all_fields: Field) -> st.SearchStrategy[List[Tuple[str, Field]]]:
    """A helper to select a subset of fields."""
    field_pairs = sorted(all_fields.items())
    # pairs are unique by field name
    return st.lists(st.sampled_from(field_pairs), min_size=1, unique_by=lambda x: x[0])


def object_field_nodes(name: str, field: graphql.GraphQLInputField) -> st.SearchStrategy[graphql.ObjectFieldNode]:
    return st.builds(
        partial(graphql.ObjectFieldNode, name=graphql.NameNode(value=name)),
        value=value_nodes(field.type),
    )


def list_of_nodes(
    items: List[Tuple],
    strategy: Callable[[str, Field], st.SearchStrategy],
) -> st.SearchStrategy[List]:
    return st.tuples(*(strategy(name, field) for name, field in items)).map(list)


list_of_object_field_nodes = partial(list_of_nodes, strategy=object_field_nodes)
lists_of_field_nodes = partial(list_of_nodes, strategy=field_nodes)
