#!/usr/bin/env python
"""This module contains regression tests for flows-related API handlers."""


import psutil

from grr.core.grr_response_core.lib import flags
from grr.core.grr_response_core.lib import registry
from grr.core.grr_response_core.lib import utils
from grr.core.grr_response_core.lib.rdfvalues import paths as rdf_paths
from grr_response_server import aff4
from grr_response_server import data_store
from grr_response_server import flow
from grr_response_server import output_plugin
from grr_response_server import queue_manager
from grr_response_server.flows.general import discovery
from grr_response_server.flows.general import file_finder
from grr_response_server.flows.general import processes
from grr_response_server.flows.general import transfer
from grr_response_server.gui import api_regression_test_lib
from grr_response_server.gui.api_plugins import flow as flow_plugin
from grr_response_server.output_plugins import email_plugin
from grr_response_server.rdfvalues import flow_runner as rdf_flow_runner
from grr.test_lib import acl_test_lib
from grr.test_lib import client_test_lib
from grr.test_lib import flow_test_lib
from grr.test_lib import hunt_test_lib
from grr.test_lib import test_lib


class ApiGetFlowHandlerRegressionTest(
    api_regression_test_lib.ApiRegressionTest):
  """Regression test for ApiGetFlowHandler."""

  api_method = "GetFlow"
  handler = flow_plugin.ApiGetFlowHandler

  def Run(self):
    # Fix the time to avoid regressions.
    with test_lib.FakeTime(42):
      client_urn = self.SetupClient(0)

      # Delete the certificates as it's being regenerated every time the
      # client is created.
      with aff4.FACTORY.Open(
          client_urn, mode="rw", token=self.token) as client_obj:
        client_obj.DeleteAttribute(client_obj.Schema.CERT)

      flow_id = flow.StartFlow(
          flow_name=discovery.Interrogate.__name__,
          client_id=client_urn,
          token=self.token)

      self.Check(
          "GetFlow",
          args=flow_plugin.ApiGetFlowArgs(
              client_id=client_urn.Basename(), flow_id=flow_id.Basename()),
          replace={flow_id.Basename(): "F:ABCDEF12"})

      with data_store.DB.GetMutationPool() as pool:
        flow.GRRFlow.MarkForTermination(
            flow_id, reason="Some reason", mutation_pool=pool)

      # Fetch the same flow which is now should be marked as pending
      # termination.
      self.Check(
          "GetFlow",
          args=flow_plugin.ApiGetFlowArgs(
              client_id=client_urn.Basename(), flow_id=flow_id.Basename()),
          replace={flow_id.Basename(): "F:ABCDEF13"})


class ApiListFlowsHandlerRegressionTest(
    api_regression_test_lib.ApiRegressionTest):
  """Test client flows list handler."""

  api_method = "ListFlows"
  handler = flow_plugin.ApiListFlowsHandler

  def Run(self):
    acl_test_lib.CreateUser(self.token.username)
    with test_lib.FakeTime(42):
      client_urn = self.SetupClient(0)

    with test_lib.FakeTime(43):
      flow_id_1 = flow.StartFlow(
          flow_name=discovery.Interrogate.__name__,
          client_id=client_urn,
          token=self.token)

    with test_lib.FakeTime(44):
      flow_id_2 = flow.StartFlow(
          flow_name=processes.ListProcesses.__name__,
          client_id=client_urn,
          token=self.token)

    self.Check(
        "ListFlows",
        args=flow_plugin.ApiListFlowsArgs(client_id=client_urn.Basename()),
        replace={
            flow_id_1.Basename(): "F:ABCDEF10",
            flow_id_2.Basename(): "F:ABCDEF11"
        })


