#!/usr/bin/env python
"""Classes for export-related tests."""

from grr.core.grr_response_core.lib import rdfvalue
from grr.core.grr_response_core.lib.rdfvalues import structs as rdf_structs

from grr_response_proto import tests_pb2

from grr_response_server import export


class DataAgnosticConverterTestValue(rdf_structs.RDFProtoStruct):
  protobuf = tests_pb2.DataAgnosticConverterTestValue
  rdf_deps = [export.ExportedMetadata, rdfvalue.RDFDatetime, rdfvalue.RDFURN]


class DataAgnosticConverterTestValueWithMetadata(rdf_structs.RDFProtoStruct):
  protobuf = tests_pb2.DataAgnosticConverterTestValueWithMetadata
