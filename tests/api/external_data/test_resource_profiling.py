from tests.api import APITest
import pytest
from awxkit.utils import (poll_until, random_title)
from awxkit.config import config
from urllib.parse import urlparse


@pytest.mark.serial
@pytest.mark.usefixtures('authtoken')
class TestResourceProfiling(APITest):

    expected_files = ['memory',
                      'cpu',
                      'pids']

    interval_settings = ['AWX_RESOURCE_PROFILING_CPU_POLL_INTERVAL',
                        'AWX_RESOURCE_PROFILING_MEMORY_POLL_INTERVAL',
                        'AWX_RESOURCE_PROFILING_PID_POLL_INTERVAL']

    default_interval = 0.25

    def toggle_resource_profiling(self, update_setting_pg, v2, state="false"):
        system_settings = v2.settings.get().get_endpoint('jobs')
        payload = {'AWX_RESOURCE_PROFILING_ENABLED': state}
        update_setting_pg(system_settings, payload)

    @pytest.fixture
    def global_resource_profiling_enabled(self, update_setting_pg, v2, request):
        self.toggle_resource_profiling(update_setting_pg, v2, state="true")

    def get_resource_profiles(self, ansible_adhoc, is_cluster, job_id, execution_node):
        hosts = ansible_adhoc()
        if not is_cluster:
            execution_node = urlparse(config.base_url).netloc
        profile_paths = hosts[execution_node].find(paths='/var/log/tower/playbook_profiling/{}'.format(job_id), recurse=True).values()[0]['files']
        filenames = [f['path'] for f in profile_paths]
        return filenames

    def count_lines_in_files(self, ansible_adhoc, is_cluster, filenames, execution_node):
        hosts = ansible_adhoc()
        if not is_cluster:
            execution_node = urlparse(config.base_url).netloc
        linecounts = {}
        for f in filenames:
            file_lc = hosts[execution_node].command('wc {}'.format(f)).values()[0]['stdout'].split()[0]
            linecounts[f] = int(file_lc)
        return linecounts

    def check_filenames(self, filenames):
        for e in self.expected_files:
            assert any(e.lower() in f.lower() for f in filenames), '{} not found'.format(e)

    def test_performance_stats_files_created(self, ansible_adhoc, skip_if_openshift, is_cluster, global_resource_profiling_enabled, factories):
        jt = factories.job_template(playbook='sleep.yml', extra_vars='{"sleep_interval": 2}')
        factories.host(inventory=jt.ds.inventory)
        job = jt.launch().wait_until_completed()
        profiles = self.get_resource_profiles(ansible_adhoc, is_cluster, job.id, job.execution_node)
        assert len(profiles) == len(self.expected_files)
        self.check_filenames(profiles)

    def test_performance_stats_not_created_when_disabled(self, ansible_adhoc, is_cluster, skip_if_openshift, factories):
        jt = factories.job_template(playbook='sleep.yml', extra_vars='{"sleep_interval": 2}')
        factories.host(inventory=jt.ds.inventory)
        job = jt.launch().wait_until_completed()
        profiles = self.get_resource_profiles(ansible_adhoc, is_cluster, job.id, job.execution_node)
        assert len(profiles) == 0

    def test_performance_stats_default_interval_is_applied(self, ansible_adhoc, v2, factories, is_cluster, skip_if_openshift, global_resource_profiling_enabled):
        system_settings = v2.settings.get().get_endpoint('jobs')
        for s in self.interval_settings:
            assert system_settings[s] == self.default_interval
        jt = factories.job_template(playbook='sleep.yml', extra_vars='{"sleep_interval": 10}')
        factories.host(inventory=jt.ds.inventory)
        job = jt.launch().wait_until_completed()
        profiles = self.get_resource_profiles(ansible_adhoc, is_cluster, job.id, job.execution_node)
        self.check_filenames(profiles)
        linecounts = self.count_lines_in_files(ansible_adhoc, is_cluster, profiles, job.execution_node)
        for f in profiles:
            assert 39 < linecounts[f] < 50, linecounts[f]

    def test_performance_stats_intervals_are_applied(self, ansible_adhoc, update_setting_pg, v2, factories, is_cluster, skip_if_openshift, global_resource_profiling_enabled):
        system_settings = v2.settings.get().get_endpoint('jobs')
        payload = {s: 0.5 for s in self.interval_settings}
        update_setting_pg(system_settings, payload)
        jt = factories.job_template(playbook='sleep.yml', extra_vars='{"sleep_interval": 10}')
        factories.host(inventory=jt.ds.inventory)
        job = jt.launch().wait_until_completed()
        profiles = self.get_resource_profiles(ansible_adhoc, is_cluster, job.id, job.execution_node)
        self.check_filenames(profiles)
        linecounts = self.count_lines_in_files(ansible_adhoc, is_cluster, profiles, job.execution_node)
        for f in profiles:
            assert 19 < linecounts[f] < 30, linecounts[f]

    def test_performance_stats_generated_on_isolated_nodes_and_copied_to_controller(self, ansible_adhoc, is_cluster, v2, factories, skip_if_openshift, skip_if_not_cluster, global_resource_profiling_enabled):
        ig = v2.instance_groups.get(name='protected').results.pop()
        jt = factories.job_template(playbook='sleep.yml', extra_vars='{"sleep_interval": 2}')
        jt.add_instance_group(ig)
        factories.host(inventory=jt.ds.inventory)
        job = jt.launch().wait_until_completed()
        profiles = self.get_resource_profiles(ansible_adhoc, is_cluster, job.id, job.controller_node)
        assert len(profiles) == len(self.expected_files)
        self.check_filenames(profiles)
        linecounts = self.count_lines_in_files(ansible_adhoc, is_cluster, profiles, job.controller_node)
        for f in profiles:
            assert linecounts[f] > 5, linecounts[f]

    def test_performance_stats_enabled_does_not_break_old_ansible(self, ansible_adhoc, v2, factories, skip_if_openshift, is_cluster, create_venv, venv_path, global_resource_profiling_enabled):
        folder_name = random_title(non_ascii=False)
        with create_venv(folder_name, 'psutil ansible==2.7'):
            poll_until(lambda: venv_path(folder_name) in v2.config.get().custom_virtualenvs, interval=1, timeout=15)
            jt = factories.job_template(playbook='sleep.yml', extra_vars='{"sleep_interval": 2}')
            jt.ds.inventory.add_host()
            jt.custom_virtualenv = venv_path(folder_name)
            job = jt.launch().wait_until_completed()
            job.assert_successful()
            assert job.job_env['VIRTUAL_ENV'].rstrip('/') == job.custom_virtualenv.rstrip('/') == venv_path(folder_name).rstrip('/')
            profiles = self.get_resource_profiles(ansible_adhoc, is_cluster, job.id, job.execution_node)
            assert len(profiles) == 0