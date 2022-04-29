# pylint: disable=unused-import
from ._strategies.schema import schemas
from ._strategies.strategy import from_schema, mutations, queries

# Backward compatibility
query = queries
schema = schemas