class ApiListFlowRequestsHandlerRegressionTest(
    api_regression_test_lib.ApiRegressionTest):
  """Regression test for ApiListFlowRequestsHandler."""

  api_method = "ListFlowRequests"
  handler = flow_plugin.ApiListFlowRequestsHandler

  def Run(self):
    client_id = self.SetupClient(0)
    with test_lib.FakeTime(42):
      flow_urn = flow.StartFlow(
          flow_name=processes.ListProcesses.__name__,
          client_id=client_id,
          token=self.token)

      test_process = client_test_lib.MockWindowsProcess(name="test_process")
      with utils.Stubber(psutil, "Process", lambda: test_process):
        mock = flow_test_lib.MockClient(client_id, None, token=self.token)
        while mock.Next():
          pass

    replace = {flow_urn.Basename(): "W:ABCDEF"}

    manager = queue_manager.QueueManager(token=self.token)
    requests_responses = manager.FetchRequestsAndResponses(flow_urn)
    for request, responses in requests_responses:
      replace[str(request.request.task_id)] = "42"
      for response in responses:
        replace[str(response.task_id)] = "42"

    self.Check(
        "ListFlowRequests",
        args=flow_plugin.ApiListFlowRequestsArgs(
            client_id=client_id.Basename(), flow_id=flow_urn.Basename()),
        replace=replace)


class ApiListFlowResultsHandlerRegressionTest(
    api_regression_test_lib.ApiRegressionTest):
  """Regression test for ApiListFlowResultsHandler."""

  api_method = "ListFlowResults"
  handler = flow_plugin.ApiListFlowResultsHandler

  def Run(self):
    acl_test_lib.CreateUser(self.token.username)
    client_id = self.SetupClient(0)
    runner_args = rdf_flow_runner.FlowRunnerArgs(
        flow_name=transfer.GetFile.__name__)

    flow_args = transfer.GetFileArgs(
        pathspec=rdf_paths.PathSpec(
            path="/tmp/evil.txt", pathtype=rdf_paths.PathSpec.PathType.OS))

    client_mock = hunt_test_lib.SampleHuntMock()

    with test_lib.FakeTime(42):
      flow_urn = flow.StartFlow(
          client_id=client_id,
          args=flow_args,
          runner_args=runner_args,
          token=self.token)

      flow_test_lib.TestFlowHelper(
          flow_urn,
          client_mock=client_mock,
          client_id=client_id,
          token=self.token)

    self.Check(
        "ListFlowResults",
        args=flow_plugin.ApiListFlowResultsArgs(
            client_id=client_id.Basename(), flow_id=flow_urn.Basename()),
        replace={flow_urn.Basename(): "W:ABCDEF"})


class ApiListFlowLogsHandlerRegressionTest(
    api_regression_test_lib.ApiRegressionTest):
  """Regression test for ApiListFlowResultsHandler."""

  api_method = "ListFlowLogs"
  handler = flow_plugin.ApiListFlowLogsHandler

  def Run(self):
    client_id = self.SetupClient(0)
    flow_urn = flow.StartFlow(
        flow_name=processes.ListProcesses.__name__,
        client_id=client_id,
        token=self.token)

    with aff4.FACTORY.Open(flow_urn, mode="rw", token=self.token) as flow_obj:
      with test_lib.FakeTime(52):
        flow_obj.Log("Sample message: foo.")

      with test_lib.FakeTime(55):
        flow_obj.Log("Sample message: bar.")

    replace = {flow_urn.Basename(): "W:ABCDEF"}
    self.Check(
        "ListFlowLogs",
        args=flow_plugin.ApiListFlowLogsArgs(
            client_id=client_id.Basename(), flow_id=flow_urn.Basename()),
        replace=replace)
    self.Check(
        "ListFlowLogs",
        args=flow_plugin.ApiListFlowLogsArgs(
            client_id=client_id.Basename(),
            flow_id=flow_urn.Basename(),
            count=1),
        replace=replace)
    self.Check(
        "ListFlowLogs",
        args=flow_plugin.ApiListFlowLogsArgs(
            client_id=client_id.Basename(),
            flow_id=flow_urn.Basename(),
            count=1,
            offset=1),
        replace=replace)


