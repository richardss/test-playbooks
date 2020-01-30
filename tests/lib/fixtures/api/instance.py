import pytest


@pytest.fixture
def active_instances(v2):
    """Returns instance list that excludes corner cases that tests should
    not normally run jobs against
    * no disabled instances
    * no lost instances
    * no isolated instances
    """
    return v2.instances.get(
        rampart_groups__controller__isnull=True,
        enabled=True,
        capacity__gt=0,
        page_size=200
    )


@pytest.fixture
def reset_instance(request):
    def func(instance):
        def teardown():
            instance.patch(capacity_adjustment=1, enabled=True, managed_by_policy=True)
        request.addfinalizer(teardown)
    return func


@pytest.fixture(params=['regular', 'isolated', 'container_group'], ids=['regular_tower_instance', 'isolated_node', 'container_group'])
def instance_group(request, authtoken, is_traditional_cluster, is_openshift_cluster, v2, session_container_group):
    """Return first the tower instance group, then an isolated instance group, then a container group.

    This is to enable running tests a second time on an isolated node if the platform
    under test is a traditional cluster and includes isolated nodes.
    """
    if request.param == 'isolated':
        if is_traditional_cluster:
            return v2.instance_groups.get(name='protected').results.pop()
        else:
            pytest.skip("Not on a traditional cluster, cannot run on isolated node.")
    if request.param == 'regular':
        return v2.instance_groups.get(name='tower').results.pop()
    if request.param == 'container_group':
        if is_traditional_cluster or is_openshift_cluster:
            # We are overloading our k8s cluster running these on all platforms
            pytest.skip("Only running container group tests from standalone instances to not overwhelm our k8s cluster nightly.")
        else:
            return session_container_group
