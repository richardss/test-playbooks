import json
import logging
import os
import random
import re
import subprocess
import sys
import time
import traceback

import pytest

from tests.api import Base_Api_Test
from towerkit import utils
from towerkit.api import Connection

log = logging.getLogger(__name__)

FAIL_STATUSES = ('error', 'failed')


class SafeStop(object):
    """A context manager that stops tower services on a single or multiple hosts
    and guarantees to restart the tower services on exit."""

    def __init__(self, stoppers, starters):
        if not isinstance(stoppers, list):
            stoppers = [stoppers]
        if not isinstance(starters, list):
            starters = [starters]
        self.stoppers = stoppers
        self.starters = starters
        self.stop_exceptions = []
        self.start_exceptions = []

    def __enter__(self):
        for stop in self.stoppers:
            self.safe_call(stop, self.stop_exceptions)
        if self.stop_exceptions:
            # Ensure we call starters if any stoppers failed
            self.__exit__()
        return self

    def __exit__(self, *exc_info):
        for start in self.starters:
            self.safe_call(start, self.start_exceptions)
        # Check if we have an exceptional exit
        self.raise_errors(exc_info)
        return False

    def safe_call(self, func, exceptions):
        try:
            func()
        except:
            exceptions.append(sys.exc_info())

    def raise_errors(self, final_error=()):
        have_exceptions = self.stop_exceptions or self.start_exceptions
        if not have_exceptions and not any(final_error):
            # No exceptions, normal exit
            return
        stop_message = self.build_error_message(self.stop_exceptions, during_stop=True)
        start_message = self.build_error_message(self.start_exceptions)
        final_error_message = ''

        if any(final_error):
            msg = 'Exception raised during test:\n\n{}\n\n'
            error_info = traceback.format_exc(final_error)
            final_error_message = msg.format(error_info)

        raise Exception(stop_message + start_message + final_error_message)

    def build_error_message(self, errors, during_stop=True):
        if not errors:
            return ''
        # We have an exceptional exit
        event = 'starting' if during_stop is False else 'stopping'
        error_info = '\n\n'.join([traceback.format_exc(info[2]) for info in errors])
        return 'Exceptions raised {} nodes:\n\n{}\n\n'.format(event, error_info)