class ApiGetFlowResultsExportCommandHandlerRegressionTest(
    api_regression_test_lib.ApiRegressionTest):
  """Regression test for ApiGetFlowResultsExportCommandHandler."""

  api_method = "GetFlowResultsExportCommand"
  handler = flow_plugin.ApiGetFlowResultsExportCommandHandler

  def Run(self):
    client_id = self.SetupClient(0)
    with test_lib.FakeTime(42):
      flow_urn = flow.StartFlow(
          flow_name=processes.ListProcesses.__name__,
          client_id=client_id,
          token=self.token)

    self.Check(
        "GetFlowResultsExportCommand",
        args=flow_plugin.ApiGetFlowResultsExportCommandArgs(
            client_id=client_id.Basename(), flow_id=flow_urn.Basename()),
        replace={flow_urn.Basename()[2:]: "ABCDEF"})


class ApiListFlowOutputPluginsHandlerRegressionTest(
    api_regression_test_lib.ApiRegressionTest):
  """Regression test for ApiListFlowOutputPluginsHandler."""

  api_method = "ListFlowOutputPlugins"
  handler = flow_plugin.ApiListFlowOutputPluginsHandler

  # ApiOutputPlugin's state is an AttributedDict containing URNs that
  # are always random. Given that currently their JSON representation
  # is proto-serialized and then base64-encoded, there's no way
  # we can replace these URNs with something stable.
  uses_legacy_dynamic_protos = True

  def Run(self):
    client_id = self.SetupClient(0)
    email_descriptor = output_plugin.OutputPluginDescriptor(
        plugin_name=email_plugin.EmailOutputPlugin.__name__,
        plugin_args=email_plugin.EmailOutputPluginArgs(
            email_address="test@localhost", emails_limit=42))

    with test_lib.FakeTime(42):
      flow_urn = flow.StartFlow(
          flow_name=processes.ListProcesses.__name__,
          client_id=client_id,
          output_plugins=[email_descriptor],
          token=self.token)

    self.Check(
        "ListFlowOutputPlugins",
        args=flow_plugin.ApiListFlowOutputPluginsArgs(
            client_id=client_id.Basename(), flow_id=flow_urn.Basename()),
        replace={flow_urn.Basename(): "W:ABCDEF"})


class ApiListFlowOutputPluginLogsHandlerRegressionTest(
    api_regression_test_lib.ApiRegressionTest):
  """Regression test for ApiListFlowOutputPluginLogsHandler."""

  api_method = "ListFlowOutputPluginLogs"
  handler = flow_plugin.ApiListFlowOutputPluginLogsHandler

  # ApiOutputPlugin's state is an AttributedDict containing URNs that
  # are always random. Given that currently their JSON representation
  # is proto-serialized and then base64-encoded, there's no way
  # we can replace these URNs with something stable.
  uses_legacy_dynamic_protos = True

  def Run(self):
    client_id = self.SetupClient(0)
    email_descriptor = output_plugin.OutputPluginDescriptor(
        plugin_name=email_plugin.EmailOutputPlugin.__name__,
        plugin_args=email_plugin.EmailOutputPluginArgs(
            email_address="test@localhost", emails_limit=42))

    with test_lib.FakeTime(42):
      flow_urn = flow.StartFlow(
          flow_name=flow_test_lib.DummyFlowWithSingleReply.__name__,
          client_id=client_id,
          output_plugins=[email_descriptor],
          token=self.token)

    with test_lib.FakeTime(43):
      flow_test_lib.TestFlowHelper(flow_urn, token=self.token)

    self.Check(
        "ListFlowOutputPluginLogs",
        args=flow_plugin.ApiListFlowOutputPluginLogsArgs(
            client_id=client_id.Basename(),
            flow_id=flow_urn.Basename(),
            plugin_id="EmailOutputPlugin_0"),
        replace={flow_urn.Basename(): "W:ABCDEF"})


