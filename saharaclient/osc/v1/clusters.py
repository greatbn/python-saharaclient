# Copyright (c) 2015 Mirantis Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json

from cliff import command
from cliff import lister
from cliff import show
from openstackclient.common import exceptions
from openstackclient.common import utils as osc_utils
from oslo_log import log as logging

from saharaclient.osc.v1 import utils

CLUSTER_FIELDS = ["cluster_template_id", "use_autoconfig", "user_keypair_id",
                  "status", "image", "node_groups", "id",
                  "anti_affinity", "version", "name", "is_transient",
                  "is_protected", "description", "is_public",
                  "neutron_management_network", "plugin_name"]


def _format_node_groups_list(node_groups):
    return ', '.join(
        ['%s:%s' % (ng['name'], ng['count']) for ng in node_groups])


def _format_cluster_output(data):
    data['version'] = data.pop('hadoop_version')
    data['image'] = data.pop('default_image_id')
    data['node_groups'] = _format_node_groups_list(data['node_groups'])
    data['anti_affinity'] = osc_utils.format_list(data['anti_affinity'])


def _get_plugin_version(cluster_template, client):
    ct = utils.get_resource(client.cluster_templates, cluster_template)
    return ct.plugin_name, ct.hadoop_version, ct.id


class CreateCluster(show.ShowOne):
    """Creates cluster"""

    log = logging.getLogger(__name__ + ".CreateCluster")

    def get_parser(self, prog_name):
        parser = super(CreateCluster, self).get_parser(prog_name)

        parser.add_argument(
            '--name',
            metavar="<name>",
            help="Name of the cluster [REQUIRED if JSON is not provided]",
        )
        parser.add_argument(
            '--cluster-template',
            metavar="<cluster-template>",
            help="Cluster template name or ID [REQUIRED if JSON is not "
                 "provided]"
        )
        parser.add_argument(
            '--image',
            metavar="<image>",
            help='Image that will be used for cluster deployment (Name or ID) '
                 '[REQUIRED if JSON is not provided]'
        )
        parser.add_argument(
            '--description',
            metavar="<description>",
            help='Description of the cluster'
        )
        parser.add_argument(
            '--user-keypair',
            metavar="<keypair>",
            help='User keypair to get acces to VMs after cluster creation'
        )
        parser.add_argument(
            '--neutron-network',
            metavar="<network>",
            help='Instances of the cluster will get fixed IP addresses in '
                 'this network. (Name or ID should be provided)'
        )
        parser.add_argument(
            '--count',
            metavar="<count>",
            type=int,
            help='Number of clusters to be created'
        )
        parser.add_argument(
            '--public',
            action='store_true',
            default=False,
            help='Make the cluster public (Visible from other tenants)',
        )
        parser.add_argument(
            '--protected',
            action='store_true',
            default=False,
            help='Make the cluster protected',
        )
        parser.add_argument(
            '--transient',
            action='store_true',
            default=False,
            help='Create transient cluster',
        )
        parser.add_argument(
            '--json',
            metavar='<filename>',
            help='JSON representation of the cluster. Other '
                 'arguments (except for --wait) will not be taken into '
                 'account if this one is provided'
        )
        parser.add_argument(
            '--wait',
            action='store_true',
            default=False,
            help='Wait for the cluster creation to complete',
        )

        return parser

    def take_action(self, parsed_args):
        self.log.debug("take_action(%s)" % parsed_args)
        client = self.app.client_manager.data_processing
        network_client = self.app.client_manager.network

        if parsed_args.json:
            blob = osc_utils.read_blob_file_contents(parsed_args.json)
            try:
                template = json.loads(blob)
            except ValueError as e:
                raise exceptions.CommandError(
                    'An error occurred when reading '
                    'template from file %s: %s' % (parsed_args.json, e))

            if 'neutron_management_network' in template:
                template['net_id'] = template.pop('neutron_management_network')

            if 'count' in template:
                parsed_args.count = template['count']

            data = client.clusters.create(**template).to_dict()
        else:
            if not parsed_args.name or not parsed_args.cluster_template \
                    or not parsed_args.image:
                raise exceptions.CommandError(
                    'At least --name , --cluster-template, --image arguments '
                    'should be specified or json template should be provided '
                    'with --json argument')

            plugin, version, template_id = _get_plugin_version(
                parsed_args.cluster_template, client)

            image_id = utils.get_resource_id(client.images, parsed_args.image)

            net_id = (network_client.api.find_attr(
                'networks', parsed_args.neutron_network)['id'] if
                parsed_args.neutron_network else None)

            data = client.clusters.create(
                name=parsed_args.name,
                plugin_name=plugin,
                hadoop_version=version,
                cluster_template_id=template_id,
                default_image_id=image_id,
                description=parsed_args.description,
                is_transient=parsed_args.transient,
                user_keypair_id=parsed_args.user_keypair,
                net_id=net_id,
                count=parsed_args.count,
                is_public=parsed_args.public,
                is_protected=parsed_args.protected
            ).to_dict()
        if parsed_args.count and parsed_args.count > 1:
            clusters = [
                utils.get_resource(client.clusters, id)
                for id in data['clusters']]

            if parsed_args.wait:
                for cluster in clusters:
                    if not osc_utils.wait_for_status(
                            client.clusters.get, cluster.id):
                        self.log.error(
                            'Error occurred during cluster creation: %s',
                            data['id'])

            data = {}
            for cluster in clusters:
                data[cluster.name] = cluster.id

        else:
            if parsed_args.wait:
                if not osc_utils.wait_for_status(
                        client.clusters.get, data['id']):
                    self.log.error(
                        'Error occurred during cluster creation: %s',
                        data['id'])
                data = client.clusters.get(data['id']).to_dict()
            _format_cluster_output(data)
            data = utils.prepare_data(data, CLUSTER_FIELDS)

        return self.dict2columns(data)