@pytest.mark.api
@pytest.mark.skip_selenium
@pytest.mark.skip_docker
@pytest.mark.usefixtures('authtoken', 'install_enterprise_license_unlimited')
class TestInstanceGroups(Base_Api_Test):

    @staticmethod
    def get_resource(jt, resource):
        if resource == 'job_template':
            return jt
        elif resource == 'inventory':
            return jt.ds.inventory
        elif resource == 'organization':
            return jt.ds.inventory.ds.organization
        else:
            raise ValueError("Unsupported resource: {0}".format(resource))

    def mutually_exclusive_instance_groups(self, instance_groups):
        instance_group_to_instances_map = [(instance_group, set([instance.id for instance in instance_group.get_related('instances').results]))
                                           for instance_group in instance_groups]
        for first in instance_group_to_instances_map:
            for second in instance_group_to_instances_map:
                if not (first[1] & second[1]):
                    return first[0], second[0]
        pytest.skip("Unable to find two mutually exclusive instance groups")

    def get_stop_and_start_funcs_for_node(self, admin_user, manager, hostname, v2):
        username = manager.get_host(hostname).get_vars()['ansible_user']
        # "-t" (twice) gives us a tty which is needed for sudo
        ssh_template = "ssh -o StrictHostKeyChecking=no -t -t {} 'sudo ansible-tower-service {}' 1>&2"
        ssh_invocation = "{}@{}".format(username, hostname)

        def offline():
            try:
                v2.get()
            except:
                # Possible errors here include ConnectionError, UnknownTowerState and
                # exc.Unknown, so we assume any exception means the tower node is
                # offline.
                return True
            return False

        connection = Connection('https://' + hostname)
        connection.login(admin_user.username, admin_user.password)

        def stop_node():
            with self.current_instance(connection, v2):
                log.debug("Shutting down node {}".format(hostname))
                # Stop the tower node
                cmd = ssh_template.format(ssh_invocation, "stop")
                ret = subprocess.call(cmd, shell=True)
                assert ret == 0
                # Wait until it goes offline
                utils.poll_until(offline, interval=5, timeout=120)

        def start_node():
            with self.current_instance(connection, v2):
                # Start the tower node
                cmd = ssh_template.format(ssh_invocation, "start")
                ret = subprocess.call(cmd, shell=True)
                assert ret == 0
                # Wait until it comes online
                utils.poll_until(lambda: not offline(), interval=5, timeout=120)

        return stop_node, start_node

    def assert_job_stays_pending(self, job):
        pending_statuses = set(('pending', 'waiting'))
        start_time = time.time()
        timeout = 60
        interval = 5
        while True:
            job.get()
            assert job.status in pending_statuses

            elapsed = time.time() - start_time
            if elapsed > timeout:
                break
            time.sleep(interval)

    def test_instance_group_creation(self, authtoken, v2, ansible_runner):
        inventory_path = os.environ.get('TQA_INVENTORY_FILE_PATH', '/tmp/setup/inventory')
        cmd = 'scripts/ansible_inventory_to_json.py --inventory {0} --group-filter tower,instance_group_,isolated_group_'.format(inventory_path)
        contacted = ansible_runner.script(cmd)
        assert len(contacted.values()) == 1, "Failed to run script against Tower instance"

        group_mapping = json.loads(contacted.values().pop()['stdout'])
        for group in group_mapping.keys():
            match = re.search('(instance_group_|isolated_group_)(.*)', group)
            if match:
                group_mapping[match.group(2)] = group_mapping.pop(group)

        instance_groups = [group.name for group in v2.instance_groups.get().results]
        assert len(instance_groups) == len(group_mapping.keys())
        assert set(instance_groups) == set(group_mapping.keys())

        for group in v2.instance_groups.get().results:
            instances = [instance.hostname for instance in group.get_related('instances').results]
            assert len(instances) == len(group_mapping[group.name])
            assert set(instances) == set(group_mapping[group.name])

    @pytest.mark.requires_ha
    @pytest.mark.parametrize('resource', ['job_template', 'inventory', 'organization'])
    def test_job_template_executes_on_assigned_instance_group(self, v2, factories, resource):
        instance_groups = v2.instance_groups.get().results
        job_template_to_instance_group_map = []
        for ig in instance_groups:
            jt = factories.v2_job_template()
            self.get_resource(jt, resource).add_instance_group(ig)
            job_template_to_instance_group_map.append((jt, ig))

        for jt, _ in job_template_to_instance_group_map:
            jt.launch()
        for jt, _ in job_template_to_instance_group_map:
            jt.wait_until_completed()

        for jt, ig in job_template_to_instance_group_map:
            job = jt.get_related('last_job')
            assert job.instance_group == ig.id, "Job instance group differs from job template instance group"

            execution_host = job.execution_node
            instances = ig.get_related('instances').results
            assert any(execution_host in instance.hostname for instance in instances), \
                "Job not run on instance in assigned instance group"

    @pytest.mark.requires_ha
    def test_use_fact_cache_with_mutually_exclusive_instance_groups(self, v2, factories):
        instance_groups = v2.instance_groups.get().results
        ig1, ig2 = self.mutually_exclusive_instance_groups(instance_groups)
        host = factories.v2_host()
        gather_facts_jt = factories.v2_job_template(inventory=host.ds.inventory, playbook='gather_facts.yml', use_fact_cache=True)
        use_facts_jt = factories.v2_job_template(inventory=host.ds.inventory, playbook='use_facts.yml', job_tags='ansible_facts',
                                                 use_fact_cache=True)
        gather_facts_jt.add_instance_group(ig1)
        use_facts_jt.add_instance_group(ig2)

        gather_facts_job, use_facts_job = [jt.launch().wait_until_completed() for jt in (gather_facts_jt, use_facts_jt)]
        assert gather_facts_job.is_successful
        assert use_facts_job.is_successful

        ansible_facts = host.related.ansible_facts.get()
        assert use_facts_job.result_stdout.count(ansible_facts.ansible_distribution) == 1
        assert use_facts_job.result_stdout.count(ansible_facts.ansible_machine) == 1
        assert use_facts_job.result_stdout.count(ansible_facts.ansible_system) == 1

    @pytest.mark.requires_ha
    @pytest.mark.requires_isolation
    @pytest.mark.parametrize('base_resource, parent_resource', [('job_template', 'inventory'), ('job_template', 'organization'), ('inventory', 'organization')])
    def test_instance_group_hierarchy(self, v2, factories, base_resource, parent_resource):
        assert not len(v2.jobs.get(status='running').results), "Test requires Tower to not have any running jobs"

        instance_groups = sorted(v2.instance_groups.get().results, key=lambda x: x.instances)
        if len(instance_groups) == 1:
            pytest.skip('Test requires multiple instance groups')

        base_instance_group, parent_instance_group = self.mutually_exclusive_instance_groups(instance_groups)
        host = factories.v2_host()
        jt = factories.v2_job_template(inventory=host.ds.inventory, playbook='sleep.yml', extra_vars=dict(sleep_interval=600), allow_simultaneous=True)
        factories.v2_host(inventory=jt.ds.inventory)

        self.get_resource(jt, base_resource).add_instance_group(base_instance_group)
        self.get_resource(jt, parent_resource).add_instance_group(parent_instance_group)

        instance_group_to_hostnames_map = {instance_group.id: [instance.hostname for instance in instance_group.get_related('instances').results]
                                           for instance_group in instance_groups}
        while True:
            job = jt.launch()
            utils.poll_until(lambda: getattr(job.get(), 'execution_node') != '', interval=10, timeout=120)
            if job.execution_node in instance_group_to_hostnames_map[base_instance_group.id]:
                assert base_instance_group.get().percent_capacity_remaining >= 0
            else:
                break
        assert job.execution_node in instance_group_to_hostnames_map[parent_instance_group.id]
        assert parent_instance_group.get().consumed_capacity > \
            base_instance_group.capacity - base_instance_group.consumed_capacity

    @pytest.mark.requires_ha
    @pytest.mark.requires_isolation
    def test_job_run_against_isolated_node_ensure_viewable_from_all_nodes(self, ansible_module_cls, factories,
                                                                          admin_user, user_password, v2):
        manager = ansible_module_cls.inventory_manager
        hosts = manager.get_group_dict()['instance_group_ordinary_instances']
        managed = manager.get_group_dict().get('managed_hosts')[0]
        protected = v2.instance_groups.get(name='protected').results[0]

        username = manager.get_host(managed).get_vars().get('ansible_user')
        cred = factories.v2_credential(username=username, password=user_password)
        host = factories.host(name=managed, variables=dict(ansible_host=managed))
        jt = factories.v2_job_template(inventory=host.ds.inventory, credential=cred)
        jt.add_instance_group(protected)
        jt.launch().wait_until_completed()

        # update the job template and fetch the id of the job that just ran
        job = jt.get().get_related('last_job')
        job_id = job.id
        assert not job.failed

        # as the job ran on another node, fetch the standard out
        job.related.stdout.get(format='txt_download')
        stdout = job.get().result_stdout

        # assert the managed host appears in the output, ensuring the job ran
        # on the machine we specified
        assert managed in stdout
        # strip line endings and empty lines because output format varies
        canonical_stdout = [line for line in stdout.splitlines() if line]

        for host in hosts:
            connection = Connection('https://' + host)
            connection.login(admin_user.username, admin_user.password)
            with self.current_instance(connection, v2):
                job = v2.get().jobs.get(id=job_id).results[0]
                assert not job.failed

                job.related.stdout.get(format='txt_download')
                stdout = [line for line in job.get().result_stdout.splitlines() if line]
                assert stdout == canonical_stdout

    @pytest.mark.requires_isolation
    def test_capacity_when_no_jobs_running(self, v2):
        for ig in v2.instance_groups.get().results:
            utils.poll_until(lambda: ig.get().jobs_running == 0, interval=10, timeout=120)
            assert ig.consumed_capacity == 0
            assert ig.capacity > 0
            assert ig.percent_capacity_remaining == 100

            for instance in ig.get_related('instances').results:
                utils.poll_until(lambda: instance.get().jobs_running == 0, interval=10, timeout=60)
                assert instance.consumed_capacity == 0
                assert instance.capacity > 0
                assert instance.percent_capacity_remaining == 100

    @pytest.mark.requires_ha
    @pytest.mark.requires_isolation
    @pytest.mark.parametrize('run_on_isolated_group', [True, False], ids=['isolated group', 'regular instance group'])
    def test_running_jobs_consume_capacity(self, factories, v2, run_on_isolated_group):
        ig_filter = dict(name='protected') if run_on_isolated_group else dict(not__name='protected')
        ig = random.choice(v2.instance_groups.get(**ig_filter).results)
        # Ensure no capacity consumed initially
        utils.poll_until(lambda: ig.get().consumed_capacity == 0, interval=10, timeout=60)

        host = factories.v2_host()
        jt = factories.v2_job_template(inventory=host.ds.inventory, playbook='sleep.yml', extra_vars=dict(sleep_interval=600), allow_simultaneous=True)
        jt.add_instance_group(ig)

        previous_ig_consumed_capacity = 0
        for _ in range(3):
            job = jt.launch().wait_until_status('running')
            utils.poll_until(lambda: getattr(job.get(), 'execution_node') != '', interval=10, timeout=45)

            # Capacity should increase after each job launch
            assert ig.get().consumed_capacity > previous_ig_consumed_capacity
            previous_ig_consumed_capacity = ig.consumed_capacity
            assert ig.percent_capacity_remaining == round(float(ig.capacity - ig.consumed_capacity) * 100 / ig.capacity, 2)
            instance = [i for i in ig.get_related('instances').results if i.hostname == job.execution_node][0]

            assert instance.get().consumed_capacity > 0
            assert instance.percent_capacity_remaining == round(float(instance.capacity - instance.consumed_capacity) * 100 / instance.capacity, 1)

    @pytest.mark.requires_ha
    @pytest.mark.requires_isolation
    def test_controller_removal(self, admin_user, ansible_module_cls, factories, user_password, v2):
        """
        Test that shutting down tower services on both controller nodes prevents us from launching
        jobs against an isolated node. This also tests that a cluster can successfully recover after
        shutting down more than one node simultaneously."""
        manager = ansible_module_cls.inventory_manager
        hosts = manager.get_group_dict()['instance_group_ordinary_instances']
        controllers = manager.get_group_dict()['instance_group_controller']

        online_hostname = None
        stoppers, starters = [], []
        for host in hosts:
            if host not in controllers:
                online_hostname = host
                continue
            stop, start = self.get_stop_and_start_funcs_for_node(admin_user, manager, host, v2)
            starters.append(start)
            stoppers.append(stop)

        assert online_hostname is not None
        assert len(stoppers) == len(starters) == len(controllers)

        connection = Connection('https://' + online_hostname)
        connection.login(admin_user.username, admin_user.password)
        with self.current_instance(connection, v2):
            # Store original controller group capacity for later verification
            controller_group = v2.instance_groups.get(name="controller").results[0]
            original_capacity = controller_group.capacity

            # Start a long running job against the isolated node
            protected_group = v2.instance_groups.get(name="protected").results[0]

            host = factories.v2_host()
            jt = factories.v2_job_template(playbook='sleep.yml',
                                           extra_vars=dict(sleep_interval=600),
                                           inventory=host.ds.inventory)
            jt.add_instance_group(protected_group)
            long_job = jt.launch().wait_until_started()

            # Stop controller nodes
            with SafeStop(stoppers, starters):
                # Wait until controller group capacity is set to zero
                utils.poll_until(lambda: controller_group.get().capacity == 0, interval=5, timeout=120)

                # Check the long running job fails
                long_job.wait_until_status(FAIL_STATUSES, interval=5, timeout=180, since_job_created=False)

                # Should fail with explanation:
                explanation = "Task was marked as running in Tower but its  controller management daemon was not present in Celery, so it has been marked as failed. Task may still be running, but contactability is unknown."
                assert long_job.job_explanation == explanation

                # Start a new job and check it remains pending
                jt = factories.v2_job_template(inventory=host.ds.inventory)
                jt.add_instance_group(protected_group)
                job = jt.launch()

                # Check it stays in pending
                self.assert_job_stays_pending(job)

            # Check group capacity is restored
            utils.poll_until(lambda: controller_group.get().capacity == original_capacity, interval=5, timeout=120)

            # Check the pending job is picked up
            job.wait_until_completed(since_job_created=False)
            # Check we can successfully launch a new job against the isolated node
            job = jt.launch().wait_until_completed()
            assert job.is_successful

    @pytest.mark.requires_ha
    @pytest.mark.requires_isolation
    def test_instance_removal(self, admin_user, ansible_module_cls, factories, user_password, v2):
        """
        This test checks the behaviour of a cluster as nodes are removed and restored.

        For each ordinary node in the cluster:

        * A long running job is started assigned to run on the node
        * The node is taken offline
        * We check the job fails
        * We check that the group and instance capacity are set to zero (where the group capacity should be zero b/c the group only contains one instance)
        * We check that the heartbeat for the offline instance does not advance
        * We check a new job launched against the node remains pending
        * We restart the node
        * We check that the pending job starts running and completes
        * We check that group and instance capacity for the now-online node are restored
        * We check a new job against the now-back-online node starts and completes
        """
        manager = ansible_module_cls.inventory_manager
        hosts = manager.get_group_dict()['instance_group_ordinary_instances']

        # fetch the instance groups containing each ordinary node
        # we name the instance groups 1...n where n is the number of ordinary nodes in the cluster
        hostname_to_instance_group = {}
        for i in range(1, len(hosts) + 1):
            group = v2.instance_groups.get(name=str(i)).results[0]
            hostname = group.related.instances.get().results[0].hostname
            hostname_to_instance_group[hostname] = group

        # create a long running job template for each host
        job_templates = {}
        for hostname in hosts:
            host = factories.v2_host()
            jt = factories.v2_job_template(playbook='sleep.yml',
                                           extra_vars=dict(sleep_interval=600),
                                           inventory=host.ds.inventory)
            jt.add_instance_group(hostname_to_instance_group[hostname])
            job_templates[hostname] = jt

        def fetch_node_not_matching_name(name):
            online_hosts = [hostname for hostname in hosts if hostname != name]
            return random.choice(online_hosts)

        for hostname in hosts:
            # Store the capacity of the group and instance for later verification
            ig = hostname_to_instance_group[hostname]
            group_capacity = ig.capacity
            instance_capacity = ig.related.instances.get().results.pop().capacity

            online_hostname = fetch_node_not_matching_name(hostname)

            def get_heartbeats():
                """
                return a dictionary of heartbeats of all ordinary nodes that are online
                and the heartbeat of the offline node"""
                instances = v2.ping.get().instances
                heartbeats = {}
                offline_heartbeat = None
                for instance in instances:
                    this_host = instance['node']
                    this_heartbeat = instance['heartbeat']
                    if this_host not in hosts:
                        # ignore nodes not in the ordinary_instances group
                        continue
                    if this_host == hostname:
                        # this is the node we took offline
                        offline_heartbeat = this_heartbeat
                    else:
                        heartbeats[this_host] = this_heartbeat
                return heartbeats, offline_heartbeat

            connection = Connection('https://' + online_hostname)
            connection.login(admin_user.username, admin_user.password)
            with self.current_instance(connection, v2):
                # Start a long running job from the node we're going to take offline
                long_job = job_templates[hostname].launch().wait_until_status('running')

                # Stop the tower node.
                stop, start = self.get_stop_and_start_funcs_for_node(admin_user, manager, hostname, v2)
                with SafeStop(stop, start):
                    log.debug("Using online node {}".format(online_hostname))

                    # Check that the heartbeat of all nodes except the stopped one advance
                    heartbeats, offline_heartbeat = get_heartbeats()
                    assert offline_heartbeat is not None

                    def heartbeats_changed():
                        new_heartbeats, _ = get_heartbeats()
                        for host, beat in new_heartbeats.items():
                            if heartbeats[host] == new_heartbeats[host]:
                                return False
                        return True

                    utils.poll_until(heartbeats_changed, interval=10, timeout=120)
                    _, current_offline_heartbeat = get_heartbeats()
                    # assert the offline heartbeat is unchanged
                    assert current_offline_heartbeat == offline_heartbeat

                    ig = hostname_to_instance_group[hostname]
                    # we have to fetch the group from an online instance
                    group = v2.instance_groups.get(id=ig.id).results.pop()

                    def check_group_capacity_zeroed():
                        group.get()
                        return group.capacity == 0
                    utils.poll_until(check_group_capacity_zeroed, interval=5, timeout=120)
                    instance = group.related.instances.get().results.pop()
                    assert instance.capacity == 0

                    # Check the job we started is marked as failed
                    long_job = v2.jobs.get(id=long_job.id).results[0]
                    long_job.wait_until_status(FAIL_STATUSES, interval=5, timeout=180, since_job_created=False)

                    # Should fail with explanation:
                    explanation = "Task was marked as running in Tower but was not present in Celery, so it has been marked as failed."
                    assert long_job.job_explanation == explanation

                    # Start a new job against the offline node
                    host = factories.v2_host()
                    jt = factories.v2_job_template(inventory=host.ds.inventory)
                    jt.add_instance_group(hostname_to_instance_group[hostname])
                    job = jt.launch()

                    # Check it stays in pending
                    self.assert_job_stays_pending(job)

                # Capacity of the instance and the group should be restored
                group = v2.instance_groups.get(id=ig.id).results.pop()

                def check_group_capacity_restored():
                    group.get()
                    return group.capacity == group_capacity
                utils.poll_until(check_group_capacity_restored, interval=5, timeout=120)
                instance = group.related.instances.get().results.pop()
                assert instance.capacity == instance_capacity

                # Check that the waiting job is picked up and completes
                job.wait_until_completed(since_job_created=False)

                # Check that we can run a new job against the node
                job = jt.launch().wait_until_completed()
                assert job.is_successful

    @pytest.mark.requires_ha
    @pytest.mark.requires_isolation
    @pytest.mark.parametrize('run_on_isolated_group', [True, False], ids=['isolated group', 'regular instance group'])
    @pytest.mark.parametrize('scm_type', ['git', 'svn', 'hg'])
    def test_project_copied_to_separate_instance_on_job_run(self, v2, factories, run_on_isolated_group, scm_type):
        if run_on_isolated_group:
            ig1 = v2.instance_groups.get(name='ordinary_instances').results.pop()
            ig2 = v2.instance_groups.get(name='protected').results.pop()
        else:
            ig1, ig2 = self.mutually_exclusive_instance_groups(v2.instance_groups.get().results)

        # Create project on first instance
        org = factories.v2_organization()
        org.add_instance_group(ig1)
        # Workaround for https://github.com/ansible/ansible/issues/17720#issuecomment-322628667
        if scm_type == 'svn':
            proj = factories.v2_project(organization=org, scm_type='svn', scm_url='https://github.com/jladdjr/ansible-playbooks', scm_branch='44')
            playbook = 'trunk/sleep.yml'
        else:
            proj = factories.v2_project(organization=org, scm_type=scm_type)
            playbook = 'sleep.yml'

        # Run job template on second instance
        host = factories.v2_host()
        jt = factories.v2_job_template(project=proj, inventory=host.ds.inventory, playbook=playbook)
        jt.add_instance_group(ig2)

        job = jt.launch().wait_until_completed()
        ig2_hostnames = [i.hostname for i in ig2.get_related('instances').results]
        assert job.execution_node in ig2_hostnames
        assert job.is_successful

    @pytest.mark.last
    @pytest.mark.requires_ha
    @pytest.mark.requires_isolation
    def test_network_partition(self, ansible_module_cls, v2, factories, admin_user):
        """
        Tests tower's ability to recover from a network partition using the following steps:

        1. Start a job that will continue to run while the partitioning event takes place.
        2. Create a network partition using network_partition.yml. While tower instances cannot
           communicate across the partition, all instances can communicate with the database.
        3. Launch a second job during the partition.
        4. Restore connectivity between the tower hosts. Restart tower services on all hosts (excepted isolated hosts).
        5. Confirm that new jobs can be launched on each host.
        6. Confirm previous jobs complete (can be successful or failed, but not pending or waiting).
           Confirm no jobs were relaunched.

        Note: Test is designed to run from an instance in the `instance_group_partition_1` instance group.
        """
        # Launch job across partition
        inventory_file = ansible_module_cls.inventory
        manager = ansible_module_cls.inventory_manager
        instance_hostname = manager.get_group_dict().get('instance_group_partition_1')[0]
        ig = v2.instance_groups.get(name='partition_2').results.pop()

        connection = Connection('https://' + instance_hostname)
        connection.login(admin_user.username, admin_user.password)
        with self.current_instance(connection, v2):
            # License not immediately propagated across cluster instances:
            # https://github.com/ansible/ansible-tower/issues/7389
            utils.poll_until(lambda: len(v2.config.get().license_info), interval=1, timeout=3)
            host = factories.v2_host()
            jt_before_partition = factories.v2_job_template(inventory=host.ds.inventory, playbook='sleep.yml', extra_vars=dict(sleep_interval=300))
            jt_before_partition.add_instance_group(ig)
            job_before_partition = jt_before_partition.launch()

        try:
            # Create network partition
            cmd = "ansible-playbook -i {} playbooks/network_partition.yml".format(inventory_file)
            rc = subprocess.call(cmd, shell=True)
            assert rc == 0, "Received non-zero response code from '{}'".format(cmd)

            # Launch second job across partition
            with self.current_instance(connection, v2):
                org = factories.organization()
                ig_partition_1 = v2.instance_groups.get(name='partition_1').results.pop()
                org.add_instance_group(ig_partition_1)
                project = factories.project(organization=org)  # Ensure project update runs on instance from partition_1
                host = factories.v2_host()
                jt_during_partition = factories.v2_job_template(inventory=host.ds.inventory, project=project)
                jt_during_partition.add_instance_group(ig)
                job_during_partition = jt_during_partition.launch()

            # Confirm rabbitmq shows drop in number of running nodes
            num_ordinary_instances = len(manager.get_group_dict()['instance_group_ordinary_instances'])
            for partition in ('instance_group_partition_1', 'instance_group_partition_2'):
                def decrease_in_rabbitmq_nodes():
                    hosts = manager.get_group_dict().get(partition)
                    cmd = "ANSIBLE_BECOME=true ansible {} -i {} -m shell -a 'rabbitmqctl cluster_status'".format(hosts[0], inventory_file)
                    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
                    stdout, stderr = proc.communicate()
                    rc = proc.returncode
                    assert rc == 0, "Received non-zero response code from '{}'\n[stdout]\n{}\n[stderr]\n{}".format(cmd, stdout, stderr)
                    node_count = re.search('running_nodes,\[([^\]]*)\]', stdout.replace('\n', '')).group(1).count('rabbitmq@')
                    return node_count < num_ordinary_instances
                utils.poll_until(decrease_in_rabbitmq_nodes, interval=10, timeout=60)
        finally:
            cmd = "ansible-playbook -i {} -e network_partition_state=disabled playbooks/network_partition.yml".format(inventory_file)
            rc = subprocess.call(cmd, shell=True)
            assert rc == 0, "Received non-zero response code from '{}'".format(cmd)

            # Restart tower services on all hosts
            for host in manager.get_group_dict()['instance_group_ordinary_instances']:
                cmd = "ANSIBLE_BECOME=true ansible {} -i {} -m shell -a 'ansible-tower-service restart'".format(host, inventory_file)
                rc = subprocess.call(cmd, shell=True)
                assert rc == 0, "Received non-zero response code from '{}'".format(cmd)

            for host in manager.get_group_dict()['instance_group_ordinary_instances']:
                def tower_serving_homepage():
                    contacted = ansible_module_cls.uri(url='https://' + host + '/api', validate_certs='no')
                    return contacted.values()[0]['status'] == 200
                utils.poll_until(tower_serving_homepage, interval=10, timeout=60)

        # Confirm that new jobs can be launched on each instance
        for hostname in manager.get_group_dict()['instance_group_ordinary_instances']:
            connection = Connection('https://' + hostname)
            connection.login(admin_user.username, admin_user.password)
            with self.current_instance(connection, v2):
                host = factories.v2_host()
                jt = factories.v2_job_template(inventory=host.ds.inventory)
                job = jt.launch().wait_until_completed()
                assert job.is_successful

        # Confirm that previous jobs resume or are marked failed
        job_before_partition.wait_until_completed()
        log.debug("Job started before partition ({j.id}) completed with status '{j.status}' and job_explanation '{j.job_explanation}'"
                  .format(j=job_before_partition))
        job_during_partition.wait_until_completed()
        log.debug("Job started during partition ({j.id}) completed with status '{j.status}' and job_explanation '{j.job_explanation}'"
                  .format(j=job_during_partition))
        celery_error_msg = 'Task was marked as running in Tower but was not present in Celery, so it has been marked as failed.'
        assert job_before_partition.job_explanation == ('' if job_before_partition.status == 'successful' else celery_error_msg)
        assert job_during_partition.job_explanation == ('' if job_during_partition.status == 'successful' else celery_error_msg)

        # Confirm that no jobs were relaunched
        assert jt_before_partition.get().get_related('last_job').id == job_before_partition.id
        assert jt_during_partition.get().get_related('last_job').id == job_during_partition.id

    @pytest.mark.parametrize('setting_endpoint', ['all', 'jobs'])
    @pytest.mark.requires_ha
    def test_ensure_awx_isolated_key_fields_are_read_only(self, ansible_module_cls, factories, admin_user, user_password, v2, setting_endpoint):
        settings = v2.settings.get().get_endpoint(setting_endpoint)
        assert settings.AWX_ISOLATED_PUBLIC_KEY != '$encrypted$' and len(settings.AWX_ISOLATED_PUBLIC_KEY)
        assert settings.AWX_ISOLATED_PRIVATE_KEY == '$encrypted$'

        initial_value_public_key = settings.AWX_ISOLATED_PUBLIC_KEY
        initial_value_private_key = settings.AWX_ISOLATED_PRIVATE_KEY

        def check_settings():
            settings.get()
            assert settings.AWX_ISOLATED_PUBLIC_KEY == initial_value_public_key
            assert settings.AWX_ISOLATED_PRIVATE_KEY == initial_value_private_key

        settings.delete()
        check_settings()
        settings.patch(AWX_ISOLATED_PUBLIC_KEY='changed', AWX_ISOLATED_PRIVATE_KEY='changed')
        check_settings()
        payload = settings.get().json
        payload.AWX_ISOLATED_PUBLIC_KEY = 'changed'
        payload.AWX_ISOLATED_PRIVATE_KEY = 'changed'
        settings.put(payload)
        check_settings()
