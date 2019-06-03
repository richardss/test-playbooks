import towerkit.exceptions as exc
import pytest

from tests.api import APITest


@pytest.mark.api
@pytest.mark.rbac
@pytest.mark.usefixtures('authtoken', 'install_enterprise_license_unlimited')
class TestJobTemplateCredentialsRBAC(APITest):

    def test_job_template_creation_request_without_credential_access_forbidden(self, request, factories, v2):
        org = factories.organization()
        inv = factories.inventory(organization=org)
        proj = factories.project(organization=org)
        cred = factories.credential(organization=org)
        user = factories.user(organization=org)

        for resource in (proj, inv):
            resource.set_object_roles(user, 'use')

        cred.set_object_roles(user, 'read')

        with self.current_user(user):
            with pytest.raises(exc.Forbidden):
                factories.job_template(project=proj, credential=cred, inventory=inv)

        for role in ('use', 'admin'):
            cred.set_object_roles(user, role)
            with self.current_user(user):
                factories.job_template(project=proj, credential=cred, inventory=inv)

    def test_job_template_creation_request_without_vault_credential_access_forbidden(self, request, factories, v2):
        """Verify that a job_template with network credential creation request
        is only permitted if the user making the request has usage permission for the network credential.
        """
        organization = factories.v2_organization()
        project = factories.v2_project()
        inventory = factories.v2_inventory()

        user = factories.v2_user(organization=organization)

        for resource in (project, inventory):
            resource.set_object_roles(user, 'use')

        vault_credential = factories.v2_credential(kind='vault', vault_password='tower', organization=organization)
        vault_credential.set_object_roles(user, 'read')

        with self.current_user(user):
            with pytest.raises(exc.Forbidden):
                factories.v2_job_template(organization=organization, project=project, credential=vault_credential, inventory=inventory)

        for role in ('use', 'admin'):
            vault_credential.set_object_roles(user, role)
            with self.current_user(user):
                factories.v2_job_template(organization=organization, project=project, credential=vault_credential, inventory=inventory)

    @pytest.mark.parametrize('cred_kind', ('net', 'aws', 'custom'))
    def test_v2_job_template_extra_credential_association_without_credential_access_forbidden(self, request, factories,
                                                                                              cred_kind):
        jt = factories.v2_job_template()
        organization = jt.ds.inventory.ds.organization

        user = factories.user(organization=organization)
        jt.set_object_roles(user, 'admin')

        for resource in ('credential', 'project', 'inventory'):
            jt.ds[resource].set_object_roles(user, 'use')

        if cred_kind == 'custom':
            extra_credential = factories.v2_credential(credential_type=True, organization=organization)
        else:
            extra_credential = factories.v2_credential(kind=cred_kind, organization=organization)

        extra_credential.set_object_roles(user, 'read')
        with self.current_user(user):
            with pytest.raises(exc.Forbidden):
                jt.add_extra_credential(extra_credential)
            assert not jt.related.extra_credentials.get(name=extra_credential.name).count

        for role in ('use', 'admin'):
            extra_credential.set_object_roles(user, role)
            with self.current_user(user):
                jt.add_extra_credential(extra_credential)
                assert jt.related.extra_credentials.get(name=extra_credential.name).count
                jt.remove_extra_credential(extra_credential)
                assert not jt.related.extra_credentials.get(name=extra_credential.name).count

    def test_launch_with_ask_credential_and_no_extra_credential_access_forbidden(self, factories):
        jt = factories.v2_job_template(ask_credential_on_launch=True)
        jt.remove_all_credentials()

        organization = jt.related.project.get().related.organization.get()

        cloud_credentials = [factories.v2_credential(credential_type=factories.credential_type(),
                                                     organization=organization)]

        user = factories.v2_user(organization=organization)

        for role in ('execute', 'admin'):
            jt.set_object_roles(user, role)
            with self.current_user(user):
                with pytest.raises(exc.Forbidden):
                    jt.launch(dict(extra_credentials=[c.id for c in cloud_credentials]))
            jt.set_object_roles(user, role, disassociate=True)

    def test_relaunch_with_ask_credential_and_no_extra_credential_access_forbidden(self, factories):
        host = factories.v2_host()
        organization = host.ds.inventory.ds.organization

        jt = factories.v2_job_template(inventory=host.ds.inventory, ask_credential_on_launch=True)
        jt.remove_all_credentials()

        user_1, user_2 = [factories.user(organization=organization) for _ in range(2)]

        cloud_credentials = []
        for i in range(4):
            cloud_credentials.append(factories.v2_credential(name='CloudCredential{}'.format(i),
                                                             credential_type=factories.credential_type(),
                                                             organization=None, user=user_1))

        with self.current_user(user_1):
            # FIXME: This works when you pass in credentials=[list of credentials] but gets Forbidden with extra_credentials
            job = jt.launch(dict(extra_credentials=[c.id for c in cloud_credentials[:2]])).wait_until_completed()

        with self.current_user(user_2):
            with pytest.raises(exc.Forbidden):
                job.relaunch(dict(extra_credentials=[c.id for c in cloud_credentials[2:]]))