class ListClusters(lister.Lister):
    """Lists clusters"""

    log = logging.getLogger(__name__ + ".ListClusters")

    def get_parser(self, prog_name):
        parser = super(ListClusters, self).get_parser(prog_name)
        parser.add_argument(
            '--long',
            action='store_true',
            default=False,
            help='List additional fields in output',
        )
        parser.add_argument(
            '--plugin',
            metavar="<plugin>",
            help="List clusters with specific plugin"
        )

        parser.add_argument(
            '--version',
            metavar="<version>",
            help="List clusters with specific version of the "
                 "plugin"
        )

        parser.add_argument(
            '--name',
            metavar="<name-substring>",
            help="List clusters with specific substring in the name"
        )

        return parser

    def take_action(self, parsed_args):
        self.log.debug("take_action(%s)" % parsed_args)
        client = self.app.client_manager.data_processing
        search_opts = {}
        if parsed_args.plugin:
            search_opts['plugin_name'] = parsed_args.plugin
        if parsed_args.version:
            search_opts['hadoop_version'] = parsed_args.version

        data = client.clusters.list(search_opts=search_opts)

        if parsed_args.name:
            data = utils.get_by_name_substring(data, parsed_args.name)

        if parsed_args.long:
            columns = ('name', 'id', 'plugin_name', 'hadoop_version',
                       'status', 'description', 'default_image_id')
            column_headers = utils.prepare_column_headers(
                columns, {'hadoop_version': 'version',
                          'default_image_id': 'image'})

        else:
            columns = ('name', 'id', 'plugin_name', 'hadoop_version', 'status')
            column_headers = utils.prepare_column_headers(
                columns, {'hadoop_version': 'version',
                          'default_image_id': 'image'})
        return (
            column_headers,
            (osc_utils.get_item_properties(
                s,
                columns
            ) for s in data)
        )


class ShowCluster(show.ShowOne):
    """Display cluster details"""

    log = logging.getLogger(__name__ + ".ShowCluster")

    def get_parser(self, prog_name):
        parser = super(ShowCluster, self).get_parser(prog_name)
        parser.add_argument(
            "cluster",
            metavar="<cluster>",
            help="Name or id of the cluster to display",
        )

        return parser

    def take_action(self, parsed_args):
        self.log.debug("take_action(%s)" % parsed_args)
        client = self.app.client_manager.data_processing

        data = utils.get_resource(
            client.clusters, parsed_args.cluster).to_dict()

        _format_cluster_output(data)
        data = utils.prepare_data(data, CLUSTER_FIELDS)

        return self.dict2columns(data)


class DeleteCluster(command.Command):
    """Deletes cluster"""

    log = logging.getLogger(__name__ + ".DeleteCluster")

    def get_parser(self, prog_name):
        parser = super(DeleteCluster, self).get_parser(prog_name)
        parser.add_argument(
            "cluster",
            metavar="<cluster>",
            nargs="+",
            help="Name(s) or id(s) of the cluster(s) to delete",
        )
        parser.add_argument(
            '--wait',
            action='store_true',
            default=False,
            help='Wait for the cluster(s) delete to complete',
        )

        return parser

    def take_action(self, parsed_args):
        self.log.debug("take_action(%s)" % parsed_args)
        client = self.app.client_manager.data_processing
        clusters = []
        for cluster in parsed_args.cluster:
            cluster_id = utils.get_resource_id(
                client.clusters, cluster)
            client.clusters.delete(cluster_id)
            clusters.append(cluster_id)
        if parsed_args.wait:
            for cluster_id in clusters:
                if not utils.wait_for_delete(client.clusters, cluster_id):
                    self.log.error(
                        'Error occurred during cluster deleting: %s',
                        cluster_id)