class ApiListFlowOutputPluginErrorsHandlerRegressionTest(
    api_regression_test_lib.ApiRegressionTest):
  """Regression test for ApiListFlowOutputPluginErrorsHandler."""

  api_method = "ListFlowOutputPluginErrors"
  handler = flow_plugin.ApiListFlowOutputPluginErrorsHandler

  # ApiOutputPlugin's state is an AttributedDict containing URNs that
  # are always random. Given that currently their JSON representation
  # is proto-serialized and then base64-encoded, there's no way
  # we can replace these URNs with something stable.
  uses_legacy_dynamic_protos = True

  def Run(self):
    client_id = self.SetupClient(0)
    failing_descriptor = output_plugin.OutputPluginDescriptor(
        plugin_name=hunt_test_lib.FailingDummyHuntOutputPlugin.__name__)

    with test_lib.FakeTime(42):
      flow_urn = flow.StartFlow(
          flow_name=flow_test_lib.DummyFlowWithSingleReply.__name__,
          client_id=client_id,
          output_plugins=[failing_descriptor],
          token=self.token)

    with test_lib.FakeTime(43):
      flow_test_lib.TestFlowHelper(flow_urn, token=self.token)

    self.Check(
        "ListFlowOutputPluginErrors",
        args=flow_plugin.ApiListFlowOutputPluginErrorsArgs(
            client_id=client_id.Basename(),
            flow_id=flow_urn.Basename(),
            plugin_id="FailingDummyHuntOutputPlugin_0"),
        replace={flow_urn.Basename(): "W:ABCDEF"})


class ApiCreateFlowHandlerRegressionTest(
    api_regression_test_lib.ApiRegressionTest):
  """Regression test for ApiCreateFlowHandler."""

  api_method = "CreateFlow"
  handler = flow_plugin.ApiCreateFlowHandler

  def Run(self):
    client_id = self.SetupClient(0)

    def ReplaceFlowId():
      flows_dir_fd = aff4.FACTORY.Open(client_id.Add("flows"), token=self.token)
      flow_urn = list(flows_dir_fd.ListChildren())[0]
      return {flow_urn.Basename(): "W:ABCDEF"}

    with test_lib.FakeTime(42):
      self.Check(
          "CreateFlow",
          args=flow_plugin.ApiCreateFlowArgs(
              client_id=client_id.Basename(),
              flow=flow_plugin.ApiFlow(
                  name=processes.ListProcesses.__name__,
                  args=processes.ListProcessesArgs(
                      filename_regex=".", fetch_binaries=True),
                  runner_args=rdf_flow_runner.FlowRunnerArgs(
                      output_plugins=[],
                      priority="HIGH_PRIORITY",
                      notify_to_user=False))),
          replace=ReplaceFlowId)


class ApiCancelFlowHandlerRegressionTest(
    api_regression_test_lib.ApiRegressionTest):
  """Regression test for ApiCancelFlowHandler."""

  api_method = "CancelFlow"
  handler = flow_plugin.ApiCancelFlowHandler

  def Run(self):
    client_id = self.SetupClient(0)
    with test_lib.FakeTime(42):
      flow_urn = flow.StartFlow(
          flow_name=processes.ListProcesses.__name__,
          client_id=client_id,
          token=self.token)

    self.Check(
        "CancelFlow",
        args=flow_plugin.ApiCancelFlowArgs(
            client_id=client_id.Basename(), flow_id=flow_urn.Basename()),
        replace={flow_urn.Basename(): "W:ABCDEF"})


class ApiListFlowDescriptorsHandlerRegressionTest(
    api_regression_test_lib.ApiRegressionTest, acl_test_lib.AclTestMixin):
  """Regression test for ApiListFlowDescriptorsHandler."""

  api_method = "ListFlowDescriptors"
  handler = flow_plugin.ApiListFlowDescriptorsHandler

  def Run(self):
    with utils.Stubber(
        registry.FlowRegistry, "FLOW_REGISTRY", {
            processes.ListProcesses.__name__: processes.ListProcesses,
            file_finder.FileFinder.__name__: file_finder.FileFinder,
        }):
      # RunReport flow is only shown for admins.
      self.CreateAdminUser("test")

      self.Check("ListFlowDescriptors")


def main(argv):
  api_regression_test_lib.main(argv)


if __name__ == "__main__":
  flags.StartMain(main)