class UpdateCluster(show.ShowOne):
    """Updates cluster"""

    log = logging.getLogger(__name__ + ".UpdateCluster")

    def get_parser(self, prog_name):
        parser = super(UpdateCluster, self).get_parser(prog_name)

        parser.add_argument(
            'cluster',
            metavar="<cluster>",
            help="Name or ID of the cluster",
        )
        parser.add_argument(
            '--name',
            metavar="<name>",
            help="New name of the cluster",
        )
        parser.add_argument(
            '--description',
            metavar="<description>",
            help='Description of the cluster'
        )
        public = parser.add_mutually_exclusive_group()
        public.add_argument(
            '--public',
            action='store_true',
            help='Make the cluster public '
                 '(Visible from other tenants)',
            dest='is_public'
        )
        public.add_argument(
            '--private',
            action='store_false',
            help='Make the cluster private '
                 '(Visible only from this tenant)',
            dest='is_public'
        )
        protected = parser.add_mutually_exclusive_group()
        protected.add_argument(
            '--protected',
            action='store_true',
            help='Make the cluster protected',
            dest='is_protected'
        )
        protected.add_argument(
            '--unprotected',
            action='store_false',
            help='Make the cluster unprotected',
            dest='is_protected'
        )
        parser.set_defaults(is_public=None, is_protected=None)

        return parser

    def take_action(self, parsed_args):
        self.log.debug("take_action(%s)" % parsed_args)
        client = self.app.client_manager.data_processing

        cluster_id = utils.get_resource_id(
            client.clusters, parsed_args.cluster)

        data = client.clusters.update(
            cluster_id,
            name=parsed_args.name,
            description=parsed_args.description,
            is_public=parsed_args.is_public,
            is_protected=parsed_args.is_protected
        ).cluster

        _format_cluster_output(data)
        data = utils.prepare_data(data, CLUSTER_FIELDS)

        return self.dict2columns(data)


class ScaleCluster(show.ShowOne):
    """Scales cluster"""

    log = logging.getLogger(__name__ + ".ScaleCluster")

    def get_parser(self, prog_name):
        parser = super(ScaleCluster, self).get_parser(prog_name)

        parser.add_argument(
            'cluster',
            metavar="<cluster>",
            help="Name or ID of the cluster",
        )
        parser.add_argument(
            '--node-groups',
            nargs='+',
            metavar='<node-group:instances_count>',
            help='Node groups and number of their instances to be scale to '
                 '[REQUIRED if JSON is not provided]'
        )
        parser.add_argument(
            '--json',
            metavar='<filename>',
            help='JSON representation of the cluster scale object. Other '
                 'arguments (except for --wait) will not be taken into '
                 'account if this one is provided'
        )
        parser.add_argument(
            '--wait',
            action='store_true',
            default=False,
            help='Wait for the cluster scale to complete',
        )

        return parser

    def take_action(self, parsed_args):
        self.log.debug("take_action(%s)" % parsed_args)
        client = self.app.client_manager.data_processing

        cluster = utils.get_resource(
            client.clusters, parsed_args.cluster)

        if parsed_args.json:
            blob = osc_utils.read_blob_file_contents(parsed_args.json)
            try:
                template = json.loads(blob)
            except ValueError as e:
                raise exceptions.CommandError(
                    'An error occurred when reading '
                    'template from file %s: %s' % (parsed_args.json, e))

            data = client.clusters.scale(cluster.id, template).to_dict()
        else:
            scale_object = {
                "add_node_groups": [],
                "resize_node_groups": []
            }
            scale_node_groups = dict(
                map(lambda x: x.split(':', 1), parsed_args.node_groups))
            cluster_node_groups = [ng['name'] for ng in cluster.node_groups]
            for name, count in scale_node_groups.items():
                ng = utils.get_resource(client.node_group_templates, name)
                if ng.name in cluster_node_groups:
                    scale_object["resize_node_groups"].append({
                        "name": ng.name,
                        "count": int(count)
                    })
                else:
                    scale_object["add_node_groups"].append({
                        "node_group_template_id": ng.id,
                        "name": ng.name,
                        "count": int(count)
                    })
            if not scale_object['add_node_groups']:
                del scale_object['add_node_groups']
            if not scale_object['resize_node_groups']:
                del scale_object['resize_node_groups']

            data = client.clusters.scale(cluster.id, scale_object).cluster

        if parsed_args.wait:
            if not osc_utils.wait_for_status(
                    client.clusters.get, data['id']):
                self.log.error(
                    'Error occurred during cluster scaling: %s',
                    cluster.id)
            data = client.clusters.get(cluster.id).to_dict()

        _format_cluster_output(data)
        data = utils.prepare_data(data, CLUSTER_FIELDS)

        return self.dict2columns(data)